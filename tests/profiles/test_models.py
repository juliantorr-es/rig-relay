from __future__ import annotations

import hashlib

from pydantic import ValidationError
import pytest

from rig_relay.profiles.models import (
    CachingPosture,
    CapabilityRequirements,
    ContextEnvelopeStrategy,
    HarnessCompatibilityProfile,
    InstructionRenderingStrategy,
    ProfileEvaluationResult,
    ProfileResolutionInput,
    ProfileStatus,
    ReasoningEffortPosture,
    TaskRole,
    ToolDialectStrategy,
    WorkspaceSubagentPosture,
)


def test_harness_compatibility_profile_creation():
    profile = HarnessCompatibilityProfile(
        profile_id="test.profile.v1",
        profile_version="1.0.0",
        display_name="Test Profile",
        description="A test profile.",
        provider_families=["openai"],
        model_patterns=["gpt-.*"],
        supported_roles=[TaskRole.IMPLEMENTATION],
        authority_rule="May shape context. Must never authorize mutation.",
    )
    assert profile.profile_id == "test.profile.v1"
    assert profile.evaluation_status == ProfileStatus.EXPERIMENTAL
    assert profile.context_envelope_strategy == ContextEnvelopeStrategy.RIG_GOVERNED
    assert profile.tool_dialect_strategy == ToolDialectStrategy.RIG_NATIVE


def test_harness_compatibility_profile_extra_fields_rejected():
    with pytest.raises(ValidationError):
        HarnessCompatibilityProfile(
            profile_id="test.profile.v1",
            profile_version="1.0.0",
            display_name="Test",
            description="Test",
            provider_families=["openai"],
            model_patterns=["gpt-.*"],
            supported_roles=[TaskRole.IMPLEMENTATION],
            authority_rule="",
            profile_digest="",
            extra_field="should_reject",
        )


def test_profile_status_enum_values():
    assert ProfileStatus.EXPERIMENTAL.value == "experimental"
    assert ProfileStatus.CANDIDATE.value == "candidate"
    assert ProfileStatus.VERIFIED.value == "verified"
    assert ProfileStatus.DEPRECATED.value == "deprecated"


def test_task_role_enum_values():
    assert TaskRole.IMPLEMENTATION.value == "implementation"
    assert TaskRole.ARCHITECTURE_PLANNING.value == "architecture_planning"
    assert TaskRole.CODE_REVIEW_ADVERSARIAL.value == "code_review_adversarial"
    assert TaskRole.AUDIT_REVIEW.value == "audit_review"
    assert TaskRole.UI_NATIVE_TASK.value == "ui_native_task"
    assert (
        TaskRole.RESTRICTED_SENSITIVE_INSPECTION.value
        == "restricted_sensitive_inspection"
    )


def test_strategy_enum_values():
    assert ContextEnvelopeStrategy.RIG_GOVERNED.value == "rig_governed"
    assert ContextEnvelopeStrategy.CODEX_COMPATIBLE.value == "codex_compatible"
    assert ContextEnvelopeStrategy.CLAUDE_COMPATIBLE.value == "claude_compatible"
    assert ContextEnvelopeStrategy.COPILOT_COMPATIBLE.value == "copilot_compatible"

    assert InstructionRenderingStrategy.RIG_DEFAULT.value == "rig_default"
    assert InstructionRenderingStrategy.CODEX.value == "codex"
    assert InstructionRenderingStrategy.CLAUDE.value == "claude"
    assert InstructionRenderingStrategy.COPILOT.value == "copilot"

    assert ToolDialectStrategy.RIG_NATIVE.value == "rig_native"
    assert (
        ToolDialectStrategy.OPENAI_FUNCTION_CALLING.value == "openai_function_calling"
    )
    assert ToolDialectStrategy.ANTHROPIC_TOOL_USE.value == "anthropic_tool_use"
    assert ToolDialectStrategy.MODEL_DRIVEN.value == "model_driven"


def test_capability_requirements_defaults():
    cap = CapabilityRequirements()
    assert cap.requires_tool_use is True
    assert cap.requires_streaming is False
    assert cap.requires_structured_output is False
    assert cap.requires_thinking is False
    assert cap.requires_vision is False
    assert cap.requires_embeddings is False
    assert cap.min_context_window == 8000
    assert cap.min_output_tokens == 1024
    assert cap.max_input_price_per_million == 0.0


def test_reasoning_effort_posture_defaults():
    re = ReasoningEffortPosture()
    assert re.supports_effort_control is False
    assert re.default_effort is None
    assert re.available_efforts == []
    assert re.adaptive_reasoning is False
    assert re.uses_keyword_triggers is False


def test_caching_posture_defaults():
    cp = CachingPosture()
    assert cp.caching_active is False
    assert cp.cache_mechanism == "none"
    assert cp.cache_ttl_seconds == 0
    assert cp.supports_extended_cache is False
    assert cp.cache_cost_discount_pct == 0.0


def test_workspace_subagent_posture_defaults():
    ws = WorkspaceSubagentPosture()
    assert ws.supports_subagents is False
    assert ws.subagent_context_isolation is False
    assert ws.max_parallel_subagents == 0
    assert ws.subagent_model_selection == "same_as_parent"


def test_profile_resolution_input_validation():
    inp = ProfileResolutionInput(provider="openai", model_id="gpt-4o")
    assert inp.task_role == TaskRole.IMPLEMENTATION
    assert inp.prefer_profile_id is None
    assert inp.model_capabilities is None


def test_profile_digest_computation():
    profile = HarnessCompatibilityProfile(
        profile_id="test.digest.v1",
        profile_version="1.0.0",
        display_name="Digest Test",
        description="Test digest computation.",
        provider_families=["openai"],
        model_patterns=[".*"],
        supported_roles=[TaskRole.IMPLEMENTATION],
        authority_rule="May shape context.",
    )
    profile = profile.model_copy(
        update={
            "profile_digest": hashlib.sha256(
                profile.model_dump_json(
                    exclude={"profile_digest"}, exclude_defaults=False
                ).encode()
            ).hexdigest()
        }
    )

    original_digest = profile.profile_digest

    changed = profile.model_copy(update={"display_name": "Changed Name"})
    new_digest = hashlib.sha256(
        changed.model_dump_json(
            exclude={"profile_digest"}, exclude_defaults=False
        ).encode()
    ).hexdigest()
    assert new_digest != original_digest


def test_profile_evaluation_result_creation():
    result = ProfileEvaluationResult(
        evaluation_id="eval-001",
        profile_id="test.profile.v1",
        task_role=TaskRole.IMPLEMENTATION,
        provider="openai",
        model_id="gpt-4o",
        context_assembly_correct=True,
        tool_authority_preserved=True,
        deterministic_resolution=True,
        unsupported_capability_refused=True,
        receipt_reconstructable=True,
    )
    assert result.evaluation_id == "eval-001"
    assert result.context_assembly_correct is True
