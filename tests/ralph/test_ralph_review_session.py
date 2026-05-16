from __future__ import annotations

import pytest

from rig_relay.ralph.review_session import (
    RalphReviewSessionRequest,
    build_widget_projection,
)

pytestmark = [pytest.mark.integration]


def test_widget_projection_defaults_disabled():
    widget = build_widget_projection()
    assert widget.background_enabled is False
    assert widget.execution_enabled is False
    assert widget.merge_enabled is False


def test_widget_projection_shows_counts():
    widget = build_widget_projection(
        background_enabled=True,
        active_lane_count=2,
        finished_lane_count=3,
        pending_review_count=1,
    )
    assert widget.background_enabled is True
    assert widget.active_lane_count == 2
    assert widget.finished_lane_count == 3
    assert widget.pending_review_count == 1


def test_widget_actions_exist():
    widget = build_widget_projection()
    actions = [a["action"] for a in widget.available_actions]
    assert "ralph_background_toggle_on" in actions
    assert "ralph_background_toggle_off" in actions
    assert "ralph_review_finished_lanes" in actions
    assert "ralph_lane_propose" in actions


def test_review_session_request():
    req = RalphReviewSessionRequest(
        pending_lane_ids=["lane-1", "lane-2"],
        include_review_bundles=True,
        include_decision_receipts=True,
        mode="explain_only",
    )
    assert req.mode == "explain_only"
    assert req.execution_enabled is False
    assert req.merge_enabled is False
    assert len(req.pending_lane_ids) == 2


def test_review_session_contract_only():
    req = RalphReviewSessionRequest()
    assert req.execution_enabled is False
    assert req.merge_enabled is False
    assert req.mode == "explain_only"
