from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.events.duckdb_projection import build_event_fabric_duckdb_projection
from rig_relay.events.seed_bridge_lifecycle import build_seed_events
from rig_relay.events.topology_projection import build_mission_topology_projection

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

ENVELOPE_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.event.envelope.v1.schema.json"
)

MANIFEST_PATH = (
    REPO_ROOT
    / ".build"
    / "rig-relay"
    / "static"
    / "mission_topology_spiderweb_manifest.v1.json"
)

HTML_PATH = (
    REPO_ROOT / ".build" / "rig-relay" / "static" / "mission_topology_spiderweb.v1.html"
)

TOKEN_PATTERNS = (
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "github_pat_",
    "authorization",
    "access_token",
)

MANIFEST_REQUIRED_KEYS = (
    "schema_version",
    "generated_at",
    "html_path",
    "html_sha256",
    "node_count",
    "edge_count",
    "remote_assets",
    "raw_payloads_exposed",
    "redaction_status",
    "status",
)


def _temp_seed(tmp_path: Path) -> Path:
    seed_path = tmp_path / "seeded.jsonl"
    build_seed_events(seed_output_path=seed_path)
    return seed_path


def _read_jsonl(path: Path) -> list[dict]:
    events: list[dict] = []
    for line in path.read_text("utf-8").strip().splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestSeedGenerator:
    def test_seed_writes_deterministic_25_events(self, tmp_path: Path):
        seed_path = _temp_seed(tmp_path)
        events = _read_jsonl(seed_path)
        assert len(events) == 25
        summary = build_seed_events()
        assert summary["event_count"] == 25
        assert summary["correlation_id"] == "corr_seeded_mission_001"

    def test_each_seeded_event_validates_against_envelope_schema(self, tmp_path: Path):
        seed_path = _temp_seed(tmp_path)
        events = _read_jsonl(seed_path)
        schema = json.loads(ENVELOPE_SCHEMA_PATH.read_text("utf-8"))
        for event in events:
            validated = {k: v for k, v in event.items() if k in schema["properties"]}
            jsonschema.Draft7Validator(schema).validate(validated)

    def test_seed_events_have_required_fields_and_clean_redaction(self, tmp_path: Path):
        seed_path = _temp_seed(tmp_path)
        events = _read_jsonl(seed_path)
        for event in events:
            assert event.get("correlation_id") == "corr_seeded_mission_001"
            assert "event_id" in event
            assert "occurred_at" in event
            assert "sequence" in event
            assert event["sequence"] >= 1
            assert event["redaction_status"] == "passed"
            assert event["content_light"] is True
            assert event["sensitivity_class"] == "internal_operational"

    def test_at_least_two_events_have_non_empty_causation_id(self, tmp_path: Path):
        seed_path = _temp_seed(tmp_path)
        events = _read_jsonl(seed_path)
        causation_count = sum(1 for e in events if e.get("causation_id"))
        assert causation_count >= 2, (
            f"expected >=2 causation links, got {causation_count}"
        )

    def test_seed_has_no_token_like_strings(self, tmp_path: Path):
        seed_path = _temp_seed(tmp_path)
        raw_text = seed_path.read_text("utf-8")
        for pattern in TOKEN_PATTERNS:
            assert pattern not in raw_text, f"found token pattern: {pattern}"


