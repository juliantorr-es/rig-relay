#!/usr/bin/env python3
"""Rig Relay Analytics Data Lake CLI.

Read-side DuckDB analytics over structured governance, telemetry,
release, and testing data. DuckDB is disposable (in-memory only).

Usage:
    uv run python scripts/rig_relay_analytics.py scan-sessions
    uv run python scripts/rig_relay_analytics.py ingest-all
    uv run python scripts/rig_relay_analytics.py view --name governance-gate-health --json
    uv run python scripts/rig_relay_analytics.py view --name session-health --csv
    uv run python scripts/rig_relay_analytics.py query --sql "SELECT ..."
    uv run python scripts/rig_relay_analytics.py correlate
    uv run python scripts/rig_relay_analytics.py export --format csv --output-dir .build/rig-relay/derived/
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

from rig_relay.analytics.engine import (
    AnalyticsEngine,
    build_projection,
    compute_view,
    correlation_check,
    ingest_all_sources,
)
from rig_relay.analytics.views import VIEW_FUNCTIONS
from rig_relay.core.logger import logger

CANONICAL_SESSION_ROOT = Path.home() / ".rig" / "relay" / "sessions"
_MAX_DISPLAY_ROWS = 20


def _check_duckdb() -> bool:
    try:
        import duckdb  # noqa: F401

        return True
    except ImportError:
        return False


def _session_dirs(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    return sorted(
        p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")
    )


def _display_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("(empty result)")
        return
    for row in rows[:_MAX_DISPLAY_ROWS]:
        print(json.dumps(row, ensure_ascii=False))
    if len(rows) > _MAX_DISPLAY_ROWS:
        print(f"... and {len(rows) - _MAX_DISPLAY_ROWS} more rows")


def cmd_scan_sessions(args: argparse.Namespace) -> int:
    root = args.sessions_root or CANONICAL_SESSION_ROOT
    dirs = _session_dirs(root)
    result: dict[str, Any] = {
        "sessions_root": str(root),
        "session_count": len(dirs),
        "sessions": [],
    }
    for d in dirs:
        obs = d / "observability.jsonl"
        receipts = d / "receipts.jsonl"
        result["sessions"].append({
            "session_id": d.name,
            "observability_present": obs.is_file(),
            "observability_size": obs.stat().st_size if obs.is_file() else 0,
            "receipts_present": receipts.is_file(),
            "receipts_size": receipts.stat().st_size if receipts.is_file() else 0,
        })
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Sessions root: {result['sessions_root']}")
        print(f"Session directories: {result['session_count']}")
        for s in result["sessions"]:
            obs_status = "present" if s["observability_present"] else "missing"
            rec_status = "present" if s["receipts_present"] else "missing"
            print(f"  {s['session_id']}: obs={obs_status} rec={rec_status}")
    return 0


def cmd_ingest_all(args: argparse.Namespace) -> int:
    if not _check_duckdb():
        print(
            "Error: DuckDB is not available. Install with: uv add duckdb",
            file=sys.stderr,
        )
        return 1
    engine = AnalyticsEngine()
    try:
        counts = ingest_all_sources(engine)
        result = {
            "ingested_at": datetime.now(UTC).isoformat(),
            "tables": engine.list_tables(),
            "row_counts": counts,
        }
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"Ingested {len(result['tables'])} tables:")
            for table in result["tables"]:
                print(f"  {table}: {counts.get(table, 'N/A')} rows")
        return 0
    finally:
        engine.close()


def cmd_view(args: argparse.Namespace) -> int:
    if not _check_duckdb():
        print(
            "Error: DuckDB is not available. Install with: uv add duckdb",
            file=sys.stderr,
        )
        return 1

    view_name = args.name
    if view_name not in VIEW_FUNCTIONS:
        available = ", ".join(sorted(VIEW_FUNCTIONS.keys()))
        print(
            f"Error: Unknown view '{view_name}'. Available: {available}",
            file=sys.stderr,
        )
        return 1

    session_root = getattr(args, "sessions_root", CANONICAL_SESSION_ROOT)
    engine = AnalyticsEngine()
    try:
        ingest_all_sources(engine, session_root=session_root)
        rows = compute_view(engine, view_name)
        if args.csv:
            _write_csv(rows, sys.stdout)
        elif args.json:
            print(json.dumps(rows, indent=2, sort_keys=True))
        else:
            _display_rows(rows)
        return 0
    finally:
        engine.close()


def cmd_query(args: argparse.Namespace) -> int:
    if not _check_duckdb():
        print(
            "Error: DuckDB is not available. Install with: uv add duckdb",
            file=sys.stderr,
        )
        return 1

    session_root = getattr(args, "sessions_root", CANONICAL_SESSION_ROOT)
    engine = AnalyticsEngine()
    try:
        ingest_all_sources(engine, session_root=session_root)
        rows = engine.execute_query(args.sql)
        if args.json:
            print(json.dumps(rows, indent=2, sort_keys=True))
        else:
            _display_rows(rows)
        return 0
    finally:
        engine.close()


def cmd_correlate(args: argparse.Namespace) -> int:
    if not _check_duckdb():
        print(
            "Error: DuckDB is not available. Install with: uv add duckdb",
            file=sys.stderr,
        )
        return 1

    session_root = getattr(args, "sessions_root", CANONICAL_SESSION_ROOT)
    engine = AnalyticsEngine()
    try:
        ingest_all_sources(engine, session_root=session_root)
        report = correlation_check(engine)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print("Correlation Report:")
            for section, data in report.items():
                print(f"  {section}:")
                for k, v in data.items():
                    print(f"    {k}: {v}")
        return 0
    finally:
        engine.close()


def cmd_export(args: argparse.Namespace) -> int:
    if not _check_duckdb():
        print(
            "Error: DuckDB is not available. Install with: uv add duckdb",
            file=sys.stderr,
        )
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fmt = args.format

    session_root = getattr(args, "sessions_root", CANONICAL_SESSION_ROOT)
    engine = AnalyticsEngine()
    try:
        ingest_all_sources(engine, session_root=session_root)

        counts: dict[str, int] = {}
        for view_name in sorted(VIEW_FUNCTIONS.keys()):
            try:
                rows = compute_view(engine, view_name)
                if fmt == "csv":
                    path = output_dir / f"{view_name}.csv"
                    with path.open("w", encoding="utf-8", newline="") as f:
                        _write_csv(rows, f)
                else:
                    path = output_dir / f"{view_name}.json"
                    path.write_text(
                        json.dumps(rows, indent=2, sort_keys=True, ensure_ascii=False),
                        encoding="utf-8",
                    )
                counts[view_name] = len(rows)
            except Exception as exc:
                logger.warning("Export view=%s failed: %s", view_name, exc)

        projection = build_projection(engine)
        proj_path = output_dir / "analytics_projection.json"
        proj_path.write_text(
            json.dumps(projection, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

        if args.json:
            print(json.dumps(counts, indent=2, sort_keys=True))
        else:
            print(f"Exported {len(counts)} views to {output_dir}")
            for name, count in sorted(counts.items()):
                print(f"  {name}: {count} rows")
        return 0
    finally:
        engine.close()


def _write_csv(rows: list[dict[str, Any]], dest: Any) -> None:
    if not rows:
        return
    writer = csv.DictWriter(dest, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rig Relay Analytics Data Lake CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand")

    sp_scan = subparsers.add_parser("scan-sessions", help="Scan session directories")
    sp_scan.add_argument("--sessions-root", type=Path, default=CANONICAL_SESSION_ROOT)
    sp_scan.add_argument("--json", action="store_true")

    sp_ingest = subparsers.add_parser("ingest-all", help="Ingest all data sources")
    sp_ingest.add_argument("--sessions-root", type=Path, default=CANONICAL_SESSION_ROOT)
    sp_ingest.add_argument("--json", action="store_true")

    sp_view = subparsers.add_parser("view", help="Compute a pre-built view")
    sp_view.add_argument("--name", required=True, help="View name")
    sp_view.add_argument("--sessions-root", type=Path, default=CANONICAL_SESSION_ROOT)
    sp_view.add_argument("--json", action="store_true")
    sp_view.add_argument("--csv", action="store_true")

    sp_query = subparsers.add_parser("query", help="Run a raw SQL query")
    sp_query.add_argument("--sql", required=True, help="SQL query string")
    sp_query.add_argument("--sessions-root", type=Path, default=CANONICAL_SESSION_ROOT)
    sp_query.add_argument("--json", action="store_true")

    sp_corr = subparsers.add_parser("correlate", help="Run cross-store correlation")
    sp_corr.add_argument("--sessions-root", type=Path, default=CANONICAL_SESSION_ROOT)
    sp_corr.add_argument("--json", action="store_true")

    sp_export = subparsers.add_parser("export", help="Export all views to disk")
    sp_export.add_argument("--format", choices=["csv", "json"], default="json")
    sp_export.add_argument(
        "--output-dir", type=Path, default=Path(".build/rig-relay/derived")
    )
    sp_export.add_argument("--json", action="store_true")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.command is None:
        args = parse_args(["--help"])
        return 0

    match args.command:
        case "scan-sessions":
            result = cmd_scan_sessions(args)
        case "ingest-all":
            result = cmd_ingest_all(args)
        case "view":
            result = cmd_view(args)
        case "query":
            result = cmd_query(args)
        case "correlate":
            result = cmd_correlate(args)
        case "export":
            result = cmd_export(args)
        case _:
            print(f"Unknown command: {args.command}", file=sys.stderr)
            result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
