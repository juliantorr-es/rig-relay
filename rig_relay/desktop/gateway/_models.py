"""Developer studio gateway models — Lane S2 (hardened from O0).

Typed aggregate projection aggregating J0/K0/L0/M0 service state into
a single frontend-safe envelope. Every field carries explicit provenance:
canonical fact, derived projection, generated proposal, review-required
draft, approval state, controlled-boundary proof, fixture status, refused
state, or corrupt/untrusted state.

Content-light: hashes, counts, statuses, labels, and SHA256 digests only.
Never contains raw file contents, secrets, tokens, unrestricted paths,
raw model payloads, or private identifying data.

Each section carries an authority_state derived from canonical evidence
(not from hardcoded labels). The GatewayAuthorityReport aggregates these
into a single evidence-backed authority picture.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

_DEVELOPER_STUDIO_SCHEMA = "rig.relay.developer_studio_projection.v1"


# ── Provenance ───────────────────────────────────────────────────────


class ProvenanceClass(StrEnum):
    CANONICAL_FACT = "canonical_fact"
    DERIVED_PROJECTION = "derived_projection"
    GENERATED_PROPOSAL = "generated_proposal"
    REVIEW_REQUIRED_DRAFT = "review_required_draft"
    APPROVED_CONTENT = "approved_content"
    CONTROLLED_BOUNDARY_PROOF = "controlled_boundary_proof"
    FIXTURE_DEFERRED = "fixture_deferred"
    REFUSED = "refused"
    CORRUPT_UNTRUSTED = "corrupt_untrusted"


class TrustState(StrEnum):
    TRUSTED_LIVE = "trusted_live"
    CONTROLLED_BOUNDARY = "controlled_boundary"
    FIXTURE = "fixture"
    DEFERRED = "deferred"
    REFUSED = "refused"
    CORRUPT = "corrupt"


# ── J0: GitHub Workspace ─────────────────────────────────────────────


class J0ConnectionProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.CANONICAL_FACT
    trust_state: TrustState = TrustState.CONTROLLED_BOUNDARY
    authority_state: str = "controlled_boundary"
    degraded_reason: str = ""
    connection_state: str = "disconnected"
    installation_id_hash: str = ""
    token_available: bool = False
    accessible_repository_count: int = 0
    live_installation_verified: bool = False
    errors: list[str] = Field(default_factory=list)


class J0RepositoryProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    repository_hash: str = ""
    owner: str = ""
    name: str = ""
    full_name: str = ""
    description_hash: str | None = None
    visibility: str = ""
    default_branch: str = ""
    has_pages: bool = False
    intake_state: str = "unknown"
    selected: bool = False
    import_state: str = ""
    local_path_digest: str = ""
    head_sha: str = ""
    branch: str = ""
    publication_readiness_state: str = "unknown"
    pages_action_state: str = "planned"
    pages_action_requires_approval: bool = True
    error_kind: str | None = None


class J0WorkspaceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    authority_state: str = "missing"
    degraded_reason: str = ""
    available: bool = False
    connection: J0ConnectionProjection = Field(default_factory=J0ConnectionProjection)
    repositories: list[J0RepositoryProjection] = Field(default_factory=list)
    selected_count: int = 0
    imported_count: int = 0
    publishable_count: int = 0
    total_discovered: int = 0


# ── K0: Operator Sessions ───────────────────────────────────────────


class K0SessionProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    session_id: str = ""
    repository_label: str = ""
    purpose: str = ""
    status: str = "opened"
    phase: str = "idle"
    agent_profile_name: str = ""
    tool_call_count: int = 0
    tool_success_count: int = 0
    tool_refusal_count: int = 0
    tool_failure_count: int = 0
    proposal_count: int = 0
    proposal_dispositions: dict[str, int] = Field(default_factory=dict)
    refusal_count: int = 0
    pending_decisions: list[str] = Field(default_factory=list)
    blocked_capabilities: list[str] = Field(default_factory=list)
    error_message: str | None = None
    created_at: str = ""
    updated_at: str = ""


class K0OperatorProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    authority_state: str = "missing"
    degraded_reason: str = ""
    available: bool = False
    active_sessions: list[K0SessionProjection] = Field(default_factory=list)
    total_sessions: int = 0
    active_session_count: int = 0
    refused_session_count: int = 0
    proposal_pending_count: int = 0
    deferred_integrations: list[str] = Field(default_factory=list)
    recovery_materialization_available: bool = False


# ── L0: Project Understanding ───────────────────────────────────────


class L0StudyProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    study_status: str = "not_studied"
    project_name: str = ""
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
    profile_candidate_ready: bool = False
    profile_candidate_digest: str = ""
    portfolio_eligibility: str = "not_included"
    approval_status: str = "proposed"
    recommendation: str = ""


class L0IntakeStatusProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    j0_intake_boundary: str = "fixture"
    k0_investigation_boundary: str = "fixture"
    j0_intake_available: bool = False
    k0_investigation_available: bool = False


class L0ContextProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    authority_state: str = "missing"
    degraded_reason: str = ""
    available: bool = False
    studies: list[L0StudyProjection] = Field(default_factory=list)
    intake_dependency_status: L0IntakeStatusProjection = Field(
        default_factory=L0IntakeStatusProjection
    )
    redaction_engine_available: bool = True


# ── M0: Local Inference ────────────────────────────────────────────


class M0TaskSuitabilityEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_kind: str = ""
    suitable: bool = False
    requires_runtime: bool = True
    enforcement_class_required: str = "json_object_formatting_only"
    publication_applicability: str = "internal_only"
    refusal_reason: str = ""


class M0DraftEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.REVIEW_REQUIRED_DRAFT
    result_id: str = ""
    task_id: str = ""
    task_kind: str = ""
    draft_sha256: str = ""
    draft_byte_count: int = 0
    output_disposition: str = "draft_requires_review"
    publication_applicability: str = "internal_only"
    requires_approval: bool = True
    created_at: str = ""


class M0RefusalEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.REFUSED
    result_id: str = ""
    task_id: str = ""
    task_kind: str = ""
    refusal_code: str = ""
    refusal_reason: str = ""
    created_at: str = ""


class M0InferenceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    authority_state: str = "missing"
    degraded_reason: str = ""
    available: bool = False
    runtime_available: bool = False
    runtime_configured: bool = False
    runtime_kind: str = "unknown"
    platform_class: str = "unknown"
    task_suitability: list[M0TaskSuitabilityEntry] = Field(default_factory=list)
    total_results: int = 0
    total_executed: int = 0
    total_refused: int = 0
    drafts_awaiting_review: int = 0
    drafts: list[M0DraftEntry] = Field(default_factory=list)
    refusals: list[M0RefusalEntry] = Field(default_factory=list)
    native_schema_capability_claimed: bool = False
    native_schema_capability_proven: bool = False
    grammar_capability_claimed: bool = False
    grammar_capability_proven: bool = False


# ── Aggregate Developer Studio Projection ──────────────────────────


class StudioProvenanceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_facts: int = 0
    derived_projections: int = 0
    generated_proposals: int = 0
    review_required_drafts: int = 0
    approved_contents: int = 0
    controlled_boundary_proofs: int = 0
    fixture_deferred: int = 0
    refused: int = 0
    corrupt_untrusted: int = 0


class StudioServiceHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    j0_workspace: str = "unavailable"
    k0_operator: str = "unavailable"
    l0_context: str = "unavailable"
    m0_inference: str = "unavailable"


class DeveloperStudioProjection(BaseModel):
    """Single coherent frontend-safe projection over J0/K0/L0/M0.

    Aggregates published application-service state without reproducing
    authority logic. Every field is content-light. Generated text is
    always proposed/review-required, never implicitly approved or public.

    Consumed by P0 (web frontend) and N1 (WebKit host) through the
    bridge protocol.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=_DEVELOPER_STUDIO_SCHEMA, frozen=True)
    projection_id: str
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    workspace: J0WorkspaceProjection = Field(default_factory=J0WorkspaceProjection)
    operator: K0OperatorProjection = Field(default_factory=K0OperatorProjection)
    context: L0ContextProjection = Field(default_factory=L0ContextProjection)
    inference: M0InferenceProjection = Field(default_factory=M0InferenceProjection)

    service_health: StudioServiceHealth = Field(default_factory=StudioServiceHealth)
    provenance_summary: StudioProvenanceSummary = Field(
        default_factory=StudioProvenanceSummary
    )

    content_light: bool = True
    projection_digest: str = ""

    def compute_digest(self) -> str:
        exclude = {"projection_digest", "generated_at", "projection_id"}
        data = self.model_dump(mode="json", exclude=exclude)
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


