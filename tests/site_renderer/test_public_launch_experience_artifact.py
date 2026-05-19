from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest

from rig_relay.site_renderer.loaders import validate_json_schema

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    """Fixture to isolate environment inputs and outputs using tmp_path."""
    for key in list(sys.modules.keys()):
        if "rig_site_render" in key:
            del sys.modules[key]

    shutil.copytree(REPO_ROOT / "docs", tmp_path / "docs")

    input_dir = tmp_path / "docs" / "json" / "site"
    manifest_path = input_dir / "input_manifest.v1.json"
    output_dir = tmp_path / "outputs"

    monkeypatch.setenv("RIG_SITE_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("RIG_SITE_INPUT_DIR", str(input_dir))
    monkeypatch.setenv("RIG_SITE_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("RIG_SITE_OUTPUT_DIR", str(output_dir))

    return {
        "input_dir": input_dir,
        "manifest_path": manifest_path,
        "output_dir": output_dir,
    }


@pytest.mark.contract
def test_public_launch_experience_schema_and_artifact_validation():
    schema_path = (
        REPO_ROOT
        / "docs"
        / "schemas"
        / "rig.static_site.public_launch_experience.v1.schema.json"
    )
    artifact_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "site"
        / "static_site_public_launch_experience_v1.v1.json"
    )

    # 1. Schema exists and is valid JSON
    assert schema_path.is_file()
    with open(schema_path, encoding="utf-8") as f:
        schema_data = json.load(f)
    assert schema_data.get("$id") == "rig.static_site.public_launch_experience.v1"

    # 2. Artifact exists and validates against schema
    assert artifact_path.is_file()
    with open(artifact_path, encoding="utf-8") as f:
        artifact_data = json.load(f)

    # Validate using the project's validate_json_schema helper
    is_valid, err = validate_json_schema(
        artifact_data, "rig.static_site.public_launch_experience.v1", REPO_ROOT
    )
    assert is_valid, f"Artifact failed validation: {err}"

    # 3. All required fields present in artifact (check schema's required list)
    required_fields = schema_data.get("required", [])
    for field in required_fields:
        assert field in artifact_data, f"Required field '{field}' missing from artifact"

    # 4. claims_supported entries are bounded and artifact-backed
    claims_supported = artifact_data.get("claims_supported", [])
    assert len(claims_supported) > 0
    for claim in claims_supported:
        assert isinstance(claim, str)
        assert len(claim) > 5

    # 5. claims_rejected entries explicitly listed
    claims_rejected = artifact_data.get("claims_rejected", [])
    assert len(claims_rejected) > 0
    for claim in claims_rejected:
        assert isinstance(claim, str)

    # 6. remaining_seams is non-empty (honest disclosure of boundaries/limitations)
    remaining_seams = artifact_data.get("remaining_seams", [])
    assert len(remaining_seams) > 0
    for seam in remaining_seams:
        assert isinstance(seam, str)
