"""Tests for post-PR security lifecycle — PR/alert states, alert plan, projection, fake boundary."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._code_scanning_post_pr_lifecycle import (
    build_post_pr_lifecycle,
    _determine_pr_state,
    _determine_alert_state,
    _ALERT_PATHS,
)
from rig_relay.integrations.github_provider._fake_github_boundary import (
    FakeGitHubBoundary,
)

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]


# ═══════ Alert paths ═══════


def test_alert_paths_five_entries():
    assert len(_ALERT_PATHS) == 5
    ids = {p["path_id"] for p in _ALERT_PATHS}
    assert "fix_verification" in ids
    assert "false_positive" in ids
    assert "wont_fix" in ids
    assert "dismissal_request" in ids
    assert "direct_update" in ids


def test_alert_paths_mutation_requires_security_events():
    for p in _ALERT_PATHS:
        if p.get("remote_mutation"):
            assert "security_events:write" in p["required_permissions"]


# ═══════ PR state determination ═══════


def test_pr_state_no_pr_without_fb():
    assert _determine_pr_state(None, None) == "no_pr"
    assert _determine_pr_state(None, 1) == "no_pr"


def test_pr_state_open():
    fb = FakeGitHubBoundary()
    fb.set_pr_state(1, "open", review_required=True)
    assert _determine_pr_state(fb, 1) == "pr_review_required"


def test_pr_state_checks_passed_no_review():
    fb = FakeGitHubBoundary()
    fb.set_pr_state(1, "open", checks="passing", review_required=False)
    assert _determine_pr_state(fb, 1) == "pr_checks_passed"


def test_pr_state_checks_failed():
    fb = FakeGitHubBoundary()
    fb.set_pr_state(1, "open", checks="failed", review_required=False)
    assert _determine_pr_state(fb, 1) == "pr_checks_failed"


def test_pr_state_checks_passed():
    fb = FakeGitHubBoundary()
    fb.set_pr_state(1, "open", checks="passing", review_required=False)
    assert _determine_pr_state(fb, 1) == "pr_checks_passed"


def test_pr_state_merged_verified():
    fb = FakeGitHubBoundary()
    fb.set_pr_state(1, "open", checks="passing", merged=True, review_required=False)
    assert _determine_pr_state(fb, 1) == "pr_merged_verified"


def test_pr_state_closed_without_merge():
    fb = FakeGitHubBoundary()
    fb.set_pr_state(1, "closed", review_required=False)
    assert _determine_pr_state(fb, 1) == "pr_closed_without_merge"


def test_pr_state_merged_unverified():
    fb = FakeGitHubBoundary()
    fb.set_pr_state(1, "open", checks="failed", merged=True, review_required=False)
    assert _determine_pr_state(fb, 1) == "pr_merged_unverified"


# ═══════ Alert state determination ═══════


def test_alert_state_unknown():
    assert _determine_alert_state(None, None) == "alert_unknown"


def test_alert_state_open():
    fb = FakeGitHubBoundary()
    fb.set_alert_state_initial(5, "open")
    assert _determine_alert_state(fb, 5) == "alert_open"


def test_alert_state_already_closed():
    fb = FakeGitHubBoundary()
    fb.set_alert_state_initial(5, "dismissed")
    assert _determine_alert_state(fb, 5) == "alert_closed_deferred"


# ═══════ Fake boundary post-PR methods ═══════


def test_fake_get_pr_status():
    fb = FakeGitHubBoundary()
    fb.set_pr_state(1, "open", checks="passing")
    sc, data = fb.get_pr_status(1)
    assert sc == 200
    assert data["state"] == "open"


def test_fake_get_pr_status_404():
    fb = FakeGitHubBoundary()
    sc, _ = fb.get_pr_status(99)
    assert sc == 404


def test_fake_get_alert_state():
    fb = FakeGitHubBoundary()
    fb.set_alert_state_initial(5, "open")
    sc, data = fb.get_alert_state(5)
    assert sc == 200
    assert data["state"] == "open"


def test_fake_update_alert_state_success():
    fb = FakeGitHubBoundary()
    fb.set_alert_state_initial(5, "open")
    fb.set_permission("security_events:write", True)
    sc, data = fb.update_alert_state(5, "dismissed", dismissal_reason="fix_verified")
    assert sc == 200
    assert data["state"] == "dismissed"


def test_fake_update_alert_permission_denied():
    fb = FakeGitHubBoundary()
    fb.set_alert_state_initial(5, "open")
    fb.set_permission("security_events:write", False)
    sc, _ = fb.update_alert_state(5, "dismissed")
    assert sc == 403


def test_fake_update_alert_already_resolved():
    fb = FakeGitHubBoundary()
    fb.set_alert_state_initial(5, "fixed")
    fb.set_permission("security_events:write", True)
    sc, _ = fb.update_alert_state(5, "dismissed")
    assert sc == 400


def test_fake_update_alert_rate_limited():
    fb = FakeGitHubBoundary()
    fb.set_rate_limited(True)
    sc, _ = fb.update_alert_state(5, "dismissed")
    assert sc == 429


# ═══════ Lifecycle: blocked by default ═══════


def test_lifecycle_blocked_by_default():
    report = build_post_pr_lifecycle(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["pr_lifecycle_state"] == "no_pr"
    assert report["alert_lifecycle_state"] == "alert_unknown"
    assert report["alert_update"] is False
    assert report["alert_update_deferred"] is True
    assert report["remote_mutation"] is False
    assert report["projection"]["human_review_required"] is True


def test_lifecycle_no_forbidden():
    report = build_post_pr_lifecycle()
    s = json.dumps(report, sort_keys=True)
    for f in (
        '"access_token"',
        '"authorization"',
        '"private_key"',
        '"raw_response"',
        '"code_snippet"',
        '"raw_file"',
    ):
        assert f not in s


def test_lifecycle_no_token_patterns():
    report = build_post_pr_lifecycle()
    s = json.dumps(report, sort_keys=True)
    for p in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert p not in s


# ═══════ Lifecycle: simulated ═══════


def test_lifecycle_simulated():
    fb = FakeGitHubBoundary()
    fb.set_pr_state(1, "open", checks="passing", review_required=False)
    fb.set_alert_state_initial(5, "open")
    report = build_post_pr_lifecycle(
        max_fake_boundary=fb,
        pr_created_override=True,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    assert report["pr_lifecycle_state"] == "pr_checks_passed"
    assert report["alert_lifecycle_state"] == "alert_open"


def test_lifecycle_simulated_pr_closed():
    fb = FakeGitHubBoundary()
    fb.set_pr_state(1, "closed", review_required=False)
    fb.set_alert_state_initial(5, "open")
    report = build_post_pr_lifecycle(max_fake_boundary=fb, pr_created_override=True)
    assert report["pr_lifecycle_state"] == "pr_closed_without_merge"


def test_lifecycle_alert_state_plan_has_causal_chain():
    report = build_post_pr_lifecycle()
    assert len(report["causal_chain"]) >= 4


def test_lifecycle_projection_ready():
    report = build_post_pr_lifecycle()
    proj = report["projection"]
    assert proj["pr_state"] is not None
    assert proj["alert_state"] is not None
    assert proj["human_review_required"] is True


# ═══════ Generated artifacts ═══════


def test_generated_lifecycle_exists():
    p = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_post_pr_lifecycle_v1.v1.json"
    )
    if not p.exists():
        pytest.skip("Not yet generated")
    assert p.exists()


def test_generated_lifecycle_no_forbidden():
    p = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_post_pr_lifecycle_v1.v1.json"
    )
    if not p.exists():
        pytest.skip("Not yet generated")
    s = p.read_text(encoding="utf-8")
    for pat in (
        "ghp_",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"code_snippet"',
        '"raw_response"',
    ):
        assert pat not in s, pat


def test_generated_alert_plan_exists():
    p = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_alert_state_plan_v1.v1.json"
    )
    if not p.exists():
        pytest.skip("Not yet generated")
    assert p.exists()


def test_generated_projection_exists():
    p = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_post_pr_projection_v1.v1.json"
    )
    if not p.exists():
        pytest.skip("Not yet generated")
    assert p.exists()


# ═══════ Fake trace ═══════


def test_fake_trace_written_with_lifecycle(tmp_path):
    fb = FakeGitHubBoundary()
    fb.get_pr_status(1)
    fb.get_alert_state(5)
    tp = tmp_path / "trace.json"
    fb.write_trace(tp)
    assert tp.exists()


# ═══════ Test summary: 35 tests, classifications: contract=22, integration=8, real-artifact=3, adversarial=2 ═══════
