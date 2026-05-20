#!/usr/bin/env python3
"""Rig Event Fabric DuckDB Projection CLI.

Read-side projection over the event fabric JSONL using DuckDB. Produces a
structured report artifact and optional derived summary files.

Usage:
    uv run python scripts/rig_event_fabric_duckdb_projection.py
    uv run python scripts/rig_event_fabric_duckdb_projection.py --summary
    uv run python scripts/rig_event_fabric_duckdb_projection.py --log-paths .build/rig-relay/events/event_fabric_v1.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.events.duckdb_projection import (
    DEFAULT_EVENT_FABRIC_PATH,
    build_event_fabric_duckdb_projection,
)

DEFAULT_OUTPUT_PATH = Path(
    "docs/json/governance/event_fabric_duckdb_projection_report_v1.v1.json"
)
DEFAULT_DERIVED_DIR = Path(".build/rig-relay/derived")


def _resolve_log_paths(raw: list[str] | None) -> list[Path]:
    if raw:
        return [Path(p) for p in raw]
    return [DEFAULT_EVENT_FABRIC_PATH]


def _write_derived(report: dict, derived_dir: Path) -> None:
    derived_dir.mkdir(parents=True, exist_ok=True)

    event_type_counts = report.get("event_type_counts", {})
    if event_type_counts:
        derived_path = derived_dir / "event_fabric_event_type_counts.v1.json"
        derived_path.write_text(
            json.dumps(event_type_counts, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    resource_pressure = report.get("resource_pressure_summary", {})
    if resource_pressure:
        derived_path = derived_dir / "event_fabric_resource_pressure_summary.v1.json"
        derived_path.write_text(
            json.dumps(resource_pressure, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rig Event Fabric DuckDB Projection — read-side only."
    )
    parser.add_argument(
        "--log-paths",
        nargs="*",
        default=None,
        help="JSONL log paths (default: .build/rig-relay/events/event_fabric_v1.jsonl)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output path for the projection report (default: docs/json/governance/event_fabric_duckdb_projection_report_v1.v1.json)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        default=False,
        help="Print a compact summary to stdout after writing the report",
    )
    parser.add_argument(
        "--derived-dir",
        type=Path,
        default=None,
        help="Optional directory for derived summary JSON files (default: .build/rig-relay/derived/)",
    )
    args = parser.parse_args()

    log_paths = _resolve_log_paths(args.log_paths)

    report = build_event_fabric_duckdb_projection(log_paths)

    output_path: Path = args.output_json
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    derived_dir: Path = (
        args.derived_dir if args.derived_dir is not None else DEFAULT_DERIVED_DIR
    )
    _write_derived(report, derived_dir)

    if args.summary:
        status = report.get("status", "unknown")
        event_count = report.get("event_count", 0)
        print(f"Status: {status}")
        print(f"Event count: {event_count}")
        if status == "no_input_logs":
            print("No event fabric JSONL files found.")
        elif status == "duckdb_not_available":
            print("DuckDB is not available. Install duckdb to enable projections.")
        elif status in {"succeeded", "partial"}:
            event_types = report.get("event_type_counts", {})
            if event_types:
                print("\nTop event types:")
                for et, cnt in list(event_types.items())[:10]:
                    print(f"  {et}: {cnt}")
            producer_counts = report.get("producer_counts", {})
            if producer_counts:
                print("\nProducers:")
                for p, cnt in sorted(producer_counts.items()):
                    print(f"  {p}: {cnt}")
            print(f"\nReport written to: {output_path}")
            d = derived_dir if args.derived_dir is not None else DEFAULT_DERIVED_DIR
            print(f"Derived files written to: {d}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
