from __future__ import annotations

import pytest

from rig_relay.orchestrator.subagent_profiles import (
    PROFILE_KIND_AUTONOMOUS_BACKGROUND,
    PROFILE_KIND_STANDARD_SUBAGENT,
    TRUST_TIER_OBSERVE,
    TRUST_TIER_PATCH_PROPOSAL,
    TRUST_TIER_SAFE_LOCAL,
    MissionAssignment,
    SubagentProfile,
    TrustTier,
    build_demo_profiles,
    build_empty_assignment,
    get_profile_registry,
)


@pytest.mark.smoke
def test_build_demo_profiles_creates_six_profiles():
    registry = build_demo_profiles()
    profiles = registry.list_all()
    assert len(profiles) == 6


def test_assignable_excludes_ralph():
    registry = build_demo_profiles()
    assignable = registry.assignable()
    ralph_ids = [p.profile_id for p in registry.autonomous_workers()]
    for p in assignable:
        assert p.profile_id not in ralph_ids


@pytest.mark.smoke
def test_autonomous_worker_is_ralph():
    registry = build_demo_profiles()
    workers = registry.autonomous_workers()
    assert len(workers) == 1
    ralph = workers[0]
    assert ralph.profile_id == "profile-ralph-background"
    assert ralph.display_name == "Ralph"
    assert ralph.profile_kind == PROFILE_KIND_AUTONOMOUS_BACKGROUND
    assert ralph.reports_to_orchestrator is True
    assert ralph.assignable is False


def test_ralph_cannot_be_assigned_like_subagent():
    registry = build_demo_profiles()
    ralph = registry.get("profile-ralph-background")
    assert ralph is not None
    assert ralph.assignable is False
    assignable = registry.assignable()
    assert ralph not in assignable


def test_profile_has_correct_capabilities():
    registry = build_demo_profiles()
    runtime = registry.get("profile-runtime-agent")
    assert runtime is not None
    assert runtime.trust_tier == TrustTier.PATCH_PROPOSAL.value
    assert "read_file" in runtime.allowed_capabilities
    assert "merge" in runtime.forbidden_capabilities


def test_ralph_isolation_invariant():
    registry = build_demo_profiles()
    ralph = registry.get("profile-ralph-background")
    assert ralph is not None
    assert "merge" in ralph.forbidden_capabilities
    assert "push_remote" in ralph.forbidden_capabilities
    assert "mutate_live_workspace" in ralph.forbidden_capabilities
    assert "mutate_orchestrator_lane" in ralph.forbidden_capabilities


def test_empty_assignment_has_defaults():
    a = build_empty_assignment()
    assert a.schema_version == "rig.orchestrator_mission_assignment.v1"
    assert a.assignment_id != ""
    assert a.status == "proposed"


def test_mission_assignment_creation():
    a = MissionAssignment(
        mission_id="test-mission-1",
        assigned_profile_id="profile-runtime-agent",
        lane_id="lane-1",
        status="assigned",
        objective="Test objective",
    )
    assert a.mission_id == "test-mission-1"
    assert a.assigned_profile_id == "profile-runtime-agent"
    assert a.status == "assigned"


def test_disabled_profile_not_in_assignable():
    registry = get_profile_registry()
    registry.reset()
    p = SubagentProfile(
        profile_id="test-disabled",
        display_name="Disabled Agent",
        enabled=False,
        assignable=True,
    )
    registry.register(p)
    assert len(registry.assignable()) == 0


def test_registry_singleton_persists():
    registry = get_profile_registry()
    registry.reset()
    p = SubagentProfile(profile_id="test-persist", display_name="Persist Agent")
    registry.register(p)
    registry2 = get_profile_registry()
    assert registry2.get("test-persist") is not None
    assert registry2.get("test-persist").display_name == "Persist Agent"


def test_profile_kind_values():
    assert PROFILE_KIND_STANDARD_SUBAGENT == "standard_subagent"
    assert PROFILE_KIND_AUTONOMOUS_BACKGROUND == "autonomous_background_worker"


def test_trust_tiers():
    assert TRUST_TIER_OBSERVE == 0
    assert TRUST_TIER_SAFE_LOCAL == 2
    assert TRUST_TIER_PATCH_PROPOSAL == 3


# ── Model/provider binding tests ────────────────────────────────────


def test_build_demo_bindings_six_bindings():
    from rig_relay.orchestrator.subagent_profiles import build_demo_bindings

    registry = build_demo_bindings()
    bindings = registry.list_all()
    assert len(bindings) == 6


def test_demo_bindings_no_api_key_required():
    from rig_relay.orchestrator.subagent_profiles import build_demo_bindings

    registry = build_demo_bindings()
    for b in registry.list_all():
        assert b.requires_api_key is False, f"{b.binding_id} requires api key"
        assert b.requires_network is False, f"{b.binding_id} requires network"


def test_runtime_agent_has_binding():
    from rig_relay.orchestrator.subagent_profiles import build_demo_bindings

    registry = build_demo_bindings()
    binding = registry.get_for_profile("profile-runtime-agent")
    assert binding is not None
    assert binding.display_name == "Local Demo"
    assert binding.provider_id == "local_demo"


def test_ralph_background_binding():
    from rig_relay.orchestrator.subagent_profiles import build_demo_bindings

    registry = build_demo_bindings()
    binding = registry.get_for_profile("profile-ralph-background")
    assert binding is not None
    assert binding.display_name == "Ralph Background (internal)"
    assert binding.provider_id == "ralph_internal"
    assert binding.supports_tool_calls is False
    assert binding.supports_streaming is False


def test_unbound_profile_returns_none():
    from rig_relay.orchestrator.subagent_profiles import build_demo_bindings

    registry = build_demo_bindings()
    binding = registry.get_for_profile("nonexistent-profile")
    assert binding is None


def test_mission_assignment_has_model_fields():
    from rig_relay.orchestrator.subagent_profiles import MissionAssignment

    a = MissionAssignment(
        mission_id="test",
        assigned_profile_id="profile-runtime-agent",
        model_binding_id="binding-demo-runtime",
        model_binding_label="Local Demo",
        provider_status="demo_local",
    )
    assert a.model_binding_id == "binding-demo-runtime"
    assert a.model_binding_label == "Local Demo"
    assert a.provider_status == "demo_local"


def test_assignment_default_model_fields_demo_local():
    from rig_relay.orchestrator.subagent_profiles import build_empty_assignment

    a = build_empty_assignment()
    assert a.provider_status == "demo_local"
    assert a.model_binding_id == ""
    assert a.model_binding_label == ""
