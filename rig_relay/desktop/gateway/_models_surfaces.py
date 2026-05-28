"""Surface-specific projection models for Connect, Repository Estate, Publish Preview,
Timeline History, and Inference Studio — Lane X0.

Content-light: hashes, counts, statuses, labels, and SHA256 digests only.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.desktop.gateway._models import (
    ProvenanceClass,
    SafariCompanionFields,
    TrustState,
)

# ── Provider Connection (for Connect surface) ────────


class SurfaceStatus(StrEnum):
    AVAILABLE = "available"
    DERIVED = "derived"
    SETUP_REQUIRED = "setup_required"
    VERIFICATION_PENDING = "verification_pending"
    UNAVAILABLE = "unavailable"
    SIGNING_REQUIRED = "signing_required"
    CONNECTION_REQUIRED = "connection_required"
    ERROR = "error"
    BLOCKED = "blocked"


class ProviderConnectionEntry(BaseModel):
    """Per-provider connection and cache disclosure status."""

    model_config = ConfigDict(extra="forbid")

    provider: str = ""
    display_name: str = ""
    configured: bool = False
    key_source: str = ""
    key_fingerprint: str = ""
    base_url: str = ""
    default_model: str = ""
    status: str = "unknown"
    warnings: list[str] = Field(default_factory=list)
    cache_mode: str = "unknown"
    cache_disclosure_required: bool = False
    cache_retention_class: str = "unknown"
    confidential_context_disposition: str = "unknown"


class ConnectSurfaceProjection(BaseModel):
    """Connect surface: provider connection status and workspace connection."""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    trust_state: TrustState = TrustState.DEFERRED
    authority_state: str = "missing"
    degraded_reason: str = ""
    available: bool = False
    surface_status: str = SurfaceStatus.SETUP_REQUIRED.value
    status_detail: str = "Connect a provider and workspace to begin"
    providers: list[ProviderConnectionEntry] = Field(default_factory=list)
    providers_configured: int = 0
    providers_total: int = 0
    workspace_connection_state: str = "disconnected"
    workspace_token_available: bool = False
    workspace_installation_id_hash: str = ""
    workspace_accessible_repository_count: int = 0


# ── Repository Estate (consumes T3.1) ─────────────────


class EstateRepositoryEntry(BaseModel):
    """A single registered repository in the estate."""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    repository_hash: str = ""
    repository_label: str = ""
    repository_kind: str = "local_only"
    root_path_digest: str = ""
    registered_at: str = ""
    last_registered_at: str = ""
    latest_observation_digest: str = ""
    latest_observation_at: str = ""
    latest_status: str = "unknown"
    latest_head_sha: str = ""
    latest_branch: str = ""
    is_detached: bool = False
    is_dirty: bool = False
    dirty_modified: int = 0
    dirty_untracked: int = 0
    tracked_file_count: int = 0
    instruction_file_count: int = 0
    remote_count: int = 0
    degraded_reason: str = ""


class EstateChangeEntry(BaseModel):
    """A recent change detected in repository estate."""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    repository_hash: str = ""
    repository_label: str = ""
    detected_at: str = ""
    change_kinds: list[str] = Field(default_factory=list)


class EstateCorruptionEntry(BaseModel):
    """A corruption event in the estate."""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.CORRUPT_UNTRUSTED
    event_kind: str = ""
    repository_hash: str = ""
    reason: str = ""


class RepositoryEstateSurfaceProjection(BaseModel):
    """Repository Estate surface: registered repos, observations, changes, corruption."""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    trust_state: TrustState = TrustState.DEFERRED
    authority_state: str = "missing"
    degraded_reason: str = ""
    available: bool = False
    surface_status: str = SurfaceStatus.VERIFICATION_PENDING.value
    status_detail: str = "Repository estate service is being verified"
    registered_repositories: list[EstateRepositoryEntry] = Field(default_factory=list)
    total_registered: int = 0
    local_only_count: int = 0
    github_backed_count: int = 0
    dirty_count: int = 0
    inaccessible_count: int = 0
    recent_changes: list[EstateChangeEntry] = Field(default_factory=list)
    total_observations: int = 0
    corrupt_registration_count: int = 0
    corrupt_observation_count: int = 0
    corrupt_chain_links: int = 0
    corruption_events: list[EstateCorruptionEntry] = Field(default_factory=list)
    content_light_guarantee: bool = True


# ── Publish Preview (consumes T1.2) ───────────────────


class PublishPreviewRefusalEntry(BaseModel):
    """A refusal from the publication preview service."""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.REFUSED
    refusal_code: str = ""
    reasons: list[str] = Field(default_factory=list)


class PublishPreviewEvidenceSummary(BaseModel):
    """Evidence receipt summary from a preview operation."""

    model_config = ConfigDict(extra="forbid")

    receipt_id: str = ""
    compiled_at: str = ""
    compilation_successful: bool = False
    profile_candidate_digest: str = ""
    safety_passed: bool = False
    preview_only: bool = True
    deployment_ready: bool = False
    evidence_digest: str = ""


class PublishPreviewSurfaceProjection(BaseModel):
    """Publish Preview surface: operation identity, preview result, evidence, refusal."""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    trust_state: TrustState = TrustState.DEFERRED
    authority_state: str = "missing"
    degraded_reason: str = ""
    available: bool = False
    surface_status: str = SurfaceStatus.VERIFICATION_PENDING.value
    status_detail: str = "Publication preview is awaiting upstream handoff"
    operation_id: str = ""
    last_result_status: str = "none"
    preview_result: PublishPreviewEvidenceSummary | None = None
    refusal: PublishPreviewRefusalEntry | None = None
    ledger_total_events: int = 0
    ledger_valid_rows: int = 0
    ledger_corrupt_rows: int = 0
    ledger_corruption_detected: bool = False
    publishable_repository_count: int = 0
    deployment_available: bool = False
    deployment_deferred_reason: str = (
        "Publication integration is pending upstream infrastructure verification."
    )
    content_light_guarantee: bool = True
    # X3.8 publication contract fields
    publication_preparation_available: bool = False
    authorization_status_field: str = "unavailable"
    authorization_receipt_digest: str = ""
    content_commit_prepared: bool = False
    ref_update_complete: bool = False
    pages_configuration_state: str = "unavailable"
    build_status_field: str = "unavailable"
    published_verification_complete: bool = False
    conflict_detected: bool = False
    recovery_available: bool = False
    external_acceptance_state: str = "unavailable"
    # Y0.1 — X3 remote truth
    x3_boundary_status: str = "unavailable"
    """candidate_local_not_remotely_released, verified_remotely, or unavailable"""


# ── Timeline History (consumes T4.2) ───────────────────


class TimelineEventEntry(BaseModel):
    """A single timeline event entry."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = ""
    timeline_sequence: int = 0
    observed_at: str = ""
    event_kind: str = ""
    source_domain: str = ""
    verification_class: str = "parsed_unverified"
    authority_classification: str = "canonical_live"
    degradation_detail: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    operation_id: str | None = None
    outcome: str | None = None
    status: str | None = None
    latency_ms: float | None = None
    path_count: int | None = None
    artifact_kind: str | None = None
    commit_sha: str | None = None
    refusal_code: str | None = None


