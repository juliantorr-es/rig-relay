"""Deterministic Tool Intent Recovery Corridor — D0 Pure Substrate.

Public API for the recovery package. D0 only — no live runtime integration.
"""

from __future__ import annotations

from rig_relay.recovery.admission_policy import (
    RecoveryAdmissionResult,
    decide_admission,
    is_auto_execute_decision,
    is_mutation_class,
)
from rig_relay.recovery.alias_policy import resolve_alias
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
from rig_relay.recovery.tool_surface_manifest import build_tool_surface_manifest
from rig_relay.recovery.transducer import transduce

__all__ = [
    "AdmittedToolEntry",
    "CanonicalToolSurfaceManifest",
    "RawRecoveryInput",
    "RecoveryAdmissionDecision",
    "RecoveryAdmissionResult",
    "RecoveryAdmissionTier",
    "RecoveryIntent",
    "RecoveryNormalizationRule",
    "RecoveryRefusal",
    "RecoveryRefusalCode",
    "RecoveryTransducerResult",
    "ToolIntentRecoveryReceipt",
    "build_recovery_receipt_from_intent",
    "build_recovery_receipt_from_refusal",
    "build_tool_surface_manifest",
    "decide_admission",
    "is_auto_execute_decision",
    "is_mutation_class",
    "resolve_alias",
    "transduce",
]
