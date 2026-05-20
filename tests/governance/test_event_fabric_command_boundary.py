from __future__ import annotations

import pytest

from rig_relay.events.command_boundary import ReactionClass, classify_reaction

pytestmark = [pytest.mark.contract, pytest.mark.sabotage]


def test_bridge_status_updated_allows_projection_update():
    result = classify_reaction("bridge.status.updated", "projection_update")
    assert result == ReactionClass.PROJECTION_UPDATE


def test_bridge_status_updated_allows_evidence_append():
    result = classify_reaction("bridge.status.updated", "evidence_append")
    assert result == ReactionClass.EVIDENCE_APPEND


def test_bridge_status_updated_allows_local_diagnostic():
    result = classify_reaction("bridge.status.updated", "local_diagnostic")
    assert result == ReactionClass.LOCAL_DIAGNOSTIC


def test_github_rate_limit_near_exhausted_gates_scheduling_hint():
    result = classify_reaction("github.rate_limit.near_exhausted", "scheduling_hint")
    assert result == ReactionClass.GATED_COMMAND_REQUIRED


def test_resource_cpu_pressure_high_allows_scheduling_hint():
    result = classify_reaction("resource.cpu_pressure.high", "scheduling_hint")
    assert result == ReactionClass.SCHEDULING_HINT


def test_tool_invocation_completed_allows_projection_update():
    result = classify_reaction("tool.invocation.completed", "projection_update")
    assert result == ReactionClass.PROJECTION_UPDATE


def test_tool_invocation_completed_gates_non_read_action():
    result = classify_reaction("tool.invocation.completed", "restart_worker")
    assert result == ReactionClass.GATED_COMMAND_REQUIRED


def test_forbidden_action_dismiss_alert():
    result = classify_reaction("bridge.status.updated", "dismiss_alert")
    assert result == ReactionClass.FORBIDDEN


def test_forbidden_action_create_pr():
    result = classify_reaction("tool.invocation.completed", "create_pr")
    assert result == ReactionClass.FORBIDDEN


def test_forbidden_action_deploy():
    result = classify_reaction("github.rate_limit.near_exhausted", "deploy")
    assert result == ReactionClass.FORBIDDEN


def test_unknown_event_with_mutation_intent_gated():
    result = classify_reaction("custom.unknown.event", "refresh_cache")
    assert result == ReactionClass.GATED_COMMAND_REQUIRED


def test_unknown_event_with_unknown_action_defaults_to_gated():
    result = classify_reaction("custom.unknown.event", "unknown_action")
    assert result == ReactionClass.GATED_COMMAND_REQUIRED
