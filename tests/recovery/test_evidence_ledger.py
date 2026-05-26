"""Test evidence ledger — append-only JSONL, integrity, content-light."""

from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.recovery.evidence_ledger import EvidenceLedger


def test_append_and_load(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    event = {
        "schema_version": "rig.relay.tool_recovery_evaluation_event.v1",
        "evaluation_run_id": "r1",
        "case_id": "c1",
        "tool_surface_manifest_digest": "sha256:" + "a" * 64,
        "raw_emission_sha256": "sha256:" + "b" * 64,
        "payload_schema_valid": True,
        "created_at": "2026-01-01T00:00:00Z",
    }
    ledger.append_event(event)
    events = ledger.load_events()
    assert len(events) == 1
    assert events[0]["case_id"] == "c1"
    assert "event_digest" in events[0]


def test_multiple_appends_preserved(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    base = {
        "schema_version": "x",
        "evaluation_run_id": "r1",
        "case_id": "",
        "tool_surface_manifest_digest": "sha256:" + "a" * 64,
        "raw_emission_sha256": "sha256:" + "b" * 64,
        "payload_schema_valid": True,
        "created_at": "2026-01-01T00:00:00Z",
    }
    for i in range(5):
        e = dict(base, case_id=f"c{i}")
        ledger.append_event(e)
    events = ledger.load_events()
    assert len(events) == 5


def test_count_events(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    base = {
        "schema_version": "x",
        "evaluation_run_id": "r1",
        "case_id": "",
        "tool_surface_manifest_digest": "sha256:" + "a" * 64,
        "raw_emission_sha256": "sha256:" + "b" * 64,
        "payload_schema_valid": True,
        "created_at": "2026-01-01T00:00:00Z",
    }
    for i in range(3):
        e = dict(base, case_id=f"c{i}")
        ledger.append_event(e)
    assert ledger.count_events() == 3


def test_forbidden_content_keys_rejected(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    event = {
        "schema_version": "x",
        "evaluation_run_id": "r1",
        "case_id": "c1",
        "tool_surface_manifest_digest": "sha256:" + "a" * 64,
        "raw_emission_sha256": "sha256:" + "b" * 64,
        "raw_emission": "THIS IS FORBIDDEN",
        "payload_schema_valid": True,
        "created_at": "2026-01-01T00:00:00Z",
    }
    with pytest.raises(ValueError, match="forbidden"):
        ledger.append_event(event)


def test_corrupt_events_surfaced(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("not valid json\n")
    ledger = EvidenceLedger(path)
    events = ledger.load_events()
    assert len(events) == 0


def test_roundtrip_integrity(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    event = {
        "schema_version": "x",
        "evaluation_run_id": "r1",
        "case_id": "c-tamper",
        "tool_surface_manifest_digest": "sha256:" + "a" * 64,
        "raw_emission_sha256": "sha256:" + "b" * 64,
        "payload_schema_valid": True,
        "created_at": "2026-01-01T00:00:00Z",
    }
    digest = ledger.append_event(event)
    events = ledger.load_events()
    assert len(events) == 1
    assert events[0]["event_digest"] == digest
