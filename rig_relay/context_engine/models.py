"""Context engine models — typed projections and candidates.

Defines:
  - ProjectUnderstandingProjection: private, operator-facing representation
  - PublishableProjectProfileCandidate: public-safe, awaiting approval
  - DeveloperCorpusIndex: private index for portfolio synthesis
  - SanitizedContextPacket: bounded, provenance-rich context payload
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.context_engine.provenance import (
    ApprovalStatus,
    ApprovedContent,
    EvidenceDerivedFact,
    GeneratedClaim,
    PrivacyDisposition,
    SourceDerivedFact,
)


class ProjectIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str
    repository_url_digest: str = Field(description="SHA256 of repository URL.")
    head_sha: str = ""
    branch: str = ""
    remotes_count: int = 0
    is_github_backed: bool = False
    is_local_only: bool = True
    git_root_digest: str = ""


class TechnologySignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    build_systems: list[str] = Field(default_factory=list)
    package_managers: list[str] = Field(default_factory=list)
    test_frameworks: list[str] = Field(default_factory=list)
    lint_tools: list[str] = Field(default_factory=list)
    type_checkers: list[str] = Field(default_factory=list)
    formatters: list[str] = Field(default_factory=list)
    protocols: list[str] = Field(default_factory=list)


class PublicationAssets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    has_readme: bool = False
    has_license: bool = False
    has_contributing: bool = False
    has_changelog: bool = False
    has_security_policy: bool = False
    has_documentation_site: bool = False
    screenshot_count: int = 0
    demo_count: int = 0
    publication_ready_asset_count: int = 0


class TestSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_framework_detected: bool = False
    test_command_detected: bool = False
    ci_test_pipeline_detected: bool = False
    coverage_tool_detected: bool = False
    test_directory_detected: bool = False


class UncertaintyMarkers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indeterminate_count: int = 0
    low_confidence_count: int = 0
    needs_investigation_count: int = 0


class WithheldItemsSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = 0
    reasons: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)


class IntakeDependencyStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    j0_intake_boundary: str = "fixture"
    k0_investigation_boundary: str = "fixture"
    j0_intake_available: bool = False
    k0_investigation_available: bool = False


class ProjectUnderstandingProjection(BaseModel):
    """Private, operator-facing projection of project understanding.

    Contains full-fidelity structural facts, evidence facts, and
    generated claims. Never published publicly. Internal-only.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.project_understanding.v1"
    projection_id: str
    project_identity: ProjectIdentity
    structural_facts: list[SourceDerivedFact] = Field(default_factory=list)
    evidence_facts: list[EvidenceDerivedFact] = Field(default_factory=list)
    generated_claims: list[GeneratedClaim] = Field(default_factory=list)
    approved_content: list[ApprovedContent] = Field(default_factory=list)
    technology_signals: TechnologySignals = Field(default_factory=TechnologySignals)
    publication_assets: PublicationAssets = Field(default_factory=PublicationAssets)
    test_signals: TestSignals = Field(default_factory=TestSignals)
    bootstrap_gaps: list[str] = Field(default_factory=list)
    withheld_items: WithheldItemsSummary = Field(default_factory=WithheldItemsSummary)
    uncertainty: UncertaintyMarkers = Field(default_factory=UncertaintyMarkers)
    intake_dependency_status: IntakeDependencyStatus = Field(
        default_factory=IntakeDependencyStatus
    )
    privacy_class: PrivacyDisposition = PrivacyDisposition.INTERNAL_ONLY
    content_light_guarantee: bool = True
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    projection_digest: str = ""

    def compute_digest(self) -> str:
        canonical = (
            f"{self.schema_version}:{self.projection_id}:"
            f"{self.project_identity.project_name}:"
            f"{self.project_identity.head_sha}"
        )
        return f"sha256:{sha256(canonical.encode()).hexdigest()}"


class PublicStructuralFact(BaseModel):
    """Public-safe subset of a structural fact — no source paths or methods."""

    model_config = ConfigDict(extra="forbid")

    fact_id: str
    category: str
    value: str
    confidence: str = "high"


class ProjectPageIdentity(BaseModel):
    """Public-safe project identity for the project page."""

    model_config = ConfigDict(extra="forbid")

    project_name: str
    tagline: str = ""
    current_milestone: str = ""
    product_identity_blurb: str = ""
    blurb_approval_status: ApprovalStatus = ApprovalStatus.PROPOSED


