"""Tests for campaign status CLI.
Classification: contract/integration
"""

from __future__ import annotations

import json

from rig_relay.cli._steward._campaign_models import CampaignState
from rig_relay.cli._steward._campaign_runtime import (
    init_campaign_dir,
    save_campaign_state,
)
from rig_relay.cli._steward._campaign_status import campaign_status


def test_status_returns_content_light_projection(tmp_path):
    init_campaign_dir("test-status", tmp_path)
    state = CampaignState.model_validate({
        "campaign_id": "test-status",
        "operating_mode": (
            "confidential_autonomous_campaign_with_private_checkpoint_push"
        ),
        "phase": "running",
        "lane_identity": "lane1",
        "baseline_sha": "abc123",
        "active_branch": "confidential/steward-campaign/test-status",
        "assigned_remote_branch": "confidential/steward-campaign/test-status",
        "current_mission_id": "m1",
        "completed_missions": [],
        "paused_missions": [],
        "pending_missions": ["m2", "m3"],
        "checkpoint_count": 2,
        "push_count": 2,
        "latest_checkpoint_sha": "def456",
        "latest_pushed_sha": "def456",
        "manifest_digest": "ghi789",
    })
    save_campaign_state(state, "test-status", tmp_path)
    result = campaign_status("test-status", tmp_path)
    assert result["exists"] is True
    assert result["phase"] == "running"
    assert result["current_mission"] == "m1"
    assert result["checkpoint_count"] == 2
    assert result["push_count"] == 2
    assert result["latest_checkpoint_sha"] == "def456"
    assert result["halted"] is False
    assert result["completed"] is False
    assert "next_action" in result


def test_status_unknown_campaign(tmp_path):
    result = campaign_status("nonexistent", tmp_path)
    assert result["exists"] is False
    assert "error" in result


def test_status_no_raw_secret_in_output(tmp_path):
    init_campaign_dir("test-secret", tmp_path)
    state = CampaignState.model_validate({
        "campaign_id": "test-secret",
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "phase": "completed",
        "lane_identity": "l1",
        "baseline_sha": "abc",
        "active_branch": "b",
        "assigned_remote_branch": "b",
        "current_mission_id": None,
        "manifest_digest": "dig",
        "latest_checkpoint_sha": "sha1",
    })
    save_campaign_state(state, "test-secret", tmp_path)
    result = campaign_status("test-secret", tmp_path)
    raw = json.dumps(result)
    assert "SECRET" not in raw
    assert "API_KEY" not in raw
    assert "password" not in raw
