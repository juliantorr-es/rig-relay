"""Deterministic Tool Intent Recovery Corridor — D0 Pure Substrate + D1A Evaluation.

Public API for the recovery package. D0 and D1A — no live runtime integration.
"""

from __future__ import annotations

from rig_relay.recovery.admission_policy import (
    RecoveryAdmissionResult,
    decide_admission,
    is_auto_execute_decision,
    is_mutation_class,
)
from rig_relay.recovery.alias_policy import resolve_alias
from rig_relay.recovery.constraint_compiler import (
    ConstraintCompilationReceipt,
    ConstraintFeatureStatus,
    compile_constraints,
)
from rig_relay.recovery.evaluation import evaluate_cases as evaluate_recovery_cases
from rig_relay.recovery.evidence_ledger import EvidenceLedger
from rig_relay.recovery.handoff import (
    RecoveryHandoffMutationProposal,
    RecoveryHandoffReadOnly,
    RecoveryHandoffRefusal,
    RecoveryHandoffValidation,
    build_mutation_handoff,
    build_read_only_handoff,
    build_refusal_handoff,
    build_validation_handoff,
)
from rig_relay.recovery.models import (
    AdmittedToolEntry,
    CanonicalToolSurfaceManifest,
    RawRecoveryInput,
    RecoveryAdmissionDecision,
    RecoveryAdmissionTier,
    RecoveryIntent,
    RecoveryNormalizationRule,
    RecoveryRefusal,
    RecoveryRefusalCode,
    RecoveryTransducerResult,
)
from rig_relay.recovery.receipt import (
    ToolIntentRecoveryReceipt,
    build_recovery_receipt_from_intent,
    build_recovery_receipt_from_refusal,
)
from rig_relay.recovery.report import build_report, write_report
from rig_relay.recovery.tool_surface_manifest import build_tool_surface_manifest
from rig_relay.recovery.transducer import transduce

__all__ = [
    "AdmittedToolEntry",
    "CanonicalToolSurfaceManifest",
    "ConstraintCompilationReceipt",
    "ConstraintFeatureStatus",
    "EvidenceLedger",
    "RawRecoveryInput",
    "RecoveryAdmissionDecision",
    "RecoveryAdmissionResult",
    "RecoveryAdmissionTier",
    "RecoveryHandoffMutationProposal",
    "RecoveryHandoffReadOnly",
    "RecoveryHandoffRefusal",
    "RecoveryHandoffValidation",
    "RecoveryIntent",
    "RecoveryNormalizationRule",
    "RecoveryRefusal",
    "RecoveryRefusalCode",
    "RecoveryTransducerResult",
    "ToolIntentRecoveryReceipt",
    "build_mutation_handoff",
    "build_read_only_handoff",
    "build_recovery_receipt_from_intent",
    "build_recovery_receipt_from_refusal",
    "build_refusal_handoff",
    "build_report",
    "build_tool_surface_manifest",
    "build_validation_handoff",
    "compile_constraints",
    "decide_admission",
    "evaluate_recovery_cases",
    "is_auto_execute_decision",
    "is_mutation_class",
    "resolve_alias",
    "transduce",
    "write_report",
]
