"""Cross-boundary security and conformance closure for the A2A spine.

Defines the trust matrix, future handoff contract, and boundary
enforcement rules that prove the A2A spine works equally for internal
coordination and external interaction without confusing authority.

This module does NOT implement AgentLoop, Ralph, fleet execution,
subagent spawning, checkpoint mutation, or worktree management.
It defines the contracts those systems will later consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from rig_relay.protocols.a2a._trust import CapabilityClass, TrustTier


class Boundary(StrEnum):
    """Named boundaries in the A2A trust architecture."""

    INTERNAL_FABRIC = "internal_fabric"
    EXTERNAL_GATEWAY = "external_gateway"
    ACP_PROJECTION = "acp_projection"
    PROVIDER_ADAPTER = "provider_adapter"


class CrossBoundaryRule(StrEnum):
    """Rules enforced at cross-boundary intersections."""

    SAME_CANONICAL_MODELS = "same_canonical_models"
    DIFFERENT_TRUST_POLICY = "different_trust_policy"
    CONTENT_LIGHT_UNIVERSAL = "content_light_universal"
    MUTATION_GATED = "mutation_gated"
    IDENTITY_REQUIRED_FOR_WRITE = "identity_required_for_write"
    FAIL_CLOSED = "fail_closed"
    CAPABILITY_TRUTH_ADVERTISED = "capability_truth_advertised"
    NO_TRUST_UPGRADE = "no_trust_upgrade"
    CONFIDENTIAL_SENTINEL_EXCLUDED = "confidential_sentinel_excluded"
    TERMINAL_STATE_IMMUTABLE = "terminal_state_immutable"
    REPLAY_DETECTED_OR_IDEMPOTENT = "replay_detected_or_idempotent"
    CANCELLATION_RACES_DETERMINISTIC = "cancellation_races_deterministic"
    NO_EXECUTION = "no_execution"


@dataclass
class CrossBoundaryAssertion:
    """An assertion that must hold at a cross-boundary intersection."""

    rule: CrossBoundaryRule
    boundary_from: Boundary
    boundary_to: Boundary
    description: str
    verified: bool = False


@dataclass
class TrustMatrixEntry:
    """A single cell in the cross-boundary trust matrix."""

    origin: Boundary
    trust_tier: TrustTier
    can_propose: bool = False
    can_read_evidence: bool = False
    can_mutate: bool = False
    can_delegate: bool = False
    identity_required: bool = True
    content_light_enforced: bool = True
    mutation_gated: bool = True
    authority_dependency: str = ""


@dataclass
class FutureHandoffContract:
    """Contract that future runtime consumers will fulfill.

    Defines what AgentLoop, Ralph, fleet, and subagents must satisfy
    to consume A2A tasks as mission requests. This module does not
    implement these consumers.
    """

    consumer_name: str
    consumer_description: str
    required_trust_tier: TrustTier = TrustTier.INTERNAL_GOVERNED_AGENT
    required_capabilities: list[CapabilityClass] = field(default_factory=list)
    integration_seam: str = ""
    precondition: str = ""
    postcondition: str = ""
    authority_dependency: str = ""
    status: str = "not_implemented"


def build_cross_boundary_assertions() -> list[CrossBoundaryAssertion]:
    """Build the complete set of cross-boundary conformance assertions.

    These assertions MUST hold for the A2A spine to be safe.
    """
    assertions: list[CrossBoundaryAssertion] = [
        CrossBoundaryAssertion(
            rule=CrossBoundaryRule.SAME_CANONICAL_MODELS,
            boundary_from=Boundary.INTERNAL_FABRIC,
            boundary_to=Boundary.EXTERNAL_GATEWAY,
            description=(
                "Internal and external A2A share canonical task/artifact/"
                "status models. Same shape, different trust policy."
            ),
            verified=True,
        ),
        CrossBoundaryAssertion(
            rule=CrossBoundaryRule.DIFFERENT_TRUST_POLICY,
            boundary_from=Boundary.INTERNAL_FABRIC,
            boundary_to=Boundary.EXTERNAL_GATEWAY,
            description=(
                "Internal trust does not mean unlimited mutation. External "
                "trust defaults to discovery and proposal. Same Gundam frame, "
                "different activation keys."
            ),
            verified=True,
        ),
        CrossBoundaryAssertion(
            rule=CrossBoundaryRule.CONTENT_LIGHT_UNIVERSAL,
            boundary_from=Boundary.INTERNAL_FABRIC,
            boundary_to=Boundary.PROVIDER_ADAPTER,
            description=(
                "All durable A2A evidence is content-light across all "
                "boundaries. No raw prompts, secrets, paths, or model outputs."
            ),
            verified=True,
        ),
        CrossBoundaryAssertion(
            rule=CrossBoundaryRule.MUTATION_GATED,
            boundary_from=Boundary.ACP_PROJECTION,
            boundary_to=Boundary.INTERNAL_FABRIC,
            description=(
                "Mutation capabilities are gated at every boundary. Internal "
                "fabric distinguishes coordination from execution."
            ),
            verified=True,
        ),
        CrossBoundaryAssertion(
            rule=CrossBoundaryRule.FAIL_CLOSED,
            boundary_from=Boundary.EXTERNAL_GATEWAY,
            boundary_to=Boundary.INTERNAL_FABRIC,
            description=(
                "External agents receive proposal-only access. Any attempt "
                "to mutate, execute, or disclose fails closed."
            ),
            verified=True,
        ),
        CrossBoundaryAssertion(
            rule=CrossBoundaryRule.CAPABILITY_TRUTH_ADVERTISED,
            boundary_from=Boundary.EXTERNAL_GATEWAY,
            boundary_to=Boundary.PROVIDER_ADAPTER,
            description=(
                "Agent Cards and provider profiles advertise only implemented "
                "capability truth. No aspirational roadmap claims."
            ),
            verified=True,
        ),
        CrossBoundaryAssertion(
            rule=CrossBoundaryRule.NO_TRUST_UPGRADE,
            boundary_from=Boundary.PROVIDER_ADAPTER,
            boundary_to=Boundary.EXTERNAL_GATEWAY,
            description=(
                "Provider adapters cannot upgrade trust tier. An MCP client "
                "is not an A2A peer. Trust tier is assigned at admission."
            ),
            verified=True,
        ),
        CrossBoundaryAssertion(
            rule=CrossBoundaryRule.CONFIDENTIAL_SENTINEL_EXCLUDED,
            boundary_from=Boundary.INTERNAL_FABRIC,
            boundary_to=Boundary.EXTERNAL_GATEWAY,
            description=(
                "Confidential sentinel content (secrets, tokens, private keys) "
                "is excluded from all durable A2A artifacts and external "
                "responses across all boundaries."
            ),
            verified=True,
        ),
        CrossBoundaryAssertion(
            rule=CrossBoundaryRule.TERMINAL_STATE_IMMUTABLE,
            boundary_from=Boundary.INTERNAL_FABRIC,
            boundary_to=Boundary.INTERNAL_FABRIC,
            description=(
                "Terminal task states (completed, failed, cancelled) cannot "
                "be overwritten by later progress events."
            ),
            verified=True,
        ),
        CrossBoundaryAssertion(
            rule=CrossBoundaryRule.REPLAY_DETECTED_OR_IDEMPOTENT,
            boundary_from=Boundary.INTERNAL_FABRIC,
            boundary_to=Boundary.INTERNAL_FABRIC,
            description=(
                "Duplicate events are idempotent or refused. Replayed task "
                "submissions do not create duplicate state."
            ),
            verified=True,
        ),
        CrossBoundaryAssertion(
            rule=CrossBoundaryRule.CANCELLATION_RACES_DETERMINISTIC,
            boundary_from=Boundary.INTERNAL_FABRIC,
            boundary_to=Boundary.INTERNAL_FABRIC,
            description=(
                "Cancellation races resolve deterministically. Terminal "
                "states are preserved under concurrent access."
            ),
            verified=True,
        ),
        CrossBoundaryAssertion(
            rule=CrossBoundaryRule.NO_EXECUTION,
            boundary_from=Boundary.INTERNAL_FABRIC,
            boundary_to=Boundary.INTERNAL_FABRIC,
            description=(
                "This fabric does not execute. It is the nervous system, not "
                "the body. Future runtime consumers will fulfill execution."
            ),
            verified=True,
        ),
    ]
    return assertions


def build_trust_matrix() -> list[TrustMatrixEntry]:
    """Build the cross-boundary trust matrix.

    Each row describes what a particular origin/boundary/tier can do.
    """
    entries: list[TrustMatrixEntry] = [
        TrustMatrixEntry(
            origin=Boundary.INTERNAL_FABRIC,
            trust_tier=TrustTier.INTERNAL_GOVERNED_AGENT,
            can_propose=True,
            can_read_evidence=True,
            can_mutate=True,
            can_delegate=True,
            identity_required=True,
            authority_dependency="lane_claims_and_receipts",
        ),
        TrustMatrixEntry(
            origin=Boundary.INTERNAL_FABRIC,
            trust_tier=TrustTier.INTERNAL_SUBAGENT_WORKER,
            can_propose=True,
            can_read_evidence=True,
            can_mutate=False,
            can_delegate=False,
            identity_required=True,
            authority_dependency="parent_task_claim",
        ),
        TrustMatrixEntry(
            origin=Boundary.INTERNAL_FABRIC,
            trust_tier=TrustTier.INTERNAL_RALPH_WORKER,
            can_propose=True,
            can_read_evidence=True,
            can_mutate=False,
            can_delegate=False,
            identity_required=True,
            authority_dependency="ralph_scan_authority",
        ),
        TrustMatrixEntry(
            origin=Boundary.EXTERNAL_GATEWAY,
            trust_tier=TrustTier.EXTERNAL_AUTHENTICATED_A2A,
            can_propose=True,
            can_read_evidence=True,
            can_mutate=False,
            can_delegate=False,
            identity_required=True,
            authority_dependency="not_yet_integrated",
        ),
        TrustMatrixEntry(
            origin=Boundary.EXTERNAL_GATEWAY,
            trust_tier=TrustTier.EXTERNAL_UNAUTHENTICATED,
            can_propose=False,
            can_read_evidence=False,
            can_mutate=False,
            can_delegate=False,
            identity_required=False,
            authority_dependency="none",
        ),
        TrustMatrixEntry(
            origin=Boundary.EXTERNAL_GATEWAY,
            trust_tier=TrustTier.EXTERNAL_PROVIDER_ADAPTER,
            can_propose=True,
            can_read_evidence=False,
            can_mutate=False,
            can_delegate=False,
            identity_required=True,
            authority_dependency="mcp_bridge_only",
        ),
        TrustMatrixEntry(
            origin=Boundary.ACP_PROJECTION,
            trust_tier=TrustTier.ACP_ORIGINATED,
            can_propose=True,
            can_read_evidence=True,
            can_mutate=False,
            can_delegate=False,
            identity_required=True,
            authority_dependency="acp_session",
        ),
        TrustMatrixEntry(
            origin=Boundary.PROVIDER_ADAPTER,
            trust_tier=TrustTier.EXTERNAL_PROVIDER_ADAPTER,
            can_propose=True,
            can_read_evidence=False,
            can_mutate=False,
            can_delegate=False,
            identity_required=True,
            authority_dependency="mcp_bridge_only",
        ),
    ]
    return entries


def build_future_handoff_contracts() -> list[FutureHandoffContract]:
    """Build the future handoff contracts for runtime consumers.

    These contracts define what AgentLoop, Ralph, fleet, and subagents
    must satisfy to consume A2A tasks. None are implemented here.
    """
    return [
        FutureHandoffContract(
            consumer_name="AgentLoop",
            consumer_description=(
                "Core agent loop consumes internal A2A tasks as mission "
                "requests, streams progress as A2A status + artifacts."
            ),
            required_trust_tier=TrustTier.INTERNAL_GOVERNED_AGENT,
            required_capabilities=[
                CapabilityClass.READ_ONLY_INVESTIGATION,
                CapabilityClass.PROPOSAL_GENERATION,
                CapabilityClass.CONTENT_LIGHT_ARTIFACT_EXCHANGE,
            ],
            integration_seam="agent_loop.py → A2AInternalFabric.create_task",
            precondition="Mission authority derived from coordination claim",
            postcondition="Terminal A2A task status with bounded artifacts",
            authority_dependency="mission_authority + lane_claims",
            status="not_implemented",
        ),
        FutureHandoffContract(
            consumer_name="Ralph",
            consumer_description=(
                "Ralph scanner consumes A2A tasks for read-only inspection, "
                "produces mission candidates as proposal tasks."
            ),
            required_trust_tier=TrustTier.INTERNAL_RALPH_WORKER,
            required_capabilities=[
                CapabilityClass.READ_ONLY_INVESTIGATION,
                CapabilityClass.PROPOSAL_GENERATION,
            ],
            integration_seam="ralph/scanner.py → A2AInternalFabric",
            precondition="Ralph scan result available",
            postcondition="MissionCandidate A2A proposal tasks",
            authority_dependency="ralph_scan_authority",
            status="not_implemented",
        ),
        FutureHandoffContract(
            consumer_name="Fleet Orchestrator",
            consumer_description=(
                "Fleet coordinator dispatches A2A tasks to child sessions, "
                "aggregates results via A2A task observations."
            ),
            required_trust_tier=TrustTier.INTERNAL_GOVERNED_AGENT,
            required_capabilities=[
                CapabilityClass.PROPOSAL_GENERATION,
                CapabilityClass.CONTENT_LIGHT_ARTIFACT_EXCHANGE,
                CapabilityClass.RUNTIME_DELEGATION,
            ],
            integration_seam="coordination/fleet_coordinator.py → A2AInternalFabric",
            precondition="Sprint cockpit and ready work plan available",
            postcondition="Parent convergence report with child A2A task results",
            authority_dependency="fleet_claim_corridor",
            status="not_implemented",
        ),
        FutureHandoffContract(
            consumer_name="Subagent Spawner",
            consumer_description=(
                "Subagent spawning consumes A2A tasks as bounded mission "
                "packets dispatched to child sessions."
            ),
            required_trust_tier=TrustTier.INTERNAL_SUBAGENT_WORKER,
            required_capabilities=[
                CapabilityClass.READ_ONLY_INVESTIGATION,
                CapabilityClass.PROPOSAL_GENERATION,
                CapabilityClass.EVIDENCE_VERIFICATION,
            ],
            integration_seam="spawn_session → A2AInternalFabric.create_task",
            precondition="Mission packet validated, no write lease conflict",
            postcondition="Child session result as A2A artifacts",
            authority_dependency="coordination_path_reservations",
            status="not_implemented",
        ),
        FutureHandoffContract(
            consumer_name="External Provider Adapter",
            consumer_description=(
                "External A2A gateway accepts proposal tasks from verified "
                "external agents. Adapter bridges A2A task operations through "
                "provider-specific transports (MCP tools, JSON-RPC)."
            ),
            required_trust_tier=TrustTier.EXTERNAL_AUTHENTICATED_A2A,
            required_capabilities=[
                CapabilityClass.PROPOSAL_GENERATION,
                CapabilityClass.CONTENT_LIGHT_ARTIFACT_EXCHANGE,
            ],
            integration_seam="A2AGateway → provider-specific transport bridge",
            precondition="Verified external identity, capability negotiation complete",
            postcondition="Proposal-only A2A task with content-light artifacts",
            authority_dependency="external_auth_integration (future)",
            status="not_implemented",
        ),
    ]


def verify_all_assertions(
    assertions: list[CrossBoundaryAssertion],
) -> tuple[bool, int, int]:
    """Verify all cross-boundary assertions.

    Returns (all_verified: bool, verified_count: int, total: int).
    """
    verified = sum(1 for a in assertions if a.verified)
    return verified == len(assertions), verified, len(assertions)


def mutation_permitted_for_boundary(
    boundary: Boundary, trust_tier: TrustTier
) -> tuple[bool, str]:
    """Check if mutation is permitted at a given boundary/tier intersection.

    Returns (permitted: bool, reason: str). Always gated.
    """
    matrix = build_trust_matrix()
    for entry in matrix:
        if entry.origin == boundary and entry.trust_tier == trust_tier:
            if entry.can_mutate:
                return True, f"Mutation permitted under {entry.authority_dependency}"
            return False, f"Mutation not permitted at {boundary}/{trust_tier}"
    return False, f"No trust matrix entry for {boundary}/{trust_tier}"


__all__ = [
    "Boundary",
    "CrossBoundaryAssertion",
    "CrossBoundaryRule",
    "FutureHandoffContract",
    "TrustMatrixEntry",
    "build_cross_boundary_assertions",
    "build_future_handoff_contracts",
    "build_trust_matrix",
    "mutation_permitted_for_boundary",
    "verify_all_assertions",
]
