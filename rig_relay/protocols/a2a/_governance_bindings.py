"""A2A governance bindings — Rig Relay extension data for A2A tasks.

These bindings carry mission, lane, evidence, confidentiality, and
authorization metadata as A2A-compatible extension data. They are
content-light: no raw prompts, paths, secrets, or model outputs.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ConfidentialityTier(StrEnum):
    """Data confidentiality classification for A2A evidence.

    Governs what evidence an agent may receive, produce, or store.
    """

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class MutationIntent(StrEnum):
    """Declared mutation intent for an A2A task.

    An agent declares what class of mutation it intends. The
    governance layer gates execution based on trust tier, lane
    authority, and authorization receipts.
    """

    NONE = "none"
    READ_ONLY = "read_only"
    PROPOSAL_ONLY = "proposal_only"
    EVIDENCE_WRITE = "evidence_write"
    CONTENT_LIGHT_WRITE = "content_light_write"
    SCOPED_MUTATION = "scoped_mutation"


class ExecutionRisk(StrEnum):
    """Execution risk classification for an A2A task.

    Used by governance to determine whether the task requires
    additional authorization, containment, or human review.
    """

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CancellationReason(StrEnum):
    """Typed cancellation reasons for A2A tasks."""

    USER_REQUESTED = "user_requested"
    GOVERNANCE_REFUSAL = "governance_refusal"
    TIMEOUT = "timeout"
    SCOPE_EXPIRED = "scope_expired"
    AUTHORITY_REVOKED = "authority_revoked"
    CONFLICT_DETECTED = "conflict_detected"
    DEPENDENCY_FAILED = "dependency_failed"
    AGENT_ERROR = "agent_error"


class RefusalReason(StrEnum):
    """Typed refusal reasons for A2A tasks."""

    CAPABILITY_MISMATCH = "capability_mismatch"
    TRUST_TIER_INSUFFICIENT = "trust_tier_insufficient"
    MUTATION_NOT_AUTHORIZED = "mutation_not_authorized"
    SCOPE_VIOLATION = "scope_violation"
    CONFIDENTIALITY_VIOLATION = "confidentiality_violation"
    IDENTITY_UNVERIFIED = "identity_unverified"
    SIGNATURE_INVALID = "signature_invalid"
    LANE_AUTHORITY_MISSING = "lane_authority_missing"
    LANE_B_AUTHORITY_MISSING = "lane_b_authority_missing"
    REPLAY_DETECTED = "replay_detected"
    MALFORMED_PAYLOAD = "malformed_payload"
    OVERSIZED_ARTIFACT = "oversized_artifact"
    BUDGET_EXCEEDED = "budget_exceeded"
    UNKNOWN = "unknown"


class A2AGovernanceBinding(BaseModel):
    """Rig Relay governance extension data for an A2A task.

    Attached to task cards as extension data. Carries mission, lane,
    evidence, confidentiality, and authorization metadata without
    raw prompts, private paths, or secrets.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.a2a.governance_binding.v1"

    mission_id: str | None = None
    lane_id: str | None = None
    parent_task_id: str | None = None

    evidence_digest: str = ""
    artifact_digest: str = ""
    receipt_id: str | None = None

    confidentiality_tier: ConfidentialityTier = ConfidentialityTier.INTERNAL
    mutation_intent: MutationIntent = MutationIntent.NONE
    execution_risk: ExecutionRisk = ExecutionRisk.NONE

    authorization_dependency: str | None = None
    producer_trust_tier: str = ""
    producer_identity_hash: str = ""

    causal_predecessor_task_id: str | None = None
    causal_predecessor_event_seq: int | None = None

    cancellation_reason: CancellationReason | None = None
    refusal_reason: RefusalReason | None = None

    required_capability_classes: list[str] = Field(default_factory=list)
    granted_capability_classes: list[str] = Field(default_factory=list)

    content_light: bool = True


class A2AAgentCardExtensions(BaseModel):
    """Rig Relay extension data for an A2A Agent Card.

    Augments the public Agent Card with trust tier and additional
    metadata. Only advertised on authenticated extended cards.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.a2a.agent_card_extensions.v1"

    trust_tier: str = "external_unauthenticated"
    rig_relay_version: str = ""
    supported_bindings: list[str] = Field(default_factory=list)
    governance_envelope_provided: bool = False

    content_light: bool = True


def _trust_tier_import() -> type:
    from rig_relay.protocols.a2a._trust import TrustTier

    return TrustTier


__all__ = [
    "A2AAgentCardExtensions",
    "A2AGovernanceBinding",
    "CancellationReason",
    "ConfidentialityTier",
    "ExecutionRisk",
    "MutationIntent",
    "RefusalReason",
    "_trust_tier_import",
]
