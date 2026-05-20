from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "swift_codeql_advisory_parking_v1.v1.json"
)
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.swift_codeql_advisory_parking.v1.schema.json"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_swift_codeql_advisory_parking_artifact_validates_against_schema():
    assert ARTIFACT_PATH.exists(), f"Artifact not found at {ARTIFACT_PATH}"
    assert SCHEMA_PATH.exists(), f"Schema not found at {SCHEMA_PATH}"

    artifact = _load_json(ARTIFACT_PATH)
    schema = _load_json(SCHEMA_PATH)

    jsonschema.Draft7Validator(schema).validate(artifact)


def test_swift_codeql_advisory_parking_fields_are_correct():
    artifact = _load_json(ARTIFACT_PATH)

    assert artifact["schema_version"] == "rig.swift_codeql_advisory_parking.v1"
    assert artifact["recommendation"] == "parked_advisory"
    assert artifact["observed_duration_seconds"] == 533
    assert artifact["default_ci_required"] is False
    assert artifact["content_light"] is True
    assert artifact["redaction_status"] == "content_light"
