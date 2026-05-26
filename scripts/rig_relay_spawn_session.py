#!/usr/bin/env python3
"""Rig Relay Spawn Session Planner — thin CLI wrapper.

Core implementation is in ``rig_relay.operational.commands.compute_spawn_plan``.

Usage:
    uv run python scripts/rig_relay_spawn_session.py \
        --mission-packet .build/rig-relay/missions/my_mission.json \
        --dry-run \
        --output .build/rig-relay/spawn/my_plan.json

    uv run python scripts/rig_relay_spawn_session.py \
        --mission-packet .build/rig-relay/missions/my_mission.json \
        --dry-run \
        --coordination-root .build/rig-relay/coordination \
        --max-parallel-sessions 4

Content-light: never includes raw file contents, prompts, model outputs,
stdout/stderr bodies, or diffs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rig_relay.operational.commands import (
    DEFAULT_MAX_PARALLEL_SESSIONS,
    compute_spawn_plan,
    validate_mission_packet,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COORD_ROOT = REPO_ROOT / ".build" / "rig-relay" / "coordination"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute a spawn plan from a mission packet."
    )
    parser.add_argument(
        "--mission-packet",
        type=Path,
        required=True,
        help="Path to the mission packet JSON file.",
    )
    parser.add_argument(
        "--coordination-root",
        type=Path,
        default=DEFAULT_COORD_ROOT,
        help="Coordination store root",
    )
    parser.add_argument(
        "--max-parallel-sessions",
        type=int,
        default=DEFAULT_MAX_PARALLEL_SESSIONS,
        help="Max parallel child sessions",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True, help="Plan only (default: on)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Request real session spawn (future — plan-only for now)",
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="Output path for the spawn plan JSON"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.mission_packet.is_file():
        print(
            f"Error: Mission packet not found: {args.mission_packet}", file=sys.stderr
        )
        return 1

    try:
        packet = json.loads(args.mission_packet.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading mission packet: {e}", file=sys.stderr)
        return 1

    # Validate first (optional, gives better error messages)
    packet_errors = validate_mission_packet(packet)
    if packet_errors:
        for err in packet_errors:
            print(f"  Validation error: {err}", file=sys.stderr)

    plan = compute_spawn_plan(
        packet,
        coordination_root=args.coordination_root,
        max_parallel_sessions=args.max_parallel_sessions,
    )

    output_path = args.output
    if output_path is None:
        mission_id = plan.get("mission_id", "unknown")
        output_path = (
            REPO_ROOT
            / ".build"
            / "rig-relay"
            / "spawn"
            / mission_id
            / "spawn_plan.json"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    status = "APPROVED" if plan["can_spawn"] else "REFUSED"
    print(f"Spawn plan: {status}")
    print(f"  Mission: {plan['mission_id']}")
    print(f"  Profile: {plan['agent_profile']}")
    if plan.get("refusal_code"):
        print(f"  Refusal: {plan['refusal_code']} — {plan.get('refusal_reason', '')}")
    print(f"  Active children: {plan.get('active_child_count', 0)}")
    print(f"  Available slots: {plan.get('available_child_slots', 0)}")
    print(f"  Output: {output_path.resolve()}")

    if args.execute:
        print(
            "NOTE: Real subprocess spawning is future work. --execute saved plan only.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
