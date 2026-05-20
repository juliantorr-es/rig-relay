#!/usr/bin/env python3
"""Rig Relay Spiderweb Mission Topology View CLI.

Consumes derived DuckDB projection reports and builds a governed topology projection.
Content-light. No raw event payloads. No mutation authority.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    REPO_ROOT
    / ".build"
    / "rig-relay"
    / "derived"
    / "mission_topology_projection.v1.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-event-fabric-topology-projection",
        description="Spiderweb Mission Topology Projection v1 from derived event-fabric artifacts.",
    )
    parser.add_argument(
        "--duckdb-report",
        type=Path,
        default=None,
        help="Path to DuckDB projection report JSON.",
    )
    parser.add_argument(
        "--pressure-summary",
        type=Path,
        default=None,
        help="Path to resource pressure summary JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output topology projection path.",
    )
    parser.add_argument("--summary", action="store_true", help="Print compact summary.")
    args = parser.parse_args(argv)

    from rig_relay.events.topology_projection import build_mission_topology_projection

    proj = build_mission_topology_projection(
        duckdb_report_path=args.duckdb_report,
        pressure_summary_path=args.pressure_summary,
    )
    out = args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(proj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    if args.summary:
        nodes = proj.get("nodes", [])
        strand = proj.get("strand_states", {})
        pressure = proj.get("resource_pressure", {})
        rows = [
            ("status", proj.get("status")),
            ("nodes", len(nodes)),
            ("active_strands", strand.get("active_count", 0)),
            ("no_input_strands", strand.get("no_input_count", 0)),
            ("degraded_strands", strand.get("degraded_count", 0)),
            ("reconnect_pressure", pressure.get("reconnect_pressure")),
            ("queue_pressure", pressure.get("queue_pressure")),
            ("consumer_errors", pressure.get("consumer_errors")),
            ("read_side_only", proj.get("read_side_only")),
            ("mutation_authority", proj.get("mutation_authority")),
            ("output", str(out)),
        ]
        width = max(len(label) for label, _ in rows)
        for label, value in rows:
            print(f"{label:<{width}}  {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
