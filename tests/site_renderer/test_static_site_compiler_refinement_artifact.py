from __future__ import annotations

import json
from pathlib import Path

from rig_relay.site_renderer.loaders import validate_json_schema

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_refinement_schema_is_valid_json_schema():
    schema_path = (
        REPO_ROOT
        / "docs"
        / "schemas"
        / "rig.static_site.compiler_refinement.v1.schema.json"
    )
    assert schema_path.is_file()
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["title"] == "Rig Static Site Compiler Refinement v1"


def test_refinement_artifact_validates_against_schema():
    artifact_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "site"
        / "static_site_compiler_refinement_v0.v1.json"
    )
    assert artifact_path.is_file()
    data = json.loads(artifact_path.read_text(encoding="utf-8"))

    # Validate using the loaders validate_json_schema function
    is_valid, err = validate_json_schema(
        data, "rig.static_site.compiler_refinement.v1", REPO_ROOT
    )
    assert is_valid, f"Refinement validation failed: {err}"
