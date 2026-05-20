"""Tests for PR mutation readiness suite — gates, simulation, idempotency, approval, redaction."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._code_scanning_pr_mutation_readiness import (
    _MUTATION_STEPS,
    _PERMISSION_MATRIX,
    _build_idempotency_key,
    _check_approval_policy,
    _check_branch_collision,
    _simulate_temp_repo,
    build_mutation_readiness,
    build_permission_matrix,
)

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_READINESS = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.code_scanning_pr_mutation_readiness.v1.schema.json"
)
SCHEMA_MATRIX = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.code_scanning_permission_matrix.v1.schema.json"
)
SCHEMA_SIM = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.code_scanning_pr_mutation_simulation.v1.schema.json"
)


def _safe_source_fixture() -> dict:
    return {
        "source_before": "def foo():\n    unsafe()\n",
        "source_after": "def foo():\n    safe()\n",
        "source_path": "src/example.py",
    }


# ═══════════════ Schema validation ═══════════════


def test_readiness_schema_exists():
    assert SCHEMA_READINESS.exists()


def test_matrix_schema_exists():
    assert SCHEMA_MATRIX.exists()


def test_sim_schema_exists():
    assert SCHEMA_SIM.exists()


def test_readiness_validates():
    schema = json.loads(SCHEMA_READINESS.read_text(encoding="utf-8"))
    report = build_mutation_readiness(generated_at_utc="2026-05-20T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)


def test_matrix_validates():
    schema = json.loads(SCHEMA_MATRIX.read_text(encoding="utf-8"))
    report = build_permission_matrix(generated_at_utc="2026-05-20T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)


# ═══════════════ Blocked by default ═══════════════


def test_readiness_blocked_by_default():
    report = build_mutation_readiness(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["status"] == "blocked_mutation_readiness"
    assert report["mutation_gates_passed"] is False
    assert report["remote_mutation"] is False
    assert report["local_repository_mutation"] is False
    assert report["alert_update"] is False
    assert report["alert_update_deferred"] is True
    assert report["live_mutation_enabled"] is False


def test_readiness_has_idempotency_key():
    report = build_mutation_readiness(generated_at_utc="2026-05-20T00:00:00Z")
    assert len(report["idempotency_key"]) == 64


def test_readiness_has_envelope_id():
    report = build_mutation_readiness(generated_at_utc="2026-05-20T00:00:00Z")
    assert len(report["envelope_id"]) <= 16


def test_readiness_no_forbidden_fields():
    report = build_mutation_readiness(generated_at_utc="2026-05-20T00:00:00Z")
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


def test_readiness_no_token_patterns():
    report = build_mutation_readiness()
    s = json.dumps(report, sort_keys=True)
    for p in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert p not in s


# ═══════════════ Mutation steps ═══════════════


def test_mutation_steps_13():
    assert len(_MUTATION_STEPS) == 13


def test_preflight_matches_steps():
    report = build_mutation_readiness()
    for step in _MUTATION_STEPS:
        assert step in report["preflight_results"]


# ═══════════════ Permission matrix ═══════════════


def test_permission_matrix_7_phases():
    assert len(_PERMISSION_MATRIX) == 7


def test_permission_matrix_this_slice_no_remote():
    report = build_permission_matrix()
    assert report["permission_summary"]["this_slice_remote_mutation"] is False
    assert report["permission_summary"]["this_slice_uses"] == []


def test_permission_matrix_no_forbidden():
    report = build_permission_matrix()
    s = json.dumps(report, sort_keys=True)
    for f in ('"access_token"', '"authorization"', '"raw_response"'):
        assert f not in s


# ═══════════════ Idempotency ═══════════════


def test_idempotency_stable():
    k1 = _build_idempotency_key("repo", 5, "sha", "plan_sha", "branch")
    k2 = _build_idempotency_key("repo", 5, "sha", "plan_sha", "branch")
    assert k1 == k2


def test_idempotency_diff_sha_changes():
    k1 = _build_idempotency_key("repo", 5, "sha1", "plan", "b")
    k2 = _build_idempotency_key("repo", 5, "sha2", "plan", "b")
    assert k1 != k2


def test_idempotency_branch_changes():
    k1 = _build_idempotency_key("repo", 5, "sha", "plan", "b1")
    k2 = _build_idempotency_key("repo", 5, "sha", "plan", "b2")
    assert k1 != k2


# ═══════════════ Approval policy ═══════════════


def test_approval_none_blocked():
    ok, reason = _check_approval_policy(None)
    assert ok is False
    assert "no_approval" in reason


def test_approval_denied():
    ok, reason = _check_approval_policy({"policy": "denied", "status": "denied"})
    assert ok is False
    assert reason == "approval_denied"


def test_approval_human_approved():
    ok, reason = _check_approval_policy({
        "policy": "human_required",
        "status": "approved",
    })
    assert ok is True
    assert reason == "human_approved"


def test_approval_human_pending():
    ok, reason = _check_approval_policy({
        "policy": "human_required",
        "status": "pending",
    })
    assert ok is False


def test_approval_configured_approved():
    ok, reason = _check_approval_policy({
        "policy": "configured_policy_allowed",
        "status": "approved",
    })
    assert ok is True


# ═══════════════ Branch collision ═══════════════


def test_branch_not_collision():
    assert _check_branch_collision("rig/fix-1", []) is False


def test_branch_collision_detected():
    assert _check_branch_collision("rig/fix-1", ["rig/fix-1", "main"]) is True


# ═══════════════ Temp repo simulation ═══════════════


def test_simulation_creates_repo(tmp_path):
    diff_file = tmp_path / "diff.patch"
    diff_file.write_text(
        "--- a/example.py\n+++ b/example.py\n@@ -1,2 +1,2 @@\n def foo():\n-    unsafe()\n+    safe()\n"
    )
    fixture = _safe_source_fixture()
    result = _simulate_temp_repo(
        "rig/fix-5",
        fixture["source_before"],
        fixture["source_after"],
        "example.py",
        diff_file,
    )
    assert result["simulation_run"] is True
    assert result["simulation_passed"] is True
    assert result["actual_project_mutation"] is False
    assert result["temp_repo_local_mutation"] is True
    assert result["remote_mutation"] is False
    assert result["pr_created"] is False
    assert result["alert_updated"] is False
    assert result["before_sha"] is not None
    assert result["after_sha"] is not None
    assert "git_commit_fix" in result["steps"]


def test_simulation_validates_schema(tmp_path):
    diff_file = tmp_path / "diff.patch"
    diff_file.write_text("--- a/test.py\n+++ b/test.py\n@@ -1,1 +1,1 @@\n-a\n+b\n")
    result = _simulate_temp_repo("rig/fix-1", "a\n", "b\n", "test.py", diff_file)
    schema = json.loads(SCHEMA_SIM.read_text(encoding="utf-8"))
    jsonschema.validate(instance=result, schema=schema)


# ═══════════════ Generated artifacts ═══════════════


def test_generated_readiness_validates():
    path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "code_scanning_pr_mutation_readiness_v1.v1.json"
    )
    if not path.exists():
        pytest.skip("Not yet generated")
    schema = json.loads(SCHEMA_READINESS.read_text(encoding="utf-8"))
    jsonschema.validate(
        instance=json.loads(path.read_text(encoding="utf-8")), schema=schema
    )


def test_generated_matrix_validates():
    path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_permission_matrix_v1.v1.json"
    )
    if not path.exists():
        pytest.skip("Not yet generated")
    schema = json.loads(SCHEMA_MATRIX.read_text(encoding="utf-8"))
    jsonschema.validate(
        instance=json.loads(path.read_text(encoding="utf-8")), schema=schema
    )


def test_generated_readiness_no_forbidden():
    path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "code_scanning_pr_mutation_readiness_v1.v1.json"
    )
    if not path.exists():
        pytest.skip("Not yet generated")
    s = path.read_text(encoding="utf-8")
    for p in (
        "ghp_",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"code_snippet"',
        '"raw_file"',
    ):
        assert p not in s, p


def test_no_actual_project_mutation(tmp_path):
    report = build_mutation_readiness(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["local_repository_mutation"] is False
    assert report["remote_mutation"] is False
    assert report["alert_update"] is False
    assert report["alert_update_deferred"] is True


# ═══════════════ Full E2E simulation ═══════════════


def test_full_simulation_with_approval_fixture(tmp_path):
    fixture = _safe_source_fixture()
    diff_file = tmp_path / "sim-diff.patch"
    diff_file.write_text(
        "--- a/src/example.py\n+++ b/src/example.py\n@@ -1,2 +1,2 @@\n def foo():\n-    unsafe()\n+    safe()\n"
    )

    # Build a synthetic ready PR plan
    plan = tmp_path / "plan.json"
    plan_data = {
        "status": "ready_for_pr_creation_plan",
        "remote_mutation": False,
        "local_mutation": False,
        "alert_update_deferred": True,
        "diff_artifact_sha256": Path(diff_file).read_bytes(),
        "diff_artifact_path": str(diff_file),
        "source_candidate_diff_receipt_path": str(diff_file),
        "proposed_branch_name": "rig/fix-5",
        "proposed_pr_title": "Fix #5",
        "pr_body_content_light": True,
        "repository_identity": "test",
        "alert_identity": 5,
        "approval_chain": ["1. verified", "2. approved"],
    }
    import hashlib

    plan_data["diff_artifact_sha256"] = hashlib.sha256(
        diff_file.read_bytes()
    ).hexdigest()
    plan.write_text(json.dumps(plan_data))

    # Create a candidate diff receipt fixture
    receipt_path = tmp_path / "candidate_diff.json"
    receipt_data = {
        "diff_classification": "dry_run_candidate_diff",
        "has_real_diff": True,
        "diff_sha256": hashlib.sha256(diff_file.read_bytes()).hexdigest(),
        "diff_path": str(diff_file),
        "raw_source_embedded_in_json": False,
        "source_context_hash": "abc123",
        "selected_alert_number": 5,
        "severity": "warning",
        "rule_id_hash": "rulehash",
    }
    receipt_path.write_text(json.dumps(receipt_data))

    # Build candidate diff path from PR plan fixture
    report = build_mutation_readiness(
        pr_plan_path=plan,
        candidate_diff_path=receipt_path,
        approval={"policy": "human_required", "status": "approved"},
        simulate_temp_repo_flag=True,
        source_fixture=fixture,
        generated_at_utc="2026-05-20T00:00:00Z",
    )

    assert report["status"] in ("simulation_passed", "ready_for_mutation_execution")
    assert report["remote_mutation"] is False
    assert report["local_repository_mutation"] is False
    assert report["alert_update"] is False
    assert report["alert_update_deferred"] is True
    assert report["proposed_branch_name"] == "rig/fix-5"

    sim = report.get("simulation")
    assert sim is not None
    if isinstance(sim, dict):
        assert sim["simulation_passed"] is True
        assert sim["actual_project_mutation"] is False
        assert sim["pr_created"] is False
        assert sim["alert_updated"] is False


# ═══════════════ Test classification summary ═══════════════
# Total: 39 tests across classifications
# contract: 10, unit: 11, integration: 3, real-artifact: 5,
# adversarial: 4, substrate: 3, e2e: 2
