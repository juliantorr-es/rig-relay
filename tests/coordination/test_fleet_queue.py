"""Tests for Fleet Queue Phase 0 — FleetQueue, event sourcing, state machine."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.coordination.fleet_queue import (
    FleetQueue,
    FleetQueueEvent,
    FleetQueueEventKind,
    FleetQueueItem,
    FleetQueueItemKind,
    FleetQueueItemStatus,
    FleetQueueSnapshot,
)

# ── Forbidden raw field names (must match fleet_queue.py) ────────────────

_FORBIDDEN_RAW = frozenset({
    "prompt",
    "stdout",
    "stderr",
    "content",
    "diff",
    "patch",
    "secret",
    "argv",
    "snippet",
    "file_content",
    "raw_prompt",
    "raw_output",
})

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def events_path(tmp_path: Path) -> Path:
    return tmp_path / "queue" / "events.jsonl"


@pytest.fixture
def queue(events_path: Path) -> FleetQueue:
    return FleetQueue(events_path)


@pytest.fixture
def queue_item_schema() -> dict:
    path = _SCHEMAS_DIR / "rig.fleet.queue_item.v1.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def queue_event_schema() -> dict:
    path = _SCHEMAS_DIR / "rig.fleet.queue_event.v1.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ── FleetQueueItem model tests ───────────────────────────────────────────


class TestFleetQueueItemModel:
    def test_minimal_valid(self) -> None:
        item = FleetQueueItem(queue_item_id="id-1", kind=FleetQueueItemKind.MESSAGE)
        assert item.queue_item_id == "id-1"
        assert item.kind == "message"
        assert item.status == "queued"
        assert item.priority == 0
        assert item.depends_on == []

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            FleetQueueItem.model_validate({
                "queue_item_id": "x",
                "kind": "message",
                "unknown": "boom",
            })

    def test_from_dict(self) -> None:
        data = {
            "queue_item_id": "id-2",
            "kind": "runtime_exec",
            "status": "running",
            "priority": 5,
            "depends_on": ["id-1"],
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "mission_id": "mission-x",
            "agent_id": "agent-y",
            "payload": {"summary": "run build"},
            "blocked_reason": None,
            "superseded_by": None,
        }
        item = FleetQueueItem.model_validate(data)
        assert item.kind == "runtime_exec"
        assert item.status == "running"
        assert item.priority == 5
        assert item.depends_on == ["id-1"]
        assert item.mission_id == "mission-x"
        assert item.payload == {"summary": "run build"}

    def test_schema_version_constant(self) -> None:
        item = FleetQueueItem(queue_item_id="i1", kind="validate")
        assert item.schema_version == "rig.fleet.queue_item.v1"


# ── FleetQueueEvent model tests ──────────────────────────────────────────


class TestFleetQueueEventModel:
    def test_minimal_valid(self) -> None:
        event = FleetQueueEvent(
            queue_item_id="id-1", event_kind=FleetQueueEventKind.ENQUEUED
        )
        assert event.queue_item_id == "id-1"
        assert event.event_kind == "enqueued"
        assert event.event_id is not None

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            FleetQueueEvent.model_validate({
                "queue_item_id": "x",
                "event_kind": "enqueued",
                "unknown": "boom",
            })

    def test_event_id_is_uuid(self) -> None:
        e1 = FleetQueueEvent(queue_item_id="i1", event_kind="enqueued")
        e2 = FleetQueueEvent(queue_item_id="i1", event_kind="enqueued")
        assert e1.event_id != e2.event_id


# ── FleetQueueSnapshot model tests ───────────────────────────────────────


class TestFleetQueueSnapshotModel:
    def test_empty(self) -> None:
        snap = FleetQueueSnapshot()
        assert snap.total_count == 0
        assert snap.items == []
        assert snap.status_counts == {}


# ── Queue item kind values ───────────────────────────────────────────────


class TestFleetQueueItemKind:
    def test_all_values_match_enum(self) -> None:
        assert FleetQueueItemKind.MESSAGE == "message"
        assert FleetQueueItemKind.RUNTIME_EXEC == "runtime_exec"
        assert FleetQueueItemKind.VALIDATE == "validate"
        assert FleetQueueItemKind.HANDOFF_NOTE == "handoff_note"
        assert FleetQueueItemKind.PAUSE == "pause"
        assert FleetQueueItemKind.RESUME == "resume"


# ── Queue item status values ─────────────────────────────────────────────


class TestFleetQueueItemStatus:
    def test_all_values(self) -> None:
        assert FleetQueueItemStatus.QUEUED == "queued"
        assert FleetQueueItemStatus.RUNNING == "running"
        assert FleetQueueItemStatus.BLOCKED == "blocked"
        assert FleetQueueItemStatus.COMPLETED == "completed"
        assert FleetQueueItemStatus.FAILED == "failed"
        assert FleetQueueItemStatus.CANCELLED == "cancelled"
        assert FleetQueueItemStatus.SUPERSEDED == "superseded"


# ── Queue event kind values ──────────────────────────────────────────────


class TestFleetQueueEventKind:
    def test_all_values(self) -> None:
        assert FleetQueueEventKind.ENQUEUED == "enqueued"
        assert FleetQueueEventKind.CANCELLED == "cancelled"
        assert FleetQueueEventKind.STATUS_CHANGED == "status_changed"
        assert FleetQueueEventKind.SUPERSEDED_BY == "superseded_by"


# ── Enqueue operation ────────────────────────────────────────────────────


class TestEnqueue:
    def test_enqueue_creates_valid_event(
        self, queue: FleetQueue, events_path: Path
    ) -> None:
        event = queue.enqueue_item(
            FleetQueueItemKind.MESSAGE,
            mission_id="mission-1",
            agent_id="agent-1",
            payload={"summary": "hello"},
        )
        assert event.event_kind == "enqueued"
        assert event.mission_id == "mission-1"
        assert event.agent_id == "agent-1"
        assert events_path.exists()

        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["queue_item_id"] == event.queue_item_id

    def test_enqueue_item_is_queued_by_default(self, queue: FleetQueue) -> None:
        event = queue.enqueue_item(FleetQueueItemKind.VALIDATE)
        snap = queue.list_items()
        assert len(snap.items) == 1
        assert snap.items[0].queue_item_id == event.queue_item_id
        assert snap.items[0].status == "queued"

    def test_enqueue_with_depends_on(self, queue: FleetQueue) -> None:
        queue.enqueue_item(
            FleetQueueItemKind.RUNTIME_EXEC, depends_on=["build-1"], priority=3
        )
        snap = queue.list_items()
        item = snap.items[0]
        assert item.depends_on == ["build-1"]
        assert item.priority == 3

    def test_enqueue_sanitises_forbidden_fields(self, queue: FleetQueue) -> None:
        queue.enqueue_item(
            FleetQueueItemKind.MESSAGE,
            payload={"summary": "ok", "stdout": "garbage", "secret": "my-key"},
        )
        snap = queue.list_items()
        item = snap.items[0]
        assert item.payload.get("summary") == "ok"
        assert "stdout" not in item.payload
        assert "secret" not in item.payload


# ── State machine transitions ────────────────────────────────────────────


class TestStateMachine:
    def test_mark_running(self, queue: FleetQueue) -> None:
        e = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        queue.mark_running(e.queue_item_id)
        snap = queue.list_items()
        assert snap.items[0].status == "running"

    def test_mark_completed(self, queue: FleetQueue) -> None:
        e = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        queue.mark_running(e.queue_item_id)
        queue.mark_completed(e.queue_item_id)
        snap = queue.list_items()
        assert snap.items[0].status == "completed"

    def test_mark_failed(self, queue: FleetQueue) -> None:
        e = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        queue.mark_running(e.queue_item_id)
        queue.mark_failed(e.queue_item_id, reason="timeout")
        snap = queue.list_items()
        assert snap.items[0].status == "failed"
        assert snap.items[0].blocked_reason is None

    def test_mark_blocked(self, queue: FleetQueue) -> None:
        e = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        queue.mark_blocked(e.queue_item_id, reason="lease conflict")
        snap = queue.list_items()
        assert snap.items[0].status == "blocked"
        assert snap.items[0].blocked_reason == "lease conflict"

    def test_cancel_item(self, queue: FleetQueue) -> None:
        e = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        queue.cancel_item(e.queue_item_id, reason="no longer needed")
        snap = queue.list_items()
        assert snap.items[0].status == "cancelled"

    def test_cancel_nonexistent_returns_none(self, queue: FleetQueue) -> None:
        result = queue.cancel_item("nonexistent")
        assert result is None

    def test_idempotent_mark(self, queue: FleetQueue) -> None:
        e = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        r1 = queue.mark_completed(e.queue_item_id)
        assert r1 is not None
        r2 = queue.mark_completed(e.queue_item_id)
        assert r2 is None

    def test_status_count_tracking(self, queue: FleetQueue) -> None:
        e1 = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        e2 = queue.enqueue_item(FleetQueueItemKind.VALIDATE)
        queue.enqueue_item(FleetQueueItemKind.RUNTIME_EXEC)
        queue.mark_completed(e1.queue_item_id)
        queue.mark_failed(e2.queue_item_id)
        snap = queue.list_items()
        assert snap.total_count == 3
        assert snap.status_counts.get("queued") == 1
        assert snap.status_counts.get("completed") == 1
        assert snap.status_counts.get("failed") == 1


# ── Event sourcing: snapshot rebuild ─────────────────────────────────────


class TestEventSourcing:
    def test_empty_store_returns_empty_snapshot(self, queue: FleetQueue) -> None:
        snap = queue.list_items()
        assert snap.total_count == 0
        assert snap.items == []

    def test_snapshot_rebuilds_from_jsonl(self, tmp_path: Path) -> None:
        p = tmp_path / "q" / "e.jsonl"
        q1 = FleetQueue(p)
        e1 = q1.enqueue_item(FleetQueueItemKind.MESSAGE)
        e2 = q1.enqueue_item(FleetQueueItemKind.VALIDATE)
        q1.mark_running(e2.queue_item_id)

        q2 = FleetQueue(p)
        snap = q2.list_items()
        assert snap.total_count == 2
        item_map = {i.queue_item_id: i for i in snap.items}
        assert item_map[e1.queue_item_id].status == "queued"
        assert item_map[e2.queue_item_id].status == "running"

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "q" / "e.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text(
            '{"queue_item_id":"i1","event_kind":"enqueued","payload":{"queue_item_id":"i1",'
            '"kind":"message","status":"queued","priority":0,"depends_on":[],'
            '"created_at":"2026-01-01T00:00:00","updated_at":"2026-01-01T00:00:00"}}\n'
            "not-json-line\n"
            '{"queue_item_id":"i2","event_kind":"enqueued","payload":{"queue_item_id":"i2",'
            '"kind":"validate","status":"queued","priority":0,"depends_on":[],'
            '"created_at":"2026-01-01T00:00:00","updated_at":"2026-01-01T00:00:00"}}\n',
            encoding="utf-8",
        )
        q = FleetQueue(p)
        snap = q.list_items()
        assert snap.total_count == 2


# ── FIFO ordering ────────────────────────────────────────────────────────


class TestOrdering:
    def test_fifo_by_created_at(self, queue: FleetQueue) -> None:
        queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        queue.enqueue_item(FleetQueueItemKind.VALIDATE)
        snap = queue.list_items()
        assert snap.items[0].kind == "message"
        assert snap.items[1].kind == "validate"

    def test_higher_priority_first(self, queue: FleetQueue) -> None:
        queue.enqueue_item(FleetQueueItemKind.MESSAGE, priority=0)
        queue.enqueue_item(FleetQueueItemKind.VALIDATE, priority=10)
        eligible = queue.next_runnable_item()
        assert eligible is not None
        assert eligible.kind == "validate"

    def test_next_runnable_fifo_within_same_priority(self, queue: FleetQueue) -> None:
        e1 = queue.enqueue_item(FleetQueueItemKind.MESSAGE, priority=1)
        queue.enqueue_item(FleetQueueItemKind.VALIDATE, priority=1)
        eligible = queue.next_runnable_item()
        assert eligible is not None
        assert eligible.queue_item_id == e1.queue_item_id


# ── depends_on blocking ──────────────────────────────────────────────────


class TestDependsOn:
    def test_depends_on_blocks_until_completed(self, queue: FleetQueue) -> None:
        dep = queue.enqueue_item(FleetQueueItemKind.VALIDATE)
        blocked = queue.enqueue_item(
            FleetQueueItemKind.RUNTIME_EXEC, depends_on=[dep.queue_item_id]
        )
        eligible = queue.next_runnable_item()
        assert eligible is not None
        assert eligible.queue_item_id == dep.queue_item_id

        queue.mark_completed(dep.queue_item_id)
        eligible = queue.next_runnable_item()
        assert eligible is not None
        assert eligible.queue_item_id == blocked.queue_item_id

    def test_depends_on_satisfied_by_any_terminal_state(
        self, queue: FleetQueue
    ) -> None:
        dep = queue.enqueue_item(FleetQueueItemKind.VALIDATE)
        blocked = queue.enqueue_item(
            FleetQueueItemKind.RUNTIME_EXEC, depends_on=[dep.queue_item_id]
        )
        queue.mark_failed(dep.queue_item_id)
        eligible = queue.next_runnable_item()
        assert eligible is not None
        assert eligible.queue_item_id == blocked.queue_item_id

    def test_depends_on_multiple_must_all_complete(self, queue: FleetQueue) -> None:
        d1 = queue.enqueue_item(FleetQueueItemKind.VALIDATE)
        d2 = queue.enqueue_item(FleetQueueItemKind.VALIDATE)
        blocked = queue.enqueue_item(
            FleetQueueItemKind.RUNTIME_EXEC,
            depends_on=[d1.queue_item_id, d2.queue_item_id],
        )
        queue.mark_completed(d1.queue_item_id)
        eligible = queue.next_runnable_item()
        assert eligible is not None
        assert eligible.queue_item_id == d2.queue_item_id

        queue.mark_completed(d2.queue_item_id)
        eligible = queue.next_runnable_item()
        assert eligible is not None
        assert eligible.queue_item_id == blocked.queue_item_id


# ── Cancel prevents run ──────────────────────────────────────────────────


class TestCancel:
    def test_cancelled_item_not_runnable(self, queue: FleetQueue) -> None:
        e = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        queue.cancel_item(e.queue_item_id)
        eligible = queue.next_runnable_item()
        assert eligible is None

    def test_cancelled_does_not_affect_others(self, queue: FleetQueue) -> None:
        e1 = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        e2 = queue.enqueue_item(FleetQueueItemKind.VALIDATE)
        queue.cancel_item(e1.queue_item_id)
        eligible = queue.next_runnable_item()
        assert eligible is not None
        assert eligible.queue_item_id == e2.queue_item_id


# ── Content-light enforcement ────────────────────────────────────────────


class TestContentLight:
    def test_queue_events_have_no_forbidden_fields(self, events_path: Path) -> None:
        q = FleetQueue(events_path)
        q.enqueue_item(
            FleetQueueItemKind.MESSAGE,
            payload={"summary": "hello", "stdout": "should-not-appear"},
        )
        q.enqueue_item(
            FleetQueueItemKind.RUNTIME_EXEC,
            payload={"ref": "abc123", "content": "should-not-appear"},
        )
        raw = events_path.read_text(encoding="utf-8")
        for forbidden in _FORBIDDEN_RAW:
            assert forbidden not in raw, (
                f"Found forbidden field '{forbidden}' in queue events"
            )

    def test_snapshot_dump_has_no_forbidden_fields(self, queue: FleetQueue) -> None:
        queue.enqueue_item(
            FleetQueueItemKind.MESSAGE, payload={"summary": "ok", "secret": "stripped"}
        )
        snap = queue.list_items()
        dumped = json.dumps(snap.model_dump(mode="json"))
        for forbidden in _FORBIDDEN_RAW:
            assert forbidden not in dumped, (
                f"Found forbidden field '{forbidden}' in snapshot dump"
            )

    def test_event_model_rejects_raw_fields(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            FleetQueueEvent.model_validate({
                "queue_item_id": "x",
                "event_kind": "enqueued",
                "stdout": "huge-output",
            })

    def test_item_model_rejects_raw_fields(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            FleetQueueItem.model_validate({
                "queue_item_id": "x",
                "kind": "message",
                "content": "full-diff",
            })


# ── Schema validation ────────────────────────────────────────────────────


class TestSchemaValidation:
    def test_queue_item_validates(
        self, queue: FleetQueue, queue_item_schema: dict
    ) -> None:
        queue.enqueue_item(FleetQueueItemKind.RUNTIME_EXEC, payload={"ref": "abc"})
        snap = queue.list_items()
        item = snap.items[0]
        validator = jsonschema.Draft7Validator(queue_item_schema)
        errors = list(validator.iter_errors(item.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_queue_event_validates(
        self, queue: FleetQueue, queue_event_schema: dict
    ) -> None:
        raw_events = queue._read_events()
        validator = jsonschema.Draft7Validator(queue_event_schema)
        for event_dict in raw_events:
            errors = list(validator.iter_errors(event_dict))
            assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_minimal_item_validates(self, queue_item_schema: dict) -> None:
        item = FleetQueueItem(queue_item_id="i1", kind="message")
        validator = jsonschema.Draft7Validator(queue_item_schema)
        errors = list(validator.iter_errors(item.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_minimal_event_validates(self, queue_event_schema: dict) -> None:
        event = FleetQueueEvent(queue_item_id="i1", event_kind="enqueued")
        validator = jsonschema.Draft7Validator(queue_event_schema)
        errors = list(validator.iter_errors(event.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_rejects_forbidden_fields(self, queue_item_schema: dict) -> None:
        validator = jsonschema.Draft7Validator(queue_item_schema)
        errors = list(
            validator.iter_errors({
                "queue_item_id": "i1",
                "kind": "message",
                "status": "queued",
                "priority": 0,
                "depends_on": [],
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
                "unknown": "boom",
            })
        )
        assert len(errors) >= 1

    def test_schema_validates_without_exclude_none(
        self, queue_item_schema: dict
    ) -> None:
        item = FleetQueueItem(queue_item_id="i1", kind="message")
        validator = jsonschema.Draft7Validator(queue_item_schema)
        errors = list(validator.iter_errors(item.model_dump(mode="json")))
        assert errors == [], (
            "model_dump(mode='json') must validate without exclude_none=True"
        )


# ── Edge cases ───────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_next_runnable_empty_queue(self, queue: FleetQueue) -> None:
        assert queue.next_runnable_item() is None

    def test_next_runnable_all_taken(self, queue: FleetQueue) -> None:
        e = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        queue.mark_running(e.queue_item_id)
        assert queue.next_runnable_item() is None

    def test_next_runnable_skips_blocked(self, queue: FleetQueue) -> None:
        e = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        queue.mark_blocked(e.queue_item_id, reason="conflict")
        assert queue.next_runnable_item() is None

    def test_next_runnable_skips_completed(self, queue: FleetQueue) -> None:
        e = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        queue.mark_completed(e.queue_item_id)
        assert queue.next_runnable_item() is None

    def test_missing_dependency_not_runnable(self, queue: FleetQueue) -> None:
        queue.enqueue_item(
            FleetQueueItemKind.RUNTIME_EXEC, depends_on=["nonexistent-dep"]
        )
        assert queue.next_runnable_item() is None

    def test_mark_on_nonexistent_returns_none(self, queue: FleetQueue) -> None:
        assert queue.mark_running("nonexistent") is None
        assert queue.mark_completed("nonexistent") is None
        assert queue.mark_failed("nonexistent") is None
        assert queue.mark_blocked("nonexistent") is None

    def test_multiple_events_persist_in_order(self, events_path: Path) -> None:
        q = FleetQueue(events_path)
        e1 = q.enqueue_item(FleetQueueItemKind.MESSAGE)
        e2 = q.enqueue_item(FleetQueueItemKind.VALIDATE)
        q.mark_running(e2.queue_item_id)
        q.mark_completed(e2.queue_item_id)

        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 4

        parsed = [json.loads(line) for line in lines]
        assert parsed[0]["event_kind"] == "enqueued"
        assert parsed[0]["queue_item_id"] == e1.queue_item_id
        assert parsed[1]["event_kind"] == "enqueued"
        assert parsed[1]["queue_item_id"] == e2.queue_item_id
        assert parsed[2]["event_kind"] == "status_changed"
        assert parsed[3]["event_kind"] == "status_changed"

    def test_running_then_running_noop(self, queue: FleetQueue) -> None:
        e = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        queue.mark_running(e.queue_item_id)
        assert queue.mark_running(e.queue_item_id) is None

    def test_reason_in_payload(self, queue: FleetQueue) -> None:
        e = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        event = queue.mark_blocked(e.queue_item_id, reason="lease held by agent-2")
        assert event is not None
        assert event.payload.get("reason") == "lease held by agent-2"

    def test_parent_dirs_created(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c" / "events.jsonl"
        q = FleetQueue(deep)
        q.enqueue_item(FleetQueueItemKind.MESSAGE)
        assert deep.exists()

    def test_snapshot_includes_all_status_counts(self, queue: FleetQueue) -> None:
        e1 = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        e2 = queue.enqueue_item(FleetQueueItemKind.VALIDATE)
        queue.enqueue_item(FleetQueueItemKind.RUNTIME_EXEC)
        queue.mark_running(e1.queue_item_id)
        queue.mark_completed(e1.queue_item_id)
        queue.mark_blocked(e2.queue_item_id, reason="waiting")
        snap = queue.list_items()
        assert snap.status_counts.get("completed") == 1
        assert snap.status_counts.get("blocked") == 1
        assert snap.status_counts.get("queued") == 1


# ── Kind-specific items ──────────────────────────────────────────────────


class TestItemKinds:
    def test_message_kind(self, queue: FleetQueue) -> None:
        queue.enqueue_item("message")
        snap = queue.list_items()
        assert snap.items[0].kind == "message"

    def test_runtime_exec_kind(self, queue: FleetQueue) -> None:
        queue.enqueue_item("runtime_exec")
        snap = queue.list_items()
        assert snap.items[0].kind == "runtime_exec"

    def test_validate_kind(self, queue: FleetQueue) -> None:
        queue.enqueue_item("validate")
        snap = queue.list_items()
        assert snap.items[0].kind == "validate"

    def test_handoff_note_kind(self, queue: FleetQueue) -> None:
        queue.enqueue_item("handoff_note")
        snap = queue.list_items()
        assert snap.items[0].kind == "handoff_note"

    def test_pause_kind(self, queue: FleetQueue) -> None:
        queue.enqueue_item("pause")
        snap = queue.list_items()
        assert snap.items[0].kind == "pause"

    def test_resume_kind(self, queue: FleetQueue) -> None:
        queue.enqueue_item("resume")
        snap = queue.list_items()
        assert snap.items[0].kind == "resume"


# ── Replay diagnostics ───────────────────────────────────────────────────


class TestReplayDiagnostics:
    def test_empty_queue_report(self, queue: FleetQueue) -> None:
        snap = queue.list_items()
        assert snap.replay_report is not None
        assert snap.replay_report.total_lines == 0
        assert snap.replay_report.valid_events == 0

    def test_clean_replay_report(self, queue: FleetQueue) -> None:
        e1 = queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        queue.enqueue_item(FleetQueueItemKind.VALIDATE)
        queue.mark_completed(e1.queue_item_id)
        snap = queue.list_items()
        r = snap.replay_report
        assert r is not None
        assert r.total_lines == 3
        assert r.valid_events == 3
        assert r.malformed_lines == 0
        assert r.invalid_events == 0
        assert r.skipped_unknown_kind == 0
        assert r.total_skipped == 0

    def test_malformed_json_report(self, tmp_path: Path) -> None:
        p = tmp_path / "q" / "e.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text(
            '{"queue_item_id":"i1","event_kind":"enqueued",'
            '"payload":{"queue_item_id":"i1","kind":"message",'
            '"status":"queued","priority":0,"depends_on":[],'
            '"created_at":"2026-01-01T00:00:00","updated_at":"2026-01-01T00:00:00"}}\n'
            "not-json\n"
            '{"queue_item_id":"i2","event_kind":"enqueued",'
            '"payload":{"queue_item_id":"i2","kind":"validate",'
            '"status":"queued","priority":0,"depends_on":[],'
            '"created_at":"2026-01-01T00:00:00","updated_at":"2026-01-01T00:00:00"}}\n',
            encoding="utf-8",
        )
        q = FleetQueue(p)
        snap = q.list_items()
        r = snap.replay_report
        assert r is not None
        assert r.total_lines == 3
        assert r.valid_events == 2
        assert r.malformed_lines == 1
        assert r.total_skipped == 1

    def test_invalid_event_record_report(self, tmp_path: Path) -> None:
        p = tmp_path / "q" / "events.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text(
            '{"queue_item_id":"i1","event_kind":"enqueued",'
            '"payload":{"queue_item_id":"i1","kind":"message",'
            '"status":"queued","priority":0,"depends_on":[],'
            '"created_at":"2026-01-01T00:00:00","updated_at":"2026-01-01T00:00:00"}}\n'
            '{"queue_item_id":"i2","event_kind":"unknown_kind",'
            '"created_at":"2026-01-01T00:00:00"}\n',
            encoding="utf-8",
        )
        q = FleetQueue(p)
        snap = q.list_items()
        r = snap.replay_report
        assert r is not None
        assert r.total_lines == 2
        assert r.valid_events == 2
        assert r.malformed_lines == 0
        # unknown_kind event is NOT an invalid_events (it parses as FleetQueueEvent)
        # but it IS skipped_unknown_kind
        assert r.skipped_unknown_kind == 1
        assert r.total_skipped == 1

    def test_report_content_light(self, queue: FleetQueue) -> None:
        queue.enqueue_item(FleetQueueItemKind.MESSAGE)
        snap = queue.list_items()
        assert snap.replay_report is not None
        dumped = json.dumps(snap.replay_report.model_dump(mode="json"))
        assert "stdout" not in dumped
        assert "content" not in dumped
        assert "prompt" not in dumped

    def test_empty_lines_do_not_count_as_malformed(self, tmp_path: Path) -> None:
        p = tmp_path / "q" / "e.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text(
            '{"queue_item_id":"i1","event_kind":"enqueued",'
            '"payload":{"queue_item_id":"i1","kind":"message",'
            '"status":"queued","priority":0,"depends_on":[],'
            '"created_at":"2026-01-01T00:00:00","updated_at":"2026-01-01T00:00:00"}}\n'
            "\n"
            "\n",
            encoding="utf-8",
        )
        q = FleetQueue(p)
        snap = q.list_items()
        r = snap.replay_report
        assert r is not None
        assert r.total_lines == 3
        assert r.valid_events == 1
        assert r.malformed_lines == 0
        assert r.total_skipped == 0
