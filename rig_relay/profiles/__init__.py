"""Governed Provider–Harness Compatibility Profiles and Session Envelope Resolution.

Exposes the profile registry, resolver, context envelope assembler,
tool dialect adapter, session receipt builder, projection, and evaluation.
"""

from __future__ import annotations

from rig_relay.profiles._context_envelope import (
    build_context_envelope,
    compute_stable_prefix_digest,
)
from rig_relay.profiles._evaluation import evaluate_all_profiles, evaluate_profile
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
    HarnessCompatibilityProfile,
    InstructionRenderingStrategy,
    ProfileEvaluationInput,
    ProfileEvaluationResult,
    ProfileResolutionError,
    ProfileResolutionInput,
    ProfileResolutionResult,
    ProfileStatus,
    ReasoningEffortPosture,
    TaskRole,
    ToolDialectStrategy,
    WorkspaceSubagentPosture,
)

__all__ = [
    "BUILTIN_PROFILES",
    "CachingPosture",
    "CapabilityRequirements",
    "ContextEnvelopeStrategy",
    "HarnessCompatibilityProfile",
    "InstructionRenderingStrategy",
    "ProfileEvaluationInput",
    "ProfileEvaluationResult",
    "ProfileResolutionError",
    "ProfileResolutionInput",
    "ProfileResolutionResult",
    "ProfileStatus",
    "ReasoningEffortPosture",
    "TaskRole",
    "ToolDialectStrategy",
    "WorkspaceSubagentPosture",
    "adapt_tool_description",
    "adapt_tool_result",
    "assert_tool_dialect_authority_preserved",
    "build_context_envelope",
    "build_profile_projection",
    "build_session_resolution_receipt",
    "compute_stable_prefix_digest",
    "evaluate_all_profiles",
    "evaluate_profile",
    "merge_profile_projection_into_desktop",
    "resolve_profile",
    "resolve_profiles_batch",
]
