"""Bash analytics query module — DuckDB-backed queries over fact_bash_invocations.

Uses the shared analytical compiler substrate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rig_relay.analytics import (
    build_projection_metadata,
    load_jsonl,
    rows_to_dicts,
    write_projection,
)
from rig_relay.analytics.bash_rows import (
    create_bash_invocations_table,
    normalize_bash_record,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LEDGER_PATH = REPO_ROOT / ".rig" / "analytics" / "bash" / "bash_invocations.jsonl"
DEFAULT_INDEXES_DIR = REPO_ROOT / ".rig" / "analytics" / "bash" / "indexes"

_PROJECTOR_VERSION = "1.0.0"


def _prep(ledger_path: Path) -> tuple[Any, dict[str, Any]]:
    """Load ledger, normalize records, register with DuckDB.

    Returns (connection, diagnostics).
    """
    from rig_relay.analytics import connect_in_memory

    result = load_jsonl(ledger_path)
    records = [normalize_bash_record(r) for r in result.valid_records]
    con = connect_in_memory()
    create_bash_invocations_table(con, records)
    return con, result.diagnostics


def _write_index(indexes_dir: Path, name: str, data: Any, metadata: dict[str, Any]) -> Path:
    """Write a projection index with metadata."""
    return write_projection(
        indexes_dir / f"{name}.json",
        data,
        metadata=metadata,
    )


def _meta(name: str, ledger_path: Path, diagnostics: dict[str, Any]) -> dict[str, Any]:
    return build_projection_metadata(
        name, ledger_path, diagnostics,
    )


def query_bash_usage_summary(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> dict[str, Any]:
    """Aggregate bash usage counts."""
    con, diagnostics = _prep(ledger_path)
    meta = _meta("bash_usage_summary", ledger_path, diagnostics)

    total = rows_to_dicts(con, "SELECT count(*) AS cnt FROM fact_bash_invocations")
    meta["total_invocations"] = total[0]["cnt"] if total else 0

    by_status = rows_to_dicts(
        con,
        "SELECT status, count(*) AS cnt FROM fact_bash_invocations "
        "GROUP BY status ORDER BY status",
    )
    meta["by_status"] = {r["status"]: r["cnt"] for r in by_status}

    by_family = rows_to_dicts(
        con,
        "SELECT command_family, count(*) AS cnt FROM fact_bash_invocations "
        "GROUP BY command_family ORDER BY cnt DESC",
    )
    meta["by_command_family"] = {r["command_family"]: r["cnt"] for r in by_family}

    agg = rows_to_dicts(
        con,
        "SELECT "
        "count(*) FILTER (WHERE is_success = 1) AS success_count, "
        "count(*) FILTER (WHERE is_failure = 1) AS failure_count, "
        "count(*) FILTER (WHERE is_timeout = 1) AS timeout_count, "
        "count(*) FILTER (WHERE is_refusal = 1) AS refusal_count, "
        "count(*) FILTER (WHERE mutation_detected = 1) AS mutation_count, "
        "count(*) FILTER (WHERE shell_used = 1) AS shell_used_count, "
        "count(*) FILTER (WHERE is_replacement_candidate = 1) AS replacement_candidate_count, "
        "avg(duration_ms) AS avg_duration_ms, "
        "sum(stdout_bytes) AS total_stdout_bytes, "
        "sum(stderr_bytes) AS total_stderr_bytes "
        "FROM fact_bash_invocations",
    )
    if agg:
        meta.update(agg[0])

    return meta


def query_bash_diagnostics(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> dict[str, Any]:
    """Return ledger diagnostics."""
    result = load_jsonl(ledger_path)
    return build_projection_metadata("bash_diagnostics", ledger_path, result.diagnostics)


def query_bash_failure_clusters(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Group failures by command family, command, and exit code."""
    con, _diagnostics = _prep(ledger_path)
    if not con:
        return []
    return rows_to_dicts(
        con,
        "SELECT command_family, command_sha256, command_text, exit_code, "
        "count(*) AS failure_count, avg(duration_ms) AS avg_duration_ms "
        "FROM fact_bash_invocations WHERE is_failure = 1 "
        "GROUP BY command_family, command_sha256, command_text, exit_code "
        "ORDER BY failure_count DESC LIMIT ?",
        (limit,),
    )


def query_bash_timeout_clusters(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Group commands that time out by family and fingerprint."""
    con, _diagnostics = _prep(ledger_path)
    if not con:
        return []
    return rows_to_dicts(
        con,
        "SELECT command_family, command_sha256, command_text, "
        "count(*) AS timeout_count, avg(duration_ms) AS avg_duration_ms "
        "FROM fact_bash_invocations WHERE is_timeout = 1 "
        "GROUP BY command_family, command_sha256, command_text "
        "ORDER BY timeout_count DESC LIMIT ?",
        (limit,),
    )


def query_bash_risk_patterns(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Show risky command patterns with risk tags."""
    con, _diagnostics = _prep(ledger_path)
    if not con:
        return []
    return rows_to_dicts(
        con,
        "SELECT command_text, command_family, risk_tags_json, "
        "count(*) AS invocation_count, "
        "count(*) FILTER (WHERE mutation_detected = 1) AS mutation_count, "
        "count(*) FILTER (WHERE shell_used = 1) AS shell_count "
        "FROM fact_bash_invocations "
        "WHERE is_destructive_candidate = 1 OR mutation_detected = 1 OR shell_used = 1 "
        "GROUP BY command_text, command_family, risk_tags_json "
        "ORDER BY invocation_count DESC, mutation_count DESC LIMIT ?",
        (limit,),
    )


def query_bash_replacement_candidates(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Identify repeated bash patterns that should become deterministic tools."""
    con, _diagnostics = _prep(ledger_path)
    if not con:
        return []
    return rows_to_dicts(
        con,
        "SELECT command_family, replacement_candidate, "
        "count(*) AS invocation_count, "
        "count(*) FILTER (WHERE mutation_detected = 0) AS read_only_count, "
        "avg(duration_ms) AS avg_duration_ms "
        "FROM fact_bash_invocations "
        "WHERE is_replacement_candidate = 1 AND mutation_detected = 0 "
        "AND status = 'completed' "
        "GROUP BY command_family, replacement_candidate "
        "ORDER BY invocation_count DESC LIMIT ?",
        (limit,),
    )


def write_bash_indexes(
    indexes_dir: Path = DEFAULT_INDEXES_DIR,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> dict[str, Path]:
    """Write all bash projections."""
    indexes_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}

    for name, query_fn in [
        ("bash_usage_summary", query_bash_usage_summary),
        ("bash_failure_clusters", lambda lp=ledger_path: query_bash_failure_clusters(lp)),
        ("bash_timeout_clusters", lambda lp=ledger_path: query_bash_timeout_clusters(lp)),
        ("bash_risk_patterns", lambda lp=ledger_path: query_bash_risk_patterns(lp)),
        ("bash_replacement_candidates", lambda lp=ledger_path: query_bash_replacement_candidates(lp)),
    ]:
        data = query_fn(ledger_path) if name == "bash_usage_summary" else query_fn()
        path = _write_index(indexes_dir, name, data, {})
        written[name] = path

    return written
