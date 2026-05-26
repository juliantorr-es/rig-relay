"""Deterministic Tool Intent Recovery Corridor — D0 + D1A + D2 live-runtime.

Public API for the recovery package. D0 (substrate), D1A (evaluation),
D2 (constrained execution corridor).
"""

from __future__ import annotations

from rig_relay.recovery.admission_policy import (
    RecoveryAdmissionResult,
    decide_admission,
    is_auto_execute_decision,
    is_mutation_class,
)
from rig_relay.recovery.alias_policy import resolve_alias
from rig_relay.recovery.capability_admission import (
    CapabilityAdmissionDecision,
    CapabilityQuery,
    ConstraintCapabilityDisposition,
    EnforcementClass,
    RecoveryConstraintCapabilityAdmissionService,
    build_constraint_capability_disposition,
    compute_capability_projection,
)
from rig_relay.recovery.constrained_execution import (
    ConstrainedExecutionRequest,
    ConstrainedExecutionResult,
    ConstraintEnforcementDisposition,
    build_captured_emission_corpus,
    build_captured_emission_event,
    execute_constrained_recovery,
    validate_captured_emission_event,
)
from rig_relay.recovery.constraint_compiler import (
    ConstraintCompilationReceipt,
    ConstraintFeatureStatus,
    compile_constraints,
    load_canonical_constraint_receipt,
    persist_constraint_compilation_receipt,
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
from rig_relay.recovery.intent_authority import (
    DurableRecoveryIntentAuthority,
    GovernedPayloadStore,
    MaterializationRequest,
)
from rig_relay.recovery.intent_query import (
    IntentQueryResult,
    RecoveryIntentQueryService,
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
    "CapabilityAdmissionDecision",
    "CapabilityQuery",
    "ConstrainedExecutionRequest",
    "ConstrainedExecutionResult",
    "ConstraintCapabilityDisposition",
    "ConstraintCompilationReceipt",
    "ConstraintEnforcementDisposition",
    "ConstraintFeatureStatus",
    "DurableRecoveryIntentAuthority",
    "EnforcementClass",
    "EvidenceLedger",
    "GovernedPayloadStore",
    "IntentQueryResult",
    "MaterializationRequest",
    "RawRecoveryInput",
    "RecoveryAdmissionDecision",
    "RecoveryAdmissionResult",
    "RecoveryAdmissionTier",
    "RecoveryConstraintCapabilityAdmissionService",
    "RecoveryHandoffMutationProposal",
    "RecoveryHandoffReadOnly",
    "RecoveryHandoffRefusal",
    "RecoveryHandoffValidation",
    "RecoveryIntent",
    "RecoveryIntentQueryService",
    "RecoveryNormalizationRule",
    "RecoveryRefusal",
    "RecoveryRefusalCode",
    "RecoveryTransducerResult",
    "ToolIntentRecoveryReceipt",
    "build_captured_emission_corpus",
    "build_captured_emission_event",
    "build_constraint_capability_disposition",
    "build_mutation_handoff",
    "build_read_only_handoff",
    "build_recovery_receipt_from_intent",
    "build_recovery_receipt_from_refusal",
    "build_refusal_handoff",
    "build_report",
    "build_tool_surface_manifest",
    "build_validation_handoff",
    "compile_constraints",
    "compute_capability_projection",
    "decide_admission",
    "evaluate_recovery_cases",
    "execute_constrained_recovery",
    "is_auto_execute_decision",
    "is_mutation_class",
    "load_canonical_constraint_receipt",
    "persist_constraint_compilation_receipt",
    "resolve_alias",
    "transduce",
    "validate_captured_emission_event",
    "write_report",
]
