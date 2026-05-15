"""Ralph widget projection — pywebview widget state for background lanes.

Includes review session contract for when user reviews finished lanes.
Contract-only: no orchestrator execution, no merge, no git commands.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

WIDGET_VERSION = "rig.ui.ralph_widget.v1"
REVIEW_SESSION_VERSION = "rig.ralph_review_session.v1"


class RalphWidgetProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = WIDGET_VERSION
    background_enabled: bool = False
    active_lane_count: int = 0
    finished_lane_count: int = 0
    pending_review_count: int = 0
    blocked_lane_count: int = 0
    latest_completed_lane_id: str | None = None
    top_adoption_proposal_id: str | None = None
    risk_warning_count: int = 0
    execution_enabled: bool = False
    merge_enabled: bool = False
    available_actions: list[dict[str, str | bool]] = Field(default_factory=lambda: [
        {"action": "ralph_background_toggle_on", "label": "Enable background lanes", "requires_confirmation": True},
        {"action": "ralph_background_toggle_off", "label": "Disable background lanes", "requires_confirmation": True},
        {"action": "ralph_review_finished_lanes", "label": "Review finished lanes", "requires_confirmation": False},
        {"action": "ralph_lane_propose", "label": "Propose lane from candidate", "requires_confirmation": True},
    ])


class RalphReviewSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = REVIEW_SESSION_VERSION
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    pending_lane_ids: list[str] = Field(default_factory=list)
    include_review_bundles: bool = True
    include_decision_receipts: bool = True
    include_validation_results: bool = True
    include_diffs: bool = False
    mode: str = "explain_only"
    execution_enabled: bool = False
    merge_enabled: bool = False


def build_widget_projection(
    background_enabled: bool = False,
    active_lane_count: int = 0,
    finished_lane_count: int = 0,
    pending_review_count: int = 0,
    blocked_lane_count: int = 0,
    latest_completed_lane_id: str | None = None,
    top_adoption_proposal_id: str | None = None,
) -> RalphWidgetProjection:
    return RalphWidgetProjection(
        background_enabled=background_enabled,
        active_lane_count=active_lane_count,
        finished_lane_count=finished_lane_count,
        pending_review_count=pending_review_count,
        blocked_lane_count=blocked_lane_count,
        latest_completed_lane_id=latest_completed_lane_id,
        top_adoption_proposal_id=top_adoption_proposal_id,
        execution_enabled=False,
        merge_enabled=False,
    )


__all__ = [
    "RalphReviewSessionRequest",
    "RalphWidgetProjection",
    "WIDGET_VERSION",
    "build_widget_projection",
]
