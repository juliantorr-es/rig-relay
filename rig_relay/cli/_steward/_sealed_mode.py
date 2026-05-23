"""Sealed Confidential Steward Workspace Mode configuration."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SealedWorkspaceMode(BaseModel):
    """Configuration for a sealed confidential workspace (non-promoting)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confidential_context_egress_required: bool = True
    write_scope: str = "isolated_lane_only"
    checkpoint_allowed: bool = False
    commit_allowed: bool = False
    promotion_allowed: bool = False
    push_allowed: bool = False
    publish_allowed: bool = False
    upload_allowed: bool = False
    public_render_allowed: bool = False
    telemetry_contribution_allowed: bool = False
    real_provider_invocation_allowed_in_v1_tests: bool = False
    human_promotion_required: bool = True
    external_authority_broker_required_for_future_autonomous_commit: bool = True
