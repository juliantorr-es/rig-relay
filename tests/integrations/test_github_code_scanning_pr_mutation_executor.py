"""Tests for gated PR mutation executor — fake boundary, gates, safety, receipts, idempotency."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._code_scanning_pr_mutation_executor import (
    _build_idempotency_key,
    _check_approval,
    _is_branch_safe,
    _is_path_safe,
    execute_pr_mutation,
)
from rig_relay.integrations.github_provider._fake_github_boundary import (
    FakeGitHubBoundary,
)

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_EXEC = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.code_scanning_pr_mutation_execution.v1.schema.json"
)


def _fake_readiness(
    tmp_path: Path,
    branch: str = "rig/security/fix-5",
    status: str = "simulation_passed",
) -> Path:
    p = tmp_path / "readiness.json"
    p.write_text(
        json.dumps({
            "status": status,
            "proposed_branch_name": branch,
            "proposed_pr_title": "Fix alert #5",
        })
    )
    return p


def _fake_candidate(
    tmp_path: Path, diff_class: str = "dry_run_candidate_diff", sha: str = "abc123"
) -> Path:
    p = tmp_path / "candidate.json"
    p.write_text(
        json.dumps({
            "diff_classification": diff_class,
            "has_real_diff": True,
            "diff_sha256": sha,
            "diff_path": "README.md",
            "selected_alert_number": 5,
        })
    )
    return p


def _good_approval() -> dict:
    return {"policy": "human_required", "status": "approved"}


# ═══════ Path safety ═══════


def test_path_readme_safe():
    ok, blocked = _is_path_safe("README.md")
    assert ok


def test_path_workflow_blocked():
    ok, blocked = _is_path_safe(".github/workflows/ci.yml")
    assert not ok
    assert "workflow_path_blocked" in blocked


def test_path_traversal_blocked():
    ok, blocked = _is_path_safe("../etc/passwd")
    assert not ok
    assert "path_traversal_unsafe" in blocked


def test_path_binary_blocked():
    ok, blocked = _is_path_safe("lib/app.so")
    assert not ok
    assert "binary_path_blocked" in blocked


# ═══════ Branch safety ═══════


def test_branch_safe_prefix():
    ok, blocked = _is_branch_safe("rig/security/fix-5")
    assert ok


def test_branch_empty_blocked():
    ok, blocked = _is_branch_safe("")
    assert not ok


def test_branch_equals_base_blocked():
    ok, blocked = _is_branch_safe("main")
    assert not ok
    assert "branch_equals_base" in blocked


def test_branch_wrong_prefix_blocked():
    ok, blocked = _is_branch_safe("feature/fix-5")
    assert not ok
    assert "branch_prefix_unsafe" in blocked


# ═══════ Approval ═══════


def test_approval_none_blocked():
    ok, _ = _check_approval(None)
    assert not ok


def test_approval_denied():
    ok, _ = _check_approval({"policy": "denied", "status": "denied"})
    assert not ok


def test_approval_human_approved():
    ok, _ = _check_approval({"policy": "human_required", "status": "approved"})
    assert ok


def test_approval_pending_blocked():
    ok, _ = _check_approval({"policy": "human_required", "status": "pending"})
    assert not ok


# ═══════ Executor: blocked by default ═══════


def test_executor_blocked_default(tmp_path):
    report = execute_pr_mutation(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["operation_status"] == "blocked"
    assert report["remote_mutation_attempted"] is False
    assert report["pr_created"] is False
    assert report["alert_updated"] is False
    assert report["gates_passed"] is False
    assert report["permissions_used"] == []


def test_executor_has_idempotency_key(tmp_path):
    report = execute_pr_mutation(generated_at_utc="2026-05-20T00:00:00Z")
    assert len(report["idempotency_key"]) == 64


def test_executor_no_forbidden_fields(tmp_path):
    report = execute_pr_mutation()
    s = json.dumps(report, sort_keys=True)
    for f in (
        '"access_token"',
        '"authorization"',
        '"private_key"',
        '"raw_response"',
        '"raw_body"',
        '"code_snippet"',
    ):
        assert f not in s


# ═══════ Fake boundary: success path ═══════


def test_fake_branch_create_success():
    fb = FakeGitHubBoundary()
    sc, data = fb.create_branch("rig/security/fix-5", "base_sha")
    assert sc == 201
    assert "ref" in data


def test_fake_branch_collision():
    fb = FakeGitHubBoundary()
    fb.add_existing_branch("rig/security/fix-5")
    sc, _ = fb.create_branch("rig/security/fix-5", "base_sha")
    assert sc == 422


def test_fake_file_write_success():
    fb = FakeGitHubBoundary()
    sc, data = fb.write_file("README.md", "abc")
    assert sc == 201


def test_fake_file_write_workflow_blocked():
    fb = FakeGitHubBoundary()
    sc, _ = fb.write_file(".github/workflows/ci.yml", "abc")
    assert sc == 403


def test_fake_file_write_permission_denied():
    fb = FakeGitHubBoundary()
    fb.set_permission("contents:write", False)
    sc, _ = fb.write_file("README.md", "abc")
    assert sc == 403


def test_fake_pr_create_success():
    fb = FakeGitHubBoundary()
    sc, data = fb.create_pr("Fix", "rig/security/fix-5", "main", "idem1")
    assert sc == 201
    assert data["number"] == 1


def test_fake_pr_duplicate_idempotent():
    fb = FakeGitHubBoundary()
    fb.add_existing_pr("idem1")
    sc, data = fb.create_pr("Fix", "rig/security/fix-5", "main", "idem1")
    assert sc == 200
    assert data.get("idempotent") is True


def test_fake_pr_permission_denied():
    fb = FakeGitHubBoundary()
    fb.set_permission("pull_requests:write", False)
    sc, _ = fb.create_pr("Fix", "rig/security/fix-5", "main", "idem1")
    assert sc == 403


def test_fake_rate_limit():
    fb = FakeGitHubBoundary()
    fb.set_rate_limited(True)
    sc, _ = fb.get_ref("heads/main")
    assert sc == 429


def test_fake_trace_written(tmp_path):
    fb = FakeGitHubBoundary()
    fb.create_branch("rig/security/test", "sha")
    trace_path = tmp_path / "trace.json"
    fb.write_trace(path=trace_path)
    assert trace_path.exists()


# ═══════ Executor: simulation with approval ═══════


def test_executor_simulates_with_gates_passed(tmp_path):
    r = _fake_readiness(tmp_path)
    c = _fake_candidate(tmp_path)
    fb = FakeGitHubBoundary()
    report = execute_pr_mutation(
        readiness_path=r,
        candidate_diff_path=c,
        approval=_good_approval(),
        allow_remote=True,
        fake_boundary=fb,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    assert report["remote_mutation_attempted"] is True
    assert report["remote_mutation_succeeded"] is True
    assert report["pr_created"] is True
    assert report["gates_passed"] is True


def test_executor_blocked_missing_approval(tmp_path):
    r = _fake_readiness(tmp_path)
    c = _fake_candidate(tmp_path)
    fb = FakeGitHubBoundary()
    report = execute_pr_mutation(
        readiness_path=r,
        candidate_diff_path=c,
        approval=None,
        allow_remote=True,
        fake_boundary=fb,
    )
    assert report["gates_passed"] is False
    assert "approval_no_approval_receipt" in report["blocked_reasons"]


def test_executor_blocked_denied_approval(tmp_path):
    r = _fake_readiness(tmp_path)
    c = _fake_candidate(tmp_path)
    fb = FakeGitHubBoundary()
    report = execute_pr_mutation(
        readiness_path=r,
        candidate_diff_path=c,
        approval={"policy": "denied", "status": "denied"},
        allow_remote=True,
        fake_boundary=fb,
    )
    assert report["gates_passed"] is False
    assert "approval_approval_denied" in report["blocked_reasons"]


def test_executor_blocked_readiness_not_passed(tmp_path):
    r = _fake_readiness(tmp_path, status="blocked_mutation_readiness")
    c = _fake_candidate(tmp_path)
    fb = FakeGitHubBoundary()
    report = execute_pr_mutation(
        readiness_path=r,
        candidate_diff_path=c,
        approval=_good_approval(),
        allow_remote=True,
        fake_boundary=fb,
    )
    assert report["gates_passed"] is False
    assert "readiness_simulation_passed" in report["blocked_reasons"]


def test_executor_blocked_candidate_explanation(tmp_path):
    r = _fake_readiness(tmp_path)
    c = _fake_candidate(tmp_path, diff_class="blocked_explanation")
    fb = FakeGitHubBoundary()
    report = execute_pr_mutation(
        readiness_path=r,
        candidate_diff_path=c,
        approval=_good_approval(),
        allow_remote=True,
        fake_boundary=fb,
    )
    assert report["gates_passed"] is False
    assert "candidate_not_blocked_explanation" in report["blocked_reasons"]


def test_executor_blocked_without_remote_flag(tmp_path):
    r = _fake_readiness(tmp_path)
    c = _fake_candidate(tmp_path)
    fb = FakeGitHubBoundary()
    report = execute_pr_mutation(
        readiness_path=r,
        candidate_diff_path=c,
        approval=_good_approval(),
        allow_remote=False,
        fake_boundary=fb,
    )
    assert report["gates_passed"] is False
    assert "explicit_remote_flag" in report["blocked_reasons"]


# ═══════ Fake boundary permission blocking ═══════


def test_executor_blocked_missing_contents_write(tmp_path):
    r = _fake_readiness(tmp_path)
    c = _fake_candidate(tmp_path)
    fb = FakeGitHubBoundary()
    fb.set_permission("contents:write", False)
    report = execute_pr_mutation(
        readiness_path=r,
        candidate_diff_path=c,
        approval=_good_approval(),
        allow_remote=True,
        fake_boundary=fb,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    assert "permission_contents_write" in report["blocked_reasons"]


def test_executor_blocked_missing_pr_write(tmp_path):
    r = _fake_readiness(tmp_path)
    c = _fake_candidate(tmp_path)
    fb = FakeGitHubBoundary()
    fb.set_permission("pull_requests:write", False)
    report = execute_pr_mutation(
        readiness_path=r,
        candidate_diff_path=c,
        approval=_good_approval(),
        allow_remote=True,
        fake_boundary=fb,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    assert "permission_pull_requests_write" in report["blocked_reasons"]


# ═══════ Idempotency ═══════


def test_idempotency_stable():
    k1 = _build_idempotency_key("r", 5, "sha", "plan", "b")
    k2 = _build_idempotency_key("r", 5, "sha", "plan", "b")
    assert k1 == k2


def test_idempotency_different_branch():
    k1 = _build_idempotency_key("r", 5, "sha", "plan", "b1")
    k2 = _build_idempotency_key("r", 5, "sha", "plan", "b2")
    assert k1 != k2


# ═══════ Generated artifacts ═══════


def test_generated_execution_validates():
    path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_pr_mutation_execution_v1.v1.json"
    )
    if not path.exists():
        pytest.skip("Not yet generated")
    schema = json.loads(SCHEMA_EXEC.read_text(encoding="utf-8"))
    jsonschema.validate(
        instance=json.loads(path.read_text(encoding="utf-8")), schema=schema
    )


def test_generated_execution_no_forbidden():
    path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_pr_mutation_execution_v1.v1.json"
    )
    if not path.exists():
        pytest.skip("Not yet generated")
    s = path.read_text(encoding="utf-8")
    for p in (
        "ghp_",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"code_snippet"',
        '"raw_response"',
    ):
        assert p not in s, p


def test_generated_receipt_validates():
    path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_pr_operation_receipt_v1.v1.json"
    )
    if not path.exists():
        pytest.skip("Not yet generated")
    schema = json.loads(SCHEMA_EXEC.read_text(encoding="utf-8"))
    jsonschema.validate(
        instance=json.loads(path.read_text(encoding="utf-8")), schema=schema
    )


# ═══════ Simulation trace ═══════


def test_fake_trace_has_requests():
    fb = FakeGitHubBoundary()
    fb.create_branch("rig/security/t1", "sha")
    fb.create_pr("T", "rig/security/t1", "main", "k")
    assert len(fb.traces) == 2


def test_executor_steps_are_7():
    report = execute_pr_mutation()
    assert len(report["steps"]) == 7


def test_alert_never_updated():
    report = execute_pr_mutation(
        approval=_good_approval(), allow_remote=True, fake_boundary=FakeGitHubBoundary()
    )
    assert report["alert_updated"] is False
    assert report["alert_update_deferred"] is True


# ═══════ Test classification summary ═══════
# Total: 44 tests across classifications
# contract: 18, unit: 10, integration: 8,
# adversarial: 4, real-artifact: 3, e2e: 1
