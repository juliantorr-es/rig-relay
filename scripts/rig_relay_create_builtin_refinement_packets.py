#!/usr/bin/env python3
"""Create mission packets from built-in tool refinement backlog — thin CLI wrapper.

Core implementation in ``rig_relay.operational.refinement``.

Usage:
    uv run python scripts/rig_relay_create_builtin_refinement_packets.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.operational.refinement import generate_refinement_packets

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKLOG = (
    REPO_ROOT
    / ".build"
    / "rig-relay"
    / "derived"
    / "builtin_tool_refinement_backlog.jsonl"
)
DEFAULT_REPORT = (
    REPO_ROOT / ".build" / "rig-relay" / "reports" / "built-in-tool-refinement.md"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".build" / "rig-relay" / "refinement-packets"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backlog", type=Path, default=DEFAULT_BACKLOG)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--priority", default="")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true", default=False)
    args = parser.parse_args()

    priority_set = {p.strip() for p in args.priority.split(",") if p.strip()} or None
    dry_run = not args.execute

    packet_paths, warnings = generate_refinement_packets(
        backlog=args.backlog,
        report=args.report,
        output_dir=args.output_dir,
        limit=args.limit,
        priority_filter=priority_set,
        dry_run=dry_run,
    )

    print(f"Generated {len(packet_paths)} packet(s) (dry-run={dry_run}).")
    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"  - {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
