"""Tests for live PR rehearsal — blocked by default, simulated success with fake boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.integrations.github_provider._code_scanning_live_pr_rehearsal import (
    _STEPS,
    build_live_pr_rehearsal,
    build_operator_checklist,
)
from rig_relay.integrations.github_provider._fake_github_boundary import (
    FakeGitHubBoundary,
)

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
GOV = REPO_ROOT / "docs" / "json" / "governance"


def test_blocked_by_default():
    r = build_live_pr_rehearsal(generated_at_utc="2026-05-20T00:00:00Z")
    assert r["status"] == "rehearsal_blocked"
    assert r["remote_mutation_succeeded"] is False
    assert r["alert_updated"] is False
    assert r["alert_update_deferred"] is True
    assert r["pr_merged"] is False


def test_blocked_reasons():
    r = build_live_pr_rehearsal()
    assert "execute_flag" in r["blocked_reasons"]
    assert "operator_acknowledged" in r["blocked_reasons"]


def test_simulated_success():
    fb = FakeGitHubBoundary()
    r = build_live_pr_rehearsal(
        allow_execute=True,
        operator_acknowledged=True,
        allow_live_writes=True,
        approval_ok=True,
        fake_boundary=fb,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    assert r["status"] == "rehearsal_success"
    assert r["branch_created"] is True
    assert r["file_written"] is True
    assert r["pr_created"] is True
    assert r["alert_updated"] is False


def test_branch_collision_blocks():
    fb = FakeGitHubBoundary()
    fb.add_existing_branch("rig/security/fix-5")
    r = build_live_pr_rehearsal(
        allow_execute=True,
        operator_acknowledged=True,
        approval_ok=True,
        fake_boundary=fb,
    )
    assert r["gates_passed"] is False


def test_rate_limit_blocks():
    fb = FakeGitHubBoundary()
    fb.set_rate_limited(True)
    r = build_live_pr_rehearsal(
        allow_execute=True,
        operator_acknowledged=True,
        approval_ok=True,
        fake_boundary=fb,
    )
    assert "rate_limit_ok" in [g["gate"] for g in r["gates"] if not g["passed"]]


def test_permission_denied_blocks():
    fb = FakeGitHubBoundary()
    fb.set_permission("contents:write", False)
    r = build_live_pr_rehearsal(
        allow_execute=True,
        operator_acknowledged=True,
        approval_ok=True,
        fake_boundary=fb,
    )
    assert "contents_write_available" in [
        g["gate"] for g in r["gates"] if not g["passed"]
    ]


def test_no_forbidden_fields():
    fb = FakeGitHubBoundary()
    r = build_live_pr_rehearsal(
        allow_execute=True,
        operator_acknowledged=True,
        approval_ok=True,
        fake_boundary=fb,
    )
    s = json.dumps(r, sort_keys=True)
    for f in (
        '"access_token"',
        '"authorization"',
        '"private_key"',
        '"raw_response"',
        '"raw_body"',
        '"code_snippet"',
    ):
        assert f not in s


def test_no_token_patterns():
    r = build_live_pr_rehearsal()
    s = json.dumps(r, sort_keys=True)
    for p in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert p not in s


def test_operator_checklist():
    cl = build_operator_checklist("rig/security/fix-5", "README.md", "abc123")
    assert cl["no_default_branch_write"] is True
    assert cl["no_workflow_paths"] is True
    assert cl["alert_update_deferred"] is True


def test_17_steps():
    assert len(_STEPS) == 17


def test_alert_deferred_in_all_steps():
    r = build_live_pr_rehearsal()
    assert r["alert_updated"] is False


def test_generated_artifacts_exist():
    build_live_pr_rehearsal(
        allow_execute=True,
        operator_acknowledged=True,
        approval_ok=True,
        fake_boundary=FakeGitHubBoundary(),
    )
    for name in (
        "github_live_pr_rehearsal_v1.v1",
        "github_live_pr_rehearsal_receipt_v1.v1",
        "github_live_pr_rehearsal_operator_checklist_v1.v1",
    ):
        assert (GOV / f"{name}.json").exists()


def test_generated_artifacts_redaction_clean():
    build_live_pr_rehearsal()
    for name in (
        "github_live_pr_rehearsal_v1.v1",
        "github_live_pr_rehearsal_receipt_v1.v1",
    ):
        p = GOV / f"{name}.json"
        s = p.read_text(encoding="utf-8")
        for pat in (
            "ghp_",
            "BEGIN PRIVATE KEY",
            '"access_token"',
            '"authorization"',
            '"raw_body"',
        ):
            assert pat not in s, f"{pat} in {name}"
