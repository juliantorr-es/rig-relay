"""Tests for codebase evidence graph assessment — schema validation, content-light, recommendation."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSESSMENT_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "codebase_evidence_graph_assessment_v1.v1.json"
)
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.relay.codebase_evidence_graph_assessment.v1.schema.json"
)


def test_assessment_validates_against_schema():
    assert SCHEMA_PATH.exists()
    assert ASSESSMENT_PATH.exists()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assessment = json.loads(ASSESSMENT_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=assessment, schema=schema)


def test_assessment_has_all_required_sections():
    assessment = json.loads(ASSESSMENT_PATH.read_text(encoding="utf-8"))
    required = [
        "existing_substrates",
        "proposed_node_types",
        "proposed_edge_types",
        "deterministic_extractors_available_now",
        "content_light_policy",
        "privacy_and_security_risks",
        "minimal_implementation_plan",
        "explicit_non_goals",
        "recommendation",
    ]
    for r in required:
        assert r in assessment, f"Missing: {r}"
        val = assessment[r]
        if isinstance(val, list):
            assert len(val) > 0, f"Empty list: {r}"


def test_assessment_node_types_meaningful():
    assessment = json.loads(ASSESSMENT_PATH.read_text(encoding="utf-8"))
    node_types = [n["node_type"] for n in assessment["proposed_node_types"]]
    assert "file" in node_types
    assert "schema" in node_types
    assert "artifact" in node_types
    assert "receipt" in node_types
    assert len(node_types) >= 10


def test_assessment_edge_types_meaningful():
    assessment = json.loads(ASSESSMENT_PATH.read_text(encoding="utf-8"))
    edge_types = [e["edge_type"] for e in assessment["proposed_edge_types"]]
    assert "depends_on" in edge_types
    assert "tests" in edge_types
    assert "validates_artifact" in edge_types
    assert len(edge_types) >= 10


def test_assessment_recommends_promote():
    assessment = json.loads(ASSESSMENT_PATH.read_text(encoding="utf-8"))
    assert assessment["recommendation"] == "promote"


def test_assessment_no_forbidden_fields():
    s = ASSESSMENT_PATH.read_text(encoding="utf-8")
    for f in (
        '"access_token"',
        '"authorization"',
        '"private_key"',
        '"raw_source"',
        '"code_snippet"',
        '"secret_value"',
    ):
        assert f not in s, f


def test_assessment_constraints_no_new_deps():
    assessment = json.loads(ASSESSMENT_PATH.read_text(encoding="utf-8"))
    assert assessment["constraints"]["new_dependencies_allowed"] is False
    assert assessment["constraints"]["sqlite_allowed"] is False


def test_derived_csv_exists():
    csv_path = (
        REPO_ROOT
        / ".build"
        / "rig-relay"
        / "derived"
        / "codebase_evidence_graph_assessment_v1.csv"
    )
    assert csv_path.exists()
