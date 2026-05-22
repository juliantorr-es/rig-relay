"""Tool result cache — DuckDB-backed, content-addressed, TTL-expiring.

Indexed by (tool_name, task_fingerprint_sha256, repo_state_fingerprint).
Cache entries expire after a configurable TTL. Uses DuckDB with short-lived
connections that are closed after each operation.

Safety rules (v1):
- Governance must run before cache reuse — the cache is an optimization, not an authorization oracle.
- Mutation tools (write_file, search_replace, bash, behavior_patch) are never cached.
- Content-bearing read tools (read_file, grep, get_context) are never cached —
  their results may contain source code, secrets, or private content.
- Cache keys use explicit workspace/worktree identity, not ambient cwd.
- The cache lives outside the package source tree (.build/rig-relay/tool-cache/).
"""

from __future__ import annotations

import contextlib
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

# Tools that MUST NOT be cached — mutation tools or content-bearing read tools.
_UNCACHEABLE_TOOLS: frozenset[str] = frozenset({
    "write_file",
    "search_replace",
    "behavior_patch",
    "bash",
    "read_file",
    "grep",
    "get_context",
})

BUILD_ROOT = Path(__file__).resolve().parent.parent.parent / ".build" / "rig-relay"
CACHE_DB_DIR = BUILD_ROOT / "tool-cache"
CACHE_DB_PATH = CACHE_DB_DIR / "tool_cache.duckdb"


@contextlib.contextmanager
def _get_db() -> Any:
    """Context manager for short-lived DuckDB connections."""
    import duckdb

    CACHE_DB_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(CACHE_DB_PATH))
    try:
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
        con.execute(
            "DELETE FROM tool_result_cache WHERE expires_at < ?", (time.time(),)
        )
        yield con
    finally:
        try:
            con.close()
        except Exception:
            pass


def _compute_cache_key(
    tool_name: str, task_fingerprint: str, repo_fingerprint: str
) -> str:
    raw = f"{tool_name}:{task_fingerprint}:{repo_fingerprint}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_tool_cacheable(tool_name: str, determinism_class: str) -> bool:
    """Return whether a tool may participate in the result cache.

    Uncachable: mutation tools, content-bearing read tools, and tools
    without a configured TTL for their determinism class.
    """
    if tool_name in _UNCACHEABLE_TOOLS:
        return False
    return determinism_class in DEFAULT_CACHE_TTL


def _compute_repo_fingerprint(workspace_root: str | Path) -> str:
    """Compute a repo-state fingerprint from git HEAD + dirty file list.

    Uses the explicit workspace root, not ambient cwd.
    """
    try:
        import subprocess

        ws = str(workspace_root)
        head = (
            subprocess
            .check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                timeout=2,
                cwd=ws,
            )
            .decode("utf-8")
            .strip()
        )
        status = subprocess.check_output(
            ["git", "status", "--short"], stderr=subprocess.DEVNULL, timeout=2, cwd=ws
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
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Look up a cached tool result (must be called after governance).

    Uncachable tools return None immediately — no DuckDB connection opened.
    """
    if not is_tool_cacheable(tool_name, determinism_class):
        return None

    task_fp = _compute_task_fingerprint(tool_name, args_dict)
    repo_fp = _compute_repo_fingerprint(workspace_root or Path.cwd())
    cache_key = _compute_cache_key(tool_name, task_fp, repo_fp)

    try:
        with _get_db() as con:
            row = con.execute(
                "SELECT result_json, hit_count FROM tool_result_cache "
                "WHERE cache_key = ? AND expires_at > ?",
                (cache_key, time.time()),
            ).fetchone()

            if row is None:
                return None

            result_json, hit_count = row
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
    *,
    workspace_root: str | Path | None = None,
) -> None:
    """Store a tool result in the cache (called after governance + invocation).

    Uncachable tools are silently skipped.
    """
    if not is_tool_cacheable(tool_name, determinism_class):
        return

    ttl = DEFAULT_CACHE_TTL[determinism_class]
    task_fp = _compute_task_fingerprint(tool_name, args_dict)
    repo_fp = _compute_repo_fingerprint(workspace_root or Path.cwd())
    cache_key = _compute_cache_key(tool_name, task_fp, repo_fp)
    now = time.time()

    result_json = json.dumps(result_dict, sort_keys=True, ensure_ascii=False)
    result_sha256 = hashlib.sha256(result_json.encode("utf-8")).hexdigest()

    try:
        with _get_db() as con:
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
    """Invalidate cache entries. If tool_name is None, clears all."""
    try:
        with _get_db() as con:
            if tool_name:
                con.execute(
                    "DELETE FROM tool_result_cache WHERE tool_name = ?", (tool_name,)
                )
            else:
                con.execute("DELETE FROM tool_result_cache")
            changes_row = con.execute("SELECT changes()").fetchone()
            return int(changes_row[0]) if changes_row else 0
    except Exception:
        return 0


def cache_stats() -> dict[str, Any]:
    """Return content-light cache statistics."""
    try:
        with _get_db() as con:
            total_row = con.execute("SELECT count(*) FROM tool_result_cache").fetchone()
            total = total_row[0] if total_row else 0
            expired_row = con.execute(
                "SELECT count(*) FROM tool_result_cache WHERE expires_at < ?",
                (time.time(),),
            ).fetchone()
            expired = expired_row[0] if expired_row else 0
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
    """No-op — connections are closed per-operation via context manager."""
    pass


__all__ = [
    "cache_stats",
    "close_cache",
    "get_cached_result",
    "invalidate_cache",
    "set_cached_result",
]
