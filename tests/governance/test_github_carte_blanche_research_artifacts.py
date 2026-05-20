"""Governance artifact tests for GitHub carte blanche research."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"
ARTIFACT_DIR = REPO_ROOT / "docs" / "json" / "governance"

ARTIFACT_SCHEMA_PAIRS = [
    (
        "github_carte_blanche_research_v1.v1.json",
        "rig.github.carte_blanche_research.v1.schema.json",
    ),
    (
        "github_carte_blanche_permission_value_matrix_v1.v1.json",
        "rig.github.carte_blanche_permission_value_matrix.v1.schema.json",
    ),
    (
        "github_carte_blanche_surface_lane_matrix_v1.v1.json",
        "rig.github.carte_blanche_surface_lane_matrix.v1.schema.json",
    ),
    (
        "github_carte_blanche_endpoint_matrix_v1.v1.json",
        "rig.github.carte_blanche_endpoint_matrix.v1.schema.json",
    ),
    (
        "github_carte_blanche_webhook_matrix_v1.v1.json",
        "rig.github.carte_blanche_webhook_matrix.v1.schema.json",
    ),
    (
        "github_carte_blanche_mutation_lanes_v1.v1.json",
        "rig.github.carte_blanche_mutation_lanes.v1.schema.json",
    ),
    (
        "github_carte_blanche_risk_register_v1.v1.json",
        "rig.github.carte_blanche_risk_register.v1.schema.json",
    ),
    (
        "github_carte_blanche_product_roadmap_v1.v1.json",
        "rig.github.carte_blanche_product_roadmap.v1.schema.json",
    ),
]


@pytest.mark.parametrize("artifact_file,schema_file", ARTIFACT_SCHEMA_PAIRS)
def test_artifact_validates_against_schema(artifact_file, schema_file):
    schema_path = SCHEMA_DIR / schema_file
    artifact_path = ARTIFACT_DIR / artifact_file
    assert schema_path.exists(), f"Schema missing: {schema_path}"
    if not artifact_path.exists():
        pytest.skip(f"Artifact not yet generated: {artifact_path}")

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_all_schemas_exist():
    for _, schema_file in ARTIFACT_SCHEMA_PAIRS:
        assert (SCHEMA_DIR / schema_file).exists(), f"Schema missing: {schema_file}"


def test_main_research_artifact_has_all_sections():
    artifact_path = ARTIFACT_DIR / "github_carte_blanche_research_v1.v1.json"
    if not artifact_path.exists():
        pytest.skip("Research artifact not yet generated")
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["permission_count"] >= 15
    assert report["surface_lane_count"] >= 20
    assert report["mutation_lane_count"] >= 10
    assert report["webhook_event_count"] >= 12
    assert report["platform_limit_count"] >= 10
    assert report["roadmap_phase_count"] >= 8


def test_permission_matrix_has_all_required_fields():
    artifact_path = (
        ARTIFACT_DIR / "github_carte_blanche_permission_value_matrix_v1.v1.json"
    )
    if not artifact_path.exists():
        pytest.skip("Permission matrix not yet generated")
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    for perm in report["permissions"]:
        assert "permission_id" in perm
        assert "permission_name" in perm
        assert "maximum_product_value" in perm


def test_mutation_lanes_have_governance():
    artifact_path = ARTIFACT_DIR / "github_carte_blanche_mutation_lanes_v1.v1.json"
    if not artifact_path.exists():
        pytest.skip("Mutation lanes not yet generated")
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    for m in report["mutations"]:
        assert "recommended_initial_state" in m
        assert m["recommended_initial_state"] in (
            "disabled",
            "dry_run",
            "approval_required",
            "automatic_under_policy",
        )


def test_roadmap_starts_with_public_surface():
    artifact_path = ARTIFACT_DIR / "github_carte_blanche_product_roadmap_v1.v1.json"
    if not artifact_path.exists():
        pytest.skip("Roadmap not yet generated")
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    phases = report["phases"]
    assert any(p["phase_id"] == "phase_0" for p in phases)
    assert any(p["phase_id"] == "phase_1" for p in phases)
    assert any(p["phase_id"] == "phase_8" for p in phases)


def test_no_redaction_forbidden_fields_in_any_artifact():
    forbidden = [
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "ghr_",
        "github_pat_",
        "ya29.",
        "1//",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"refresh_token"',
        '"token_prefix"',
        '"authorization"',
        '"client_secret"',
        '"private_key"',
        '"raw_response"',
        '"raw_body"',
        '"patch"',
        '"diff"',
        '"code_snippet"',
    ]
    for artifact_file, _ in ARTIFACT_SCHEMA_PAIRS:
        artifact_path = ARTIFACT_DIR / artifact_file
        if not artifact_path.exists():
            continue
        serialized = artifact_path.read_text(encoding="utf-8")
        for f in forbidden:
            assert f not in serialized, f"'{f}' found in {artifact_file}"


def test_risk_register_records_platform_limits():
    artifact_path = ARTIFACT_DIR / "github_carte_blanche_risk_register_v1.v1.json"
    if not artifact_path.exists():
        pytest.skip("Risk register not yet generated")
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    limit_types = {l["limitation_type"] for l in report["limits"]}
    assert "API_unavailable" in limit_types or "app_not_supported" in limit_types
    assert "requires_user_oauth" in limit_types
