from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.desktop.projection import PATCH_SECTION_NAMES, build_projection
from rig_relay.desktop.projection_widgets import (
    ALL_WIDGETS,
    OPERATE_WIDGETS,
    PROJECTION_FIELD_TO_WIDGET,
    SPIDERWEB_TOPOLOGY,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.relay.desktop_projection.v1.schema.json"
)
TOPO_PATH = (
    REPO_ROOT
    / ".build"
    / "rig-relay"
    / "derived"
    / "mission_topology_projection.v1.json"
)

GITHUB_TOKEN_PATTERNS = ("ghp_", "gho_", "ghu_", "ghs_", "github_pat_")


def _spiderweb_section() -> dict:
    proj = build_projection()
    return proj["spiderweb_topology"]


def test_build_projection_includes_spiderweb_topology_section():
    proj = build_projection()
    assert "spiderweb_topology" in proj
    section = proj["spiderweb_topology"]
    assert section["available"] is True
    assert section["status"] == "live"


def test_spiderweb_topology_has_node_count_16():
    section = _spiderweb_section()
    assert section["node_count"] == 16


def test_spiderweb_topology_has_edge_count_10():
    section = _spiderweb_section()
    assert section["edge_count"] == 10


def test_spiderweb_topology_has_active_strand_count_4():
    section = _spiderweb_section()
    assert section["active_strand_count"] == 4


def test_spiderweb_topology_has_strand_state_summary():
    section = _spiderweb_section()
    sss = section["strand_state_summary"]
    for key in ("active_count", "idle_count", "no_input_count"):
        assert key in sss, f"missing strand_state_summary key: {key}"
    assert sss["active_count"] == 4
    assert isinstance(sss["idle_count"], int)
    assert isinstance(sss["no_input_count"], int)


def test_spiderweb_topology_has_resource_pressure_summary():
    section = _spiderweb_section()
    rps = section["resource_pressure_summary"]
    for key in ("reconnect_pressure", "queue_pressure", "consumer_errors"):
        assert key in rps, f"missing resource_pressure_summary key: {key}"
    assert rps["reconnect_pressure"] is not None
    assert rps["queue_pressure"] is not None
    assert rps["consumer_errors"] is not None


def test_spiderweb_topology_has_causal_summary():
    section = _spiderweb_section()
    cs = section["causal_summary"]
    for key in ("observed_links", "correlated_only_links"):
        assert key in cs, f"missing causal_summary key: {key}"
    assert isinstance(cs["observed_links"], int)
    assert isinstance(cs["correlated_only_links"], int)


def test_spiderweb_topology_has_degraded_reasons_list():
    section = _spiderweb_section()
    assert isinstance(section["degraded_reasons"], list)
    for reason in section["degraded_reasons"]:
        assert isinstance(reason, str)


def test_spiderweb_topology_has_source_artifact_hashes_dict():
    section = _spiderweb_section()
    assert isinstance(section["source_artifact_hashes"], dict)


def test_spiderweb_topology_has_raw_payloads_exposed_false():
    section = _spiderweb_section()
    assert section["raw_payloads_exposed"] is False


def test_source_status_includes_spiderweb_topology():
    proj = build_projection()
    assert proj["source_status"]["spiderweb_topology"] is True


def test_build_projection_dict_validates_against_desktop_schema():
    proj = build_projection()
    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
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


def test_spiderweb_topology_widget_in_all_widgets():
    assert SPIDERWEB_TOPOLOGY in ALL_WIDGETS


def test_spiderweb_topology_widget_in_operate_widgets():
    assert SPIDERWEB_TOPOLOGY in OPERATE_WIDGETS


def test_projection_field_to_widget_maps_spiderweb_topology():
    assert PROJECTION_FIELD_TO_WIDGET["spiderweb_topology"] == SPIDERWEB_TOPOLOGY


def test_patch_section_names_includes_spiderweb_topology():
    assert "spiderweb_topology" in PATCH_SECTION_NAMES
