"""Rig Relay Governance Engine — Ported from Rig domain/governance/engine.py.

Pure, side-effect-free evaluation of governance gates. Decides whether
a proposed runtime/desktop/tool intent is allowed, blocked, requires
review, or not applicable.

This is the first pure engine — not the final policy brain.

Provenance (Rig-to-Relay porting doctrine):
  Porting status: port_direct (Rig source: rig/domain/governance/engine.py).
  Deviations: Simplified input signature (no proposal/evidence model);
  relay-native capability-based checks; use of RuntimeCapabilityKind from
  rig_relay.runtime.models instead of inline proposal parsing.
  See docs/governance/rig-to-relay-pattern-inventory.md for pattern map.
"""

from __future__ import annotations

from rig_relay.governance.decisions import (
    AllowedIntent,
    BlockedIntent,
    DecisionReason,
    GateDecision,
    GovernanceDecisionKind,
    GovernanceReasonSeverity,
    uuid7,
)
from rig_relay.runtime.models import (
    RuntimeCapabilityKind,
    RuntimeProviderKind,
    RuntimeProviderStatus,
    RuntimeProviderTrustTier,
)

# ── Provider trust tier defaults ──────────────────────────────────────

_PROVIDER_TRUST_TIER_DEFAULTS: dict[str, RuntimeProviderTrustTier] = {
    RuntimeProviderKind.LOCAL: RuntimeProviderTrustTier.EXECUTOR_CANDIDATE,
    RuntimeProviderKind.CLI: RuntimeProviderTrustTier.EXECUTOR_CANDIDATE,
    RuntimeProviderKind.CUSTOM: RuntimeProviderTrustTier.ADVISORY,
    RuntimeProviderKind.DRY_RUN: RuntimeProviderTrustTier.REVIEWER,
    RuntimeProviderKind.STUB: RuntimeProviderTrustTier.ADVISORY,
    RuntimeProviderKind.LOCAL_INFERENCE: RuntimeProviderTrustTier.EXECUTOR_CANDIDATE,
}

# ── Capability classification ──────────────────────────────────────────

_MUTATION_CAPABILITIES: frozenset[str] = frozenset({
    RuntimeCapabilityKind.FILE_WRITE_PROPOSAL,
    RuntimeCapabilityKind.SHELL_PROPOSAL,
    RuntimeCapabilityKind.PATCH_PROPOSAL,
    RuntimeCapabilityKind.COORDINATION_WRITE,
    RuntimeCapabilityKind.WORKTREE_WRITE,
})

_NETWORK_CAPABILITIES: frozenset[str] = frozenset({
    RuntimeCapabilityKind.NETWORK_FETCH_PROPOSAL,
    RuntimeCapabilityKind.DOCS_FETCH_PROPOSAL,
    RuntimeCapabilityKind.TELEMETRY_EXPORT_PROPOSAL,
})

_DEFAULT_GATE = "rig_relay.gate.default"


def _is_mutation_capability(kind: str) -> bool:
    return kind in _MUTATION_CAPABILITIES


def _is_network_capability(kind: str) -> bool:
    return kind in _NETWORK_CAPABILITIES


def _classify_capability(kind: str) -> str | None:
    if _is_mutation_capability(kind):
        return "mutation"
    if _is_network_capability(kind):
        return "network"
    return None


# ── Engine ─────────────────────────────────────────────────────────────


