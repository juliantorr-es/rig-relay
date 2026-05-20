from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.events.duckdb_projection import build_event_fabric_duckdb_projection

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.real_artifact]

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.event.duckdb_projection_report.v1.schema.json"
)

SAMPLE_EVENTS: list[dict] = [
    {
        "event_id": "evt_001",
        "event_type": "bridge.status.updated",
        "source": "bridge",
        "occurred_at": "2026-05-20T10:00:00Z",
        "producer": "bridge",
        "correlation_id": "corr_abc",
        "causation_id": "",
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "sequence": 1,
        "payload": {"runtime_state": "idle"},
    },
    {
        "event_id": "evt_002",
        "event_type": "bridge.disconnect",
        "source": "bridge",
        "occurred_at": "2026-05-20T10:01:00Z",
        "producer": "bridge",
        "correlation_id": "corr_abc",
        "causation_id": "evt_001",
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "sequence": 2,
        "payload": {},
    },
    {
        "event_id": "evt_003",
        "event_type": "worker.failed",
        "source": "supervisor",
        "occurred_at": "2026-05-20T10:02:00Z",
        "producer": "supervisor",
        "correlation_id": "corr_def",
        "causation_id": "",
        "sensitivity_class": "telemetry_opt_in",
        "redaction_status": "passed",
        "content_light": True,
        "sequence": 1,
        "payload": {"error": "timeout"},
    },
    {
        "event_id": "evt_004",
        "event_type": "github.rate_limit.near_exhausted",
        "source": "github",
        "occurred_at": "2026-05-20T10:03:00Z",
        "producer": "github_provider",
        "correlation_id": "corr_def",
        "causation_id": "",
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "sequence": 2,
        "payload": {"remaining": 5},
    },
]


def _write_event_log(path: Path, events: list[dict]) -> Path:
    with path.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    return path


