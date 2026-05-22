"""Governance decision evidence persistence.

Bridges GateDecision → ReceiptEnvelope → ReceiptStore.
Provides fail-closed persistence for mutation-capable operations.
"""

from __future__ import annotations

from dataclasses import dataclass

from rig_relay.evidence.receipt_envelope import (
    ReceiptEnvelope,
    build_governance_decision_envelope,
)


@dataclass(slots=True)
class GovernanceDecisionEvidence:
    """Lightweight persistence adapter for governance decisions.

    Wraps an optional ReceiptStore to persist governance decisions
    as content-light evidence artifacts through ReceiptEnvelope.

    If no store is available, decisions are not persisted and the
    persistence_failed flag is set. For mutation-capable operations,
    callers should check persisted() before allowing mutation.
    """

    store: object | None = None
    _persisted: bool = False

    def persist(
        self,
        gate_decision: object,
        *,
        session_id: str | None = None,
        actor_id: str = "governance_runtime",
    ) -> ReceiptEnvelope | None:
        """Persist a GateDecision as a ReceiptEnvelope.

        Returns the envelope if persisted, or None if persistence failed.
        The caller should treat None as evidence persistence failure.
        For mutation-capable operations, this should trigger fail-closed
        (block or require review).

        Content-light: no raw prompts, completions, private repo content,
        secrets, credentials, raw diffs, or raw Actions logs.
        """
        envelope = build_governance_decision_envelope(
            gate_decision, session_id=session_id, actor_id=actor_id
        )
        if self.store is None:
            self._persisted = False
            return None

        try:
            append = getattr(self.store, "append", None)
            if append is None or not callable(append):
                self._persisted = False
                return None

            append(envelope)
            self._persisted = True
            return envelope
        except Exception:
            self._persisted = False
            return None

    def persisted(self) -> bool:
        """True if the last persist() call succeeded."""
        return self._persisted

    def store_is_available(self) -> bool:
        """True if a ReceiptStore is configured and accessible."""
        if self.store is None:
            return False
        append = getattr(self.store, "append", None)
        return append is not None and callable(append)


def should_block_mutation_on_evidence_failure(
    gate_decision: object, evidence: GovernanceDecisionEvidence | None
) -> bool:
    """Determine if a mutation should be blocked due to evidence persistence failure.

    Returns True if:
    - The gate decision was not persisted (evidence is None or persisted() is False)
    - AND the decision is for a mutation-capable operation (requires evidence trace)

    Read-only operations may proceed with evidence degradation.
    Mutation-capable operations must fail closed.
    """
    decision_value = str(getattr(gate_decision, "decision", ""))
    decision_attr = getattr(gate_decision, "decision", None)
    if decision_attr is not None and hasattr(decision_attr, "value"):
        decision_value = decision_attr.value
    if decision_value in {"blocked", "requires_review"}:
        return False

    if evidence is None:
        return True

    if not evidence.persisted():
        return True

    return False


__all__ = ["GovernanceDecisionEvidence", "should_block_mutation_on_evidence_failure"]
