"""Gridline projection for the context engine.

Produces typed, content-light projections suitable for rendering
in the Gridline Interface (native desktop cockpit). These projections
are read-only, disposable, and must be reconstructable from canonical
evidence. Never contains raw repository contents or private paths.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.context_engine.provenance import ApprovalStatus


class ProjectStudyStatus(StrEnum):
    NOT_STUDIED = "not_studied"
    STUDYING = "studying"
    STUDY_COMPLETE = "study_complete"
    CANDIDATE_GENERATED = "candidate_generated"
    APPROVED = "approved"
    PUBLISHED = "published"


class PortfolioEligibilityState(StrEnum):
    NOT_INCLUDED = "not_included"
    CANDIDATE = "candidate"
    APPROVED_FOR_LATER_AGGREGATION = "approved_for_later_aggregation"


class GridlineProjectUnderstandingProjection(BaseModel):
    """Content-light projection for the Gridline Interface.

    Renders project identity, study status, discovered facts with
    provenance, public-ready assets, withheld material counts,
    draft narrative status, bootstrap gaps, context packet readiness,
    and portfolio eligibility.

    Never contains raw repository contents, private paths, or
    internal-only canonical evidence details.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.context_engine.gridline_projection.v1"
    projection_id: str
    project_name: str
    study_status: ProjectStudyStatus = ProjectStudyStatus.NOT_STUDIED
    head_sha: str = ""
    branch: str = ""

    facts_discovered: int = 0
    facts_with_provenance: int = 0
    fact_categories: list[str] = Field(default_factory=list)

    languages_detected: list[str] = Field(default_factory=list)
    frameworks_detected: list[str] = Field(default_factory=list)
    test_frameworks_detected: list[str] = Field(default_factory=list)

    public_ready_assets: list[str] = Field(default_factory=list)
    public_ready_asset_count: int = 0

    withheld_material_count: int = 0
    withheld_reasons: list[str] = Field(default_factory=list)

    draft_narrative_count: int = 0
    draft_narrative_awaiting_approval: int = 0

    bootstrap_gaps: list[str] = Field(default_factory=list)

    context_packet_ready: bool = False
    context_packet_digest: str = ""

    portfolio_eligibility: PortfolioEligibilityState = (
        PortfolioEligibilityState.NOT_INCLUDED
    )

    approval_status: ApprovalStatus = ApprovalStatus.PROPOSED

    recommendation: str = ""

    content_light_guarantee: bool = True
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def build_gridline_project_understanding_projection(
    projection_id: str,
    project_name: str,
    head_sha: str = "",
    branch: str = "",
    fact_count: int = 0,
    fact_categories: list[str] | None = None,
    languages_detected: list[str] | None = None,
    frameworks_detected: list[str] | None = None,
    test_frameworks_detected: list[str] | None = None,
    public_assets: list[str] | None = None,
    withheld_count: int = 0,
    withheld_reasons: list[str] | None = None,
    draft_count: int = 0,
    draft_awaiting: int = 0,
    bootstrap_gaps: list[str] | None = None,
    context_packet_ready: bool = False,
    context_packet_digest: str = "",
    portfolio_eligible: PortfolioEligibilityState = PortfolioEligibilityState.NOT_INCLUDED,
    approval_status: ApprovalStatus = ApprovalStatus.PROPOSED,
) -> GridlineProjectUnderstandingProjection:
    return GridlineProjectUnderstandingProjection(
        projection_id=projection_id,
        project_name=project_name,
        head_sha=head_sha,
        branch=branch,
        facts_discovered=fact_count,
        facts_with_provenance=fact_count,
        fact_categories=fact_categories or [],
        languages_detected=languages_detected or [],
        frameworks_detected=frameworks_detected or [],
        test_frameworks_detected=test_frameworks_detected or [],
        public_ready_assets=public_assets or [],
        public_ready_asset_count=len(public_assets) if public_assets else 0,
        withheld_material_count=withheld_count,
        withheld_reasons=withheld_reasons or [],
        draft_narrative_count=draft_count,
        draft_narrative_awaiting_approval=draft_awaiting,
        bootstrap_gaps=bootstrap_gaps or [],
        context_packet_ready=context_packet_ready,
        context_packet_digest=context_packet_digest,
        portfolio_eligibility=portfolio_eligible,
        approval_status=approval_status,
        recommendation=_derive_recommendation(
            context_packet_ready, approval_status, bootstrap_gaps or []
        ),
    )


def _derive_recommendation(
    context_packet_ready: bool,
    approval_status: ApprovalStatus,
    bootstrap_gaps: list[str],
) -> str:
    if approval_status == ApprovalStatus.APPROVED:
        return "Project profile approved — ready for publication."
    if context_packet_ready:
        return "Context packet ready — project can be consumed by AgentLoop."
    if bootstrap_gaps:
        return f"Bootstrap gaps detected: {', '.join(bootstrap_gaps[:3])}. Run intake study first."
    return "Project intake study recommended before context assembly."


__all__ = [
    "GridlineProjectUnderstandingProjection",
    "PortfolioEligibilityState",
    "ProjectStudyStatus",
    "build_gridline_project_understanding_projection",
]