class GovernanceEngine:
    """Pure governance gate evaluator.

    This class has no mutable state. All inputs are passed to
    evaluate_action_legality() and a GateDecision is returned
    without side effects.
    """

    @staticmethod
    def default_trust_tier_for_provider(provider_kind: str) -> RuntimeProviderTrustTier:
        return _PROVIDER_TRUST_TIER_DEFAULTS.get(
            provider_kind, RuntimeProviderTrustTier.ADVISORY
        )

    @staticmethod
    def evaluate_action_legality(
        workspace_id: str | None = None,
        intent_id: str = "",
        intent_kind: str = "",
        requested_capabilities: list[RuntimeCapabilityKind] | list[str] | None = None,
        provider_trust_tier: RuntimeProviderTrustTier | None = None,
        provider_status: RuntimeProviderStatus | None = None,
        evidence_available: bool = False,
        allow_mutation: bool = False,
        allow_network: bool = False,
        dirty_policy_satisfied: bool = True,
        receipt_store: object | None = None,
        session_id: str | None = None,
        surface: str | None = None,
    ) -> GateDecision:
        """Evaluate whether a proposed action is legal under governance.

        Args:
            workspace_id: Optional workspace context identifier.
            intent_id: Identifier of the proposed intent.
            intent_kind: Kind of the proposed intent.
            requested_capabilities: Capabilities requested by the intent.
            provider_trust_tier: Trust tier of the provider.
            provider_status: Operational status of the provider.
            evidence_available: Whether evidence is available.
            allow_mutation: Whether mutation is explicitly allowed.
            allow_network: Whether network access is explicitly allowed.
            dirty_policy_satisfied: Whether dirty-file policy is satisfied.
            receipt_store: Optional ReceiptStore for audit trail persistence.
            session_id: Optional session ID for cross-surface correlation.
            surface: Optional surface identifier.

        Returns:
            A GateDecision with the evaluation result.

        When receipt_store is provided, the decision is persisted as a
        ReceiptEnvelope through the evidence spine for audit trail purposes.
        """
        reasons: list[DecisionReason] = []
        blocked: list[BlockedIntent] = []
        allowed: list[AllowedIntent] = []

        caps = list(requested_capabilities or [])
        cap_strs = [str(c) for c in caps]

        # ── Not applicable: no capabilities, unknown intent ──────────
        if not caps and not intent_kind:
            decision = GovernanceDecisionKind.NOT_APPLICABLE
            reasons_na = [
                DecisionReason(
                    code="no_requested_capabilities",
                    message="No capabilities requested and no intent kind specified",
                    severity=GovernanceReasonSeverity.INFO,
                )
            ]
            if receipt_store is not None:
                _emit_decision_receipt(
                    receipt_store,
                    workspace_id=workspace_id,
                    decision=decision,
                    reasons=reasons_na,
                    session_id=session_id,
                    surface=surface,
                )
            return GateDecision(
                schema_version="rig.relay.governance_decision.v1",
                decision_id=uuid7(),
                workspace_id=workspace_id,
                decision=decision,
                gate=_DEFAULT_GATE,
                reasons=reasons_na,
            )

        # ── Dirty policy ────────────────────────────────────────────
        if not dirty_policy_satisfied:
            reasons.append(
                DecisionReason(
                    code="dirty_policy_violated",
                    message="Dirty-file policy is not satisfied",
                    severity=GovernanceReasonSeverity.ERROR,
                )
            )
            blocked.append(
                BlockedIntent(
                    intent_id=intent_id,
                    reason="Dirty-file policy not satisfied",
                    code="dirty_policy_violated",
                )
            )

        # ── Provider trust tier ─────────────────────────────────────
        if provider_trust_tier == RuntimeProviderTrustTier.BLOCKED:
            reasons.append(
                DecisionReason(
                    code="provider_trust_tier_blocked",
                    message="Provider trust tier is blocked",
                    severity=GovernanceReasonSeverity.ERROR,
                )
            )
            blocked.append(
                BlockedIntent(
                    intent_id=intent_id,
                    reason="Provider trust tier is blocked",
                    code="provider_trust_tier_blocked",
                )
            )

        # ── Provider status for execution-like capabilities ─────────
        if provider_status is not None and provider_status in {
            RuntimeProviderStatus.BLOCKED,
            RuntimeProviderStatus.ERROR,
            RuntimeProviderStatus.UNAVAILABLE,
        }:
            has_execution_caps = any(
                _is_mutation_capability(c) or _is_network_capability(c)
                for c in cap_strs
            )
            if has_execution_caps:
                reasons.append(
                    DecisionReason(
                        code="provider_status_blocked_execution",
                        message=f"Provider status is {provider_status.value}",
                        severity=GovernanceReasonSeverity.ERROR,
                    )
                )
                blocked.append(
                    BlockedIntent(
                        intent_id=intent_id,
                        reason=f"Provider status is {provider_status.value}",
                        code="provider_status_blocked_execution",
                    )
                )

        # ── Mutation review ─────────────────────────────────────────
        if not allow_mutation:
            mutation_caps = [c for c in cap_strs if _is_mutation_capability(c)]
            if mutation_caps:
                reasons.append(
                    DecisionReason(
                        code="mutation_requires_review",
                        message=f"Mutation capability requested without allow_mutation: {mutation_caps}",
                        severity=GovernanceReasonSeverity.WARNING,
                    )
                )
                blocked.append(
                    BlockedIntent(
                        intent_id=intent_id,
                        reason="Mutation requires review — set allow_mutation=True to proceed",
                        code="mutation_requires_review",
                    )
                )

        # ── Network review ──────────────────────────────────────────
        if not allow_network:
            network_caps = [c for c in cap_strs if _is_network_capability(c)]
            if network_caps:
                reasons.append(
                    DecisionReason(
                        code="network_requires_review",
                        message=f"Network capability requested without allow_network: {network_caps}",
                        severity=GovernanceReasonSeverity.WARNING,
                    )
                )
                blocked.append(
                    BlockedIntent(
                        intent_id=intent_id,
                        reason="Network access requires review — set allow_network=True to proceed",
                        code="network_requires_review",
                    )
                )

        # ── Determine decision ──────────────────────────────────────
        has_blocked_reasons = any(
            r.severity
            in {GovernanceReasonSeverity.ERROR, GovernanceReasonSeverity.CRITICAL}
            for r in reasons
        )
        has_warning_reasons = any(
            r.severity == GovernanceReasonSeverity.WARNING for r in reasons
        )

        if has_blocked_reasons:
            decision = GovernanceDecisionKind.BLOCKED
        elif has_warning_reasons:
            decision = GovernanceDecisionKind.REQUIRES_REVIEW
        else:
            decision = GovernanceDecisionKind.ALLOWED
            allowed.append(
                AllowedIntent(
                    intent_id=intent_id, reason="All governance checks passed"
                )
            )
            if not reasons:
                reasons.append(
                    DecisionReason(
                        code="all_checks_passed",
                        message="All governance checks passed",
                        severity=GovernanceReasonSeverity.INFO,
                    )
                )

        if receipt_store is not None:
            _emit_decision_receipt(
                receipt_store,
                workspace_id=workspace_id,
                decision=decision,
                reasons=reasons,
                session_id=session_id,
                surface=surface,
            )

        return GateDecision(
            schema_version="rig.relay.governance_decision.v1",
            decision_id=uuid7(),
            workspace_id=workspace_id,
            decision=decision,
            gate=_DEFAULT_GATE,
            reasons=reasons,
            allowed_intents=allowed,
            blocked_intents=blocked,
        )


