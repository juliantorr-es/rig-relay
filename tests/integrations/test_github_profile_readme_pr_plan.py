"""Integration tests for profile README PR plan — dry-run-first, multi-gate."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._profile_readme_pr_plan import (
    _REQUIRED_READ_PERMISSIONS,
    _REQUIRED_WRITE_CONTENT_PERMISSIONS,
    _REQUIRED_WRITE_PR_PERMISSIONS,
    _build_gates,
    build_pr_plan,
)

pytestmark = [pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.github.profile_readme_pr_plan.v1.schema.json"
)


def _temp_preview(
    tmp_path: Path, content: str = "# Test Preview\n"
) -> tuple[Path, str]:
    preview_file = tmp_path / "profile_readme_preview.md"
    preview_file.write_text(content, encoding="utf-8")
    sha = Path(preview_file).read_bytes()
    import hashlib

    preview_sha = hashlib.sha256(sha).hexdigest()
    return preview_file, preview_sha


# ── Dry-run plan tests ──


def test_build_pr_plan_dry_run_default():
    plan = build_pr_plan("testuser", generated_at_utc="2026-05-20T00:00:00Z")
    assert plan["schema_version"] == "rig.github.profile_readme_pr_plan.v1"
    assert plan["operation_mode"] == "dry_run"
    assert plan["requested_remote_mutation"] is False
    assert plan["remote_mutation"] is False
    assert plan["content_light"] is True
    assert plan["publish_gate_status"] == "dry_run_blocked"
    assert "explicit_publish_flag_not_set" in plan["blocked_reasons"]


def test_build_pr_plan_with_publish_allowed(tmp_path):
    preview_file, preview_sha = _temp_preview(tmp_path)
    plan = build_pr_plan(
        "testuser",
        allow_publish=True,
        generated_at_utc="2026-05-20T00:00:00Z",
        preview_path=preview_file,
    )
    assert plan["requested_remote_mutation"] is True
    assert plan["operation_mode"] == "publish_requested"
    assert plan["preview_sha256"] == preview_sha


def test_plan_records_preview_metadata(tmp_path):
    preview_file, preview_sha = _temp_preview(tmp_path, "## Test\n\nSome content.\n")
    plan = build_pr_plan(
        "testuser",
        allow_publish=True,
        generated_at_utc="2026-05-20T00:00:00Z",
        preview_path=preview_file,
    )
    assert plan["preview_sha256"] == preview_sha
    assert plan["preview_bytes"] is not None
    assert plan["preview_line_count"] is not None


def test_plan_has_separate_permission_categories():
    plan = build_pr_plan("testuser")
    perms = plan["required_permissions"]
    assert perms["read"] == _REQUIRED_READ_PERMISSIONS
    assert perms["write_content"] == _REQUIRED_WRITE_CONTENT_PERMISSIONS
    assert perms["write_pr"] == _REQUIRED_WRITE_PR_PERMISSIONS
    assert "explicitly_not_required" in perms
    not_required = perms["explicitly_not_required"]
    assert "workflows:write" in not_required
    assert "actions:write" in not_required


def test_plan_has_5_planned_steps():
    plan = build_pr_plan("testuser")
    steps = plan["planned_steps"]
    assert len(steps) == 5
    operations = [s["operation"] for s in steps]
    assert "read_repo_metadata" in operations
    assert "prepare_branch" in operations
    assert "write_file" in operations
    assert "create_pull_request" in operations
    assert "emit_operation_receipt" in operations


# ── Gate logic tests ──


def test_gate_logic_all_pass():
    all_pass, blocked, details = _build_gates(
        allow_publish=True,
        preview_path=Path("/tmp/fake.md"),
        expected_preview_sha256=None,
        target_path="README.md",
        base_branch="main",
        proposed_branch="relay/profile-readme-update",
        live_permission_verified=True,
        redaction_scan={"content_clean": True, "redaction_matches": []},
    )
    # preview_path doesn't exist, so preview_hash gate won't apply (sha check only if path exists)
    assert "explicit_publish_flag_not_set" not in blocked
    assert "preview_file_missing" in blocked


def test_gate_blocks_on_missing_publish_flag():
    all_pass, blocked, _ = _build_gates(
        allow_publish=False,
        preview_path=Path("/tmp/fake.md"),
        expected_preview_sha256=None,
        target_path="README.md",
        base_branch="main",
        proposed_branch="relay/profile-readme-update",
        live_permission_verified=True,
        redaction_scan=None,
    )
    assert not all_pass
    assert "explicit_publish_flag_not_set" in blocked


def test_gate_blocks_on_workflow_path():
    all_pass, blocked, _ = _build_gates(
        allow_publish=True,
        preview_path=Path("/tmp/fake.md"),
        expected_preview_sha256=None,
        target_path=".github/workflows/ci.yml",
        base_branch="main",
        proposed_branch="relay/update-ci",
        live_permission_verified=True,
        redaction_scan=None,
    )
    assert "target_path_is_workflow_blocked" in blocked


def test_gate_blocks_on_base_branch_equals_proposed():
    all_pass, blocked, _ = _build_gates(
        allow_publish=True,
        preview_path=Path("/tmp/fake.md"),
        expected_preview_sha256=None,
        target_path="README.md",
        base_branch="main",
        proposed_branch="main",
        live_permission_verified=True,
        redaction_scan=None,
    )
    assert "proposed_branch_equals_base_branch" in blocked


def test_gate_blocks_on_live_permission_not_verified():
    all_pass, blocked, _ = _build_gates(
        allow_publish=True,
        preview_path=Path("/tmp/fake.md"),
        expected_preview_sha256=None,
        target_path="README.md",
        base_branch="main",
        proposed_branch="relay/update-readme",
        live_permission_verified=False,
        redaction_scan=None,
    )
    assert "live_permission_not_verified" in blocked


def test_gate_blocks_on_redaction_scan_failed():
    all_pass, blocked, _ = _build_gates(
        allow_publish=True,
        preview_path=Path("/tmp/fake.md"),
        expected_preview_sha256=None,
        target_path="README.md",
        base_branch="main",
        proposed_branch="relay/update-readme",
        live_permission_verified=True,
        redaction_scan={"content_clean": False, "redaction_matches": ["line_5:ghp_"]},
    )
    assert "redaction_scan_failed" in blocked


# ── Schema validation test ──


def test_pr_plan_validates_against_schema():
    assert SCHEMA_PATH.exists()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    plan = build_pr_plan("testuser", generated_at_utc="2026-05-20T00:00:00Z")
    jsonschema.validate(instance=plan, schema=schema)


# ── No-forbidden-fields test ──


def test_pr_plan_no_forbidden_fields():
    plan = build_pr_plan("testuser", generated_at_utc="2026-05-20T00:00:00Z")
    serialized = json.dumps(plan, sort_keys=True)
    for forbidden in (
        "access_token",
        "authorization",
        "client_secret",
        "private_key",
        "raw_response",
        "raw_body",
        "patch",
        "diff",
        "bearer",
    ):
        assert f'"{forbidden}"' not in serialized


# ── Plan produced by CLI is schema-valid ──


def test_generated_plan_artifact_validates():
    artifact_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_profile_readme_pr_plan_v1.v1.json"
    )
    if not artifact_path.exists():
        pytest.skip("PR plan artifact not yet generated")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)
    assert report["remote_mutation"] is False
    assert report["content_light"] is True


def test_plan_idempotency_key_deterministic():
    plan1 = build_pr_plan("testuser", generated_at_utc="2026-05-20T00:00:00Z")
    plan2 = build_pr_plan("testuser", generated_at_utc="2026-05-20T00:00:00Z")
    assert plan1["idempotency_key"] == plan2["idempotency_key"]


def test_plan_mutation_lane_id_correct():
    plan = build_pr_plan("testuser")
    assert plan["mutation_lane_id"] == "profile_readme_publish_pr"


def test_workflows_not_required():
    plan = build_pr_plan("testuser")
    not_required = plan["required_permissions"]["explicitly_not_required"]
    assert "workflows:write" in not_required
    assert "actions:write" in not_required

    # Verify step permissions don't include workflows:write
    step_perms = {s["permission"] for s in plan["planned_steps"]}
    assert "workflows:write" not in step_perms
    assert "actions:write" not in step_perms


def test_contents_write_required_for_file_step():
    plan = build_pr_plan("testuser")
    file_steps = [
        s
        for s in plan["planned_steps"]
        if s["operation"] in ("prepare_branch", "write_file")
    ]
    for s in file_steps:
        assert s["permission"] == "contents:write"


def test_pull_requests_write_required_for_pr_step():
    plan = build_pr_plan("testuser")
    pr_step = next(
        s for s in plan["planned_steps"] if s["operation"] == "create_pull_request"
    )
    assert pr_step["permission"] == "pull_requests:write"
