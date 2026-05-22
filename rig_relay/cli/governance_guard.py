from __future__ import annotations

"""CLI governance pre-flight helper.

Provides reusable governance checks for CLI scripts that perform
mutation, admin configuration, remote provider mutations, or
destructive deletions. Scripts that mutate must route through
this guard before execution.

Evidence integration: mutation-capable --execute paths can persist
GateDecision through the canonical evidence adapter (GovernanceDecisionEvidence
+ ReceiptStore). If evidence persistence fails for mutation, execution
is blocked (fail-closed).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from rig_relay.evidence.governance_decision_evidence import (
    GovernanceDecisionEvidence,
    should_block_mutation_on_evidence_failure,
)
from rig_relay.governance.decisions import GateDecision, GovernanceDecisionKind
from rig_relay.governance.governance_engine import GovernanceEngine


@dataclass(slots=True)
class GovernedExecution:
    """Result of a governed execution check including evidence status.

    Fields:
        decision: The governance decision.
        can_execute: True if the mutation/action may proceed.
        evidence_status: Persistence status (persisted / not_persisted /
            persistence_failed / not_applicable).
        evidence_ref: Receipt envelope_id if persisted, else None.
    """

    decision: GateDecision
    can_execute: bool
    evidence_status: str = "not_applicable"
    evidence_ref: str | None = None


def require_governed_execution(
    *,
    script_name: str,
    authority_tier: str,
    capability_id: str,
    execute_requested: bool,
    workspace_id: str | None = None,
    allow_mutation: bool = True,
    allow_network: bool = False,
    allow_admin: bool = False,
) -> GateDecision:
    """Require a governance decision before allowing execution.

    Args:
        script_name: Name of the calling script.
        authority_tier: Cross-surface authority tier for this script.
        capability_id: Capability being exercised (e.g. 'admin_config').
        execute_requested: Whether --execute or --execute-remote was passed.
        workspace_id: Optional workspace context.
        allow_mutation: Whether mutation is explicitly allowed.
        allow_network: Whether network access is explicitly allowed.
        allow_admin: Whether admin configuration is explicitly allowed
            (admin operations always require --execute).

    Returns:
        GateDecision with the governance result.
    """
    if not execute_requested:
        return GateDecision(
            schema_version="rig.relay.governance_decision.v1",
            decision=GovernanceDecisionKind.ALLOWED,
            gate="cli.dry_run",
            surface="cli_script",
            authority_tier=authority_tier,
            capability_id=capability_id,
        )

    engine = GovernanceEngine()
    decision = engine.evaluate_action_legality(
        workspace_id=workspace_id,
        intent_id=script_name,
        intent_kind=capability_id,
        requested_capabilities=[capability_id],
        allow_mutation=allow_mutation or allow_admin,
        allow_network=allow_network,
        dirty_policy_satisfied=True,
    )
    decision.surface = "cli_script"
    decision.authority_tier = authority_tier
    decision.capability_id = capability_id
    return decision


def require_governed_execution_with_evidence(
    *,
    script_name: str,
    authority_tier: str,
    capability_id: str,
    execute_requested: bool,
    receipt_store: Any = None,
    workspace_id: str | None = None,
    allow_mutation: bool = True,
    allow_network: bool = False,
    allow_admin: bool = False,
) -> GovernedExecution:
    """Require a governance decision and persist evidence.

    For mutation-capable operations, governance decision evidence is
    persisted through the canonical evidence path. If persistence fails,
    the execution is blocked (fail-closed).

    Args:
        script_name: Name of the calling script.
        authority_tier: Cross-surface authority tier.
        capability_id: Capability exercised.
        execute_requested: Whether --execute was passed.
        receipt_store: Optional ReceiptStore for evidence persistence.
        workspace_id: Optional workspace context.
        allow_mutation: Whether mutation is allowed.
        allow_network: Whether network access is allowed.
        allow_admin: Whether admin configuration is allowed.

    Returns:
        GovernedExecution with decision, can_execute, evidence_status, evidence_ref.
    """
    decision = require_governed_execution(
        script_name=script_name,
        authority_tier=authority_tier,
        capability_id=capability_id,
        execute_requested=execute_requested,
        workspace_id=workspace_id,
        allow_mutation=allow_mutation,
        allow_network=allow_network,
        allow_admin=allow_admin,
    )

    if not execute_requested:
        return GovernedExecution(
            decision=decision, can_execute=True, evidence_status="not_applicable"
        )

    if decision.decision.value in {"blocked", "requires_review"}:
        return GovernedExecution(
            decision=decision, can_execute=False, evidence_status="not_persisted"
        )

    evidence = GovernanceDecisionEvidence(store=receipt_store)
    envelope = evidence.persist(decision)

    if envelope is not None and evidence.persisted():
        return GovernedExecution(
            decision=decision,
            can_execute=True,
            evidence_status="persisted",
            evidence_ref=envelope.envelope_id,
        )

    mutation_capable = authority_tier in {
        "local_mutation",
        "remote_mutation",
        "admin_configuration",
    }
    if mutation_capable and should_block_mutation_on_evidence_failure(
        decision, evidence
    ):
        return GovernedExecution(
            decision=decision, can_execute=False, evidence_status="persistence_failed"
        )

    return GovernedExecution(
        decision=decision, can_execute=True, evidence_status="not_persisted"
    )


def emit_structured_result(
    *,
    script_name: str,
    authority_tier: str,
    capability_id: str,
    dry_run: bool,
    execute_requested: bool,
    decision: GateDecision,
    status: str,
    can_execute: bool | None = None,
    evidence_ref: str | None = None,
    evidence_status: str | None = None,
    artifacts: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Emit a structured JSON result for CLI script invocation.

    Args:
        script_name: Name of the calling script.
        authority_tier: Cross-surface authority tier.
        capability_id: Capability exercised.
        dry_run: Whether the invocation was dry-run.
        execute_requested: Whether --execute was passed.
        decision: The governance decision.
        status: Execution status (dry_run, executed, blocked_by_governance, failed).
        can_execute: Optional explicit execution permission flag.
        evidence_ref: Optional receipt envelope_id if evidence persisted.
        evidence_status: Persistence status (persisted, not_persisted,
            persistence_failed, not_applicable).
        artifacts: Optional artifact references.
        error: Optional error message.

    Returns:
        A content-light structured result dict.
    """
    result: dict[str, Any] = {
        "schema_version": "rig.relay.cli_script_result.v1",
        "script": script_name,
        "surface": "cli_script",
        "authority_tier": authority_tier,
        "capability_id": capability_id,
        "dry_run": dry_run,
        "execute_requested": execute_requested,
        "decision_id": decision.decision_id,
        "decision": decision.decision.value,
        "status": status,
        "content_light": True,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    if can_execute is not None:
        result["can_execute"] = can_execute
    if evidence_ref is not None:
        result["evidence_ref"] = evidence_ref
    if evidence_status is not None:
        result["evidence_status"] = evidence_status
    if artifacts:
        result["artifacts"] = artifacts
    if error:
        result["error"] = error
    return result


__all__ = [
    "GovernedExecution",
    "emit_structured_result",
    "require_governed_execution",
    "require_governed_execution_with_evidence",
]
