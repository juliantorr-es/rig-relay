#!/usr/bin/env python3
"""Rig Relay Queue Planner — thin CLI wrapper.

Core implementation is in ``rig_relay.operational.commands.compute_queue_plan``.

Usage:
    uv run python scripts/rig_relay_queue_plan.py \\
        --queue .build/rig-relay/queue/work_queue.json \\
        --coordination-root .build/rig-relay/coordination \\
        --max-items 4 \\
        --output .build/rig-relay/queue/ready_plan.json

Content-light: never includes raw file contents, prompts, model outputs,
stdout/stderr bodies, or diffs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.operational.commands import DEFAULT_MAX_ITEMS, compute_queue_plan

DEFAULT_COORD_ROOT = (
    Path(__file__).resolve().parent.parent / ".build" / "rig-relay" / "coordination"
)
DEFAULT_QUEUE_DIR = (
    Path(__file__).resolve().parent.parent / ".build" / "rig-relay" / "queue"
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute a ready work plan from the pending work queue."
    )
    parser.add_argument(
        "--queue", type=Path, required=True, help="Path to the work queue JSON file."
    )
    parser.add_argument(
        "--coordination-root",
        type=Path,
        default=DEFAULT_COORD_ROOT,
        help="Coordination store root",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=DEFAULT_MAX_ITEMS,
        help="Maximum ready items to return",
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="Output path for the ready plan JSON"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.queue.is_file():
        print(f"Error: Queue file not found: {args.queue}")
        return 1

    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    plan = compute_queue_plan(
        queue, coordination_root=args.coordination_root, max_items=args.max_items
    )

    output_path = args.output or DEFAULT_QUEUE_DIR / "ready_plan.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    print(f"Ready plan written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
