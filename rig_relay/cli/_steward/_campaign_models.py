"""Campaign runtime models for confidential autonomous campaign mode.

Extends the accepted campaign-contract substrate with runtime-specific
models for manifest loading, state management, and execution authority.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CampaignOperatingMode = Literal[
    "confidential_autonomous_campaign_with_private_checkpoint_push",
]

CampaignPhase = Literal[
    "pending",
    "running",
    "paused_for_blocker",
    "resolver_active",
    "repair_active",
    "halted",
    "completed",
]

CheckpointCadence = Literal["per_mission", "per_change", "manual"]

PushCadence = Literal["per_checkpoint", "per_mission", "manual"]


class CampaignManifestExtension(BaseModel):
    """Runtime extensions to the accepted campaign manifest.

    These fields are additive metadata that the runtime uses for
    execution authority. The accepted contract substrate validates
    the base manifest.
    """

    model_config = ConfigDict(extra="forbid")

    campaign_id: str = Field(min_length=1)
    operating_mode: CampaignOperatingMode
    lane_root_identity: str = Field(min_length=1)
    baseline_commit_sha: str = Field(min_length=1)
    assigned_local_branch: str = Field(min_length=1)
    assigned_remote_repository: str = Field(min_length=1)
    assigned_remote_branch: str = Field(min_length=1)
    private_checkpoint_push_authorized: bool
    checkpoint_cadence: CheckpointCadence
    push_cadence: PushCadence
    path_classification_registry_digest: str = Field(default="", min_length=0)
    allowed_validation_commands: list[str] = Field(default_factory=list)
    halt_policy: str = Field(default="stop_on_security_or_confidentiality")
    human_promotion_required: Literal[True]
    merge_to_main_allowed: Literal[False] = False
    publication_allowed: Literal[False] = False
    release_allowed: Literal[False] = False
    force_push_allowed: Literal[False] = False
    ref_deletion_allowed: Literal[False] = False
    tag_creation_allowed: Literal[False] = False


class CampaignCheckpointReceipt(BaseModel):
    """Content-light receipt for a campaign checkpoint commit."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.campaign_checkpoint_receipt.v1"
    receipt_id: str = Field(min_length=1)
    campaign_id: str = Field(min_length=1)
    checkpoint_sequence: int = Field(ge=0)
    commit_sha: str = Field(min_length=1)
    commit_message: str = Field(min_length=1)
    author_timestamp: str = Field(default="")
    branch: str = Field(min_length=1)
    manifest_digest: str = Field(min_length=1)
    mission_phase: str = Field(min_length=1)
    files_committed: list[str] = Field(default_factory=list)
    validation_status: str = Field(default="")
    event_hash: str = Field(default="")
    recovery_reason: str | None = None


class CampaignPushReceipt(BaseModel):
    """Content-light receipt for a campaign private-branch push."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.campaign_push_receipt.v1"
    receipt_id: str = Field(min_length=1)
    campaign_id: str = Field(min_length=1)
    push_sequence: int = Field(ge=0)
    remote_repository: str = Field(min_length=1)
    destination_branch: str = Field(min_length=1)
    pushed_head_sha: str = Field(min_length=1)
    pushed_to_sha: str = Field(default="")
    succeeded: bool
    refusal_reason: str | None = None
    fast_forward: bool = True
    force_pushed: bool = False
    tags_pushed: bool = False
    manifest_digest: str = Field(min_length=1)
    recovery_reason: str | None = None
    expected_predecessor: str | None = None


class CampaignState(BaseModel):
    """Runtime state projection for a campaign.

    This is derived from the append-only ledgers and may be
    rebuilt; it is not the authoritative record.
    """

    model_config = ConfigDict(extra="forbid")

    campaign_id: str = Field(min_length=1)
    operating_mode: CampaignOperatingMode
    phase: CampaignPhase
    lane_identity: str = Field(min_length=1)
    baseline_sha: str = Field(min_length=1)
    active_branch: str = Field(min_length=1)
    assigned_remote_branch: str = Field(min_length=1)
    current_mission_id: str | None = None
    completed_missions: list[str] = Field(default_factory=list)
    paused_missions: list[str] = Field(default_factory=list)
    pending_missions: list[str] = Field(default_factory=list)
    resolver_reorder_history: list[str] = Field(default_factory=list)
    incidental_repair_history: list[str] = Field(default_factory=list)
    accumulated_changed_paths: list[str] = Field(default_factory=list)
    accumulated_diff_digest: str = ""
    latest_checkpoint_sha: str | None = None
    latest_pushed_sha: str | None = None
    checkpoint_count: int = 0
    push_count: int = 0
    refused_operation_counts: dict[str, int] = Field(default_factory=dict)
    validation_summaries: list[str] = Field(default_factory=list)
    halt_reason: str | None = None
    manifest_digest: str = ""


def compute_manifest_digest(manifest_dict: dict) -> str:
    """Compute a deterministic digest of the campaign manifest."""
    return hashlib.sha256(
        json.dumps(manifest_dict, sort_keys=True).encode("utf-8")
    ).hexdigest()


def compute_campaign_state_digest(state: CampaignState) -> str:
    """Compute a deterministic digest of the campaign state."""
    return hashlib.sha256(
        json.dumps(state.model_dump(), sort_keys=True).encode("utf-8")
    ).hexdigest()


def build_campaign_state_dir(campaign_id: str, root: Path) -> Path:
    """Return the campaign state directory path."""
    return root / ".rig" / "relay" / "campaigns" / campaign_id
