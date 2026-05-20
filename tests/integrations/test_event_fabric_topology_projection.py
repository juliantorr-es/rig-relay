from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.events.topology_projection import build_mission_topology_projection

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.real_artifact]

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.relay.mission_topology_projection.v1.schema.json"
)

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

REQUIRED_NODE_FIELDS = ["node_id", "node_type", "label", "strand_state"]
REQUIRED_EDGE_FIELDS = ["edge_id", "from_node_id", "to_node_id", "edge_type"]

NODE_BLUEPRINT_COUNT = 16

STRAND_STATE_KEYS = [
    "total_nodes",
    "healthy_count",
    "idle_count",
    "active_count",
    "stale_count",
    "degraded_count",
    "blocked_count",
    "quarantined_count",
    "backpressured_count",
    "waiting_for_permission_count",
    "no_input_count",
    "unknown_count",
]

PRESSURE_KEYS = [
    "reconnect_pressure",
    "reconnect_failed_count",
    "queue_pressure",
    "queue_pressure_high_count",
    "consumer_errors",
    "consumer_error_count",
    "bridge_health",
    "github_rate_limit_health",
]


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text("utf-8"))


def _validate_topology(topology: dict) -> None:
    schema = _load_schema()
    jsonschema.Draft7Validator(schema).validate(topology)


def test_empty_topology_with_nonexistent_duckdb_report(tmp_path: Path):
    topology = build_mission_topology_projection(
        duckdb_report_path=tmp_path / "nonexistent.json"
    )
    assert topology["status"] == "empty"
    assert len(topology["nodes"]) == 3
    assert topology["strand_states"]["total_nodes"] == 3
    assert topology["strand_states"]["no_input_count"] == 3


def test_empty_topology_validates_against_schema(tmp_path: Path):
    topology = build_mission_topology_projection(
        duckdb_report_path=tmp_path / "nonexistent.json"
    )
    _validate_topology(topology)


def test_degraded_no_input_topology_validates_against_schema():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    _validate_topology(topology)


def test_nodes_has_all_blueprint_types():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    assert len(topology["nodes"]) == NODE_BLUEPRINT_COUNT
    node_ids = {n["node_id"] for n in topology["nodes"]}
    expected_ids = {
        "event_fabric",
        "duckdb_projection",
        "derived_artifact",
        "bridge",
        "projection",
        "runtime",
        "worker",
        "supervisor",
        "tool",
        "github",
        "test",
        "release_gate",
        "telemetry",
        "redaction",
        "coordination",
        "resource",
    }
    assert node_ids == expected_ids


def test_every_node_has_required_fields():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    for node in topology["nodes"]:
        for field in REQUIRED_NODE_FIELDS:
            assert field in node, f"node {node.get('node_id')} missing {field}"


def test_edges_has_at_least_10_edges():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    assert len(topology["edges"]) >= 10


def test_every_edge_has_required_fields():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    for edge in topology["edges"]:
        for field in REQUIRED_EDGE_FIELDS:
            assert field in edge, f"edge {edge.get('edge_id')} missing {field}"


def test_strand_states_has_all_required_count_fields():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    ss = topology["strand_states"]
    for key in STRAND_STATE_KEYS:
        assert key in ss, f"missing strand_state key: {key}"
    assert ss["total_nodes"] == len(topology["nodes"])


def test_resource_pressure_has_all_required_fields():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    rp = topology["resource_pressure"]
    for key in PRESSURE_KEYS:
        assert key in rp, f"missing pressure key: {key}"
    assert rp["reconnect_pressure"] in {"none", "moderate", "high"}
    assert rp["queue_pressure"] in {"none", "normal", "high"}
    assert rp["consumer_errors"] in {"none", "low", "elevated", "high"}


def test_source_artifacts_has_at_least_2_entries():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    assert len(topology["source_artifacts"]) >= 2


def test_read_side_only_is_true():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    assert topology["read_side_only"] is True


def test_mutation_authority_is_false():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    assert topology["mutation_authority"] is False


def test_redaction_summary_raw_event_payloads_exposed_is_false():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    assert topology["redaction_summary"]["raw_event_payloads_exposed"] is False


def test_degraded_reasons_is_list_of_strings():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    reasons = topology["degraded_reasons"]
    assert isinstance(reasons, list)
    for reason in reasons:
        assert isinstance(reason, str)


def test_missing_duckdb_report_does_not_crash(tmp_path: Path):
    topology = build_mission_topology_projection(
        duckdb_report_path=tmp_path / "definitely_does_not_exist.json"
    )
    assert topology["status"] == "empty"
    assert "nodes" in topology
    assert "edges" in topology


def test_content_light_is_true():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    assert topology["content_light"] is True


def test_schema_version_is_constant():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    assert topology["schema_version"] == "rig.relay.mission_topology_projection.v1"


def test_empty_topology_has_read_side_and_mutation_flags(tmp_path: Path):
    topology = build_mission_topology_projection(
        duckdb_report_path=tmp_path / "nonexistent.json"
    )
    assert topology["read_side_only"] is True
    assert topology["mutation_authority"] is False


def test_degraded_no_input_has_matching_node_count_and_strand_count():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("DuckDB report not found")
    topology = build_mission_topology_projection(
        duckdb_report_path=DUCKDB_REPORT_PATH,
        pressure_summary_path=PRESSURE_SUMMARY_PATH,
    )
    assert topology["strand_states"]["total_nodes"] == len(topology["nodes"])
    assert topology["strand_states"]["total_nodes"] == (
        topology["strand_states"]["no_input_count"]
        + topology["strand_states"]["active_count"]
        + topology["strand_states"]["idle_count"]
        + topology["strand_states"]["stale_count"]
        + topology["strand_states"]["degraded_count"]
        + topology["strand_states"]["blocked_count"]
        + topology["strand_states"]["quarantined_count"]
        + topology["strand_states"]["backpressured_count"]
        + topology["strand_states"]["waiting_for_permission_count"]
        + topology["strand_states"]["unknown_count"]
    )