def test_report_validates_against_schema(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    validated = {k: v for k, v in report.items() if k in schema["properties"]}
    jsonschema.Draft7Validator(schema).validate(validated)


def test_no_input_logs_with_nonexistent_path_returns_valid_report(tmp_path: Path):
    report = build_event_fabric_duckdb_projection(
        log_paths=[tmp_path / "nonexistent.jsonl"]
    )
    assert report["status"] == "no_input_logs"
    assert report["event_count"] == 0
    assert report["read_side_only"] is True
    assert report["mutation_authority"] is False
    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    validated = {k: v for k, v in report.items() if k in schema["properties"]}
    jsonschema.Draft7Validator(schema).validate(validated)


def test_no_input_logs_with_empty_list():
    report = build_event_fabric_duckdb_projection(log_paths=[])
    assert report["status"] == "no_input_logs"
    assert report["event_count"] == 0


def test_valid_jsonl_produces_event_count(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    assert report["event_count"] > 0
    assert report["event_count"] == len(SAMPLE_EVENTS)


def test_event_type_counts_has_correct_keys_and_values(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    counts = report["event_type_counts"]
    assert counts["bridge.status.updated"] == 1
    assert counts["bridge.disconnect"] == 1
    assert counts["worker.failed"] == 1
    assert counts["github.rate_limit.near_exhausted"] == 1


def test_event_category_counts_derives_prefix(tmp_path: Path):
    events = [
        {
            "event_id": "evt_001",
            "event_type": "bridge.status.updated",
            "source": "bridge",
            "occurred_at": "2026-05-20T10:00:00Z",
            "producer": "bridge",
            "correlation_id": "corr_abc",
            "causation_id": "",
            "sensitivity_class": "internal_operational",
            "redaction_status": "passed",
            "content_light": True,
            "sequence": 1,
            "payload": {},
        },
        {
            "event_id": "evt_002",
            "event_type": "bridge.disconnect",
            "source": "bridge",
            "occurred_at": "2026-05-20T10:01:00Z",
            "producer": "bridge",
            "correlation_id": "corr_abc",
            "causation_id": "",
            "sensitivity_class": "internal_operational",
            "redaction_status": "passed",
            "content_light": True,
            "sequence": 2,
            "payload": {},
        },
        {
            "event_id": "evt_003",
            "event_type": "worker.failed",
            "source": "supervisor",
            "occurred_at": "2026-05-20T10:02:00Z",
            "producer": "supervisor",
            "correlation_id": "corr_def",
            "causation_id": "",
            "sensitivity_class": "telemetry_opt_in",
            "redaction_status": "passed",
            "content_light": True,
            "sequence": 1,
            "payload": {},
        },
    ]
    log_path = _write_event_log(tmp_path / "events.jsonl", events)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    category_counts = report["event_category_counts"]
    assert category_counts["bridge"] == 2
    assert category_counts["worker"] == 1


def test_producer_counts_has_correct_counts(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    producer_counts = report["producer_counts"]
    assert producer_counts.get("bridge") == 2
    assert producer_counts.get("supervisor") == 1
    assert producer_counts.get("github_provider") == 1


def test_sensitivity_class_counts_are_correct(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    counts = report["sensitivity_class_counts"]
    assert counts["internal_operational"] == 3
    assert counts["telemetry_opt_in"] == 1


def test_redaction_status_counts_are_correct(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    counts = report["redaction_status_counts"]
    assert counts["passed"] == 4


def test_bridge_lifecycle_summary_has_correct_counts(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    bridge_summary = report["bridge_lifecycle_summary"]
    assert bridge_summary["bridge.status.updated"] == 1
    assert bridge_summary["bridge.disconnect"] == 1


def test_resource_pressure_summary_counts_reconnect_and_queue_events(tmp_path: Path):
    pressure_events = [
        {
            "event_id": "evt_001",
            "event_type": "runtime.reconnect_failed",
            "source": "runtime",
            "occurred_at": "2026-05-20T10:00:00Z",
            "producer": "bridge",
            "correlation_id": "corr_abc",
            "causation_id": "",
            "sensitivity_class": "internal_operational",
            "redaction_status": "passed",
            "content_light": True,
            "sequence": 1,
            "payload": {},
        },
        {
            "event_id": "evt_002",
            "event_type": "bridge.reconnect_failed",
            "source": "bridge",
            "occurred_at": "2026-05-20T10:01:00Z",
            "producer": "bridge",
            "correlation_id": "corr_abc",
            "causation_id": "",
            "sensitivity_class": "internal_operational",
            "redaction_status": "passed",
            "content_light": True,
            "sequence": 2,
            "payload": {},
        },
        {
            "event_id": "evt_003",
            "event_type": "runtime.queue_pressure.high",
            "source": "runtime",
            "occurred_at": "2026-05-20T10:02:00Z",
            "producer": "supervisor",
            "correlation_id": "corr_def",
            "causation_id": "",
            "sensitivity_class": "internal_operational",
            "redaction_status": "passed",
            "content_light": True,
            "sequence": 1,
            "payload": {},
        },
    ]
    log_path = _write_event_log(tmp_path / "events.jsonl", pressure_events)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    pressure = report["resource_pressure_summary"]
    assert pressure["reconnect_failed_count"] == 2
    assert pressure["queue_pressure_high_count"] == 1


def test_consumer_error_summary_counts_error_events(tmp_path: Path):
    consumer_events = [
        {
            "event_id": "evt_001",
            "event_type": "runtime.consumer_error",
            "source": "runtime",
            "occurred_at": "2026-05-20T10:00:00Z",
            "producer": "bridge",
            "correlation_id": "corr_abc",
            "causation_id": "",
            "sensitivity_class": "internal_operational",
            "redaction_status": "passed",
            "content_light": True,
            "sequence": 1,
            "payload": {},
        },
        {
            "event_id": "evt_002",
            "event_type": "bridge.projection_loop.error",
            "source": "bridge",
            "occurred_at": "2026-05-20T10:01:00Z",
            "producer": "bridge",
            "correlation_id": "corr_def",
            "causation_id": "",
            "sensitivity_class": "internal_operational",
            "redaction_status": "passed",
            "content_light": True,
            "sequence": 1,
            "payload": {},
        },
    ]
    log_path = _write_event_log(tmp_path / "events.jsonl", consumer_events)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    error_summary = report["consumer_error_summary"]
    assert error_summary["consumer_error_count"] == 2


def test_causal_chain_summary_has_observed_and_correlated(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    causal = report["causal_chain_summary"]
    assert "observed_count" in causal
    assert "correlated_only_count" in causal
    assert causal["observed_count"] >= 0
    assert causal["correlated_only_count"] >= 0
    assert isinstance(causal["observed_count"], int)
    assert isinstance(causal["correlated_only_count"], int)


def test_query_manifest_entries_are_read_side_only(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    manifest = report["query_manifest"]
    assert len(manifest) > 0
    for entry in manifest:
        assert entry["read_side_only"] is True
        assert entry["mutation_risk"] == "none"
        assert "query_id" in entry


def test_report_has_read_side_only_and_mutation_authority(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    assert report["read_side_only"] is True
    assert report["mutation_authority"] is False


def test_malformed_jsonl_line_is_handled_without_crashing(tmp_path: Path):
    log_path = tmp_path / "events.jsonl"
    with log_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(SAMPLE_EVENTS[0]) + "\n")
        f.write("this is not valid json\n")
        f.write(json.dumps(SAMPLE_EVENTS[1]) + "\n")
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    assert report["malformed_lines"] == 1
    assert report["status"] in {"succeeded", "partial", "read_failed", "no_input_logs"}


def test_report_has_source_event_logs_field(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    assert "source_event_logs" in report
    assert isinstance(report["source_event_logs"], list)
    assert len(report["source_event_logs"]) == 1


def test_report_includes_branch_and_head(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    assert "branch" in report
    assert "head" in report
