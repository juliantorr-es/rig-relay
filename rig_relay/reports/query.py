"""DuckDB-backed report query layer.

Uses the shared analytical compiler substrate from rig_relay.analytics.
JSONL remains the append-only source of truth. DuckDB is the analytical
query engine — never the operational write target.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rig_relay.analytics import (
    build_projection_metadata,
    create_reports_table,
    load_jsonl,
    normalize_report_record,
    rows_to_dicts,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LEDGER_PATH = REPO_ROOT / ".rig" / "reports" / "reports.jsonl"

_STALE_DAYS = 30
_PROJECTION_POLICY_CANDIDATE_FINDING = "rig.report.candidate_finding_policy.v1"


def _stale_cutoff() -> str:
    """Return ISO timestamp for the staleness threshold (30 days ago)."""
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(days=_STALE_DAYS)
    return cutoff.isoformat()


def _prep(ledger_path: Path) -> tuple[Any, dict[str, Any]]:
    """Load ledger, normalize records, register with DuckDB.

    Returns (connection, diagnostics).
    """
    result = load_jsonl(ledger_path)
    records = [normalize_report_record(r) for r in result.valid_records]
    con = _connect(records)
    return con, result.diagnostics


def _connect(records: list[dict[str, Any]]) -> Any:
    """Create an in-memory DuckDB connection with registered reports."""
    from rig_relay.analytics import connect_in_memory

    con = connect_in_memory()
    create_reports_table(con, records)
    return con


def query_report_summary(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> dict[str, Any]:
    """Aggregate report counts from the ledger."""
    con, diagnostics = _prep(ledger_path)

    result: dict[str, Any] = build_projection_metadata(
        "report_summary", ledger_path, diagnostics,
    )

    records = rows_to_dicts(con, "SELECT count(*) AS cnt FROM reports")
    result["total_reports"] = records[0]["cnt"] if records else 0

    by_status = rows_to_dicts(
        con, "SELECT status, count(*) AS cnt FROM reports GROUP BY status ORDER BY status"
    )
    result["by_status"] = {r["status"]: r["cnt"] for r in by_status}

    by_kind = rows_to_dicts(
        con, "SELECT kind, count(*) AS cnt FROM reports GROUP BY kind ORDER BY kind"
    )
    result["by_kind"] = {r["kind"]: r["cnt"] for r in by_kind}

    by_severity = rows_to_dicts(
        con,
        "SELECT severity, count(*) AS cnt FROM reports GROUP BY severity ORDER BY severity",
    )
    result["by_severity"] = {r["severity"]: r["cnt"] for r in by_severity}

    stale = rows_to_dicts(
        con,
        "SELECT count(*) AS cnt FROM reports WHERE status = 'open' AND created_at < ?",
        (_stale_cutoff(),),
    )
    result["stale_raw_report_count"] = stale[0]["cnt"] if stale else 0

    open_raw = rows_to_dicts(
        con, "SELECT count(*) AS cnt FROM reports WHERE status = 'open'"
    )
    result["open_raw_report_count"] = open_raw[0]["cnt"] if open_raw else 0

    # Canonical findings (separate)
    try:
        from rig_relay.governance.findings_lifecycle import compute_findings_summary

        fs = compute_findings_summary()
        result["open_finding_count"] = fs.get("by_status", {}).get("open", 0)
        result["stale_finding_count"] = len(fs.get("stale_findings", []))
    except Exception:
        result["open_finding_count"] = None
        result["stale_finding_count"] = None

    if diagnostics.get("malformed_line_numbers"):
        result["malformed_line_numbers"] = diagnostics["malformed_line_numbers"]

    return result


def query_report_diagnostics(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> dict[str, Any]:
    """Return ledger diagnostics without building full projections."""
    _result = load_jsonl(ledger_path)
    return build_projection_metadata(
        "report_diagnostics", ledger_path, _result.diagnostics,
    )


def query_report_snapshots(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return the latest snapshot per report, newest first."""
    con, _diagnostics = _prep(ledger_path)
    if not con:
        return []
    return rows_to_dicts(
        con,
        "SELECT DISTINCT ON (report_id) * FROM reports "
        "ORDER BY report_id, created_at DESC, report_id ASC LIMIT ?",
        (limit,),
    )


def query_open_raw_reports(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return reports with status=open, sorted newest first."""
    con, _diagnostics = _prep(ledger_path)
    if not con:
        return []
    return rows_to_dicts(
        con,
        "SELECT * FROM reports WHERE status = 'open' "
        "ORDER BY created_at DESC, report_id ASC LIMIT ?",
        (limit,),
    )


def query_duplicate_candidates(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> list[dict[str, Any]]:
    """Group reports by dedupe_key, return groups with >1 entry."""
    con, _diagnostics = _prep(ledger_path)
    if not con:
        return []

    rows = rows_to_dicts(
        con,
        "SELECT dedupe_key, count(*) AS report_count, "
        "list(report_id ORDER BY created_at DESC, report_id ASC) AS report_ids, "
        "list(title ORDER BY created_at DESC, report_id ASC) AS titles "
        "FROM reports WHERE dedupe_key IS NOT NULL AND dedupe_key != '' "
        "GROUP BY dedupe_key HAVING count(*) > 1 "
        "ORDER BY report_count DESC, dedupe_key ASC",
    )

    for r in rows:
        r["report_count"] = int(r["report_count"])
    return rows


def query_candidate_findings(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return reports that qualify as candidate findings.

    Policy: rig.report.candidate_finding_policy.v1
    """
    con, _diagnostics = _prep(ledger_path)
    if not con:
        return []

    result = rows_to_dicts(
        con,
        "SELECT * FROM reports "
        "WHERE kind NOT IN ('mission_report', 'handoff_note') "
        "AND severity IN ('medium', 'high', 'critical') "
        "AND status = 'open' AND evidence_count > 0 "
        "ORDER BY created_at DESC, report_id ASC LIMIT ?",
        (limit,),
    )

    for r in result:
        r["_projection_policy"] = _PROJECTION_POLICY_CANDIDATE_FINDING
    return result
