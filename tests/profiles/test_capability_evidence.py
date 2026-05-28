from __future__ import annotations

from pydantic import ValidationError
import pytest

from rig_relay.profiles._capability_evidence import (
    BUILTIN_CAPABILITY_EVIDENCE,
    CapabilityEvidenceItem,
    CapabilityEvidenceSourceClass,
    CapabilityName,
    CapabilityPosture,
    build_capability_projection,
    resolve_capability_evidence,
    validate_profile_requirements_against_evidence,
)
from rig_relay.profiles._profile_registry import BUILTIN_PROFILES
from rig_relay.profiles.models import (
    CapabilityRequirements,
    HarnessCompatibilityProfile,
)
from rig_relay.providers.models import Provider


def _find_rig_native():
    for p in BUILTIN_PROFILES:
        if p.profile_id == "rig.native.governed.v1":
            return p
    raise ValueError("rig.native profile not found")


def test_thirteen_builtin_evidence_items():
    assert len(BUILTIN_CAPABILITY_EVIDENCE) == 13


def test_all_evidence_items_have_valid_sha256_digests():
    for item in BUILTIN_CAPABILITY_EVIDENCE:
        assert item.evidence_digest, f"{item.evidence_id} has empty digest"
        assert item.evidence_digest.startswith("sha256:"), (
            f"{item.evidence_id} digest missing sha256: prefix"
        )
        assert len(item.evidence_digest) > len("sha256:")


def test_all_evidence_items_have_valid_source_classes():
    valid = set(CapabilityEvidenceSourceClass)
    for item in BUILTIN_CAPABILITY_EVIDENCE:
        assert item.source_class in valid, (
            f"{item.evidence_id} has invalid source_class {item.source_class}"
        )


def test_resolve_capability_evidence_finds_tool_use_for_openai_gpt4o():
    result = resolve_capability_evidence("openai", "gpt-4o", CapabilityName.TOOL_USE)
    assert result is not None
    assert result.provider == "openai"
    assert result.capability == CapabilityName.TOOL_USE
    assert result.posture == CapabilityPosture.SUPPORTED


def test_resolve_capability_evidence_returns_none_for_unsupported_combination():
    result = resolve_capability_evidence(
        "unknown_provider", "nonexistent-model", CapabilityName.TOOL_USE
    )
    assert result is None


def test_resolve_capability_evidence_prefers_specific_over_wildcard():
    wildcard = CapabilityEvidenceItem(
        evidence_id="test-wildcard",
        provider="openai",
        model_pattern=".*",
        capability=CapabilityName.TOOL_USE,
        posture=CapabilityPosture.UNSUPPORTED,
        source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
        source_reference="test",
        confidence="high",
    )
    specific = CapabilityEvidenceItem(
        evidence_id="test-specific",
        provider="openai",
        model_pattern="gpt-4o",
        capability=CapabilityName.TOOL_USE,
        posture=CapabilityPosture.SUPPORTED,
        source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
        source_reference="test",
        confidence="high",
    )
    digest_wc = wildcard.compute_digest()
    digest_sp = specific.compute_digest()
    wildcard = wildcard.model_copy(update={"evidence_digest": digest_wc})
    specific = specific.model_copy(update={"evidence_digest": digest_sp})
    sources = (wildcard, specific)

    result = resolve_capability_evidence(
        "openai", "gpt-4o", CapabilityName.TOOL_USE, sources
    )
    assert result is not None
    assert result.evidence_id == "test-specific"


def test_validate_rig_native_requirements_satisfied_for_openai_gpt4o():
    rig_native = _find_rig_native()
    satisfied, evidence_map, warnings = validate_profile_requirements_against_evidence(
        rig_native, "openai", "gpt-4o"
    )
    assert satisfied is True
    assert len(evidence_map) > 0
    assert "tool_use" in evidence_map


def test_validate_unsatisfied_when_required_capability_has_no_evidence():
    profile = HarnessCompatibilityProfile(
        profile_id="test.requires.vision.v1",
        profile_version="1.0.0",
        display_name="Test Vision Required",
        description="Test profile requiring vision",
        provider_families=["openai"],
        model_patterns=["gpt-.*"],
        supported_roles=[],
        required_capabilities=CapabilityRequirements(
            requires_tool_use=False, requires_vision=True
        ),
    )
    satisfied, _evidence_map, _warnings = (
        validate_profile_requirements_against_evidence(profile, "openai", "gpt-4o")
    )
    assert satisfied is False


def test_validate_warns_when_only_user_declared_evidence():
    user_evidence = CapabilityEvidenceItem(
        evidence_id="test-user-declared",
        provider="openai",
        model_pattern="gpt-4o",
        capability=CapabilityName.TOOL_USE,
        posture=CapabilityPosture.SUPPORTED,
        source_class=CapabilityEvidenceSourceClass.USER_DECLARED_CONFIGURATION,
        source_reference="user config",
        confidence="low",
    )
    digest = user_evidence.compute_digest()
    user_evidence = user_evidence.model_copy(update={"evidence_digest": digest})
    sources = (user_evidence,)

    rig_native = _find_rig_native()
    satisfied, _evidence_map, warnings = validate_profile_requirements_against_evidence(
        rig_native, "openai", "gpt-4o", sources
    )
    assert satisfied is True
    assert any("user-declared" in w for w in warnings)


def test_build_capability_projection_returns_valid_structure():
    projection = build_capability_projection("openai", "gpt-4o")
    assert "provider" in projection
    assert projection["provider"] == "openai"
    assert "model_id" in projection
    assert "capabilities" in projection
    caps = projection["capabilities"]
    assert isinstance(caps, dict)
    assert len(caps) > 0
    for cap_name in CapabilityName:
        assert cap_name.value in caps


def test_capability_evidence_item_is_frozen():
    item = BUILTIN_CAPABILITY_EVIDENCE[0]
    with pytest.raises(ValidationError):
        item.evidence_digest = "tampered"


def test_all_evidence_providers_are_valid_provider_enum_members():
    valid_providers = {p.value for p in Provider}
    for item in BUILTIN_CAPABILITY_EVIDENCE:
        assert item.provider in valid_providers, (
            f"{item.evidence_id}: provider '{item.provider}' not in Provider enum"
        )


def test_no_evidence_item_has_conflicting_supported_and_unsupported_postures():
    for item in BUILTIN_CAPABILITY_EVIDENCE:
        assert item.posture.value in {p.value for p in CapabilityPosture}, (
            f"{item.evidence_id}: invalid posture {item.posture}"
        )