class TimelineSurfaceProjection(BaseModel):
    """Timeline History surface: canonical event timeline with verification classes."""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    trust_state: TrustState = TrustState.DEFERRED
    authority_state: str = "missing"
    degraded_reason: str = ""
    available: bool = False
    surface_status: str = SurfaceStatus.VERIFICATION_PENDING.value
    status_detail: str = "Timeline service is being verified"
    timeline_id: str = ""
    assembled_at: str = ""
    investigation_id: str | None = None
    session_id: str | None = None
    project_id: str | None = None
    events: list[TimelineEventEntry] = Field(default_factory=list)
    event_count: int = 0
    domain_coverage: dict[str, int] = Field(default_factory=dict)
    unsupported_domains: list[str] = Field(default_factory=list)
    verified_canonical_count: int = 0
    parsed_unverified_count: int = 0
    canonical_degraded_count: int = 0
    corrupt_count: int = 0
    unsupported_count: int = 0
    missing_count: int = 0
    contradictory_count: int = 0
    stale_count: int = 0
    assembly_warnings: list[str] = Field(default_factory=list)
    assembly_errors: list[str] = Field(default_factory=list)
    content_light_guarantee: bool = True


# ── Inference Studio pass-through for OMLX disclosure ──


class InferenceStudioSurfaceProjection(SafariCompanionFields):
    """Inference Studio surface: runtime state with truthful OMLX/X2 pending disclosure."""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    trust_state: TrustState = TrustState.DEFERRED
    authority_state: str = "missing"
    degraded_reason: str = ""
    available: bool = False
    surface_status: str = SurfaceStatus.VERIFICATION_PENDING.value
    status_detail: str = "Inference Studio service is being verified"
    runtime_available: bool = False
    runtime_configured: bool = False
    runtime_kind: str = "unknown"
    platform_class: str = "unknown"
    omlx_strategy: str = "pending_infrastructure_handoff"
    omlx_available: bool = False
    omlx_disclosure: str = (
        "Hardware-accelerated local inference is pending "
        "infrastructure integration and verification."
    )
    task_suitability_count: int = 0
    total_results: int = 0
    total_executed: int = 0
    total_refused: int = 0
    drafts_awaiting_review: int = 0
    native_schema_capability_claimed: bool = False
    native_schema_capability_proven: bool = False
    grammar_capability_claimed: bool = False
    grammar_capability_proven: bool = False


