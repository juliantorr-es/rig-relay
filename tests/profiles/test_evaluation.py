from __future__ import annotations

from rig_relay.profiles._evaluation import evaluate_all_profiles, evaluate_profile
from rig_relay.profiles._profile_registry import BUILTIN_PROFILES
from rig_relay.profiles.models import ProfileEvaluationInput, TaskRole


def test_evaluate_profile_context_assembly_correct():
    rig_native = BUILTIN_PROFILES[0]
    inp = ProfileEvaluationInput(
        profile_id=rig_native.profile_id,
        task_role=TaskRole.IMPLEMENTATION,
        provider="openai",
        model_id="gpt-4o",
    )
    result = evaluate_profile(rig_native, inp)
    assert result.context_assembly_correct is True


def test_evaluate_profile_tool_authority_preserved():
    rig_native = BUILTIN_PROFILES[0]
    inp = ProfileEvaluationInput(
        profile_id=rig_native.profile_id,
        task_role=TaskRole.IMPLEMENTATION,
        provider="openai",
        model_id="gpt-4o",
    )
    result = evaluate_profile(rig_native, inp)
    assert result.tool_authority_preserved is True


def test_evaluate_profile_deterministic_resolution():
    rig_native = BUILTIN_PROFILES[0]
    inp = ProfileEvaluationInput(
        profile_id=rig_native.profile_id,
        task_role=TaskRole.IMPLEMENTATION,
        provider="openai",
        model_id="gpt-4o",
    )
    result = evaluate_profile(rig_native, inp)
    assert result.deterministic_resolution is True


def test_evaluate_profile_unsupported_capability_refused():
    rig_native = BUILTIN_PROFILES[0]
    inp = ProfileEvaluationInput(
        profile_id=rig_native.profile_id,
        task_role=TaskRole.IMPLEMENTATION,
        provider="openai",
        model_id="gpt-4o",
    )
    result = evaluate_profile(rig_native, inp)
    assert result.unsupported_capability_refused is True


def test_evaluate_profile_receipt_reconstructable():
    rig_native = BUILTIN_PROFILES[0]
    inp = ProfileEvaluationInput(
        profile_id=rig_native.profile_id,
        task_role=TaskRole.IMPLEMENTATION,
        provider="openai",
        model_id="gpt-4o",
    )
    result = evaluate_profile(rig_native, inp)
    assert result.receipt_reconstructable is True


def test_evaluate_all_profiles_returns_results_for_each():
    results = evaluate_all_profiles(BUILTIN_PROFILES)
    assert len(results) >= len(BUILTIN_PROFILES)
    profile_ids = {r.profile_id for r in results}
    for p in BUILTIN_PROFILES:
        assert p.profile_id in profile_ids, (
            f"Profile {p.profile_id} missing from results"
        )
