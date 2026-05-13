from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft7Validator, validate
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


def get_schemas():
    return list(SCHEMA_DIR.glob("*.schema.json"))


@pytest.mark.parametrize("schema_path", get_schemas())
def test_schema_is_valid_json_and_draft7(schema_path: Path):
    """Ensure every schema is valid JSON and follows Draft 7 conventions."""
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    # Assert top-level fields
    assert "$schema" in schema
    assert "$id" in schema
    assert "title" in schema
    assert "type" in schema

    # Validate the schema itself against the meta-schema
    Draft7Validator.check_schema(schema)


def test_envelope_schema_validates_minimal_example():
    """Ensure the envelope schema validates a minimal valid example."""
    schema_path = SCHEMA_DIR / "rig.relay.artifact.envelope.v1.schema.json"
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    instance = {
        "schema_version": "rig.relay.artifact.envelope.v1",
        "artifact_kind": "tool_result",
        "session_id": "00000000-0000-0000-0000-000000000000",
        "created_at": "2024-01-01T00:00:00Z",
        "payload_sha256": "sha256:" + "a" * 64,
        "artifact_record_sha256": "sha256:" + "b" * 64,
        "payload": {},
    }

    validate(instance=instance, schema=schema)


def test_tool_call_schema_validates_minimal_example():
    schema_path = SCHEMA_DIR / "rig.relay.artifact.tool_call.v1.schema.json"
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    instance = {
        "tool_name": "read_file",
        "tool_call_id": "call_123",
        "normalized_input": {"path": "README.md"},
        "input_sha256": "sha256:" + "c" * 64,
    }

    validate(instance=instance, schema=schema)


def test_schema_id_matches_filename():
    """Ensure the $id field in the schema matches its filename."""
    for schema_path in get_schemas():
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)

        expected_id_suffix = schema_path.name
        assert schema["$id"].endswith(expected_id_suffix)


def test_schema_version_matches_filename():
    """Ensure the schema_version (if constant) matches the filename parts."""
    for schema_path in get_schemas():
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)

        # This only applies to schemas that have a const schema_version
        props = schema.get("properties", {})
        if "schema_version" in props and "const" in props["schema_version"]:
            const_version = props["schema_version"]["const"]
            # e.g. rig.relay.artifact.envelope.v1
            # filename: rig.relay.artifact.envelope.v1.schema.json
            assert const_version in schema_path.name
