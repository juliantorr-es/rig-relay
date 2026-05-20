"""Integration tests for code scanning fix patch proposal — proposal-only, no mutation."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._code_scanning_patch_proposal import (
    build_code_scanning_patch_proposal,
)

pytestmark = [pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.code_scanning_patch_proposal.v1.schema.json"
)


def test_proposal_validates_against_schema():
    assert SCHEMA_PATH.exists()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = build_code_scanning_patch_proposal(generated_at_utc="2026-05-20T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)


def test_proposal_selects_top_code_scanning_item():
    report = build_code_scanning_patch_proposal(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["schema_version"] == "rig.github.code_scanning_patch_proposal.v1"
    assert report["source_surface"] == "code_scanning"
    assert report["selected_queue_item_id"] is not None
    assert report["selected_plan_id"] is not None
    assert report["alert_number"] is not None


def test_proposal_references_source_artifacts():
    report = build_code_scanning_patch_proposal(generated_at_utc="2026-05-20T00:00:00Z")
    assert "governance/github_security_queue" in report["source_queue_artifact"]
    assert (
        "governance/github_security_remediation_plan"
        in report["source_remediation_plan_artifact"]
    )


def test_proposal_mutation_disabled():
    report = build_code_scanning_patch_proposal(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["remote_mutation_status"] == "disabled"
    assert report["local_mutation_status"] == "disabled"
    assert report["pr_creation_status"] == "disabled"
    assert report["alert_update_status"] == "disabled"


def test_proposal_permissions_separated():
    report = build_code_scanning_patch_proposal(generated_at_utc="2026-05-20T00:00:00Z")
    assert "required_read_permissions" in report
    assert "required_mutation_permissions_later" in report
    assert "security_events:read" in report["required_read_permissions"]
    assert "contents:write" in report["required_mutation_permissions_later"]
    assert "pull_requests:write" in report["required_mutation_permissions_later"]


def test_proposal_no_raw_code_content():
    report = build_code_scanning_patch_proposal(generated_at_utc="2026-05-20T00:00:00Z")
    serialized = json.dumps(report, sort_keys=True)
    for forbidden in (
        "code_snippet",
        "vulnerable_code",
        "raw_body",
        "source_content",
        "raw_response",
        "secret_value",
    ):
        assert f'"{forbidden}"' not in serialized


def test_proposal_no_token_patterns():
    report = build_code_scanning_patch_proposal(generated_at_utc="2026-05-20T00:00:00Z")
    serialized = json.dumps(report, sort_keys=True)
    for pattern in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert pattern not in serialized


def test_proposal_human_review_required():
    report = build_code_scanning_patch_proposal(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["human_review_required"] is True


def test_proposal_content_light():
    report = build_code_scanning_patch_proposal(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["content_light"] is True
    assert "content_light" in report["content_light_status"]


def test_proposal_has_location_summary():
    report = build_code_scanning_patch_proposal(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["location_summary_safe"] is not None
    assert (
        "rule_hash=" in report["location_summary_safe"]
        or "unknown" in report["location_summary_safe"]
    )


def test_proposal_has_patch_strategy():
    report = build_code_scanning_patch_proposal(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["patch_strategy"] is not None
    assert len(report["patch_strategy"]) > 50


def test_proposal_diff_deferred():
    report = build_code_scanning_patch_proposal(generated_at_utc="2026-05-20T00:00:00Z")
    assert "deferred" in report["proposed_diff_summary"].lower()


def test_proposal_test_strategy_targeted():
    report = build_code_scanning_patch_proposal(generated_at_utc="2026-05-20T00:00:00Z")
    assert "do_not_run_full_pytest" in report["proposed_test_strategy"]


def test_generated_artifact_validates():
    artifact_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_patch_proposal_v1.v1.json"
    )
    if not artifact_path.exists():
        pytest.skip("Artifact not yet generated")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_generated_artifact_no_forbidden_content():
    artifact_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_patch_proposal_v1.v1.json"
    )
    if not artifact_path.exists():
        pytest.skip("Artifact not yet generated")
    serialized = artifact_path.read_text(encoding="utf-8")
    for pattern in (
        "ghp_",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"code_snippet"',
        '"vulnerable_code"',
    ):
        assert pattern not in serialized, f"'{pattern}' found"
