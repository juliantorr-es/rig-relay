"""A2A trust tier and capability class models.

Trust tiers govern what operations an agent is permitted to perform.
Capability classes define precisely what each capability enables.
Both internal and external agents use the same vocabulary; the trust
policy (not the protocol shape) differs.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TrustTier(StrEnum):
    """Admission trust tier for an agent interacting through A2A.

    Internal tiers inherit governed authority from mission and lane
    claims. External tiers default to discovery and proposal until
    explicit authority is later integrated.
    """

    INTERNAL_GOVERNED_AGENT = "internal_governed_agent"
    INTERNAL_SUBAGENT_WORKER = "internal_subagent_worker"
    INTERNAL_RALPH_WORKER = "internal_ralph_worker"
    EXTERNAL_AUTHENTICATED_A2A = "external_authenticated_a2a"
    EXTERNAL_UNAUTHENTICATED = "external_unauthenticated"
    EXTERNAL_PROVIDER_ADAPTER = "external_provider_adapter"
    ACP_ORIGINATED = "acp_originated"


class CapabilityClass(StrEnum):
    """Precise capability classification for A2A operations.

    Capabilities escalate from discovery-only through read-only
    investigation up to mutation and runtime delegation. Each class
    carries explicit authority dependencies that a trust tier must satisfy.
    """

    DISCOVERY_ONLY = "discovery_only"
    READ_ONLY_INVESTIGATION = "read_only_investigation"
    EVIDENCE_VERIFICATION = "evidence_verification"
    PROPOSAL_GENERATION = "proposal_generation"
    CONTENT_LIGHT_ARTIFACT_EXCHANGE = "content_light_artifact_exchange"
    VALIDATION_PENDING_LANE_A = "validation_pending_lane_a"
    DISCLOSURE_PENDING_LANE_A = "disclosure_pending_lane_a"
    GITHUB_PENDING_LANE_B = "github_pending_lane_b"
    MUTATION_PENDING_AUTHORITY = "mutation_pending_authority"
    RUNTIME_DELEGATION = "runtime_delegation"


class AgentTrustProfile(BaseModel):
    """Trust profile assigned to an A2A agent at admission.

    The profile gates every A2A operation: an agent may only exercise
    capabilities that its trust tier permits.
    """

    model_config = ConfigDict(extra="forbid")

    trust_tier: TrustTier
    agent_id: str
    identity_proof_hash: str = ""
    granted_capabilities: list[CapabilityClass] = Field(default_factory=list)
    content_light: bool = True


_CAPABILITY_PERMISSIONS: dict[TrustTier, set[CapabilityClass]] = {
    TrustTier.INTERNAL_GOVERNED_AGENT: {
        CapabilityClass.DISCOVERY_ONLY,
        CapabilityClass.READ_ONLY_INVESTIGATION,
        CapabilityClass.EVIDENCE_VERIFICATION,
        CapabilityClass.PROPOSAL_GENERATION,
        CapabilityClass.CONTENT_LIGHT_ARTIFACT_EXCHANGE,
        CapabilityClass.VALIDATION_PENDING_LANE_A,
        CapabilityClass.DISCLOSURE_PENDING_LANE_A,
        CapabilityClass.GITHUB_PENDING_LANE_B,
        CapabilityClass.MUTATION_PENDING_AUTHORITY,
        CapabilityClass.RUNTIME_DELEGATION,
    },
    TrustTier.INTERNAL_SUBAGENT_WORKER: {
        CapabilityClass.DISCOVERY_ONLY,
        CapabilityClass.READ_ONLY_INVESTIGATION,
        CapabilityClass.EVIDENCE_VERIFICATION,
        CapabilityClass.PROPOSAL_GENERATION,
        CapabilityClass.CONTENT_LIGHT_ARTIFACT_EXCHANGE,
    },
    TrustTier.INTERNAL_RALPH_WORKER: {
        CapabilityClass.DISCOVERY_ONLY,
        CapabilityClass.READ_ONLY_INVESTIGATION,
        CapabilityClass.EVIDENCE_VERIFICATION,
        CapabilityClass.PROPOSAL_GENERATION,
        CapabilityClass.CONTENT_LIGHT_ARTIFACT_EXCHANGE,
    },
    TrustTier.EXTERNAL_AUTHENTICATED_A2A: {
        CapabilityClass.DISCOVERY_ONLY,
        CapabilityClass.PROPOSAL_GENERATION,
        CapabilityClass.CONTENT_LIGHT_ARTIFACT_EXCHANGE,
        CapabilityClass.EVIDENCE_VERIFICATION,
    },
    TrustTier.EXTERNAL_UNAUTHENTICATED: {CapabilityClass.DISCOVERY_ONLY},
    TrustTier.EXTERNAL_PROVIDER_ADAPTER: {
        CapabilityClass.DISCOVERY_ONLY,
        CapabilityClass.PROPOSAL_GENERATION,
        CapabilityClass.CONTENT_LIGHT_ARTIFACT_EXCHANGE,
        CapabilityClass.EVIDENCE_VERIFICATION,
    },
    TrustTier.ACP_ORIGINATED: {
        CapabilityClass.DISCOVERY_ONLY,
        CapabilityClass.READ_ONLY_INVESTIGATION,
        CapabilityClass.EVIDENCE_VERIFICATION,
        CapabilityClass.PROPOSAL_GENERATION,
        CapabilityClass.CONTENT_LIGHT_ARTIFACT_EXCHANGE,
    },
}


PUBLIC_CAPABILITIES: set[CapabilityClass] = {
    CapabilityClass.DISCOVERY_ONLY,
    CapabilityClass.PROPOSAL_GENERATION,
    CapabilityClass.CONTENT_LIGHT_ARTIFACT_EXCHANGE,
}


AUTHENTICATED_CAPABILITIES: set[CapabilityClass] = PUBLIC_CAPABILITIES | {
    CapabilityClass.EVIDENCE_VERIFICATION,
    CapabilityClass.READ_ONLY_INVESTIGATION,
}


MUTATION_CAPABILITIES: set[CapabilityClass] = {
    CapabilityClass.MUTATION_PENDING_AUTHORITY,
    CapabilityClass.RUNTIME_DELEGATION,
    CapabilityClass.GITHUB_PENDING_LANE_B,
    CapabilityClass.VALIDATION_PENDING_LANE_A,
    CapabilityClass.DISCLOSURE_PENDING_LANE_A,
}


def capabilities_for_tier(tier: TrustTier) -> set[CapabilityClass]:
    """Return the set of capability classes permitted for a trust tier."""
    return _CAPABILITY_PERMISSIONS.get(tier, set())


def capability_admitted(
    tier: TrustTier, capability: CapabilityClass
) -> tuple[bool, str]:
    """Check whether a capability is admitted for a trust tier.

    Returns (admitted: bool, reason: str).
    """
    permitted = capabilities_for_tier(tier)
    if capability in permitted:
        return True, ""
    return False, (
        f"Capability {capability.value} is not admitted for trust tier {tier.value}"
    )


def public_capability_subset(tier: TrustTier) -> set[CapabilityClass]:
    """Return only the capabilities safe to advertise publicly for a tier."""
    return capabilities_for_tier(tier) & PUBLIC_CAPABILITIES


def authenticated_capability_subset(tier: TrustTier) -> set[CapabilityClass]:
    """Return capabilities available on authenticated extended cards."""
    return capabilities_for_tier(tier) & AUTHENTICATED_CAPABILITIES


def mutation_capability_admitted(tier: TrustTier) -> bool:
    """Check if any mutation-class capability is admitted for a tier."""
    return bool(capabilities_for_tier(tier) & MUTATION_CAPABILITIES)


__all__ = [
    "MUTATION_CAPABILITIES",
    "PUBLIC_CAPABILITIES",
    "AgentTrustProfile",
    "CapabilityClass",
    "TrustTier",
    "authenticated_capability_subset",
    "capabilities_for_tier",
    "capability_admitted",
    "mutation_capability_admitted",
    "public_capability_subset",
]
