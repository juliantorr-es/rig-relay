from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "two_pr_verification_review_v1.v1.json"
)
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.two_pr_verification_review.v1.schema.json"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_two_pr_verification_review_artifact_validates_against_schema():
    artifact = _load_json(ARTIFACT_PATH)
    schema = _load_json(SCHEMA_PATH)
    jsonschema.Draft7Validator(schema).validate(artifact)


def test_artifact_details_are_consistent():
    artifact = _load_json(ARTIFACT_PATH)
    assert artifact["schema_version"] == "rig.two_pr_verification_review.v1"
    assert artifact["base_branch"] == "main"
    assert artifact["current_branch"] == "main"
    assert artifact["dirty_state_before"] is True
    assert artifact["content_light"] is True
    assert artifact["redaction_status"] == "content_light"

    assert len(artifact["pr_reviews"]) == 2

    # Check PR A
    pr_a = artifact["pr_reviews"][0]
    assert pr_a["pr_label"] == "PR A: Copilot CI/CD Reliability PR"
    assert pr_a["branch"] == "origin/copilot/fix-ci-workflow-validation"
    assert pr_a["head_sha"] == "be255183b0692c74b6e6123306fb85fb113cb35c"
    assert "ci.yml" in "".join(pr_a["workflow_files_changed"])
    assert pr_a["policy_checks"]["permissions_minimal"] is True
    assert pr_a["policy_checks"]["no_write_all"] is True
    assert pr_a["policy_checks"]["no_pull_request_target"] is True
    assert pr_a["policy_checks"]["live_auth_disabled_by_default"] is True
    assert pr_a["policy_checks"]["no_sensitive_caching"] is True
    assert pr_a["policy_checks"]["reproduction_commands_in_summary"] is True

    # Check PR B
    pr_b = artifact["pr_reviews"][1]
    assert pr_b["pr_label"] == "PR B: Swift CodeQL Parking PR"
    assert pr_b["branch"] == "origin/copilot/fix-codeql-swift-trigger"
    assert pr_b["head_sha"] == "85a6a27d4891e657829a74c60e35cd20095321a7"
    assert "codeql" in "".join(pr_b["workflow_files_changed"])
    assert pr_b["policy_checks"]["permissions_minimal"] is True
    assert pr_b["policy_checks"]["no_write_all"] is True
    assert pr_b["policy_checks"]["no_pull_request_target"] is True
    assert pr_b["policy_checks"]["live_auth_disabled_by_default"] is True
    assert pr_b["policy_checks"]["no_sensitive_caching"] is True
    assert pr_b["policy_checks"]["reproduction_commands_in_summary"] is True

    # Check overlaps and recommendation
    assert any(
        "github_ci_cd_reliability_v1.v1.json" in path
        for path in artifact["overlapping_files"]
    )
    assert any(
        "test_github_ci_cd_reliability_artifact.py" in path
        for path in artifact["overlapping_files"]
    )
    assert "PR B" in artifact["merge_order_recommendation"]
