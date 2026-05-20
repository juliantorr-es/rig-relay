"""Governance artifact test for distribution and release research artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact, pytest.mark.substrate]

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"
ARTIFACT_DIR = REPO_ROOT / "docs" / "json" / "governance"

SCHEMA_ARTIFACT_PAIRS = [
    (
        "rig.distribution.release_channel_matrix.v1.schema.json",
        "distribution_release_channel_matrix_v1.v1.json",
    ),
    (
        "rig.distribution.release_credential_matrix.v1.schema.json",
        "distribution_release_credential_matrix_v1.v1.json",
    ),
    (
        "rig.distribution.release_api_matrix.v1.schema.json",
        "distribution_release_api_matrix_v1.v1.json",
    ),
    (
        "rig.distribution.release_validation_matrix.v1.schema.json",
        "distribution_release_validation_matrix_v1.v1.json",
    ),
    (
        "rig.distribution.release_mutation_lane_matrix.v1.schema.json",
        "distribution_release_mutation_lane_matrix_v1.v1.json",
    ),
    (
        "rig.distribution.release_risk_register.v1.schema.json",
        "distribution_release_risk_register_v1.v1.json",
    ),
    (
        "rig.distribution.release_roadmap.v1.schema.json",
        "distribution_release_roadmap_v1.v1.json",
    ),
    (
        "rig.distribution.release_research.v1.schema.json",
        "distribution_release_research_v1.v1.json",
    ),
]


@pytest.mark.parametrize("schema_file,artifact_file", SCHEMA_ARTIFACT_PAIRS)
def test_artifact_validates_against_schema(schema_file, artifact_file):
    schema_path = SCHEMA_DIR / schema_file
    artifact_path = ARTIFACT_DIR / artifact_file
    assert schema_path.exists(), f"Schema missing: {schema_file}"
    assert artifact_path.exists(), f"Artifact missing: {artifact_file}"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=artifact, schema=schema)


def test_channel_matrix_covers_major_channels():
    channel_matrix = json.loads(
        (ARTIFACT_DIR / "distribution_release_channel_matrix_v1.v1.json").read_text(
            encoding="utf-8"
        )
    )
    channels = channel_matrix["channels"]
    families = {c.get("channel_family", "") for c in channels}
    required = {
        "apple_app_store",
        "google_play_production",
        "microsoft_store",
        "github_releases",
        "github_pages",
        "npm_registry",
        "pypi",
        "crates_io",
        "homebrew_formula",
    }
    for r in required:
        assert r in families, f"Missing channel family: {r}"
    assert channel_matrix["channel_count"] >= 25


def test_credential_matrix_includes_signing_and_tokens():
    cm = json.loads(
        (ARTIFACT_DIR / "distribution_release_credential_matrix_v1.v1.json").read_text(
            encoding="utf-8"
        )
    )
    creds = {c["credential_id"] for c in cm["credentials"]}
    required = {
        "dist-cred:apple_connect_api_key",
        "dist-cred:apple_dev_cert",
        "dist-cred:google_service_account",
        "dist-cred:npm_token",
        "dist-cred:pypi_token",
        "dist-cred:crates_token",
    }
    for r in required:
        assert r in creds, f"Missing credential: {r}"
    # Check OIDC entries exist
    assert any("oidc" in c["credential_id"].lower() for c in cm["credentials"])
    assert cm["credential_count"] >= 20


def test_api_matrix_includes_official_apis():
    am = json.loads(
        (ARTIFACT_DIR / "distribution_release_api_matrix_v1.v1.json").read_text(
            encoding="utf-8"
        )
    )
    surfaces = {a["surface_id"] for a in am["apis"]}
    required = {
        "dist-api:app_store_connect",
        "dist-api:google_play",
        "dist-api:gh_releases",
        "dist-api:npm_publish",
        "dist-api:twine",
        "dist-api:cargo_publish",
    }
    for r in required:
        assert r in surfaces, f"Missing API: {r}"
    assert am["api_count"] >= 10


def test_validation_matrix_blocks_publishing_errors():
    vm = json.loads(
        (ARTIFACT_DIR / "distribution_release_validation_matrix_v1.v1.json").read_text(
            encoding="utf-8"
        )
    )
    vals = {v["validation_id"] for v in vm["validations"]}
    required = {
        "dist-valid:code_signing",
        "dist-valid:provenance_check",
        "dist-valid:semver_check",
        "dist-valid:secret_scan",
    }
    for r in required:
        assert r in vals, f"Missing validation: {r}"
    blocking = [v for v in vm["validations"] if v.get("can_block_publish")]
    assert len(blocking) >= 5
    assert vm["validation_count"] >= 20


def test_mutation_lane_matrix_defaults_safe():
    mm = json.loads(
        (
            ARTIFACT_DIR / "distribution_release_mutation_lane_matrix_v1.v1.json"
        ).read_text(encoding="utf-8")
    )
    assert mm["remote_mutation_performed"] is False
    for lane in mm["mutation_lanes"]:
        assert lane["recommended_initial_state"] in (
            "approval_required",
            "automatic_under_policy",
            "disabled",
        )
        if lane["remote_mutation"] is True:
            assert lane["recommended_initial_state"] != "automatic_under_policy"


def test_risk_register_covers_credential_and_mutation_risks():
    rr = json.loads(
        (ARTIFACT_DIR / "distribution_release_risk_register_v1.v1.json").read_text(
            encoding="utf-8"
        )
    )
    risk_ids = {r["risk_id"] for r in rr["risks"]}
    assert "dist-risk:credential_leakage" in risk_ids
    assert "dist-risk:irreversible_publish" in risk_ids
    assert "dist-risk:supply_chain_attestation_gap" in risk_ids
    criticals = [r for r in rr["risks"] if r.get("severity") == "critical"]
    assert len(criticals) >= 3
    assert rr["risk_count"] >= 10


def test_roadmap_starts_with_research_and_defers_real_mutation():
    rm = json.loads(
        (ARTIFACT_DIR / "distribution_release_roadmap_v1.v1.json").read_text(
            encoding="utf-8"
        )
    )
    phases = {p["phase_id"] for p in rm["phases"]}
    assert "dist-roadmap:phase_0_research" in phases
    assert "dist-roadmap:phase_1_operating_picture" in phases
    assert "dist-roadmap:phase_11_chief_of_staff" in phases
    # Phase 0 and 1 must have mutation_policy: none
    early = [
        p
        for p in rm["phases"]
        if p["phase_id"]
        in ("dist-roadmap:phase_0_research", "dist-roadmap:phase_1_operating_picture")
    ]
    for p in early:
        assert p["mutation_policy"] == "none"


def test_all_artifacts_content_light_and_no_remote_mutation():
    for _, artifact_file in SCHEMA_ARTIFACT_PAIRS:
        artifact = json.loads(
            (ARTIFACT_DIR / artifact_file).read_text(encoding="utf-8")
        )
        assert artifact.get("content_light") is True, (
            f"{artifact_file}: content_light not True"
        )
        assert artifact.get("remote_mutation") is False, (
            f"{artifact_file}: remote_mutation not False"
        )


def test_research_top_level_includes_metadata_and_concepts():
    research = json.loads(
        (ARTIFACT_DIR / "distribution_release_research_v1.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert "metadata_matrix" in research
    assert "artifact_concepts" in research
    assert len(research["metadata_matrix"]) >= 4
    assert len(research["artifact_concepts"]) >= 5
