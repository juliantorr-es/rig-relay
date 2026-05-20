"""Tests for code scanning PR creation plan — blocked by default, ready with verified diff."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._code_scanning_pr_plan import (
    _build_branch_name,
    _pr_gates_pass,
    _sanitize_branch_name,
    build_code_scanning_pr_plan,
)

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.code_scanning_pr_creation_plan.v1.schema.json"
)


def _blocked_receipt() -> dict:
    return {
        "diff_classification": "blocked_explanation",
        "has_real_diff": False,
        "policy_gate_passed": False,
        "diff_sha256": "blocksha",
        "diff_path": "/nonexistent",
        "source_context_hash": None,
        "selected_alert_number": None,
        "raw_source_embedded_in_json": True,
        "severity": "warning",
        "rule_id_hash": "rulehash",
    }


def _ready_receipt(tmp_path: Path) -> tuple[dict, Path]:
    diff_file = tmp_path / "candidate.diff"
    diff_file.write_text("--- a/test\n+++ b/test\n@@ -1,1 +1,1 @@\n-foo\n+bar\n")
    receipt = {
        "diff_classification": "dry_run_candidate_diff",
        "has_real_diff": True,
        "policy_gate_passed": True,
        "diff_sha256": None,
        "diff_path": str(diff_file),
        "source_context_hash": "abc123source",
        "selected_alert_number": 5,
        "raw_source_embedded_in_json": False,
        "remote_mutation": False,
        "local_mutation": False,
        "severity": "warning",
        "rule_id_hash": "rule5hash",
    }
    receipt["diff_sha256"] = Path(diff_file).read_bytes()  # won't work - need hex
    import hashlib

    receipt["diff_sha256"] = hashlib.sha256(diff_file.read_bytes()).hexdigest()
    return receipt, diff_file


# ── Branch name sanitization ──


def test_sanitize_lowercase():
    result = _sanitize_branch_name("Fix/Alert#5")
    assert "fix" in result
    assert "alert" in result
    assert "5" in result


def test_sanitize_spaces():
    assert _sanitize_branch_name("fix alert 5") == "fix-alert-5"


def test_sanitize_path_traversal():
    name = _sanitize_branch_name("../../etc/passwd")
    assert ".." not in name
    assert "etc" in name
    assert "passwd" in name


def test_sanitize_length():
    long_name = "a" * 100
    result = _sanitize_branch_name(long_name)
    assert len(result) <= 80


def test_sanitize_empty():
    assert len(_sanitize_branch_name("---")) > 0


def test_branch_name_deterministic():
    receipt = _blocked_receipt()
    receipt["selected_alert_number"] = 5
    receipt["diff_sha256"] = (
        "abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234"
    )
    b1 = _build_branch_name(receipt)
    b2 = _build_branch_name(receipt)
    assert b1 == b2
    assert "rig/code-scanning/5-fix" in b1


# ── PR gate tests ──


def test_gate_blocks_blocked_classification(tmp_path):
    receipt = _blocked_receipt()
    diff_path = tmp_path / "diff.diff"
    diff_path.write_text("blocked")
    receipt["diff_path"] = str(diff_path)
    receipt["diff_sha256"] = Path(diff_path).read_bytes()  # wrong - let's fix
    import hashlib

    receipt["diff_sha256"] = hashlib.sha256(diff_path.read_bytes()).hexdigest()
    ok, blocked = _pr_gates_pass(receipt, diff_path)
    assert ok is False
    assert "diff_classification_not_dry_run_candidate" in blocked


def test_gate_blocks_missing_file(tmp_path):
    receipt = _ready_receipt(tmp_path)[0]
    ok, blocked = _pr_gates_pass(receipt, Path("/nonexistent.diff"))
    assert ok is False
    assert "diff_artifact_file_missing" in blocked


def test_gate_blocks_sha_mismatch(tmp_path):
    receipt, diff_file = _ready_receipt(tmp_path)
    receipt["diff_sha256"] = "wrongsha"
    ok, blocked = _pr_gates_pass(receipt, diff_file)
    assert ok is False
    assert "diff_sha256_mismatch" in blocked


def test_gate_blocks_missing_context_hash(tmp_path):
    receipt, diff_file = _ready_receipt(tmp_path)
    receipt["source_context_hash"] = None
    ok, blocked = _pr_gates_pass(receipt, diff_file)
    assert ok is False
    assert "source_context_hash_missing" in blocked


def test_gate_blocks_missing_alert(tmp_path):
    receipt, diff_file = _ready_receipt(tmp_path)
    receipt["selected_alert_number"] = None
    ok, blocked = _pr_gates_pass(receipt, diff_file)
    assert ok is False
    assert "alert_identity_missing" in blocked


# ── PR plan tests ──


def test_blocked_plan_by_default():
    report = build_code_scanning_pr_plan(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["status"] == "blocked_pr_creation_plan"
    assert report["remote_mutation"] is False
    assert report["local_mutation"] is False
    assert report["alert_update_deferred"] is True
    assert len(report["blocked_reasons"]) > 0


def test_blocked_plan_validates_schema():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = build_code_scanning_pr_plan(generated_at_utc="2026-05-20T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)


def test_blocked_plan_permissions_not_used():
    report = build_code_scanning_pr_plan(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["permissions_used_this_slice"] == []


def test_blocked_plan_pr_body_light():
    report = build_code_scanning_pr_plan(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["pr_body_content_light"] is True


def test_blocked_plan_no_forbidden():
    report = build_code_scanning_pr_plan(generated_at_utc="2026-05-20T00:00:00Z")
    s = json.dumps(report, sort_keys=True)
    for f in (
        '"access_token"',
        '"authorization"',
        '"private_key"',
        '"raw_response"',
        '"code_snippet"',
    ):
        assert f not in s


# ── Generated artifact tests ──


def test_generated_artifact_validates():
    artifact_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "code_scanning_pr_creation_plan_v1.v1.json"
    )
    if not artifact_path.exists():
        pytest.skip("Artifact not yet generated")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_generated_artifact_no_forbidden():
    artifact_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "code_scanning_pr_creation_plan_v1.v1.json"
    )
    if not artifact_path.exists():
        pytest.skip("Artifact not yet generated")
    s = artifact_path.read_text(encoding="utf-8")
    for p in ("ghp_", "BEGIN PRIVATE KEY", '"access_token"', '"code_snippet"'):
        assert p not in s


def test_approval_chain_has_7_steps():
    report = build_code_scanning_pr_plan()
    assert len(report["approval_chain"]) == 7
    assert "alert update remains separate" in report["approval_chain"][-1]