class TestDuckDBProjection:
    def test_duckdb_reads_seeded_jsonl_event_count_25(self, tmp_path: Path):
        pytest.importorskip("duckdb")
        seed_path = _temp_seed(tmp_path)
        report = build_event_fabric_duckdb_projection(log_paths=[seed_path])
        assert report["event_count"] == 25, f"got {report.get('event_count')}"
        assert report["status"] == "succeeded"

    def test_bridge_lifecycle_summary_has_nonzero_counts(self, tmp_path: Path):
        pytest.importorskip("duckdb")
        seed_path = _temp_seed(tmp_path)
        report = build_event_fabric_duckdb_projection(log_paths=[seed_path])
        bridge = report["bridge_lifecycle_summary"]
        assert sum(bridge.values()) > 0
        assert "bridge.status.updated" in bridge
        assert "bridge.connection.begin" in bridge

    def test_causal_chain_summary_observed_count_at_least_2(self, tmp_path: Path):
        pytest.importorskip("duckdb")
        seed_path = _temp_seed(tmp_path)
        report = build_event_fabric_duckdb_projection(log_paths=[seed_path])
        causal = report["causal_chain_summary"]
        assert isinstance(causal["observed_count"], int)
        assert causal["observed_count"] >= 2, (
            f"observed_count={causal['observed_count']}"
        )

    def test_resource_pressure_summary_consumer_error_count_at_least_1(
        self, tmp_path: Path
    ):
        pytest.importorskip("duckdb")
        seed_path = _temp_seed(tmp_path)
        report = build_event_fabric_duckdb_projection(log_paths=[seed_path])
        pressure = report["resource_pressure_summary"]
        assert pressure["consumer_error_count"] >= 1

    def test_no_persistent_duckdb_file_created(self, tmp_path: Path):
        pytest.importorskip("duckdb")
        seed_path = _temp_seed(tmp_path)
        before = set(tmp_path.rglob("*"))
        build_event_fabric_duckdb_projection(log_paths=[seed_path])
        after = set(tmp_path.rglob("*"))
        new_files = after - before
        db_files = [f for f in new_files if f.suffix in {".db", ".duckdb", ".wal"}]
        assert not db_files, f"found persistent DuckDB files: {db_files}"


class TestTopologyProjection:
    def _seeded_artifacts(self, tmp_path: Path) -> tuple[Path, Path]:
        pytest.importorskip("duckdb")
        seed_path = _temp_seed(tmp_path)
        report = build_event_fabric_duckdb_projection(log_paths=[seed_path])
        report_path = _write_json(tmp_path / "duckdb_report.json", report)
        pressure = report.get("resource_pressure_summary", {})
        pressure_path = _write_json(
            tmp_path / "pressure_summary.json",
            {
                "reconnect_failed_count": pressure.get("reconnect_failed_count", 0),
                "queue_pressure_high_count": pressure.get(
                    "queue_pressure_high_count", 0
                ),
                "consumer_error_count": pressure.get("consumer_error_count", 0),
            },
        )
        return report_path, pressure_path

    def test_topology_with_seeded_data_has_status_live(self, tmp_path: Path):
        report_path, pressure_path = self._seeded_artifacts(tmp_path)
        topology = build_mission_topology_projection(
            duckdb_report_path=report_path, pressure_summary_path=pressure_path
        )
        assert topology["status"] != "degraded_no_input"
        assert topology["status"] != "empty"
        assert topology["status"] == "live"

    def test_topology_has_16_nodes_and_at_least_10_edges(self, tmp_path: Path):
        report_path, pressure_path = self._seeded_artifacts(tmp_path)
        topology = build_mission_topology_projection(
            duckdb_report_path=report_path, pressure_summary_path=pressure_path
        )
        assert len(topology["nodes"]) == 16
        assert len(topology["edges"]) >= 10

    def test_bridge_projection_resource_nodes_active_or_idle(self, tmp_path: Path):
        report_path, pressure_path = self._seeded_artifacts(tmp_path)
        topology = build_mission_topology_projection(
            duckdb_report_path=report_path, pressure_summary_path=pressure_path
        )
        nodes = {n["node_id"]: n for n in topology["nodes"]}
        for node_id in ("bridge", "projection", "resource"):
            node = nodes.get(node_id)
            assert node is not None, f"{node_id} node missing"
            assert node["strand_state"] != "no_input", (
                f"{node_id} strand_state={node['strand_state']}"
            )

    def test_resource_pressure_consumer_errors_not_none(self, tmp_path: Path):
        report_path, pressure_path = self._seeded_artifacts(tmp_path)
        topology = build_mission_topology_projection(
            duckdb_report_path=report_path, pressure_summary_path=pressure_path
        )
        rp = topology["resource_pressure"]
        assert rp["consumer_errors"] != "none", (
            f"consumer_errors={rp['consumer_errors']}"
        )

    def test_read_side_only_true_mutation_authority_false(self, tmp_path: Path):
        report_path, pressure_path = self._seeded_artifacts(tmp_path)
        topology = build_mission_topology_projection(
            duckdb_report_path=report_path, pressure_summary_path=pressure_path
        )
        assert topology["read_side_only"] is True
        assert topology["mutation_authority"] is False


