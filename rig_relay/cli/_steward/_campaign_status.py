"""Campaign status read-only CLI surface.

Exposes campaign state, events, findings, checkpoints, pushes, and
completion status as content-light output. Never mutates campaign state.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from rig_relay.cli._steward._campaign_models import CampaignState
from rig_relay.cli._steward._campaign_runtime import (
    build_campaign_state_dir,
    load_campaign_state,
)


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in open(path))


def campaign_status(campaign_id: str, root: Path) -> dict:
    """Return a content-light campaign status projection.

    Never returns raw source, secrets, or confidential bodies.
    """
    state_dir = build_campaign_state_dir(campaign_id, root)
    state = load_campaign_state(campaign_id, root)

    if state is None:
        return {
            "campaign_id": campaign_id,
            "exists": False,
            "error": f"no state found for campaign '{campaign_id}'",
        }

    findings_count = _count_lines(state_dir / "findings.v1.jsonl")
    events_count = _count_lines(state_dir / "events.v1.jsonl")
    checkpoints_count = state.checkpoint_count
    pushes_count = state.push_count

    return {
        "campaign_id": state.campaign_id,
        "exists": True,
        "operating_mode": state.operating_mode,
        "phase": state.phase,
        "current_mission": state.current_mission_id,
        "completed_missions": state.completed_missions,
        "paused_missions": state.paused_missions,
        "pending_missions": state.pending_missions,
        "latest_checkpoint_sha": state.latest_checkpoint_sha,
        "latest_pushed_sha": state.latest_pushed_sha,
        "checkpoint_count": checkpoints_count,
        "push_count": pushes_count,
        "findings_count": findings_count,
        "events_count": events_count,
        "halt_reason": state.halt_reason,
        "halted": state.phase in {"halted"},
        "completed": state.phase == "completed",
        "awaiting_human_promotion": state.phase == "completed",
        "next_action": _next_action(state),
    }


def _next_action(state: CampaignState) -> str:
    if state.phase == "completed":
        return "human_review_and_promotion_required"
    if state.phase == "halted":
        return f"halted: {state.halt_reason or 'unknown'}. human_review_required"
    if state.phase == "paused_for_blocker":
        return "resolve_blocker_or_record_unresolved_finding"
    if state.phase == "running":
        return f"continue_mission: {state.current_mission_id}"
    return f"unknown_phase: {state.phase}"


_MIN_ARGS_FOR_STATUS = 2


def main() -> None:
    if len(sys.argv) < _MIN_ARGS_FOR_STATUS:
        print(json.dumps({"error": "usage: campaign-status <campaign-id>"}))
        sys.exit(1)
    campaign_id = sys.argv[1]
    root = Path.cwd()
    result = campaign_status(campaign_id, root)
    print(json.dumps(result, indent=2))
    if not result.get("exists"):
        sys.exit(1)


if __name__ == "__main__":
    main()
