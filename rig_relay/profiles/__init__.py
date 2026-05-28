"""Governed Provider–Harness Compatibility Profiles and Session Envelope Resolution.

Exposes the profile registry, resolver, context envelope assembler,
tool dialect adapter, session receipt builder, projection, evaluation,
and capability evidence layer.
"""

from __future__ import annotations

from rig_relay.profiles._capability_evidence import (
    BUILTIN_CAPABILITY_EVIDENCE,
    CapabilityEvidenceItem,
    CapabilityEvidenceSourceClass,
    CapabilityName,
    CapabilityPosture,
    build_capability_projection,
    merge_capability_evidence,
    resolve_capability_evidence,
    validate_profile_requirements_against_evidence,
)
from rig_relay.profiles._context_envelope import (
    build_context_envelope,
    compute_stable_prefix_digest,
)
from rig_relay.profiles._downstream_contracts import (
    ContextCapsuleBindingReceipt,
    ContextCapsuleBindingRequest,
    HarnessProfileStatusProjection,
    ProfileEvaluationObservation,
    ProfileSelectionMetrics,
    RuntimeProfileCapabilityObservation,
    WorkspaceProfileAssignmentReceipt,
    WorkspaceProfileAssignmentRequest,
    build_y0_projection,
    build_y1_assignment_request,
    build_y2_binding_request,
    build_y4_observation,
)
from rig_relay.profiles._evaluation import evaluate_all_profiles, evaluate_profile
from rig_relay.profiles._evidence_ledger import (
    Y3ProfileEvent,
    Y3ProfileEventKind,
    load_y3_events,
    persist_y3_event,
    verify_y3_ledger_integrity,
)
from rig_relay.profiles._governance_adapter import admit_profile_selection
from rig_relay.profiles._profile_registry import BUILTIN_PROFILES
from rig_relay.profiles._projection import (
    build_profile_projection,
    merge_profile_projection_into_desktop,
)
from rig_relay.profiles._resolver import resolve_profile, resolve_profiles_batch
from rig_relay.profiles._session_receipt import build_session_resolution_receipt
from rig_relay.profiles._tool_dialect import (
    adapt_tool_description,
    adapt_tool_result,
    assert_tool_dialect_authority_preserved,
)
from rig_relay.profiles.models import (
    CachingPosture,
    CapabilityRequirements,
    ContextEnvelopeStrategy,
    GovernanceAdmissionState,
    HarnessCompatibilityProfile,
    InstructionRenderingStrategy,
    ProfileEvaluationInput,
    ProfileEvaluationResult,
    ProfileResolutionError,
    ProfileResolutionInput,
    ProfileResolutionResult,
    ProfileStatus,
    ReasoningEffortPosture,
    ResolutionOutcome,
    TaskRole,
    ToolDialectStrategy,
    WorkspaceSubagentPosture,
)

__all__ = [
    "BUILTIN_CAPABILITY_EVIDENCE",
    "BUILTIN_PROFILES",
    "CachingPosture",
    "CapabilityEvidenceItem",
    "CapabilityEvidenceSourceClass",
    "CapabilityName",
    "CapabilityPosture",
    "CapabilityRequirements",
    "ContextCapsuleBindingReceipt",
    "ContextCapsuleBindingRequest",
    "ContextEnvelopeStrategy",
    "GovernanceAdmissionState",
    "HarnessCompatibilityProfile",
    "HarnessProfileStatusProjection",
    "InstructionRenderingStrategy",
    "ProfileEvaluationInput",
    "ProfileEvaluationObservation",
    "ProfileEvaluationResult",
    "ProfileResolutionError",
    "ProfileResolutionInput",
    "ProfileResolutionResult",
    "ProfileSelectionMetrics",
    "ProfileStatus",
    "ReasoningEffortPosture",
    "ResolutionOutcome",
    "RuntimeProfileCapabilityObservation",
    "TaskRole",
    "ToolDialectStrategy",
    "WorkspaceProfileAssignmentReceipt",
    "WorkspaceProfileAssignmentRequest",
    "WorkspaceSubagentPosture",
    "Y3ProfileEvent",
    "Y3ProfileEventKind",
    "adapt_tool_description",
    "adapt_tool_result",
    "admit_profile_selection",
    "assert_tool_dialect_authority_preserved",
    "build_capability_projection",
    "build_context_envelope",
    "build_profile_projection",
    "build_session_resolution_receipt",
    "build_y0_projection",
    "build_y1_assignment_request",
    "build_y2_binding_request",
    "build_y4_observation",
    "compute_stable_prefix_digest",
    "evaluate_all_profiles",
    "evaluate_profile",
    "load_y3_events",
    "merge_capability_evidence",
    "merge_profile_projection_into_desktop",
    "persist_y3_event",
    "resolve_capability_evidence",
    "resolve_profile",
    "resolve_profiles_batch",
    "validate_profile_requirements_against_evidence",
    "verify_y3_ledger_integrity",
]