class TestStaticArtifacts:
    def test_manifest_exists_and_has_required_keys(self):
        if not MANIFEST_PATH.exists():
            pytest.skip("Static renderer manifest not found")
        manifest = json.loads(MANIFEST_PATH.read_text("utf-8"))
        for key in MANIFEST_REQUIRED_KEYS:
            assert key in manifest, f"manifest missing key: {key}"

    def test_html_sha256_matches_manifest(self):
        if not MANIFEST_PATH.exists() or not HTML_PATH.exists():
            pytest.skip("Static artifacts not found")
        manifest = json.loads(MANIFEST_PATH.read_text("utf-8"))
        html_sha256 = _sha256_file(HTML_PATH)
        assert html_sha256 == manifest["html_sha256"], (
            f"html_sha256={html_sha256}, manifest={manifest['html_sha256']}"
        )

    def test_html_has_no_remote_asset_references(self):
        if not HTML_PATH.exists():
            pytest.skip("Static HTML not found")
        html = HTML_PATH.read_text("utf-8")
        assert 'href="http://' not in html
        assert 'href="https://' not in html
        assert 'src="http://' not in html
        assert 'src="https://' not in html
        assert "fetch(" not in html
        assert "XMLHttpRequest" not in html

    def test_html_has_fallback_table_with_16_rows(self):
        if not HTML_PATH.exists():
            pytest.skip("Static HTML not found")
        html = HTML_PATH.read_text("utf-8")
        node_count = html.count('"node_id"')
        assert node_count >= 16, f"embedded topology has {node_count} node_id entries"

    def test_html_has_status_badge_svg_pressure_degraded_legend_meta(self):
        if not HTML_PATH.exists():
            pytest.skip("Static HTML not found")
        html = HTML_PATH.read_text("utf-8")
        assert "status-badge" in html
        assert '<svg id="topology-svg"' in html
        assert 'class="pressure-grid"' in html
        assert 'class="degraded"' in html
        assert 'class="legend"' in html
        assert 'class="meta"' in html


class TestFullPipelineE2E:
    def test_seed_to_duckdb_to_topology_all_artifacts_correct(self, tmp_path: Path):
        pytest.importorskip("duckdb")
        seed_path = _temp_seed(tmp_path)
        assert seed_path.exists()
        events = _read_jsonl(seed_path)
        assert len(events) == 25

        report = build_event_fabric_duckdb_projection(log_paths=[seed_path])
        assert report["status"] == "succeeded"
        assert report["event_count"] == 25

        report_path = _write_json(tmp_path / "duckdb_report.json", report)
        pressure = report.get("resource_pressure_summary", {})
        pressure_path = _write_json(
            tmp_path / "pressure_summary.json",
            {
                "reconnect_failed_count": pressure.get("reconnect_failed_count", 0),
                "queue_pressure_high_count": pressure.get(
                    "queue_pressure_high_count", 0
                ),
                "consumer_error_count": pressure.get("consumer_error_count", 0),
            },
        )
        topology = build_mission_topology_projection(
            duckdb_report_path=report_path, pressure_summary_path=pressure_path
        )
        assert topology["status"] == "live"
        assert len(topology["nodes"]) == 16
        assert len(topology["edges"]) >= 10
        assert topology["read_side_only"] is True
        assert topology["mutation_authority"] is False
