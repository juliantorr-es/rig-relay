"""Deterministic read projections for the report event ledger.

Reads .rig/reports/reports.jsonl and builds structured read models:
  - report_summary: aggregate counts by status, kind, severity
  - report_snapshots: current state of each report
  - open_raw_reports: reports with status=open
  - duplicate_candidates: reports derived from heuristic dedupe
  - candidate_findings: reports that could become canonical findings

Projectors are deterministic: same input → same output.
No side effects on canonical findings. Raw ledger is never mutated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LEDGER_PATH = REPO_ROOT / ".rig" / "reports" / "reports.jsonl"
DEFAULT_INDEXES_DIR = REPO_ROOT / ".rig" / "reports" / "indexes"

STALE_DAYS = 30


# ── Public projector functions ───────────────────────────────────


def build_report_summary(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> dict[str, Any]:
    """Aggregate counts from the report ledger via DuckDB query layer."""
    from rig_relay.reports.query import query_report_summary

    return query_report_summary(ledger_path)


def build_report_snapshots(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Build current snapshot for each report via DuckDB query layer."""
    from rig_relay.reports.query import query_report_snapshots

    return query_report_snapshots(ledger_path, limit=limit)


def build_open_raw_reports(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return reports with status=open via DuckDB query layer."""
    from rig_relay.reports.query import query_open_raw_reports

    return query_open_raw_reports(ledger_path, limit=limit)


def build_duplicate_candidates(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> list[dict[str, Any]]:
    """Return duplicate candidate groups via DuckDB query layer."""
    from rig_relay.reports.query import query_duplicate_candidates

    return query_duplicate_candidates(ledger_path)


def build_candidate_findings(
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return plausible candidate findings via DuckDB query layer."""
    from rig_relay.reports.query import query_candidate_findings

    return query_candidate_findings(ledger_path, limit=limit)


def write_indexes(
    indexes_dir: Path = DEFAULT_INDEXES_DIR,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> dict[str, Path]:
    """Write all projections to .rig/reports/indexes/.

    Returns dict of name → path for each written index.
    """
    indexes_dir.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, dict | list] = {
        "report_summary": build_report_summary(ledger_path),
        "report_snapshots": build_report_snapshots(ledger_path)[:100],
        "open_raw_reports": build_open_raw_reports(ledger_path)[:100],
        "duplicate_candidates": build_duplicate_candidates(ledger_path),
        "candidate_findings": build_candidate_findings(ledger_path)[:50],
    }

    from rig_relay.analytics import write_projection

    written: dict[str, Path] = {}
    for name, data in outputs.items():
        path = write_projection(indexes_dir / f"{name}.json", data)
        written[name] = path

    return written


__all__ = [
    "build_candidate_findings",
    "build_duplicate_candidates",
    "build_open_raw_reports",
    "build_report_snapshots",
    "build_report_summary",
    "write_indexes",
]
