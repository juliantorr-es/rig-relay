"""ACP-to-A2A control projection — maps ACP client sessions onto A2A capabilities.

Preserves ACP as the IDE/operator control corridor while projecting
A2A capabilities as inspectable, requestable, and observable through
ACP sessions. ACP state remains ACP state; A2A task identity remains
A2A task identity. This module bridges the two without collapsing them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rig_relay.protocols.a2a._gateway import A2AGateway, refusal_response
from rig_relay.protocols.a2a._trust import (
    CapabilityClass,
    TrustTier,
    capability_admitted,
)


class ACPA2ACapabilityStatus(StrEnum):
    """Status of an A2A capability as visible from ACP."""

    AVAILABLE = "available"
    REQUIRES_AUTHORIZATION = "requires_authorization"
    REFUSED = "refused"
    NOT_IMPLEMENTED = "not_implemented"


@dataclass
class ACPA2ACapabilityEntry:
    """Projection of an A2A capability for ACP client inspection."""

    capability: str
    status: ACPA2ACapabilityStatus
    trust_tier: str
    authorization_dependency: str = ""
    refusal_reason: str = ""


def build_acp_a2a_capability_map(
    trust_tier: TrustTier = TrustTier.ACP_ORIGINATED,
) -> list[ACPA2ACapabilityEntry]:
    """Build the A2A capability map visible to ACP clients.

    Returns a content-light list of capability entries with status
    (available, requires_authorization, refused, not_implemented).
    """
    entries: list[ACPA2ACapabilityEntry] = []
    for cap in CapabilityClass:
        admitted, reason = capability_admitted(trust_tier, cap)

        if cap in {
            CapabilityClass.MUTATION_PENDING_AUTHORITY,
            CapabilityClass.RUNTIME_DELEGATION,
        }:
            status = ACPA2ACapabilityStatus.REQUIRES_AUTHORIZATION
            auth_dep = "lane_a_authority"
        elif cap in {
            CapabilityClass.GITHUB_PENDING_LANE_B,
            CapabilityClass.VALIDATION_PENDING_LANE_A,
            CapabilityClass.DISCLOSURE_PENDING_LANE_A,
        }:
            status = ACPA2ACapabilityStatus.REQUIRES_AUTHORIZATION
            auth_dep = (
                "lane_b_authority"
                if cap == CapabilityClass.GITHUB_PENDING_LANE_B
                else "lane_a_authority"
            )
        elif admitted:
            status = ACPA2ACapabilityStatus.AVAILABLE
            auth_dep = ""
        else:
            status = ACPA2ACapabilityStatus.REFUSED
            auth_dep = ""

        entries.append(
            ACPA2ACapabilityEntry(
                capability=cap.value,
                status=status,
                trust_tier=trust_tier.value,
                authorization_dependency=auth_dep,
                refusal_reason=reason if not admitted else "",
            )
        )
    return entries


def inspect_a2a_capability(
    capability: str, trust_tier: TrustTier = TrustTier.ACP_ORIGINATED
) -> ACPA2ACapabilityEntry:
    """Inspect a single A2A capability from ACP perspective."""
    try:
        cap = CapabilityClass(capability)
    except ValueError:
        return ACPA2ACapabilityEntry(
            capability=capability,
            status=ACPA2ACapabilityStatus.NOT_IMPLEMENTED,
            trust_tier=trust_tier.value,
            refusal_reason=f"Unknown capability: {capability}",
        )
    admitted, reason = capability_admitted(trust_tier, cap)
    if not admitted:
        return ACPA2ACapabilityEntry(
            capability=cap.value,
            status=ACPA2ACapabilityStatus.REFUSED,
            trust_tier=trust_tier.value,
            refusal_reason=reason,
        )
    return ACPA2ACapabilityEntry(
        capability=cap.value,
        status=ACPA2ACapabilityStatus.AVAILABLE,
        trust_tier=trust_tier.value,
    )


def validate_acp_task_request(
    description: str,
    required_capability: str = "proposal_generation",
    trust_tier: TrustTier = TrustTier.ACP_ORIGINATED,
) -> tuple[bool, dict[str, object]]:
    """Validate an ACP-originated A2A task creation request."""
    try:
        cap = CapabilityClass(required_capability)
    except ValueError:
        return False, refusal_response(
            f"Unknown capability: {required_capability}", code="unknown_capability"
        )

    # Check authority-gated capabilities first (specific codes).
    authority_refusals = {
        CapabilityClass.MUTATION_PENDING_AUTHORITY: (
            "requires_authorization",
            f"Capability {cap.value} requires lane authority",
        ),
        CapabilityClass.RUNTIME_DELEGATION: (
            "requires_authorization",
            f"Capability {cap.value} requires lane authority",
        ),
        CapabilityClass.GITHUB_PENDING_LANE_B: (
            "lane_b_authority_required",
            "GitHub operations require Lane B authority",
        ),
        CapabilityClass.VALIDATION_PENDING_LANE_A: (
            "lane_a_authority_required",
            f"Capability {cap.value} requires Lane A authority",
        ),
        CapabilityClass.DISCLOSURE_PENDING_LANE_A: (
            "lane_a_authority_required",
            f"Capability {cap.value} requires Lane A authority",
        ),
    }
    if cap in authority_refusals:
        code, msg = authority_refusals[cap]
        return False, refusal_response(msg, code=code)

    admitted, reason = capability_admitted(trust_tier, cap)
    if not admitted:
        return False, refusal_response(reason, code="capability_refused")

    gateway = A2AGateway(trust_tier=TrustTier.ACP_ORIGINATED)
    valid, reason = gateway.validate_task_request(description)
    if not valid:
        return False, refusal_response(reason, code="validation_failed")

    return True, {
        "status": "accepted",
        "trust_tier": trust_tier.value,
        "mutation_refused": True,
        "content_light": True,
    }


def build_acp_a2a_observation(
    task_id: str,
    status: str,
    messages_count: int,
    artifacts_count: int,
    trust_tier: str = "",
) -> dict[str, object]:
    """Build a content-light A2A task observation for ACP clients.

    Does not include raw message bodies, artifact payloads, or
    task descriptions — only counts and status.
    """
    return {
        "task_id": task_id,
        "status": status,
        "trust_tier": trust_tier,
        "messages_count": messages_count,
        "artifacts_count": artifacts_count,
        "content_light": True,
    }


__all__ = [
    "ACPA2ACapabilityEntry",
    "ACPA2ACapabilityStatus",
    "build_acp_a2a_capability_map",
    "build_acp_a2a_observation",
    "inspect_a2a_capability",
    "validate_acp_task_request",
]
