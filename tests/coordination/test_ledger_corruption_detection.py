"""Coordination Ledger Corruption Detection — sabotage/real-artifact tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.coordination.models import reset_path_salt_for_testing
from rig_relay.coordination.store import CoordinationStore, check_ledger_integrity

pytestmark = [pytest.mark.sabotage, pytest.mark.real_artifact]


def _make_valid_event_line(
    event_id: str | None = None,
    sequence: int | None = None,
    event_name: str | None = "coord.test.event",
    created_at: str | None = "2025-01-01T00:00:00+00:00",
) -> str:
    eid = event_id or f"evt-{hash(sequence) & 0xFFFFFFFF:08x}"
    seq_val = sequence if sequence is not None else 1
    return json.dumps({
        "schema_version": "rig.relay.coordination.event.v1",
        "event_id": eid,
        "sequence": seq_val,
        "event_name": event_name,
        "created_at": created_at,
        "payload": {},
        "event_hash": f"sha256:deadbeef{eid}",
        "session_id": None,
        "task_id": None,
    })


def _write_ledger(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Malformed JSON ───────────────────────────────────────────


class TestMalformedJsonDetection:
    def test_unparseable_line_detected(self, tmp_path: Path) -> None:
        ledger = tmp_path / "events.jsonl"
        _write_ledger(
            ledger,
            [
                _make_valid_event_line(sequence=1),
                "this is not json {{{",
                _make_valid_event_line(sequence=2),
            ],
        )
        findings = check_ledger_integrity(ledger)
        malformed = [f for f in findings if f["type"] == "malformed_json"]
        assert len(malformed) >= 1
        assert malformed[0]["line_number"] == 2

    def test_truncated_json_detected(self, tmp_path: Path) -> None:
        ledger = tmp_path / "events.jsonl"
        _write_ledger(
            ledger,
            [
                _make_valid_event_line(sequence=1),
                '{"schema_version": "rig.relay.coordination.event.v1", "event_id": "evt-2"',
                _make_valid_event_line(sequence=2),
            ],
        )
        findings = check_ledger_integrity(ledger)
        malformed = [f for f in findings if f["type"] == "malformed_json"]
        assert len(malformed) >= 1
        assert malformed[0]["line_number"] == 2


# ── Duplicate detection ──────────────────────────────────────


class TestDuplicateDetection:
    def test_duplicate_sequence_rejected(self, tmp_path: Path) -> None:
        ledger = tmp_path / "events.jsonl"
        _write_ledger(
            ledger,
            [
                _make_valid_event_line(sequence=1, event_id="evt-a"),
                _make_valid_event_line(sequence=1, event_id="evt-b"),
            ],
        )
        findings = check_ledger_integrity(ledger)
        dup_seqs = [f for f in findings if f["type"] == "duplicate_sequence"]
        assert len(dup_seqs) >= 1

    def test_duplicate_event_id_rejected(self, tmp_path: Path) -> None:
        ledger = tmp_path / "events.jsonl"
        _write_ledger(
            ledger,
            [
                _make_valid_event_line(sequence=1, event_id="evt-same"),
                _make_valid_event_line(sequence=2, event_id="evt-same"),
            ],
        )
        findings = check_ledger_integrity(ledger)
        dup_ids = [f for f in findings if f["type"] == "duplicate_event_id"]
        assert len(dup_ids) >= 1

    def test_no_duplicates_in_valid_ledger(self, tmp_path: Path) -> None:
        reset_path_salt_for_testing()
        store = CoordinationStore(tmp_path / ".build" / "rig-relay" / "coordination")
        for i in range(5):
            store.reserve_paths(
                session_id=f"sess-{i}",
                task_id=f"task-{i}",
                mode="write",
                paths=[f"src/file-{i}.py"],
                ttl_seconds=120,
            )
        findings = check_ledger_integrity(store.root / "events.jsonl")
        dup_types = {f["type"] for f in findings if f["type"].startswith("duplicate_")}
        assert not dup_types, f"Unexpected duplicates in valid ledger: {findings}"


# ── Missing required fields ──────────────────────────────────


class TestMissingRequiredFields:
    def test_missing_event_id_detected(self, tmp_path: Path) -> None:
        ledger = tmp_path / "events.jsonl"
        _write_ledger(
            ledger,
            [
                json.dumps({
                    "schema_version": "rig.relay.coordination.event.v1",
                    "sequence": 1,
                    "event_name": "coord.test.event",
                    "created_at": "2025-01-01T00:00:00+00:00",
                    "payload": {},
                })
            ],
        )
        findings = check_ledger_integrity(ledger)
        missing = [
            f
            for f in findings
            if f["type"] == "missing_field"
            and f["detail"] == "Missing required field: event_id"
        ]
        assert len(missing) == 1

    def test_missing_sequence_detected(self, tmp_path: Path) -> None:
        ledger = tmp_path / "events.jsonl"
        _write_ledger(
            ledger,
            [
                json.dumps({
                    "schema_version": "rig.relay.coordination.event.v1",
                    "event_id": "evt-a",
                    "event_name": "coord.test.event",
                    "created_at": "2025-01-01T00:00:00+00:00",
                    "payload": {},
                })
            ],
        )
        findings = check_ledger_integrity(ledger)
        missing = [
            f
            for f in findings
            if f["type"] == "missing_field" and "sequence" in f["detail"]
        ]
        assert len(missing) == 1

    def test_missing_event_name_detected(self, tmp_path: Path) -> None:
        ledger = tmp_path / "events.jsonl"
        _write_ledger(
            ledger,
            [
                json.dumps({
                    "schema_version": "rig.relay.coordination.event.v1",
                    "event_id": "evt-a",
                    "sequence": 1,
                    "created_at": "2025-01-01T00:00:00+00:00",
                    "payload": {},
                })
            ],
        )
        findings = check_ledger_integrity(ledger)
        missing = [
            f
            for f in findings
            if f["type"] == "missing_field" and "event_name" in f["detail"]
        ]
        assert len(missing) == 1

    def test_missing_created_at_detected(self, tmp_path: Path) -> None:
        ledger = tmp_path / "events.jsonl"
        _write_ledger(
            ledger,
            [
                json.dumps({
                    "schema_version": "rig.relay.coordination.event.v1",
                    "event_id": "evt-a",
                    "sequence": 1,
                    "event_name": "coord.test.event",
                    "payload": {},
                })
            ],
        )
        findings = check_ledger_integrity(ledger)
        missing = [
            f
            for f in findings
            if f["type"] == "missing_field" and "created_at" in f["detail"]
        ]
        assert len(missing) == 1

    def test_valid_event_no_missing_fields(self, tmp_path: Path) -> None:
        ledger = tmp_path / "events.jsonl"
        _write_ledger(ledger, [_make_valid_event_line(sequence=1)])
        findings = check_ledger_integrity(ledger)
        missing = [f for f in findings if f["type"] == "missing_field"]
        assert len(missing) == 0


# ── Integration: corrupt ledger + read-side audit ────────────


class TestCorruptionDetectionIntegration:
    def test_corrupt_ledger_is_detectable_by_read_side(self, tmp_path: Path) -> None:
        reset_path_salt_for_testing()
        store = CoordinationStore(tmp_path / ".build" / "rig-relay" / "coordination")
        for i in range(3):
            store.reserve_paths(
                session_id="sess-mixed",
                task_id=f"task-{i}",
                mode="write",
                paths=[f"src/good-{i}.py"],
                ttl_seconds=120,
            )
        events_path = store.root / "events.jsonl"
        lines = events_path.read_text("utf-8").splitlines(keepends=False)
        # Inject corruption: mid-entry truncation
        corrupted_lines = lines[:2] + ['{"bad": "truncated'] + lines[2:]
        events_path.write_text("\n".join(corrupted_lines) + "\n", encoding="utf-8")
        # Also inject a duplicate event_id
        dup_line = lines[0]
        corrupted_lines2 = lines + [dup_line]
        events_path.write_text("\n".join(corrupted_lines2) + "\n", encoding="utf-8")

        findings = check_ledger_integrity(events_path)
        types_found = {f["type"] for f in findings}
        assert "malformed_json" in types_found or "duplicate_event_id" in types_found, (
            f"Expected corruption to be detected, got: {findings}"
        )

    def test_valid_ledger_passes_integrity_check(self, tmp_path: Path) -> None:
        reset_path_salt_for_testing()
        store = CoordinationStore(tmp_path / ".build" / "rig-relay" / "coordination")
        for i in range(10):
            store.reserve_paths(
                session_id=f"sess-{i}",
                task_id=f"task-{i}",
                mode="read",
                paths=[f"src/valid-{i}.py"],
                ttl_seconds=300,
            )
        events_path = store.root / "events.jsonl"
        findings = check_ledger_integrity(events_path)
        assert findings == [], f"Valid ledger should have no findings, got: {findings}"
