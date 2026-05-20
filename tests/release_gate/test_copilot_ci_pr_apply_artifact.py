from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "copilot_ci_pr_apply_v1.v1.json"
)
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "rig.copilot_ci_pr_apply.v1.schema.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_copilot_ci_pr_apply_artifact_validates_against_schema():
    assert ARTIFACT_PATH.exists(), f"Artifact not found at {ARTIFACT_PATH}"
    assert SCHEMA_PATH.exists(), f"Schema not found at {SCHEMA_PATH}"

    artifact = _load_json(ARTIFACT_PATH)
    schema = _load_json(SCHEMA_PATH)

    jsonschema.Draft7Validator(schema).validate(artifact)


def test_copilot_ci_pr_apply_fields_are_correct():
    artifact = _load_json(ARTIFACT_PATH)

    assert artifact["schema_version"] == "rig.copilot_ci_pr_apply.v1"
    assert artifact["recommendation"] == "ready_for_user_commit"
    assert artifact["content_light"] is True
    assert artifact["redaction_status"] == "content_light"

    # Git flow constraints
    assert artifact["branch_checkout"] is False
    assert artifact["path_checkout_from_pr"] is True
    assert artifact["merge_performed"] is False
    assert artifact["push_performed"] is False
    assert artifact["working_tree_mutated_by_pr_files"] is True

    # Check applied files
    expected_files = [
        ".github/workflows/ci.yml",
        "docs/json/governance/github_ci_cd_reliability_v1.v1.json",
        "docs/schemas/rig.github_ci_cd_reliability.v1.schema.json",
        "tests/release_gate/test_github_ci_cd_reliability_artifact.py",
    ]
    assert sorted(artifact["applied_files"]) == sorted(expected_files)
