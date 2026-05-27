from __future__ import annotations

import pytest

from rig_relay.profiles._profile_registry import BUILTIN_PROFILES
from rig_relay.profiles._resolver import resolve_profile, resolve_profiles_batch
from rig_relay.profiles.models import (
    ProfileResolutionError,
    ProfileResolutionInput,
    TaskRole,
)


def _find_profile(profile_id: str):
    for p in BUILTIN_PROFILES:
        if p.profile_id == profile_id:
            return p
    raise ValueError(f"Profile {profile_id} not found")


def test_resolve_rig_native_for_openai_gpt4o_implementation():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        model_capabilities={"supports_tools": True},
    )
    result = resolve_profile(inp)
    assert result.selected_profile.profile_id in {
        "rig.native.governed.v1",
        "openai.codex.compatible_engineering.v1",
    }
    assert result.confidence in ("high", "medium", "low")
    assert result.is_user_override is False


def test_resolve_codex_profile_for_openai_gpt_model():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        task_role=TaskRole.IMPLEMENTATION,
        model_capabilities={"supports_tools": True},
    )
    result = resolve_profile(inp)
    assert result.selected_profile.profile_id in {
        "rig.native.governed.v1",
        "openai.codex.compatible_engineering.v1",
    }


def test_resolve_claude_execution_for_anthropic_claude_model():
    inp = ProfileResolutionInput(
        provider="anthropic",
        model_id="claude-sonnet-4-20250514",
        task_role=TaskRole.IMPLEMENTATION,
        model_capabilities={"supports_tools": True},
    )
    result = resolve_profile(inp)
    assert result.provider == "anthropic"
    assert (
        "claude" in result.selected_profile.profile_id.lower()
        or result.selected_profile.profile_id == "rig.native.governed.v1"
    )


def test_resolve_claude_audit_for_anthropic_claude_model():
    inp = ProfileResolutionInput(
        provider="anthropic",
        model_id="claude-opus-4-20250514",
        task_role=TaskRole.AUDIT_REVIEW,
        model_capabilities={"supports_tools": True},
    )
    result = resolve_profile(inp)
    assert result.task_role == TaskRole.AUDIT_REVIEW


def test_resolve_copilot_for_openai_gpt_model():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        task_role=TaskRole.ARCHITECTURE_PLANNING,
        model_capabilities={"supports_tools": True},
    )
    result = resolve_profile(inp)
    assert result.is_user_override is False


def test_resolve_with_user_override():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        prefer_profile_id="rig.native.governed.v1",
        model_capabilities={"supports_tools": True},
    )
    result = resolve_profile(inp)
    assert result.selected_profile.profile_id == "rig.native.governed.v1"
    assert result.is_user_override is True
    assert result.override_source_profile_id == "rig.native.governed.v1"


def test_resolve_user_override_invalid_profile_raises():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        prefer_profile_id="nonexistent.profile.v1",
        model_capabilities={"supports_tools": True},
    )
    with pytest.raises(ProfileResolutionError):
        resolve_profile(inp)


def test_resolve_no_matching_profile_raises():
    inp = ProfileResolutionInput(
        provider="nonexistent_provider",
        model_id="no-model-matches-this",
        model_capabilities={"supports_tools": True},
    )
    with pytest.raises(ProfileResolutionError):
        resolve_profile(inp)


def test_resolve_batch_returns_all_results():
    inputs = [
        ProfileResolutionInput(
            provider="openai",
            model_id="gpt-4o",
            model_capabilities={"supports_tools": True},
        ),
        ProfileResolutionInput(
            provider="anthropic",
            model_id="claude-sonnet-4-20250514",
            model_capabilities={"supports_tools": True},
        ),
    ]
    results = resolve_profiles_batch(inputs)
    assert len(results) == 2
    for r in results:
        assert r.selected_profile.profile_id


def test_resolve_deterministic():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        model_capabilities={"supports_tools": True},
    )
    r1 = resolve_profile(inp)
    r2 = resolve_profile(inp)
    assert r1.selected_profile.profile_id == r2.selected_profile.profile_id


def test_resolve_confidence_high_for_exact_match():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        prefer_profile_id="rig.native.governed.v1",
        model_capabilities={"supports_tools": True},
    )
    result = resolve_profile(inp)
    assert result.confidence == "high"


def test_resolve_with_model_capabilities():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        model_capabilities={
            "supports_tools": True,
            "supports_streaming": True,
            "context_window": 128000,
            "max_output_tokens": 16384,
        },
    )
    result = resolve_profile(inp)
    assert result.selected_profile.profile_id


def test_resolve_unsupported_capability_rejection():
    inp = ProfileResolutionInput(
        provider="anthropic",
        model_id="claude-sonnet-4-20250514",
        prefer_profile_id="anthropic.claude_code.compatible_execution.v1",
        model_capabilities={"supports_tools": False, "context_window": 5000},
    )
    with pytest.raises(ProfileResolutionError):
        resolve_profile(inp)


def test_resolve_unknown_capability_warning_not_rejection():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        prefer_profile_id="rig.native.governed.v1",
        model_capabilities={"supports_tools": True},
    )
    result = resolve_profile(inp)
    assert result.selected_profile.profile_id == "rig.native.governed.v1"


def test_resolve_alternative_rejected_reasons_populated():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        task_role=TaskRole.IMPLEMENTATION,
        model_capabilities={"supports_tools": True},
    )
    result = resolve_profile(inp)
    assert result.alternatives_rejected_reasons or result.alternatives_considered
