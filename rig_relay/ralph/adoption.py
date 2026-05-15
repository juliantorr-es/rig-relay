"""Orchestrator adoption — proposes sealed Ralph lanes for review/adoption.

Adoption is a separate governed action from lane-start approval.
No merge, no git commands, no source mutation in this phase.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

ADOPTION_VERSION = "rig.ralph_adoption_proposal.v1"


class RalphAdoptionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = ADOPTION_VERSION
    proposal_id: str = Field(default_factory=lambda: str(uuid4()))
    source_ralph_lane_id: str = ""
    source_branch_name: str = ""
    source_head_sha: str | None = None
    review_bundle_sha256: str = ""
    target_kind: str = "user_review"
    target_lane_id: str | None = None
    target_branch_name: str | None = None
    relevance_score: float = 0.0
    relevance_reason: str = ""
    status: str = "proposed"
    merge_enabled: bool = False
    requires_human_approval: bool = True
    requires_orchestrator_acceptance: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def build_adoption_proposal(
    lane: Any,
    *,
    target_kind: str = "user_review",
    target_lane_id: str | None = None,
    relevance_score: float = 0.0,
    relevance_reason: str = "",
) -> RalphAdoptionProposal:
    """Build an adoption proposal from a sealed Ralph lane.

    If relevant to an orchestrator lane, target_kind=orchestrator_lane.
    If not, target_kind=user_review for later user inspection.
    No merge, no git commands.
    """
    requires_orch = target_kind == "orchestrator_lane" and target_lane_id is not None

    return RalphAdoptionProposal(
        source_ralph_lane_id=getattr(lane, "lane_id", ""),
        source_branch_name=getattr(lane, "branch_name", ""),
        source_head_sha=getattr(lane, "latest_commit_sha", None),
        review_bundle_sha256=getattr(lane, "review_bundle_sha256", ""),
        target_kind=target_kind,
        target_lane_id=target_lane_id,
        relevance_score=relevance_score,
        relevance_reason=relevance_reason,
        status="proposed",
        merge_enabled=False,
        requires_human_approval=True,
        requires_orchestrator_acceptance=requires_orch,
    )


__all__ = [
    "ADOPTION_VERSION",
    "RalphAdoptionProposal",
    "build_adoption_proposal",
]