# ── Y1-Y4 Deferred Surface Projections ──────────────


class RepositoryReadinessSurfaceProjection(BaseModel):
    """Repository Readiness: availability of repository intake pipeline and compilation state. (Y1)"""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    trust_state: TrustState = TrustState.DEFERRED
    authority_state: str = "missing"
    degraded_reason: str = ""
    available: bool = False
    surface_status: str = SurfaceStatus.SETUP_REQUIRED.value
    status_detail: str = "Repository Readiness is not yet available in this release"


class FleetWorkspacesSurfaceProjection(BaseModel):
    """Fleet Workspaces: active worktrees, lane reservations, and workspace isolation state. (Y2)"""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    trust_state: TrustState = TrustState.DEFERRED
    authority_state: str = "missing"
    degraded_reason: str = ""
    available: bool = False
    surface_status: str = SurfaceStatus.SETUP_REQUIRED.value
    status_detail: str = "Fleet Workspaces is not yet available in this release"


class HarnessProfileSurfaceProjection(BaseModel):
    """Harness Profile: agent profile configuration, tool policy, and safety gates. (Y3)"""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    trust_state: TrustState = TrustState.DEFERRED
    authority_state: str = "missing"
    degraded_reason: str = ""
    available: bool = False
    surface_status: str = SurfaceStatus.SETUP_REQUIRED.value
    status_detail: str = "Harness Profile is not yet available in this release"


class AnalyticsReportsSurfaceProjection(BaseModel):
    """Analytics & Reports: dataset summaries, refinement reports, and evidence exports. (Y4, wired by Y0.1)"""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    trust_state: TrustState = TrustState.DEFERRED
    authority_state: str = "missing"
    degraded_reason: str = ""
    available: bool = False
    surface_status: str = SurfaceStatus.SETUP_REQUIRED.value
    status_detail: str = "Analytics & Reports is initializing"

    # Dataset summaries
    dataset_count: int = 0
    total_rows: int = 0
    export_manifest: str = ""  # digest of export manifest

    # Report counts
    report_count: int = 0
    refinement_candidate_count: int = 0

    # X-Wave readiness
    x_wave_providers: list[dict[str, str]] = Field(default_factory=list)
    landed_and_visible: int = 0
    remote_not_consumed: int = 0
    cannot_confirm_remotely: int = 0

    # Content-light guarantee
    content_light_guarantee: bool = True


__all__ = [
    "AnalyticsReportsSurfaceProjection",
    "ConnectSurfaceProjection",
    "EstateChangeEntry",
    "EstateCorruptionEntry",
    "EstateRepositoryEntry",
    "FleetWorkspacesSurfaceProjection",
    "HarnessProfileSurfaceProjection",
    "InferenceStudioSurfaceProjection",
    "ProviderConnectionEntry",
    "PublishPreviewEvidenceSummary",
    "PublishPreviewRefusalEntry",
    "PublishPreviewSurfaceProjection",
    "RepositoryEstateSurfaceProjection",
    "RepositoryReadinessSurfaceProjection",
    "SurfaceStatus",
    "TimelineEventEntry",
    "TimelineSurfaceProjection",
]