def _emit_decision_receipt(
    receipt_store: object,
    *,
    workspace_id: str | None,
    decision: GovernanceDecisionKind,
    reasons: list[DecisionReason],
    session_id: str | None,
    surface: str | None,
) -> None:
    try:
        from rig_relay.evidence.receipt_envelope import (
            ReceiptActor,
            ReceiptActorKind,
            ReceiptActorTier,
            ReceiptDecision,
            ReceiptSubject,
            ReceiptSubjectKind,
            build_receipt_envelope,
        )

        env_id = uuid7()
        reason_codes = [r.code for r in reasons]
        rationale = "; ".join(reason_codes) if reason_codes else None

        actor = ReceiptActor(
            actor_id="governance_engine",
            actor_kind=ReceiptActorKind.RUNTIME,
            display_name="Governance Engine",
            is_human=False,
            authority_tier=ReceiptActorTier.ADMINISTRATIVE,
        )

        subject = ReceiptSubject(
            subject_id=env_id,
            subject_kind=ReceiptSubjectKind.GOVERNANCE_DECISION,
            workspace_id=workspace_id,
            session_id=session_id,
        )

        receipt_decision = ReceiptDecision(
            decision=decision.value,
            rationale=rationale,
            gate=_DEFAULT_GATE,
            governance_decision_id=env_id,
            surface=surface,
            authority_tier="administrative",
            content_light_classification="public_safe",
        )

        envelope = build_receipt_envelope(
            envelope_id=env_id,
            receipt_kind="governance_decision",
            actor=actor,
            subject=subject,
            decision=receipt_decision,
            session_id=session_id,
            authority_tier="administrative",
        )

        append_fn = getattr(receipt_store, "append", None)
        if append_fn is not None and callable(append_fn):
            append_fn(envelope)
    except Exception:
        pass


__all__ = ["GovernanceEngine", "_is_mutation_capability"]
