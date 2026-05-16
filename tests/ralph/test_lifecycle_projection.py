from __future__ import annotations

import pytest

from rig_relay.ralph.background_policy import demo_policy
from rig_relay.ralph.lane_contracts import RalphLane
from rig_relay.ralph.lifecycle_projection import build_lifecycle_projection


@pytest.mark.smoke
def test_lifecycle_projection_default_disabled():
    proj = build_lifecycle_projection()
    assert proj.background_enabled is False
    assert proj.isolated_lane_execution_enabled is False
    assert proj.live_runtime_mutation_enabled is False
    assert proj.merge_enabled is False
    assert proj.push_enabled is False
    assert proj.active_lane_count == 0
    assert proj.schema_version == "rig.ui.ralph_background_lifecycle.v1"


@pytest.mark.smoke
def test_lifecycle_projection_demo_enabled():
    proj = build_lifecycle_projection(policy=demo_policy())
    assert proj.background_enabled is True
    assert proj.isolated_lane_execution_enabled is True
    assert proj.live_runtime_mutation_enabled is False
    assert proj.merge_enabled is False


def test_lifecycle_with_active_lanes():
    lane = RalphLane(
        lane_id="lane-1",
        branch_name="ralph/test-abc12345",
        status="active",
        latest_commit_sha="abc123",
    )
    proj = build_lifecycle_projection(policy=demo_policy(), active_lanes=[lane])
    assert proj.active_lane_count == 1
    assert proj.latest_lane is not None
    assert proj.latest_lane.lane_id == "lane-1"
    assert proj.latest_lane.latest_commit_sha == "abc123"


def test_lifecycle_with_completed_lanes():
    lane = RalphLane(
        lane_id="lane-2",
        branch_name="ralph/done",
        status="sealed",
        review_bundle_sha256="sha256:def",
    )
    proj = build_lifecycle_projection(policy=demo_policy(), completed_lanes=[lane])
    assert proj.completed_lane_count == 1
    assert proj.pending_review_count == 1


def test_gates_present():
    proj = build_lifecycle_projection(policy=demo_policy())
    assert len(proj.gates) == 5
    gate_names = [g.name for g in proj.gates]
    assert "Worktree creation" in gate_names
    assert "Adoption merge" in gate_names
    assert "Push to preproduction" in gate_names

    merge_gate = [g for g in proj.gates if g.name == "Adoption merge"][0]
    assert merge_gate.allowed is False


def test_execution_scopes_distinct():
    proj = build_lifecycle_projection(policy=demo_policy())
    assert proj.isolated_lane_execution_enabled is True
    assert proj.live_runtime_mutation_enabled is False
    assert proj.isolated_lane_execution_enabled != proj.live_runtime_mutation_enabled


def test_available_actions_present():
    proj = build_lifecycle_projection()
    actions = [a["action"] for a in proj.available_actions]
    assert "ralph_background_toggle_on" in actions
    assert "ralph_background_toggle_off" in actions
    assert "ralph_review_finished_lanes" in actions
