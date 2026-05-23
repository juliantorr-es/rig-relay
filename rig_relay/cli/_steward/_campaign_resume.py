"""Campaign completion and resume UX.

Exposes campaign completion state, unresolved findings, and next-action
recommendations. Does not add automated promotion, merge, publication,
or new mission generation.
"""

from __future__ import annotations

import json
from pathlib import Path

from rig_relay.cli._steward._campaign_models import CampaignState
from rig_relay.cli._steward._campaign_runtime import (
    build_campaign_state_dir,
    load_campaign_state,
)


def campaign_resume_info(campaign_id: str, root: Path) -> dict:
    """Return content-light resume and completion state.

    Never returns raw source, secrets, or confidential bodies.
    """
    state = load_campaign_state(campaign_id, root)

    if state is None:
        return _missing(campaign_id)

    state_dir = build_campaign_state_dir(campaign_id, root)
    completion_path = state_dir / "completion.v1.json"
    completion_exists = completion_path.exists()
    completion_data = None
    if completion_exists:
        try:
            completion_data = json.loads(completion_path.read_text())
        except json.JSONDecodeError:
            pass

    findings = _read_findings(state_dir)
    unresolved = [f for f in findings if f.get("status") != "resolved"]

    return {
        "campaign_id": state.campaign_id,
        "runnable": state.phase in {"running", "paused_for_blocker"},
        "halted": state.phase == "halted",
        "completed": state.phase == "completed",
        "phase": state.phase,
        "current_mission": state.current_mission_id,
        "completed_missions": state.completed_missions,
        "paused_missions": state.paused_missions,
        "pending_missions": state.pending_missions,
        "checkpoint_latest_pushed": (
            state.latest_pushed_sha == state.latest_checkpoint_sha
            and state.latest_pushed_sha is not None
        ),
        "latest_checkpoint_sha": state.latest_checkpoint_sha,
        "latest_pushed_sha": state.latest_pushed_sha,
        "halt_reason": state.halt_reason,
        "unresolved_finding_count": len(unresolved),
        "unresolved_finding_ids": [
            f.get("finding_id", f"finding-{i}") for i, f in enumerate(unresolved)
        ],
        "deferred_seam_count": 0,
        "completion_packet_generated": completion_exists,
        "human_promotion_required": (
            completion_data.get("human_promotion_required", True)
            if completion_data
            else True
        ),
        "next_action": _resume_next_action(state, len(unresolved)),
    }


def _read_findings(state_dir: Path) -> list[dict]:
    path = state_dir / "findings.v1.jsonl"
    if not path.exists():
        return []
    findings = []
    for line in path.read_text().strip().split("\n"):
        if line:
            try:
                findings.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return findings


def _missing(campaign_id: str) -> dict:
    return {"campaign_id": campaign_id, "exists": False}


def _resume_next_action(state: CampaignState, unresolved_count: int) -> str:
    if state.phase == "completed":
        return "human_review_and_manual_merge_decision"
    if state.phase == "halted":
        return f"halted: {state.halt_reason or 'human_review_required'}"
    if state.phase == "paused_for_blocker":
        return (
            f"{unresolved_count} unresolved finding(s). "
            "human_author_resolver_or_next_campaign_slice"
        )
    if state.phase == "running":
        return f"continue_mission: {state.current_mission_id}"
    if state.phase == "pending":
        return "ready_to_start"
    return f"unknown_phase: {state.phase}"
