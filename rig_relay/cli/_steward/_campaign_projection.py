"""Campaign operating picture projection for static docs/UI surface.

Renders content-light campaign state for read-side inspection.
Never renders raw source, prompts, secrets, confidential evidence bodies,
crosswalks, patent/legal material, or provider-context bodies.
"""

from __future__ import annotations

from pathlib import Path

from rig_relay.cli._steward._campaign_runtime import load_campaign_state


def campaign_projection(campaign_id: str, root: Path) -> dict:
    """Build a content-light campaign operating picture.

    Read-side projection only. Never mutates state or reads
    confidential source.
    """
    state = load_campaign_state(campaign_id, root)
    if state is None:
        return {"campaign_id": campaign_id, "exists": False}

    return {
        "campaign_id": state.campaign_id,
        "exists": True,
        "operating_mode": state.operating_mode,
        "phase": state.phase,
        "current_mission": state.current_mission_id,
        "completed_missions": state.completed_missions,
        "paused_missions": state.paused_missions,
        "pending_missions": state.pending_missions,
        "checkpoint_count": state.checkpoint_count,
        "push_count": state.push_count,
        "latest_checkpoint_sha": state.latest_checkpoint_sha,
        "latest_pushed_sha": state.latest_pushed_sha,
        "checkpoint_push_aligned": (
            state.latest_checkpoint_sha == state.latest_pushed_sha
            and state.latest_checkpoint_sha is not None
        ),
        "findings_muted": False,
        "halted": state.phase == "halted",
        "halt_reason": state.halt_reason,
        "completed": state.phase == "completed",
        "human_review_required": True,
        "refused_operation_counts": state.refused_operation_counts,
        "resolver_reorder_events": state.resolver_reorder_history,
        "incidental_repairs": state.incidental_repair_history,
        "deferred_seams_open": [
            "provider_transport_not_implemented",
            "live_steward_dispatch_canary_only",
        ],
    }


def campaign_projection_html(campaign_id: str, root: Path) -> str:
    """Render a minimal content-light HTML projection.

    Never includes raw source, secrets, or confidential content.
    """
    data = campaign_projection(campaign_id, root)
    if not data["exists"]:
        return f"<p>Campaign '{campaign_id}' not found.</p>"

    status_class = {
        "running": "active",
        "completed": "done",
        "halted": "halted",
        "paused_for_blocker": "blocked",
        "pending": "pending",
    }.get(data["phase"], "unknown")

    return f"""<div class="campaign-{status_class}">
  <h2>Campaign: {data["campaign_id"]}</h2>
  <p>Phase: {data["phase"]} | Mode: {data["operating_mode"]}</p>
  <p>Mission: {data["current_mission"] or "none"}</p>
  <p>Completed: {len(data["completed_missions"])} | Paused: {len(data["paused_missions"])} | Pending: {len(data["pending_missions"])}</p>
  <p>Checkpoints: {data["checkpoint_count"]} (latest: {data["latest_checkpoint_sha"][:8] if data["latest_checkpoint_sha"] else "none"})</p>
  <p>Pushes: {data["push_count"]} (aligned: {str(data["checkpoint_push_aligned"]).lower()})</p>
  <p>Human review required: {str(data["human_review_required"]).lower()}</p>
</div>"""
