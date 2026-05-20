from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from rig_relay.events.duckdb_projection import build_event_fabric_duckdb_projection

pytestmark = [pytest.mark.adversarial]

GITHUB_TOKEN_PATTERNS = ("ghp_", "gho_", "ghu_", "ghs_", "github_pat_")

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
]


def _write_event_log(path: Path, events: list[dict]) -> Path:
    with path.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    return path


def test_report_has_no_token_like_strings(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    report_str = json.dumps(report)
    for pattern in GITHUB_TOKEN_PATTERNS:
        assert pattern not in report_str, f"found token pattern: {pattern}"


def test_report_has_redaction_summary_field(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    assert "redaction_summary" in report
    redaction = report["redaction_summary"]
    assert isinstance(redaction, dict)
    assert redaction.get("raw_payloads_exposed") is False
    assert redaction.get("envelope_only") is True
    assert "payload_hash_only" in redaction


def test_report_serialized_json_has_no_raw_payload_data(tmp_path: Path):
    events_with_secrets = [
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
            "payload": {"runtime_state": "active", "access_token": "ghp_deadbeef1234"},
        }
    ]
    log_path = _write_event_log(tmp_path / "events.jsonl", events_with_secrets)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    report_str = json.dumps(report)
    assert "ghp_deadbeef1234" not in report_str
    assert "access_token" not in report


def test_raw_payload_fields_not_flattened_into_top_level_keys(tmp_path: Path):
    events_with_nested = [
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
            "payload": {
                "runtime_state": "active",
                "nested": {"secret": "hidden-value", "token": "ghp_abcdef"},
            },
        }
    ]
    log_path = _write_event_log(tmp_path / "events.jsonl", events_with_nested)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    assert "runtime_state" not in report
    assert "nested" not in report
    assert "secret" not in report
    assert "token" not in report
    assert "hidden-value" not in report
    assert "ghp_abcdef" not in json.dumps(report)


def test_duckdb_unavailable_handles_gracefully(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    with mock.patch("rig_relay.events.duckdb_projection.HAS_DUCKDB", False):
        report = build_event_fabric_duckdb_projection(log_paths=[log_path])
        assert report["read_side_only"] is True
        assert report["mutation_authority"] is False
        assert report["duckdb_available"] is False
        assert report["status"] == "duckdb_not_available"


def test_report_has_telemetry_redaction_implications(tmp_path: Path):
    log_path = _write_event_log(tmp_path / "events.jsonl", SAMPLE_EVENTS)
    report = build_event_fabric_duckdb_projection(log_paths=[log_path])
    assert "telemetry_redaction_implications" in report
    tr = report["telemetry_redaction_implications"]
    assert isinstance(tr, list)
    assert len(tr) >= 2
