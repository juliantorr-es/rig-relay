"""Integration tests for code scanning patch preview — blocked by source unavailability."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._code_scanning_patch_preview import (
    build_code_scanning_patch_preview,
)

pytestmark = [pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.code_scanning_patch_preview.v1.schema.json"
)


def test_preview_validates_against_schema():
    assert SCHEMA_PATH.exists()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = build_code_scanning_patch_preview(generated_at_utc="2026-05-20T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)


def test_preview_is_blocked_by_source_unavailability():
    report = build_code_scanning_patch_preview(generated_at_utc="2026-05-20T00:00:00Z")
    assert "blocked" in report["patch_preview_status"]
    assert "source_context_unavailable" in report["blocked_reasons"]


def test_preview_no_fake_diff():
    report = build_code_scanning_patch_preview(generated_at_utc="2026-05-20T00:00:00Z")
    assert (
        "not_generated" in report["diff_content_classification"]
        or "blocked" in report["diff_content_classification"]
    )
    assert report["diff_content_classification"] != "candidate_fix_diff"


def test_preview_has_deterministic_blocked_diff_file():
    report = build_code_scanning_patch_preview(generated_at_utc="2026-05-20T00:00:00Z")
    diff_path = Path(report["diff_preview_path"])
    assert diff_path.exists()
    assert report["diff_preview_sha256"] is not None
    assert report["diff_preview_bytes"] is not None
    assert report["diff_preview_line_count"] is not None


def test_preview_mutations_disabled():
    report = build_code_scanning_patch_preview(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["local_mutation_status"] == "disabled"
    assert report["remote_mutation_status"] == "disabled"
    assert report["pr_creation_status"] == "disabled"
    assert report["alert_update_status"] == "disabled"


def test_preview_permissions_separated():
    report = build_code_scanning_patch_preview(generated_at_utc="2026-05-20T00:00:00Z")
    audit = report["permission_audit"]
    assert "read_for_context" in audit
    assert "mutation_later" in audit
    assert "none_used_in_this_slice" in audit
    assert audit["none_used_in_this_slice"] is True


def test_preview_proposed_operations_blocked():
    report = build_code_scanning_patch_preview(generated_at_utc="2026-05-20T00:00:00Z")
    ops = report["proposed_operations"]
    assert len(ops) >= 2
    for op in ops:
        if op.get("operation_type") != "inspect":
            assert op.get("blocked_reason") is not None


def test_preview_no_forbidden_content():
    report = build_code_scanning_patch_preview(generated_at_utc="2026-05-20T00:00:00Z")
    serialized = json.dumps(report, sort_keys=True)
    for forbidden in (
        "access_token",
        "authorization",
        "client_secret",
        "private_key",
        "raw_response",
        "raw_body",
        "code_snippet",
        "vulnerable_code",
        "source_content",
        "secret_value",
    ):
        assert f'"{forbidden}"' not in serialized


def test_preview_no_token_patterns():
    report = build_code_scanning_patch_preview(generated_at_utc="2026-05-20T00:00:00Z")
    serialized = json.dumps(report, sort_keys=True)
    for pattern in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert pattern not in serialized


def test_preview_references_source_artifacts():
    report = build_code_scanning_patch_preview(generated_at_utc="2026-05-20T00:00:00Z")
    assert "governance/github_security_queue" in report["source_queue_artifact"]
    assert (
        "governance/github_code_scanning_patch_proposal"
        in report["source_patch_proposal_artifact"]
    )


def test_preview_verification_plan_targeted():
    report = build_code_scanning_patch_preview(generated_at_utc="2026-05-20T00:00:00Z")
    assert "do_not_run_full_pytest" in report["verification_plan"]
    assert any("redaction scan" in v.lower() for v in report["verification_plan"])


def test_preview_human_review_required():
    report = build_code_scanning_patch_preview(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["human_review_required"] is True


def test_generated_artifact_validates():
    artifact_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_patch_preview_v1.v1.json"
    )
    assert artifact_path.exists()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_generated_diff_file_clean():
    diff_path = (
        REPO_ROOT
        / ".build"
        / "rig-relay"
        / "previews"
        / "code_scanning_patch_preview.diff"
    )
    assert diff_path.exists()
    content = diff_path.read_text(encoding="utf-8")
    for pattern in ("ghp_", "BEGIN PRIVATE KEY", "access_token", "ya29."):
        assert pattern not in content
