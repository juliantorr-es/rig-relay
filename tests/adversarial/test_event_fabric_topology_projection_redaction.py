from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.events.topology_projection import build_mission_topology_projection

pytestmark = [pytest.mark.adversarial]

GITHUB_TOKEN_PATTERNS = ("ghp_", "gho_", "ghu_", "ghs_", "github_pat_")

DUCKDB_REPORT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "json"
    / "governance"
    / "event_fabric_duckdb_projection_report_v1.v1.json"
)

PRESSURE_SUMMARY_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".build"
    / "rig-relay"
    / "derived"
    / "event_fabric_resource_pressure_summary.v1.json"
)


def test_topology_has_no_token_like_strings(tmp_path: Path):
    topology = build_mission_topology_projection(
        duckdb_report_path=tmp_path / "nonexistent.json"
    )
    serialized = json.dumps(topology)
    for pattern in GITHUB_TOKEN_PATTERNS:
        assert pattern not in serialized, f"found token pattern: {pattern}"


def test_topology_has_no_token_like_strings_with_real_report():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    serialized = json.dumps(topology)
    for pattern in GITHUB_TOKEN_PATTERNS:
        assert pattern not in serialized, f"found token pattern: {pattern}"


def test_topology_redaction_summary_envelope_level_only():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    assert topology["redaction_summary"]["envelope_level_only"] is True


def test_topology_redaction_summary_raw_event_payloads_exposed_false():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    assert topology["redaction_summary"]["raw_event_payloads_exposed"] is False


def test_topology_nodes_have_safe_details_no_raw_event_data():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    for node in topology["nodes"]:
        details = node.get("details", "")
        assert isinstance(details, str)
        assert len(details) < 200, f"node {node['node_id']} details too long"
        assert "access_token" not in details
        assert "api_key" not in details


def test_topology_edges_have_no_raw_event_payload_references():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    for edge in topology["edges"]:
        label = edge.get("label", "")
        assert isinstance(label, str)
        assert "payload" not in label.lower()