class StatusOverview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_status: str = "alpha"
    implemented_count: int = 0
    planned_count: int = 0
    evidence_backed: bool = True


class AccomplishmentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    receipt_ref: str = ""
    status: str = "proposed"


class Accomplishments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AccomplishmentItem] = Field(default_factory=list)
    total_receipts_referenced: int = 0


class ReleasedBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boundary_name: str
    release_status: str = "planned"
    consuming_surfaces: list[str] = Field(default_factory=list)


class MissionTimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    title: str
    status: str = "planned"
    completed_at: datetime | None = None


class GeneratedNarrative(BaseModel):
    """A generated narrative section — marked proposed, not fact."""

    model_config = ConfigDict(extra="forbid")

    narrative: str = ""
    approval_status: ApprovalStatus = ApprovalStatus.PROPOSED
    basis_fact_ids: list[str] = Field(default_factory=list)


class RedactionLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items_withheld: int = 0
    items_redacted: int = 0
    reasons: list[str] = Field(default_factory=list)


class PublicationReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready_for_publication: bool = False
    missing_sections: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class PublishableProjectProfileCandidate(BaseModel):
    """Public-safe project profile candidate awaiting developer approval.

    Grounded in source-derived structural facts and evidence-derived
    operational facts. Generated interpretations are explicitly marked
    proposed. No private repository contents, secrets, or internal-only
    artifacts may appear.

    Consumed by the E0 ProjectPagePublicationProjection surface and
    the future static publication compiler.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.publishable_project_profile_candidate.v1"
    candidate_id: str
    project_identity: ProjectPageIdentity
    structural_facts_public: list[PublicStructuralFact] = Field(default_factory=list)
    technology_capabilities: TechnologySignals = Field(
        default_factory=TechnologySignals
    )
    status_overview: StatusOverview = Field(default_factory=StatusOverview)
    accomplishments: Accomplishments = Field(default_factory=Accomplishments)
    architecture_overview: dict[str, str] = Field(default_factory=dict)
    released_boundaries: list[ReleasedBoundary] = Field(default_factory=list)
    mission_timeline: list[MissionTimelineEntry] = Field(default_factory=list)
    generated_narrative_sections: dict[str, GeneratedNarrative] = Field(
        default_factory=dict
    )
    approval_status: ApprovalStatus = ApprovalStatus.PROPOSED
    redaction_log: RedactionLog = Field(default_factory=RedactionLog)
    publication_readiness: PublicationReadiness = Field(
        default_factory=PublicationReadiness
    )
    privacy_class: PrivacyDisposition = PrivacyDisposition.PUBLIC_SAFE
    content_light_guarantee: bool = True
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    candidate_digest: str = ""

    def compute_digest(self) -> str:
        canonical = (
            f"{self.schema_version}:{self.candidate_id}:"
            f"{self.project_identity.project_name}"
        )
        return f"sha256:{sha256(canonical.encode()).hexdigest()}"


class ProjectReference(BaseModel):
    """Lightweight project reference for the developer corpus index."""

    model_config = ConfigDict(extra="forbid")

    project_ref_id: str
    project_name: str
    repository_url_digest: str = ""
    profile_approval_status: str = "not_yet_generated"
    portfolio_eligible: bool = False
    technology_signals: TechnologySignals = Field(default_factory=TechnologySignals)
    case_study_eligible: bool = False
    released_boundary_count: int = 0
    last_updated: datetime | None = None
    profile_candidate_digest: str = ""


class TechnologyIndex(BaseModel):
    """Cross-project technology aggregation for portfolio synthesis."""

    model_config = ConfigDict(extra="forbid")

    languages: dict[str, list[str]] = Field(default_factory=dict)
    frameworks: dict[str, list[str]] = Field(default_factory=dict)
    protocols: dict[str, list[str]] = Field(default_factory=dict)


class DeveloperCorpusIndex(BaseModel):
    """Private aggregation index of approved or candidate project references.

    For later portfolio synthesis. Does NOT produce a public developer
    profile — that is the portfolio site's responsibility.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.developer_corpus_index.v1"
    corpus_id: str
    project_references: list[ProjectReference] = Field(default_factory=list)
    technology_index: TechnologyIndex = Field(default_factory=TechnologyIndex)
    profile_ready_count: int = 0
    candidate_count: int = 0
    total_projects_indexed: int = 0
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))
    portfolio_synthesis_status: str = "not_started"
    privacy_class: PrivacyDisposition = PrivacyDisposition.INTERNAL_ONLY
    content_light_guarantee: bool = True
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    corpus_digest: str = ""

    def compute_digest(self) -> str:
        canonical = (
            f"{self.schema_version}:{self.corpus_id}:{self.total_projects_indexed}"
        )
        return f"sha256:{sha256(canonical.encode()).hexdigest()}"


class TokenBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_tokens_available: int = 4096
    tokens_consumed: int = 0
    tokens_remaining: int = 4096
    budget_warnings: list[str] = Field(default_factory=list)


class ProvenanceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref_type: str = Field(
        description="structural_fact, evidence_fact, investigation_ref"
    )
    ref_id: str = ""
    confidence: str = "medium"
    source_digest: str = ""


class ForbiddenContentCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool = True
    checked_fields: list[str] = Field(
        default_factory=lambda: [
            f"sha256:{sha256(k.encode()).hexdigest()[:16]}"
            for k in [
                "raw_file_contents",
                "raw_prompt_text",
                "model_output_text",
                "stdout_bodies",
                "stderr_bodies",
                "secrets",
                "raw_private_code",
            ]
        ]
    )
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConsumptionHints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_kind: str = "codebase_context"
    intended_consumer: str = "agent_loop"
    refresh_after_sha_change: bool = True
    stale_if_head_differs: bool = True


class ContextSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    test_frameworks: list[str] = Field(default_factory=list)
    build_systems: list[str] = Field(default_factory=list)
    project_type_hint: str = ""
    subsystem_count: int = 0
    file_count: int = 0
    has_documentation: bool = False
    has_tests: bool = False
    has_ci: bool = False


class SanitizedContextPacket(BaseModel):
    """Bounded, provenance-rich context payload for AgentLoop or local inference.

    Deterministic, digest-bound, content-light. Contains no raw
    repository contents, secrets, tokens, or private paths.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.sanitized_context_packet.v1"
    packet_id: str
    project_identity_hash: str = ""
    context_summary: ContextSummary = Field(default_factory=ContextSummary)
    token_budget: TokenBudget = Field(default_factory=TokenBudget)
    provenance_references: list[ProvenanceReference] = Field(default_factory=list)
    redaction_summary: RedactionLog = Field(default_factory=RedactionLog)
    forbidden_content_check: ForbiddenContentCheck = Field(
        default_factory=ForbiddenContentCheck
    )
    consumption_hints: ConsumptionHints = Field(default_factory=ConsumptionHints)
    privacy_class: PrivacyDisposition = PrivacyDisposition.PUBLIC_SAFE
    content_light_guarantee: bool = True
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    packet_digest: str = ""

    def compute_digest(self) -> str:
        canonical = (
            f"{self.schema_version}:{self.packet_id}:{self.project_identity_hash}"
        )
        return f"sha256:{sha256(canonical.encode()).hexdigest()}"


class ProjectPageCandidate(BaseModel):
    """Convenience wrapper: binds a profile candidate to its Gridline projection."""

    model_config = ConfigDict(extra="forbid")

    profile_candidate: PublishableProjectProfileCandidate

    @property
    def digest(self) -> str:
        return self.profile_candidate.compute_digest()


__all__ = [
    "AccomplishmentItem",
    "Accomplishments",
    "ConsumptionHints",
    "ContextSummary",
    "DeveloperCorpusIndex",
    "ForbiddenContentCheck",
    "GeneratedNarrative",
    "IntakeDependencyStatus",
    "MissionTimelineEntry",
    "ProjectIdentity",
    "ProjectPageCandidate",
    "ProjectPageIdentity",
    "ProjectReference",
    "ProjectUnderstandingProjection",
    "ProvenanceReference",
    "PublicStructuralFact",
    "PublicationAssets",
    "PublicationReadiness",
    "PublishableProjectProfileCandidate",
    "RedactionLog",
    "ReleasedBoundary",
    "SanitizedContextPacket",
    "StatusOverview",
    "TechnologyIndex",
    "TechnologySignals",
    "TestSignals",
    "TokenBudget",
    "UncertaintyMarkers",
    "WithheldItemsSummary",
]
