"""Risk-tiered admission policy for recovered tool intents.

Applies hard invariants: no auto-execute for mutations, shell, or external effects.
"""

from __future__ import annotations

from rig_relay.core.telemetry.tool_contract import ToolMutationClass
from rig_relay.recovery.models import (
    AdmittedToolEntry,
    RecoveryAdmissionDecision,
    RecoveryAdmissionResult,
    RecoveryAdmissionTier,
    RecoveryIntent,
)

_AUTO_EXECUTE_DECISIONS = frozenset({
    RecoveryAdmissionDecision.AUTO_EXECUTE_READ_ONLY,
    RecoveryAdmissionDecision.AUTO_EXECUTE_VALIDATION,
})


def decide_admission(
    intent: RecoveryIntent, manifest_entry: AdmittedToolEntry
) -> RecoveryAdmissionResult:
    """Decide the admission path for a recovered tool intent."""
    tier = manifest_entry.recovery_admission_tier
    mutation_class = intent.mutation_class or manifest_entry.mutation_class
    canonical_name = intent.canonical_tool_name

    match tier:
        case RecoveryAdmissionTier.READ_ONLY_RECOVERABLE:
            decision = RecoveryAdmissionDecision.AUTO_EXECUTE_READ_ONLY
            proposal_only = False
            reason = None
        case RecoveryAdmissionTier.VALIDATION_RECOVERABLE:
            decision = RecoveryAdmissionDecision.AUTO_EXECUTE_VALIDATION
            proposal_only = False
            reason = None
        case RecoveryAdmissionTier.MUTATION_PROPOSAL_ONLY:
            decision = RecoveryAdmissionDecision.PROPOSAL_ONLY_MUTATION
            proposal_only = True
            reason = None
        case RecoveryAdmissionTier.EXTERNAL_SIDE_EFFECT_REFUSE:
            decision = RecoveryAdmissionDecision.REQUIRE_REMOTE_AUTHORIZATION
            proposal_only = False
            reason = (
                "External side effect requires remote authorization"
                " — not auto-executable through recovery"
            )
        case RecoveryAdmissionTier.RAW_SHELL_REFUSE:
            decision = RecoveryAdmissionDecision.REFUSE_RAW_SHELL
            proposal_only = False
            reason = "Raw shell execution is not recoverable through D0"
        case _:
            decision = RecoveryAdmissionDecision.REFUSE_UNSUPPORTED
            proposal_only = False
            reason = f"Tool '{canonical_name}' is not supported for recovery"

    return RecoveryAdmissionResult(
        admission_decision=decision,
        canonical_tool_name=canonical_name,
        mutation_class=mutation_class,
        proposal_only=proposal_only,
        refused_reason=reason,
    )


def is_auto_execute_decision(decision: RecoveryAdmissionDecision) -> bool:
    """Check if the decision permits automatic execution (no proposal needed)."""
    return decision in _AUTO_EXECUTE_DECISIONS


_MUTATION_CLASSES = frozenset({
    ToolMutationClass.WRITES_WORKSPACE,
    ToolMutationClass.MUTATES_GIT_STATE,
    ToolMutationClass.EXTERNAL_SIDE_EFFECT,
})


def is_mutation_class(mutation_class: str | None) -> bool:
    """Check if the mutation class is mutation-capable."""
    if mutation_class is None:
        return False
    return mutation_class.lower() in _MUTATION_CLASSES
