"""External A2A gateway — trust-tier-gated boundary for external agents.

Implements Rig Relay as an A2A-compatible external agent boundary.
Shares canonical task and artifact models with internal fabric but
enforces stricter trust and authorization:
- External tasks are proposal-only unless explicit authority exists.
- Public Agent Card derives from implemented capability truth.
- Unauthenticated clients receive discovery-only capabilities.
- Mutation, validation, GitHub ops, and runtime delegation are refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from rig_relay.protocols.a2a._governance_bindings import (
    A2AGovernanceBinding,
    ConfidentialityTier,
    ExecutionRisk,
    MutationIntent,
)
from rig_relay.protocols.a2a._trust import (
    PUBLIC_CAPABILITIES,
    CapabilityClass,
    TrustTier,
    capability_admitted,
    public_capability_subset,
)

_GATEWAY_FORBIDDEN_CAPABILITIES: set[CapabilityClass] = {
    CapabilityClass.MUTATION_PENDING_AUTHORITY,
    CapabilityClass.RUNTIME_DELEGATION,
    CapabilityClass.GITHUB_PENDING_LANE_B,
    CapabilityClass.VALIDATION_PENDING_LANE_A,
    CapabilityClass.DISCLOSURE_PENDING_LANE_A,
    CapabilityClass.READ_ONLY_INVESTIGATION,
    CapabilityClass.EVIDENCE_VERIFICATION,
}

_EXTERNAL_SAFE_CAPABILITIES: set[CapabilityClass] = (
    PUBLIC_CAPABILITIES | {CapabilityClass.EVIDENCE_VERIFICATION}
) - _GATEWAY_FORBIDDEN_CAPABILITIES


@dataclass
class GatewayConfig:
    """Configuration for the external A2A gateway."""

    agent_id: str = "rig-relay-a2a"
    agent_name: str = "Rig Relay A2A Agent"
    agent_description: str = "Governed A2A coordination agent for Rig Relay"
    local_only: bool = True
    remote_federation_supported: bool = False
    bindings: list[str] = field(default_factory=lambda: ["jsonrpc-2.0"])
    supported_authentication: list[str] = field(
        default_factory=lambda: ["none", "bearer"]
    )
    max_artifact_bytes: int = 65536
    max_task_description_chars: int = 4096
    content_light: bool = True


class A2AGateway:
    """External A2A boundary with trust-tier enforcement.

    All external requests pass through this gateway. The gateway
    determines an agent's trust tier at admission and enforces
    capability restrictions at every operation.
    """

    def __init__(
        self,
        config: GatewayConfig | None = None,
        trust_tier: TrustTier = TrustTier.EXTERNAL_UNAUTHENTICATED,
    ) -> None:
        self.config = config or GatewayConfig()
        self._trust_tier = trust_tier
        self._admitted_capabilities = public_capability_subset(self._trust_tier)

    @property
    def trust_tier(self) -> TrustTier:
        return self._trust_tier

    def set_trust_tier(self, tier: TrustTier, identity_proof: str = "") -> None:
        """Update the gateway's trust tier (e.g., after authentication)."""
        self._trust_tier = tier
        self._admitted_capabilities = public_capability_subset(tier)

    def build_agent_card(self) -> dict[str, object]:
        """Build a truthful Agent Card for the current trust tier.

        Only capabilities actually implemented and safe for the
        current trust tier are advertised.
        """
        safe_caps = [
            c.value
            for c in self._admitted_capabilities
            if c in _EXTERNAL_SAFE_CAPABILITIES
        ]
        now = datetime.now(UTC).isoformat()
        return {
            "schema_version": "rig.relay.a2a.agent_card.v1",
            "agent_id": self.config.agent_id,
            "name": self.config.agent_name,
            "description": self.config.agent_description,
            "capabilities": safe_caps,
            "supported_task_types": safe_caps,
            "local_only": self.config.local_only,
            "remote_federation_supported": self.config.remote_federation_supported,
            "content_light": self.config.content_light,
            "generated_at": now,
            "trust_tier": self._trust_tier.value,
            "bindings": self.config.bindings,
            "supported_authentication": self.config.supported_authentication,
            "security_schemes": [
                {"scheme_type": a, "description": ""}
                for a in self.config.supported_authentication
            ],
            "identity": {
                "agent_id_hash": "",
                "identity_proof_hash": "",
                "federation_trust_boundary": "none",
            },
            "extensions": {
                "rig_relay_governance": {
                    "mutation_refused": True,
                    "remote_federation_refused": True,
                    "content_light": True,
                }
            },
        }

    def admit_capability(self, capability: CapabilityClass) -> tuple[bool, str]:
        """Check if a capability is admitted at the gateway.

        Returns (admitted: bool, reason: str).
        """
        if capability in _GATEWAY_FORBIDDEN_CAPABILITIES:
            return False, (
                f"Capability {capability.value} is not available "
                "through the external A2A gateway"
            )
        return capability_admitted(self._trust_tier, capability)

    def validate_task_request(
        self,
        description: str,
        required_capabilities: list[CapabilityClass] | None = None,
    ) -> tuple[bool, str]:
        """Validate an external task creation request.

        Returns (valid: bool, reason: str).
        """
        if len(description) > self.config.max_task_description_chars:
            return (
                False,
                f"Task description exceeds {self.config.max_task_description_chars} characters",
            )

        forbidden_scan = _scan_for_forbidden(description)
        if forbidden_scan:
            return (
                False,
                f"Task description contains forbidden content: {forbidden_scan}",
            )

        for cap in required_capabilities or []:
            admitted, reason = self.admit_capability(cap)
            if not admitted:
                return False, reason

        return True, ""

    def build_governance_binding_for_external_task(
        self, task_id: str, description: str
    ) -> A2AGovernanceBinding:
        """Build a governance binding appropriate for an external task.

        External tasks are defaulted to proposal-only with no mutation
        intent. The binding carries the gateway's trust tier as the
        producer identity.
        """
        return A2AGovernanceBinding(
            mission_id=None,
            lane_id=None,
            confidentiality_tier=ConfidentialityTier.INTERNAL,
            mutation_intent=MutationIntent.PROPOSAL_ONLY,
            execution_risk=ExecutionRisk.NONE,
            producer_trust_tier=self._trust_tier.value,
            producer_identity_hash="",
        )


def _scan_for_forbidden(text: str) -> list[str]:
    """Scan text for forbidden content markers."""
    forbidden = {"api_key", "token", "secret", "password", "credential", "private_key"}
    found: list[str] = []
    lowered = text.lower()
    for marker in forbidden:
        if marker in lowered:
            found.append(marker)
    return found


def refusal_response(
    reason: str, code: str = "gateway_refused", task_id: str = ""
) -> dict[str, object]:
    """Build a typed refusal response."""
    return {
        "status": "refused",
        "refusal_code": code,
        "refusal_reason": reason,
        "task_id": task_id,
        "content_light": True,
    }


def gateway_admit_mutation(
    trust_tier: TrustTier, mutation_intent: MutationIntent
) -> tuple[bool, str]:
    """Admission check for mutation at the external gateway.

    Always refuses: external A2A does not authorize mutation.
    """
    if mutation_intent != MutationIntent.NONE:
        return False, (
            "Mutation not authorized through external A2A gateway. "
            "External tasks are proposal-only."
        )
    return True, ""


__all__ = ["A2AGateway", "GatewayConfig", "gateway_admit_mutation", "refusal_response"]
