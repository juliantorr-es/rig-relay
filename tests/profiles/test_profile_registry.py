from __future__ import annotations

from rig_relay.profiles._profile_registry import BUILTIN_PROFILES
from rig_relay.profiles.models import ProfileStatus
from rig_relay.providers.models import Provider


def test_builtin_profiles_not_empty():
    assert len(BUILTIN_PROFILES) >= 5


def test_all_profiles_have_valid_provider_families():
    valid_providers = {p.value for p in Provider}
    for profile in BUILTIN_PROFILES:
        for fam in profile.provider_families:
            assert fam in valid_providers, (
                f"Profile {profile.profile_id} has invalid provider family {fam}"
            )


def test_all_profiles_have_digest():
    for profile in BUILTIN_PROFILES:
        assert profile.profile_digest, f"Profile {profile.profile_id} has empty digest"
        assert profile.profile_digest.startswith("sha256:"), (
            f"Profile {profile.profile_id} digest doesn't start with sha256:"
        )


def test_profile_digests_unique():
    digests = [p.profile_digest for p in BUILTIN_PROFILES]
    assert len(digests) == len(set(digests)), "Profile digests are not unique"


def test_no_verified_profile_with_unsupported_claims():
    for profile in BUILTIN_PROFILES:
        if profile.evaluation_status == ProfileStatus.VERIFIED:
            assert not profile.unsupported_claims, (
                f"Verified profile {profile.profile_id} has unsupported_claims"
            )


def test_authority_rule_present_on_all_profiles():
    for profile in BUILTIN_PROFILES:
        assert profile.authority_rule, (
            f"Profile {profile.profile_id} has empty authority_rule"
        )


def test_each_profile_has_at_least_one_role():
    for profile in BUILTIN_PROFILES:
        assert len(profile.supported_roles) >= 1, (
            f"Profile {profile.profile_id} has no supported roles"
        )


def test_each_profile_has_at_least_one_model_pattern():
    for profile in BUILTIN_PROFILES:
        assert len(profile.model_patterns) >= 1, (
            f"Profile {profile.profile_id} has no model patterns"
        )


def test_rig_native_is_candidate():
    rig_native = next(
        p for p in BUILTIN_PROFILES if p.profile_id == "rig.native.governed.v1"
    )
    assert rig_native.evaluation_status == ProfileStatus.CANDIDATE


def test_codex_profile_is_experimental():
    codex = next(
        p
        for p in BUILTIN_PROFILES
        if p.profile_id == "openai.codex.compatible_engineering.v1"
    )
    assert codex.evaluation_status == ProfileStatus.EXPERIMENTAL
    assert codex.provider_families == ["openai"]


def test_claude_execution_profile_supports_claude_models():
    claude = next(
        p
        for p in BUILTIN_PROFILES
        if p.profile_id == "anthropic.claude_code.compatible_execution.v1"
    )
    assert claude.provider_families == ["anthropic"]
    assert any("claude" in pat for pat in claude.model_patterns)
    assert claude.reasoning_effort_posture.adaptive_reasoning is True
    assert claude.reasoning_effort_posture.uses_keyword_triggers is True


def test_copilot_profile_supports_multiple_providers():
    copilot = next(
        p
        for p in BUILTIN_PROFILES
        if p.profile_id == "github.copilot.fleet.compatible_orchestration.v1"
    )
    assert "openai" in copilot.provider_families
    assert "anthropic" in copilot.provider_families
    assert copilot.workspace_subagent_posture.supports_worktrees is True
    assert copilot.workspace_subagent_posture.subagent_tool_scoping is True
