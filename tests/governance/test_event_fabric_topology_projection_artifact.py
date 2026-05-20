from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

ARTIFACT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".build"
    / "rig-relay"
    / "derived"
    / "mission_topology_projection.v1.json"
)

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.relay.mission_topology_projection.v1.schema.json"
)


def _skip_if_no_artifact():
    if not ARTIFACT_PATH.exists():
        pytest.skip("No committed topology projection artifact to validate")


def test_committed_artifact_validates_against_schema():
    _skip_if_no_artifact()
    artifact = json.loads(ARTIFACT_PATH.read_text("utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    jsonschema.Draft7Validator(schema).validate(artifact)


def test_committed_artifact_has_content_light_true():
    _skip_if_no_artifact()
    artifact = json.loads(ARTIFACT_PATH.read_text("utf-8"))
    assert artifact["content_light"] is True


def test_committed_artifact_strand_states_total_nodes_matches_nodes_length():
    _skip_if_no_artifact()
    artifact = json.loads(ARTIFACT_PATH.read_text("utf-8"))
    assert artifact["strand_states"]["total_nodes"] == len(artifact["nodes"])


def test_committed_artifact_has_read_side_only_and_mutation_flags():
    _skip_if_no_artifact()
    artifact = json.loads(ARTIFACT_PATH.read_text("utf-8"))
    assert artifact["read_side_only"] is True
    assert artifact["mutation_authority"] is False
