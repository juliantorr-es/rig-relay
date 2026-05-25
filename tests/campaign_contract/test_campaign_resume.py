"""Tests for campaign completion/resume UX.
Classification: contract/integration
"""

from __future__ import annotations

import json

from rig_relay.cli._steward._campaign_models import CampaignState
from rig_relay.cli._steward._campaign_resume import campaign_resume_info
from rig_relay.cli._steward._campaign_runtime import (
    append_finding,
    init_campaign_dir,
    save_campaign_state,
)


def test_resume_runnable_campaign(tmp_path):
    init_campaign_dir("test-resume", tmp_path)
    state = CampaignState.model_validate({
        "campaign_id": "test-resume",
        "operating_mode": (
            "confidential_autonomous_campaign_with_private_checkpoint_push"
        ),
        "phase": "running",
        "lane_identity": "lane1",
        "baseline_sha": "abc",
        "active_branch": "b",
        "assigned_remote_branch": "b",
        "current_mission_id": "m1",
        "completed_missions": [],
        "paused_missions": [],
        "manifest_digest": "dig",
        "latest_checkpoint_sha": "sha1",
        "latest_pushed_sha": "sha1",
    })
    save_campaign_state(state, "test-resume", tmp_path)
    result = campaign_resume_info("test-resume", tmp_path)
    assert result["runnable"] is True
    assert result["halted"] is False
    assert result["completed"] is False
    assert result["checkpoint_latest_pushed"] is True


def test_resume_halted_campaign(tmp_path):
    init_campaign_dir("test-halted", tmp_path)
    state = CampaignState.model_validate({
        "campaign_id": "test-halted",
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "phase": "halted",
        "lane_identity": "l1",
        "baseline_sha": "abc",
        "active_branch": "b",
        "assigned_remote_branch": "b",
        "halt_reason": "security boundary violation",
        "manifest_digest": "dig",
        "latest_checkpoint_sha": "sha1",
        "latest_pushed_sha": "sha1",
    })
    save_campaign_state(state, "test-halted", tmp_path)
    result = campaign_resume_info("test-halted", tmp_path)
    assert result["halted"] is True
    assert result["runnable"] is False
    assert result["halt_reason"] == "security boundary violation"


def test_resume_with_findings(tmp_path):
    init_campaign_dir("test-findings", tmp_path)
    state = CampaignState.model_validate({
        "campaign_id": "test-findings",
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "phase": "paused_for_blocker",
        "lane_identity": "l1",
        "baseline_sha": "abc",
        "active_branch": "b",
        "assigned_remote_branch": "b",
        "current_mission_id": "m1",
        "manifest_digest": "dig",
        "latest_checkpoint_sha": "sha1",
        "latest_pushed_sha": "sha1",
    })
    save_campaign_state(state, "test-findings", tmp_path)
    append_finding(
        "test-findings",
        tmp_path,
        {
            "finding_id": "f1",
            "mission_id": "m1",
            "finding_class": "out_of_scope_blocker",
            "status": "unresolved",
        },
    )
    append_finding(
        "test-findings",
        tmp_path,
        {
            "finding_id": "f2",
            "mission_id": "m1",
            "finding_class": "validation_failure",
            "status": "resolved",
        },
    )
    result = campaign_resume_info("test-findings", tmp_path)
    assert result["unresolved_finding_count"] == 1


def test_resume_no_raw_secrets(tmp_path):
    init_campaign_dir("test-no-secrets", tmp_path)
    state = CampaignState.model_validate({
        "campaign_id": "test-no-secrets",
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "phase": "completed",
        "lane_identity": "l1",
        "baseline_sha": "abc",
        "active_branch": "b",
        "assigned_remote_branch": "b",
        "manifest_digest": "dig",
        "latest_checkpoint_sha": "sha1",
        "latest_pushed_sha": "sha1",
    })
    save_campaign_state(state, "test-no-secrets", tmp_path)
    result = campaign_resume_info("test-no-secrets", tmp_path)
    raw = json.dumps(result)
    assert "SECRET" not in raw
    assert "API_KEY" not in raw
    assert "password" not in raw
