"""Campaign completion packet.

Emitted at campaign completion or halt. Records execution order,
checkpoint SHAs, push SHAs, findings, and remaining seams.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rig_relay.cli._steward._campaign_models import (
    CampaignManifestExtension,
    CampaignState,
)
from rig_relay.cli._steward._campaign_runtime import save_completion_packet


def build_campaign_completion_packet(
    extension: CampaignManifestExtension, state: CampaignState, repo_root: Path
) -> dict:
    """Build a content-light campaign completion packet.

    Records execution order, checkpoints, pushes, findings, tests,
    and remaining seams. Never contains raw source, secrets, or
    confidential evidence.
    """
    execution_order = (
        state.completed_missions + state.paused_missions + state.pending_missions
    )

    # Compute a deterministic completion digest
    completion_digest = hashlib.sha256(
        json.dumps(
            {
                "campaign_id": extension.campaign_id,
                "execution_order": execution_order,
                "checkpoint_count": state.checkpoint_count,
                "push_count": state.push_count,
                "phase": state.phase,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    return {
        "campaign_id": extension.campaign_id,
        "operating_mode": extension.operating_mode,
        "execution_order": execution_order,
        "completed_missions": state.completed_missions,
        "paused_missions": state.paused_missions,
        "pending_missions": state.pending_missions,
        "resolver_reorder_history": state.resolver_reorder_history,
        "incidental_repair_history": state.incidental_repair_history,
        "accumulated_changed_paths": state.accumulated_changed_paths,
        "accumulated_diff_digest": state.accumulated_diff_digest,
        "checkpoint_count": state.checkpoint_count,
        "checkpoint_latest_sha": state.latest_checkpoint_sha or "",
        "push_count": state.push_count,
        "push_latest_sha": state.latest_pushed_sha or "",
        "refused_operation_counts": state.refused_operation_counts,
        "validation_summaries": state.validation_summaries,
        "phase": state.phase,
        "halt_reason": state.halt_reason,
        "completion_digest": completion_digest,
        "baseline_sha": state.baseline_sha,
        "branch": state.active_branch,
        "manifest_digest": state.manifest_digest,
        "checkpoint_performed": state.checkpoint_count > 0,
        "commit_performed": False,
        "promotion_performed": False,
        "push_performed": state.push_count > 0,
        "publication_performed": False,
        "external_transmission_performed": False,
        "human_promotion_required": True,
    }


def emit_campaign_completion(
    extension: CampaignManifestExtension, state: CampaignState, repo_root: Path
) -> Path:
    """Build and persist the campaign completion packet."""
    packet = build_campaign_completion_packet(extension, state, repo_root)
    save_completion_packet(extension.campaign_id, repo_root, packet)
    return (
        Path(".rig") / "relay" / "campaigns" / extension.campaign_id / "completion.json"
    )
