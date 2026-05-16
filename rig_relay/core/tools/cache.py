"""Tool result cache — DuckDB-backed, content-addressed, TTL-expiring.

Indexed by (tool_name, task_fingerprint_sha256, repo_state_fingerprint).
Cache entries expire after a configurable TTL. Uses DuckDB via the
coordination store's database connection when available.

This reduces CPU/memory pressure from deterministic tools (read_file,
grep, validate, git_status, etc.) when multiple agents or turns call
the same tool with the same arguments against the same repo state.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any

# Cache TTLs per determinism class (in seconds)
DEFAULT_CACHE_TTL: dict[str, int] = {
    "DETERMINISTIC_PURE": 300,  # Pure functions: 5 min
    "DETERMINISTIC_REPO_STATE": 60,  # Repo-state dependent: 1 min
    "DETERMINISTIC_ENV_SENSITIVE": 30,  # Env sensitive: 30s
    "DETERMINISTIC_TIME_SENSITIVE": 10,  # Time sensitive: 10s
}

BUILD_ROOT = Path(__file__).resolve().parent.parent.parent / ".build" / "rig-relay"
CACHE_DB_DIR = BUILD_ROOT / "tool-cache"
CACHE_DB_PATH = CACHE_DB_DIR / "tool_cache.duckdb"


def _ensure_db() -> Any:
    """Get or create the DuckDB connection and schema."""
    import duckdb

    CACHE_DB_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(CACHE_DB_PATH))

    con.execute("""
        CREATE TABLE IF NOT EXISTS tool_result_cache (
            cache_key VARCHAR PRIMARY KEY,
            tool_name VARCHAR NOT NULL,
            task_fingerprint VARCHAR NOT NULL,
            repo_fingerprint VARCHAR NOT NULL,
            determinism_class VARCHAR NOT NULL,
            result_json VARCHAR NOT NULL,
            result_sha256 VARCHAR NOT NULL,
            created_at DOUBLE NOT NULL,
            expires_at DOUBLE NOT NULL,
            hit_count INTEGER DEFAULT 1
        )
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_cache_expires
        ON tool_result_cache (expires_at)
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_cache_lookup
        ON tool_result_cache (tool_name, task_fingerprint, repo_fingerprint)
    """)

    # Prune expired entries on connection
    con.execute("DELETE FROM tool_result_cache WHERE expires_at < ?", (time.time(),))

    return con


def _compute_cache_key(
    tool_name: str, task_fingerprint: str, repo_fingerprint: str
) -> str:
    raw = f"{tool_name}:{task_fingerprint}:{repo_fingerprint}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _compute_repo_fingerprint() -> str:
    """Compute a fast repo-state fingerprint from git HEAD + dirty file list.

    This is a lightweight hash — not as precise as full git status but
    fast enough to call on every tool invocation.
    """
    try:
        import subprocess

        head = (
            subprocess
            .check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            .decode("utf-8")
            .strip()
        )
        status = subprocess.check_output(
            ["git", "status", "--short"], stderr=subprocess.DEVNULL, timeout=2
        ).decode("utf-8")
    except Exception:
        return "no-git"

    raw = f"{head}:{status}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _compute_task_fingerprint(tool_name: str, args_dict: dict[str, Any]) -> str:
    """Compute a content-addressed fingerprint of the tool's arguments.

    Only includes args that affect the deterministic output. Excludes
    context-only args like ctx, session_dir, etc.
    """
    # Serialize args to canonical JSON
    canonical = json.dumps(args_dict, sort_keys=True, ensure_ascii=False)
    prefix = f"rig-relay-tool-args-v1:{tool_name}:"
    return hashlib.sha256((prefix + canonical).encode("utf-8")).hexdigest()


def get_cached_result(
    tool_name: str,
    args_dict: dict[str, Any],
    determinism_class: str,
    repo_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    """Look up a cached tool result.

    Args:
        tool_name: Name of the tool.
        args_dict: The tool's validated arguments dict.
        determinism_class: The tool's determinism class string.
        repo_fingerprint: Override repo fingerprint. Auto-computed if None.

    Returns:
        The cached result dict, or None if not cached / expired.
    """
    ttl = DEFAULT_CACHE_TTL.get(determinism_class)
    if ttl is None:
        return None  # Not cacheable

    task_fp = _compute_task_fingerprint(tool_name, args_dict)
    repo_fp = repo_fingerprint or _compute_repo_fingerprint()
    cache_key = _compute_cache_key(tool_name, task_fp, repo_fp)

    try:
        con = _ensure_db()
        row = con.execute(
            "SELECT result_json, hit_count FROM tool_result_cache "
            "WHERE cache_key = ? AND expires_at > ?",
            (cache_key, time.time()),
        ).fetchone()

        if row is None:
            return None

        result_json, hit_count = row

        # Update hit count
        con.execute(
            "UPDATE tool_result_cache SET hit_count = ? WHERE cache_key = ?",
            (hit_count + 1, cache_key),
        )

        return json.loads(result_json)

    except Exception:
        return None


def set_cached_result(
    tool_name: str,
    args_dict: dict[str, Any],
    result_dict: dict[str, Any],
    determinism_class: str,
    repo_fingerprint: str | None = None,
) -> None:
    """Store a tool result in the cache.

    Args:
        tool_name: Name of the tool.
        args_dict: The tool's validated arguments dict.
        result_dict: The tool's result model dict.
        determinism_class: The tool's determinism class string.
        repo_fingerprint: Override repo fingerprint. Auto-computed if None.
    """
    ttl = DEFAULT_CACHE_TTL.get(determinism_class)
    if ttl is None:
        return  # Not cacheable

    task_fp = _compute_task_fingerprint(tool_name, args_dict)
    repo_fp = repo_fingerprint or _compute_repo_fingerprint()
    cache_key = _compute_cache_key(tool_name, task_fp, repo_fp)
    now = time.time()

    result_json = json.dumps(result_dict, sort_keys=True, ensure_ascii=False)
    result_sha256 = hashlib.sha256(result_json.encode("utf-8")).hexdigest()

    try:
        con = _ensure_db()
        con.execute(
            """
            INSERT OR REPLACE INTO tool_result_cache
            (cache_key, tool_name, task_fingerprint, repo_fingerprint,
             determinism_class, result_json, result_sha256,
             created_at, expires_at, hit_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                cache_key,
                tool_name,
                task_fp,
                repo_fp,
                determinism_class,
                result_json,
                result_sha256,
                now,
                now + ttl,
            ),
        )
    except Exception:
        pass


