"""rig_relay.protocols.a2a — content-light agent-to-agent protocol spine.

A2A is Rig Relay's canonical coordination vocabulary: internal agents,
subagents, future Ralph workers, fleet members, and external coding-agent
adapters all speak the same task/message/artifact/status language.

The distinction is not protocol shape; it is trust tier, identity,
authorization, transport, and allowed effects.
"""

from __future__ import annotations

from rig_relay.protocols.a2a._artifacts import (
    A2AArtifact,
    A2AArtifactKind,
    A2AArtifactRef,
)
from rig_relay.protocols.a2a._canonical import (
    compute_agent_card_digest,
    compute_digest,
    compute_governance_binding_digest,
    compute_task_card_digest,
    content_integrity_chain,
    dump_canonical_json,
    verify_digest,
)
from rig_relay.protocols.a2a._governance_bindings import (
    A2AAgentCardExtensions,
    A2AGovernanceBinding,
    CancellationReason,
    ConfidentialityTier,
    ExecutionRisk,
    MutationIntent,
    RefusalReason,
)
from rig_relay.protocols.a2a._identity import (
    A2ALocalIdentity,
    A2ASecurityScheme,
    build_agent_card_with_security,
    build_identity_metadata,
)
from rig_relay.protocols.a2a._internal_fabric import (
    A2AInternalFabric,
    InternalA2ATaskState,
    capability_check_for_task,
)
from rig_relay.protocols.a2a._lifecycle import (
    build_agent_card,
    build_delegation_receipt,
    build_task_card,
    cancel_task,
    delegation_allowed_by_governance,
    send_local_task_message,
    transition_task,
)
from rig_relay.protocols.a2a._models import (
    A2AAgentCard,
    A2ADelegationReceipt,
    A2ATaskCard,
    A2ATaskLifecycle,
    A2ATaskLifecycleEvent,
    A2ATaskStatus,
)
from rig_relay.protocols.a2a._trust import (
    MUTATION_CAPABILITIES,
    PUBLIC_CAPABILITIES,
    AgentTrustProfile,
    CapabilityClass,
    TrustTier,
    authenticated_capability_subset,
    capabilities_for_tier,
    capability_admitted,
    mutation_capability_admitted,
    public_capability_subset,
)
from rig_relay.protocols.a2a.server import serve_agent_card, serve_agent_card_json

__all__ = [
    "MUTATION_CAPABILITIES",
    "PUBLIC_CAPABILITIES",
    "A2AAgentCard",
    "A2AAgentCardExtensions",
    "A2AArtifact",
    "A2AArtifactKind",
    "A2AArtifactRef",
    "A2ADelegationReceipt",
    "A2AGovernanceBinding",
    "A2AInternalFabric",
    "A2ALocalIdentity",
    "A2ASecurityScheme",
    "A2ATaskCard",
    "A2ATaskLifecycle",
    "A2ATaskLifecycleEvent",
    "A2ATaskStatus",
    "AgentTrustProfile",
    "CancellationReason",
    "CapabilityClass",
    "ConfidentialityTier",
    "ExecutionRisk",
    "InternalA2ATaskState",
    "MutationIntent",
    "RefusalReason",
    "TrustTier",
    "authenticated_capability_subset",
    "build_agent_card",
    "build_agent_card_with_security",
    "build_delegation_receipt",
    "build_identity_metadata",
    "build_task_card",
    "cancel_task",
    "capabilities_for_tier",
    "capability_admitted",
    "capability_check_for_task",
    "compute_agent_card_digest",
    "compute_digest",
    "compute_governance_binding_digest",
    "compute_task_card_digest",
    "content_integrity_chain",
    "delegation_allowed_by_governance",
    "dump_canonical_json",
    "mutation_capability_admitted",
    "public_capability_subset",
    "send_local_task_message",
    "serve_agent_card",
    "serve_agent_card_json",
    "transition_task",
    "verify_digest",
]
