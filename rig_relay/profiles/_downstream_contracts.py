"""Downstream Y0/Y1/Y2/Y4 integration contracts.

Typed Pydantic contracts consumed by the desktop cockpit (Y0),
managed workspaces (Y1), context compiler (Y2), runtime observations (Y4),
and analytics (Y3). These are published interfaces only — no consumer lane
edits are made here.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import uuid

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.profiles.models import ProfileResolutionResult

# === Y0: Desktop Cockpit Projection ===


class HarnessProfileStatusProjection(BaseModel):
    """Content-light projection for Y0 cockpit rendering of the selected profile."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = "rig.relay.y0.harness_profile_status.v1"
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    selected_profile_id: str = ""
    selected_profile_display_name: str = ""
    selected_profile_status: str = (
        ""  # candidate, experimental, restricted, unavailable
    )
    provider: str = ""
    model_id: str = ""
    task_role: str = ""
    resolution_outcome: str = ""
    recommendation_summary: str = ""
    missing_capabilities_summary: list[str] = Field(default_factory=list)
    setup_required_summary: list[str] = Field(default_factory=list)
    evidence_health: str = "unknown"  # healthy, degraded, missing, conflicting
    governance_admission_state: str = "not_evaluated"
    warnings: list[str] = Field(default_factory=list)


# === Y1: Managed Workspace Contracts ===


class WorkspaceProfileAssignmentRequest(BaseModel):
    """Contract for Y1: request a workspace to adopt a resolved profile."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = "rig.relay.y1.workspace_profile_assignment_request.v1"
    request_id: str = ""  # UUID
    workspace_id_ref: str = ""
    agent_role: str = ""
    provider: str = ""
    model_id: str = ""
    selected_profile_digest: str = ""
    session_envelope_digest: str = ""
    capability_evidence_digest: str = ""
    governance_admission_digest: str = ""
    assignment_admissibility: str = (
        "not_evaluated"  # admissible, requires_review, refused
    )
    requested_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class WorkspaceProfileAssignmentReceipt(BaseModel):
    """Contract for Y1: receipt acknowledging profile assignment to workspace."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = "rig.relay.y1.workspace_profile_assignment_receipt.v1"
    receipt_id: str = ""
    request_id: str = ""
    workspace_id_ref: str = ""
    assignment_accepted: bool = False
    assignment_digest: str = ""
    issued_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# === Y2: Context Compiler Contracts ===


class ContextCapsuleBindingRequest(BaseModel):
    """Contract for Y2: request context capsule binding for an envelope."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = "rig.relay.y2.context_capsule_binding_request.v1"
    request_id: str = ""
    context_capsule_digest: str = ""  # Y2 capsule reference
    instruction_scope_digest: str = ""
    required_envelope_strategy: str = ""
    stale_handling: str = "warn"  # warn, refuse, accept
    requested_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ContextCapsuleBindingReceipt(BaseModel):
    """Contract for Y2: receipt of context capsule binding."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = "rig.relay.y2.context_capsule_binding_receipt.v1"
    receipt_id: str = ""
    request_id: str = ""
    capsule_bound: bool = False
    binding_digest: str = ""
    issued_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# === Y4: Runtime Observation Contracts ===


class RuntimeProfileCapabilityObservation(BaseModel):
    """Contract for Y4: runtime capability observation for a profile."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = "rig.relay.y4.runtime_profile_capability_observation.v1"
    observation_id: str = ""
    runtime_provider: str = ""
    runtime_model: str = ""
    selected_profile_id: str = ""
    selected_profile_digest: str = ""
    advertised_runtime_capability_posture: str = ""
    observed_outcome: str = ""  # success, failure, refusal, timeout
    evidence_health: str = ""
    observed_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ProfileEvaluationObservation(BaseModel):
    """Contract for Y4: evaluation observation for analytics consumption."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = "rig.relay.y4.profile_evaluation_observation.v1"
    observation_id: str = ""
    profile_id: str = ""
    provider: str = ""
    model_id: str = ""
    task_role: str = ""
    evaluation_checks_passed: int = 0
    evaluation_checks_total: int = 5
    context_assembly_correct: bool | None = None
    tool_authority_preserved: bool | None = None
    deterministic_resolution: bool | None = None
    unsupported_capability_refused: bool | None = None
    receipt_reconstructable: bool | None = None
    observed_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# === Analytics: Content-light metrics ===


