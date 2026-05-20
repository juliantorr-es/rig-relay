from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "pr_reconciliation_review_v1.v1.json"
)
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.pr_reconciliation_review.v1.schema.json"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_reconciliation_artifact_validates_against_schema():
    assert ARTIFACT_PATH.exists(), f"Artifact not found at {ARTIFACT_PATH}"
    assert SCHEMA_PATH.exists(), f"Schema not found at {SCHEMA_PATH}"

    artifact = _load_json(ARTIFACT_PATH)
    schema = _load_json(SCHEMA_PATH)

    jsonschema.Draft7Validator(schema).validate(artifact)


def test_reconciliation_fields_are_correct():
    artifact = _load_json(ARTIFACT_PATH)

    assert artifact["schema_version"] == "rig.pr_reconciliation_review.v1"
    assert artifact["recommendation"] == "approve_copilot_pr"
    assert artifact["content_light"] is True
    assert artifact["redaction_status"] == "content_light"
    assert isinstance(artifact["overlapping_files"], list)
    assert len(artifact["overlapping_files"]) == 0

    # Ensure git checkout and path mutation details are recorded
    assert artifact["branch_checkout"] is False
    assert artifact["path_checkout_from_pr"] is True
    assert artifact["merge_performed"] is False
    assert artifact["push_performed"] is False
    assert artifact["working_tree_mutated_by_pr_files"] is True
