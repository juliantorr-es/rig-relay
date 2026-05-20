from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.desktop.projection import build_projection

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DESKTOP_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.relay.desktop_projection.v1.schema.json"
)
PATCH_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.relay.backend_projection_patch.v1.schema.json"
)
WIDGETS_JS_PATH = REPO_ROOT / "frontend" / "desktop" / "js" / "widgets.js"
MAIN_JS_PATH = REPO_ROOT / "frontend" / "desktop" / "js" / "main.js"
STATE_JS_PATH = REPO_ROOT / "frontend" / "desktop" / "js" / "state.js"


def _read_schema(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def test_desktop_projection_schema_requires_spiderweb_topology():
    schema = _read_schema(DESKTOP_SCHEMA_PATH)
    required = schema["required"]
    assert "spiderweb_topology" in required


def test_backend_patch_schema_has_spiderweb_topology_in_changed_sections():
    schema = _read_schema(PATCH_SCHEMA_PATH)
    enum_values = schema["properties"]["changed_sections"]["items"]["enum"]
    assert "spiderweb_topology" in enum_values


def test_desktop_projection_schema_validates_projection_output():
    proj = build_projection()
    schema = _read_schema(DESKTOP_SCHEMA_PATH)
    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(proj))
    spiderweb_errors = [
        e for e in errors if "spiderweb" in str(e.path) or "spiderweb" in e.message
    ]
    assert len(spiderweb_errors) == 0, (
        f"spiderweb_topology schema violations: {spiderweb_errors}"
    )
    if errors:
        expected_pre_existing = [
            e for e in errors if "profile_readme_lane" in e.message
        ]
        assert len(expected_pre_existing) == len(errors), (
            f"Unexpected non-profile_readme_lane errors: {errors}"
        )


def test_widgets_js_contains_register_widget_spiderweb_topology():
    js = WIDGETS_JS_PATH.read_text("utf-8")
    assert "registerWidget('spiderwebTopology'" in js


def test_main_js_operator_assignment_includes_spiderweb_topology():
    js = MAIN_JS_PATH.read_text("utf-8")
    assert "spiderwebTopology" in js
    # Verify it's in the operator mode array
    operator_section = js.split("operator: [")[1].split("],")[0]
    assert "spiderwebTopology" in operator_section


def test_state_js_has_spiderweb_topology_disclosure_default():
    js = STATE_JS_PATH.read_text("utf-8")
    assert "spiderwebTopology:" in js
    assert "'standard'" in js  # or "standard" somewhere nearby
    lines = js.splitlines()
    found = False
    for line in lines:
        if "spiderwebTopology" in line and "standard" in line:
            found = True
            break
    assert found, "spiderwebTopology disclosure default not 'standard' in state.js"