def invalidate_cache(tool_name: str | None = None) -> int:
    """Invalidate cache entries. If tool_name is None, clears all.

    Args:
        tool_name: Optional tool name to clear. All tools if None.

    Returns:
        Number of deleted entries.
    """
    try:
        con = _ensure_db()
        if tool_name:
            con.execute(
                "DELETE FROM tool_result_cache WHERE tool_name = ?", (tool_name,)
            )
        else:
            con.execute("DELETE FROM tool_result_cache")
        return int(con.execute("SELECT changes()").fetchone()[0])
    except Exception:
        return 0


def cache_stats() -> dict[str, Any]:
    """Return content-light cache statistics."""
    try:
        con = _ensure_db()
        total = con.execute("SELECT count(*) FROM tool_result_cache").fetchone()[0]
        expired = con.execute(
            "SELECT count(*) FROM tool_result_cache WHERE expires_at < ?",
            (time.time(),),
        ).fetchone()[0]
        active = total - expired
        top_tools = con.execute(
            "SELECT tool_name, count(*) as cnt, sum(hit_count) as hits "
            "FROM tool_result_cache "
            "WHERE expires_at > ? "
            "GROUP BY tool_name ORDER BY cnt DESC LIMIT 5",
            (time.time(),),
        ).fetchall()
        return {
            "total_entries": total,
            "expired_entries": expired,
            "active_entries": active,
            "top_tools": [
                {"tool": row[0], "entries": row[1], "total_hits": row[2]}
                for row in top_tools
            ],
        }
    except Exception as e:
        return {"error": str(e)}


def close_cache() -> None:
    """Close the DuckDB connection."""
    try:
        import duckdb

        if CACHE_DB_PATH.is_file():
            con = duckdb.connect(str(CACHE_DB_PATH))
            con.close()
    except Exception:
        pass


__all__ = [
    "cache_stats",
    "close_cache",
    "get_cached_result",
    "invalidate_cache",
    "set_cached_result",
]