class ProfileSelectionMetrics(BaseModel):
    """Content-light metrics for analytics consumption."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = "rig.relay.y3.analytics.profile_selection_metrics.v1"
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    total_selections: int = 0
    selections_by_outcome: dict[str, int] = Field(default_factory=dict)
    selections_by_profile: dict[str, int] = Field(default_factory=dict)
    selections_by_provider: dict[str, int] = Field(default_factory=dict)
    selections_by_task_role: dict[str, int] = Field(default_factory=dict)
    refusal_reasons: dict[str, int] = Field(default_factory=dict)
    evidence_source_distribution: dict[str, int] = Field(default_factory=dict)
    experimental_profile_usage: int = 0
    admitted_profile_usage: int = 0


# === Builder helpers ===


def build_y0_projection(
    resolution: ProfileResolutionResult,
) -> HarnessProfileStatusProjection:
    """Build a Y0 cockpit projection from a profile resolution result."""
    profile = resolution.selected_profile
    return HarnessProfileStatusProjection(
        selected_profile_id=profile.profile_id,
        selected_profile_display_name=profile.display_name,
        selected_profile_status=profile.evaluation_status.value,
        provider=resolution.provider,
        model_id=resolution.model_id,
        task_role=resolution.task_role.value,
        resolution_outcome=resolution.outcome,
        recommendation_summary=resolution.selected_reason,
        evidence_health=_classify_evidence_health(resolution),
        governance_admission_state=resolution.governance_admission_state,
        warnings=list(resolution.warnings),
    )


def build_y1_assignment_request(
    workspace_id: str, resolution: ProfileResolutionResult, envelope_digest: str
) -> WorkspaceProfileAssignmentRequest:
    """Build a Y1 workspace assignment request from a resolved profile."""
    profile = resolution.selected_profile
    profile_payload = json.dumps(
        profile.model_dump(exclude={"profile_digest"}),
        sort_keys=True,
        separators=(",", ":"),
    )
    profile_digest = f"sha256:{hashlib.sha256(profile_payload.encode()).hexdigest()}"
    return WorkspaceProfileAssignmentRequest(
        request_id=str(uuid.uuid4()),
        workspace_id_ref=workspace_id,
        agent_role=resolution.task_role.value,
        provider=resolution.provider,
        model_id=resolution.model_id,
        selected_profile_digest=profile_digest,
        session_envelope_digest=envelope_digest,
        capability_evidence_digest=resolution.capability_evidence_digest,
        governance_admission_digest=resolution.governance_admission_digest,
        assignment_admissibility=_derive_admissibility(resolution),
    )


def build_y2_binding_request(
    capsule_digest: str, envelope_strategy: str
) -> ContextCapsuleBindingRequest:
    """Build a Y2 context capsule binding request."""
    return ContextCapsuleBindingRequest(
        request_id=str(uuid.uuid4()),
        context_capsule_digest=capsule_digest,
        required_envelope_strategy=envelope_strategy,
    )


def build_y4_observation(
    profile_id: str, provider: str, model_id: str, outcome: str
) -> RuntimeProfileCapabilityObservation:
    """Build a Y4 runtime capability observation entry."""
    return RuntimeProfileCapabilityObservation(
        observation_id=str(uuid.uuid4()),
        runtime_provider=provider,
        runtime_model=model_id,
        selected_profile_id=profile_id,
        observed_outcome=outcome,
        evidence_health="healthy" if outcome == "success" else "degraded",
    )


# === Internal helpers ===


def _classify_evidence_health(resolution: ProfileResolutionResult) -> str:
    """Classify evidence health based on capability evidence presence/conflicts."""
    if not resolution.capability_evidence_digest:
        return "missing"
    if "conflicting" in resolution.outcome.lower():
        return "conflicting"
    if "missing" in resolution.outcome.lower():
        return "missing"
    return "healthy"


def _derive_admissibility(resolution: ProfileResolutionResult) -> str:
    """Derive assignment admissibility from governance admission state."""
    state = resolution.governance_admission_state
    if state in {"admitted"}:
        return "admissible"
    if state in {"requires_review"}:
        return "requires_review"
    if state in {"refused"}:
        return "refused"
    return "not_evaluated"
