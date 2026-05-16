from __future__ import annotations

from rig_relay.ralph.mission_board import build_mission_board


def test_mission_board_default():
    board = build_mission_board()
    assert board.schema_version == "rig.ui.orchestrator_mission_board.v2"
    assert board.total_missions >= 2
    assert board.active_missions >= 2
    assert board.background_enabled is False
    assert board.live_runtime_mutation_enabled is False
    assert board.merge_enabled is False
    assert board.push_enabled is False


def test_mission_board_with_custom_missions():
    missions = [
        {"mission_id": "m1", "title": "Task A", "status": "active", "lane_id": "lane-a"},
        {"mission_id": "m2", "title": "Task B", "status": "completed", "lane_id": "lane-b"},
    ]
    board = build_mission_board(missions=missions)
    assert board.total_missions == 2
    assert board.active_missions == 1
    assert board.completed_missions == 1


def test_lifecycle_timeline_present():
    board = build_mission_board()
    assert len(board.lifecycle_timeline) == 9
    steps = [e.label for e in board.lifecycle_timeline]
    assert "Background enabled" in steps
    assert "Merge" in steps
    assert "Push to preproduction" in steps


def test_lifecycle_timeline_merge_push_blocked():
    board = build_mission_board()
    merge = [e for e in board.lifecycle_timeline if e.label == "Merge"][0]
    assert merge.blocked is True
    push = [e for e in board.lifecycle_timeline if e.label == "Push to preproduction"][0]
    assert push.blocked is True


def test_review_entrypoint_when_pending_review():
    board = build_mission_board(pending_review_count=3)
    assert board.review_entrypoint is not None
    assert board.review_entrypoint.available is True
    assert board.review_entrypoint.pending_review_count == 3
    assert board.review_entrypoint.action == "review_with_orchestrator"


def test_review_entrypoint_none_when_no_pending():
    board = build_mission_board(pending_review_count=0)
    assert board.review_entrypoint is None


def test_execution_scopes_always_distinct():
    board = build_mission_board(background_enabled=True,
                               lifecycle={"isolated_lane_execution_enabled": True,
                                          "merge_enabled": False, "push_enabled": False})
    assert board.isolated_lane_execution_enabled is True
    assert board.live_runtime_mutation_enabled is False
    assert board.merge_enabled is False
    assert board.push_enabled is False


def test_available_actions():
    board = build_mission_board(pending_review_count=1)
    actions = [a["action"] for a in board.available_actions]
    assert "orchestrator_new_mission" in actions
    assert "ralph_scan" in actions
    assert "review_with_orchestrator" in actions


def test_lifecycle_timeline_respects_active_lanes():
    lifecycle = {"active_lanes": [{"latest_commit_sha": "abc123", "review_bundle_sha256": "def456"}]}
    board = build_mission_board(background_enabled=True, lifecycle=lifecycle)
    lane_step = [e for e in board.lifecycle_timeline if e.label == "Lane created"][0]
    assert lane_step.status == "completed"
    commit_step = [e for e in board.lifecycle_timeline if e.label == "Commit recorded"][0]
    assert commit_step.status == "completed"
    bundle_step = [e for e in board.lifecycle_timeline if e.label == "Review bundle sealed"][0]
    assert bundle_step.status == "completed"
