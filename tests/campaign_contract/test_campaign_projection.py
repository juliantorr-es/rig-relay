"""Tests for campaign projection.
Classification: contract/integration, contract/adversarial
"""

from __future__ import annotations

import json

from rig_relay.cli._steward._campaign_models import CampaignState
from rig_relay.cli._steward._campaign_projection import (
    campaign_projection,
    campaign_projection_html,
)
from rig_relay.cli._steward._campaign_runtime import (
    init_campaign_dir,
    save_campaign_state,
)


def test_projection_content_light(tmp_path):
    init_campaign_dir("test-proj", tmp_path)
    state = CampaignState.model_validate({
        "campaign_id": "test-proj",
        "operating_mode": (
            "confidential_autonomous_campaign_with_private_checkpoint_push"
        ),
        "phase": "running",
        "lane_identity": "lane1",
        "baseline_sha": "abc",
        "active_branch": "b",
        "assigned_remote_branch": "b",
        "current_mission_id": "m1",
        "completed_missions": ["m0"],
        "checkpoint_count": 1,
        "push_count": 1,
        "latest_checkpoint_sha": "sha1",
        "latest_pushed_sha": "sha1",
        "manifest_digest": "dig",
    })
    save_campaign_state(state, "test-proj", tmp_path)
    result = campaign_projection("test-proj", tmp_path)
    assert result["exists"] is True
    assert result["phase"] == "running"
    assert "m1" in json.dumps(result)
    assert "sha1" in json.dumps(result)


def test_projection_html_content_light(tmp_path):
    init_campaign_dir("test-html", tmp_path)
    state = CampaignState.model_validate({
        "campaign_id": "test-html",
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "phase": "completed",
        "lane_identity": "l1",
        "baseline_sha": "abc",
        "active_branch": "b",
        "assigned_remote_branch": "b",
        "manifest_digest": "dig",
        "latest_checkpoint_sha": "sha1",
        "latest_pushed_sha": "sha1",
        "completed_missions": [],
    })
    save_campaign_state(state, "test-html", tmp_path)
    html = campaign_projection_html("test-html", tmp_path)
    assert "test-html" in html
    assert "completed" in html
    assert "Human review required: true" in html


def test_projection_no_secrets(tmp_path):
    init_campaign_dir("test-no-sec", tmp_path)
    state = CampaignState.model_validate({
        "campaign_id": "test-no-sec",
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "phase": "running",
        "lane_identity": "l1",
        "baseline_sha": "abc",
        "active_branch": "b",
        "assigned_remote_branch": "b",
        "manifest_digest": "dig",
        "latest_checkpoint_sha": "sha1",
        "latest_pushed_sha": "sha1",
    })
    save_campaign_state(state, "test-no-sec", tmp_path)
    result = campaign_projection("test-no-sec", tmp_path)
    raw = json.dumps(result)
    for forbidden in ["SECRET", "API_KEY", "password", "BEGIN PRIVATE KEY"]:
        assert forbidden not in raw
    html = campaign_projection_html("test-no-sec", tmp_path)
    for forbidden in ["SECRET", "API_KEY", "password"]:
        assert forbidden not in html


def test_projection_missing_campaign(tmp_path):
    result = campaign_projection("nonexistent", tmp_path)
    assert result["exists"] is False