# ── Gateway Error ────────────────────────────────────────────────────


class GatewayErrorKind(StrEnum):
    SERVICE_UNAVAILABLE = "gateway.service_unavailable"
    INTENT_UNKNOWN = "gateway.intent_unknown"
    INTENT_REFUSED = "gateway.intent_refused"
    DEPENDENCY_FAILED = "gateway.dependency_failed"
    CONTROLLED_BOUNDARY_REQUIRED = "gateway.controlled_boundary_required"
    LIVE_INSTALLATION_DEFERRED = "gateway.live_installation_deferred"
    UNSAFE_PAYLOAD = "gateway.unsafe_payload"
    INTERNAL_ERROR = "gateway.internal_error"


class GatewayError(Exception):
    def __init__(self, kind: GatewayErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


__all__ = [
    "DeveloperStudioProjection",
    "GatewayError",
    "GatewayErrorKind",
    "J0ConnectionProjection",
    "J0RepositoryProjection",
    "J0WorkspaceProjection",
    "K0OperatorProjection",
    "K0SessionProjection",
    "L0ContextProjection",
    "L0IntakeStatusProjection",
    "L0StudyProjection",
    "M0DraftEntry",
    "M0InferenceProjection",
    "M0RefusalEntry",
    "M0TaskSuitabilityEntry",
    "ProvenanceClass",
    "StudioProvenanceSummary",
    "StudioServiceHealth",
    "TrustState",
]
