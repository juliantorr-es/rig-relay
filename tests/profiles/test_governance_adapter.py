from __future__ import annotations

from uuid import uuid4

from rig_relay.profiles._governance_adapter import (
    _local_admission_rules,
    admit_profile_selection,
)
from rig_relay.profiles._profile_registry import BUILTIN_PROFILES
from rig_relay.profiles.models import (
    GovernanceAdmissionState,
    HarnessCompatibilityProfile,
    ProfileResolutionResult,
    ProfileStatus,
    ResolutionOutcome,
    TaskRole,
)


def _find_profile(profile_id: str) -> HarnessCompatibilityProfile:
    for p in BUILTIN_PROFILES:
        if p.profile_id == profile_id:
            return p
    raise ValueError(f"Profile {profile_id} not found")


def _make_resolution(
    provider: str = "openai",
    model_id: str = "gpt-4o",
    profile_id: str = "rig.native.governed.v1",
    outcome: str = "selected",
    is_user_override: bool = False,
    evaluation_status_override: ProfileStatus | None = None,
) -> ProfileResolutionResult:
    profile = _find_profile(profile_id)
    if evaluation_status_override is not None:
        profile = profile.model_copy(
            update={"evaluation_status": evaluation_status_override}
        )
    return ProfileResolutionResult(
        resolution_id=str(uuid4()),
        provider=provider,
        model_id=model_id,
        task_role=TaskRole.IMPLEMENTATION,
        selected_profile=profile,
        selected_reason="test",
        confidence="high",
        outcome=outcome,
        is_user_override=is_user_override,
    )


def test_admit_returns_admitted_for_rig_native_with_clean_input():
    resolution = _make_resolution(
        provider="openai",
        model_id="gpt-4o",
        profile_id="rig.native.governed.v1",
        outcome=ResolutionOutcome.SELECTED.value,
    )
    state, digest = admit_profile_selection(
        resolution, "openai", "gpt-4o", "implementation", str(uuid4())
    )
    assert state == GovernanceAdmissionState.ADMITTED.value
    assert digest is not None
    assert digest.startswith("sha256:")


def test_admit_returns_admitted_for_candidate_profile_with_satisfied_evidence():
    rig_native = _find_profile("rig.native.governed.v1")
    assert rig_native.evaluation_status == ProfileStatus.CANDIDATE
    resolution = _make_resolution(
        profile_id="rig.native.governed.v1", outcome=ResolutionOutcome.SELECTED.value
    )
    state, _digest = admit_profile_selection(
        resolution, "openai", "gpt-4o", "implementation", str(uuid4())
    )
    assert state == GovernanceAdmissionState.ADMITTED.value


def test_admission_digest_is_nonempty_sha256_format():
    resolution = _make_resolution(
        provider="openai",
        model_id="gpt-4o",
        profile_id="rig.native.governed.v1",
        outcome=ResolutionOutcome.SELECTED.value,
    )
    _state, digest = admit_profile_selection(
        resolution, "openai", "gpt-4o", "implementation", str(uuid4())
    )
    assert digest is not None
    assert isinstance(digest, str)
    assert digest.startswith("sha256:")
    assert len(digest) > len("sha256:")


def test_local_rules_not_evaluated_for_empty_provider():
    resolution = _make_resolution(
        provider="",
        model_id="",
        profile_id="rig.native.governed.v1",
        outcome=ResolutionOutcome.SELECTED.value,
    )
    state = _local_admission_rules(resolution, "", "", "implementation")
    assert state == GovernanceAdmissionState.NOT_EVALUATED.value


def test_local_rules_not_evaluated_for_unknown_provider():
    resolution = _make_resolution(
        provider="",
        model_id="",
        profile_id="rig.native.governed.v1",
        outcome=ResolutionOutcome.UNAVAILABLE_PROVIDER_CAPABILITY_RESOLUTION.value,
    )
    state = _local_admission_rules(resolution, "", "", "implementation")
    assert state == GovernanceAdmissionState.NOT_EVALUATED.value


def test_local_rules_refused_for_conflicting_capability_evidence():
    resolution = _make_resolution(
        outcome=ResolutionOutcome.REFUSED_CONFLICTING_CAPABILITY_EVIDENCE.value
    )
    state = _local_admission_rules(resolution, "openai", "gpt-4o", "implementation")
    assert state == GovernanceAdmissionState.REFUSED.value


def test_local_rules_refused_for_missing_capability_evidence():
    resolution = _make_resolution(
        outcome=ResolutionOutcome.REFUSED_MISSING_CAPABILITY_EVIDENCE.value
    )
    state = _local_admission_rules(resolution, "openai", "gpt-4o", "implementation")
    assert state == GovernanceAdmissionState.REFUSED.value


def test_local_rules_requires_review_for_experimental_with_user_override():
    resolution = _make_resolution(
        profile_id="openai.codex.compatible_engineering.v1",
        outcome=ResolutionOutcome.SELECTED_EXPERIMENTAL.value,
        is_user_override=True,
        evaluation_status_override=ProfileStatus.EXPERIMENTAL,
    )
    state = _local_admission_rules(resolution, "openai", "gpt-4o", "implementation")
    assert state == GovernanceAdmissionState.REQUIRES_REVIEW.value
