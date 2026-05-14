"""Rig Fleet Queue — Phase 0.

A minimal fleet queue/scheduler primitive that allows an orchestrator to
accept typed queue items, order them deterministically, and dispatch eligible
items one at a time.

Design:
  - Items are submitted via enqueue_item() which appends a FleetQueueEvent.
  - The canonical source is an append-only JSONL file built from FleetQueueEvent.
  - The current FleetQueueSnapshot is derived by replaying events on read.
  - Content-light: no raw prompts, stdout, stderr, content, diffs, patches,
    secrets, argv, snippets, or file contents in queue events.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.coordination._canonical_json import dump_canonical_json

# ── Enums ────────────────────────────────────────────────────────────────


class FleetQueueItemKind(str):
    """Typed queue item kinds for fleet coordination."""

    MESSAGE = "message"
    RUNTIME_EXEC = "runtime_exec"
    VALIDATE = "validate"
    HANDOFF_NOTE = "handoff_note"
    PAUSE = "pause"
    RESUME = "resume"


class FleetQueueItemStatus(str):
    """State machine status for a queue item."""

    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class FleetQueueEventKind(str):
    """Event kinds for the append-only queue event log."""

    ENQUEUED = "enqueued"
    CANCELLED = "cancelled"
    STATUS_CHANGED = "status_changed"
    SUPERSEDED_BY = "superseded_by"


_TERMINAL_STATUSES: frozenset[str] = frozenset({
    FleetQueueItemStatus.COMPLETED,
    FleetQueueItemStatus.FAILED,
    FleetQueueItemStatus.CANCELLED,
    FleetQueueItemStatus.SUPERSEDED,
})


# ── Models ───────────────────────────────────────────────────────────────


class FleetQueueItem(BaseModel):
    """A typed item in the fleet queue.

    Content-light: payload carries only summary/hash/ref, never raw data.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.fleet.queue_item.v1"
    queue_item_id: str
    kind: str  # FleetQueueItemKind value
    status: str = FleetQueueItemStatus.QUEUED
    priority: int = 0
    depends_on: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    mission_id: str | None = None
    agent_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    blocked_reason: str | None = None
    superseded_by: str | None = None


class FleetQueueEvent(BaseModel):
    """A single event in the append-only queue event log.

    Content-light: no raw prompts, stdout, content, diffs, patches, secrets,
    argv, snippets, or file contents.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.fleet.queue_event.v1"
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    queue_item_id: str
    event_kind: str  # FleetQueueEventKind value
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    mission_id: str | None = None
    agent_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class FleetQueueSnapshot(BaseModel):
    """Derived current state of the fleet queue, rebuilt from events."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.fleet.queue_snapshot.v1"
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    items: list[FleetQueueItem] = Field(default_factory=list)
    total_count: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    replay_report: FleetQueueReplayReport | None = None


class FleetQueueReplayReport(BaseModel):
    """Diagnostics from replaying the queue event log.

    Content-light: counts only, no raw event data.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.fleet.replay_report.v1"
    total_lines: int = 0
    valid_events: int = 0
    malformed_lines: int = 0
    invalid_events: int = 0
    skipped_unknown_kind: int = 0
    total_skipped: int = 0


# ── Forbidden raw field names (content-light enforcement) ────────────────

_FORBIDDEN_RAW_FIELD_NAMES: frozenset[str] = frozenset({
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


# ── Queue implementation ────────────────────────────────────────────────


class FleetQueue:
    """Minimal append-only event-sourced fleet queue.

    Not thread-safe. Not multi-process safe. Phase 0 — no locking.
    """

    def __init__(self, events_path: Path) -> None:
        self._events_path = events_path
        self._events_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Mutation operations ──────────────────────────────────────────

    def enqueue_item(
        self,
        kind: str,
        *,
        queue_item_id: str | None = None,
        mission_id: str | None = None,
        agent_id: str | None = None,
        priority: int = 0,
        depends_on: list[str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> FleetQueueEvent:
        """Create a new queue item and append an enqueued event."""
        item_id = queue_item_id or str(uuid4())
        now = datetime.now(UTC).isoformat()
        item = FleetQueueItem(
            queue_item_id=item_id,
            kind=kind,
            status=FleetQueueItemStatus.QUEUED,
            priority=priority,
            depends_on=depends_on or [],
            created_at=now,
            updated_at=now,
            mission_id=mission_id,
            agent_id=agent_id,
            payload=_sanitise_payload(payload or {}),
        )
        event = FleetQueueEvent(
            queue_item_id=item_id,
            event_kind=FleetQueueEventKind.ENQUEUED,
            created_at=now,
            mission_id=mission_id,
            agent_id=agent_id,
            payload=item.model_dump(mode="json"),
        )
        self._append_event(event)
        return event

    def cancel_item(
        self, queue_item_id: str, *, reason: str | None = None
    ) -> FleetQueueEvent | None:
        """Mark a queued item as cancelled. Returns None if item not found."""
        item = self._find_item(queue_item_id)
        if item is None:
            return None
        if item.status == FleetQueueItemStatus.CANCELLED:
            return None
        payload: dict[str, Any] = {}
        if reason:
            payload["reason"] = reason
        event = FleetQueueEvent(
            queue_item_id=queue_item_id,
            event_kind=FleetQueueEventKind.CANCELLED,
            payload=payload,
        )
        self._append_event(event)
        return event

    def mark_running(self, queue_item_id: str) -> FleetQueueEvent | None:
        return self._status_change_event(queue_item_id, FleetQueueItemStatus.RUNNING)

    def mark_completed(self, queue_item_id: str) -> FleetQueueEvent | None:
        return self._status_change_event(queue_item_id, FleetQueueItemStatus.COMPLETED)

    def mark_failed(
        self, queue_item_id: str, *, reason: str | None = None
    ) -> FleetQueueEvent | None:
        return self._status_change_event(
            queue_item_id, FleetQueueItemStatus.FAILED, reason=reason
        )

    def mark_blocked(
        self, queue_item_id: str, *, reason: str | None = None
    ) -> FleetQueueEvent | None:
        return self._status_change_event(
            queue_item_id, FleetQueueItemStatus.BLOCKED, reason=reason
        )

    # ── Read operations ──────────────────────────────────────────────

    def list_items(self) -> FleetQueueSnapshot:
        """Rebuild and return the current queue snapshot from events.

        Returns a snapshot with an embedded FleetQueueReplayReport tracking
        malformed lines, invalid events, and skipped unknown kinds.
        """
        return self._replay_from_file()

    def next_runnable_item(self) -> FleetQueueItem | None:
        """Return the next eligible item, or None.

        Ordering:
          1. Only queued items (not cancelled/running/completed/etc.)
          2. depends_on must be in a terminal state (completed/failed/cancelled/superseded)
          3. Highest priority first, then FIFO by created_at, then queue_item_id.
        """
        snapshot = self.list_items()
        terminal = _TERMINAL_STATUSES

        eligible: list[FleetQueueItem] = []
        item_map = {item.queue_item_id: item for item in snapshot.items}
        for item in snapshot.items:
            if item.status != FleetQueueItemStatus.QUEUED:
                continue
            if not item.depends_on:
                eligible.append(item)
                continue
            all_met = True
            for dep_id in item.depends_on:
                dep = item_map.get(dep_id)
                if dep is None or dep.status not in terminal:
                    all_met = False
                    break
            if all_met:
                eligible.append(item)

        eligible.sort(key=lambda i: (-i.priority, i.created_at, i.queue_item_id))
        return eligible[0] if eligible else None

    # ── Internal helpers ─────────────────────────────────────────────

    def _status_change_event(
        self, queue_item_id: str, new_status: str, *, reason: str | None = None
    ) -> FleetQueueEvent | None:
        prev = self._find_item(queue_item_id)
        if prev is None:
            return None
        if prev.status == new_status:
            return None
        payload: dict[str, Any] = {"status": new_status, "previous_status": prev.status}
        if reason:
            payload["reason"] = reason
        event = FleetQueueEvent(
            queue_item_id=queue_item_id,
            event_kind=FleetQueueEventKind.STATUS_CHANGED,
            payload=payload,
        )
        self._append_event(event)
        return event

    def _find_item(self, queue_item_id: str) -> FleetQueueItem | None:
        events = self._read_events()
        snapshot = self._replay(events)
        for item in snapshot.items:
            if item.queue_item_id == queue_item_id:
                return item
        return None

    def _append_event(self, event: FleetQueueEvent) -> None:
        line = dump_canonical_json(event.model_dump(mode="json")) + "\n"
        with open(self._events_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()

    def _read_events(self) -> list[dict[str, Any]]:
        if not self._events_path.exists():
            return []
        raw: list[dict[str, Any]] = []
        with open(self._events_path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        raw.append(json.loads(stripped))
                    except JSONDecodeError:
                        continue
        return raw

    @staticmethod
    def _replay(raw_events: list[dict[str, Any]]) -> FleetQueueSnapshot:
        """Rebuild queue state from an ordered list of event dicts."""
        state: dict[str, FleetQueueItem] = {}
        for event_dict in raw_events:
            try:
                event = FleetQueueEvent.model_validate(event_dict)
            except Exception:
                continue
            FleetQueue._apply_event(state, event)

        items = list(state.values())
        total = len(items)
        counts: dict[str, int] = {}
        for s in _TERMINAL_STATUSES | {
            FleetQueueItemStatus.QUEUED,
            FleetQueueItemStatus.RUNNING,
            FleetQueueItemStatus.BLOCKED,
        }:
            c = sum(1 for i in items if i.status == s)
            if c:
                counts[s] = c

        return FleetQueueSnapshot(items=items, total_count=total, status_counts=counts)

    def _replay_from_file(self) -> FleetQueueSnapshot:
        """Read events file, parse, replay, and build snapshot with diagnostics."""
        if not self._events_path.exists():
            report = FleetQueueReplayReport(total_lines=0)
            return FleetQueueSnapshot(
                items=[], total_count=0, status_counts={}, replay_report=report
            )

        total_lines = 0
        parsed: list[dict[str, Any]] = []
        malformed_lines = 0
        with open(self._events_path, encoding="utf-8") as f:
            for line in f:
                total_lines += 1
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    parsed.append(json.loads(stripped))
                except JSONDecodeError:
                    malformed_lines += 1

        snapshot = FleetQueue._replay(parsed)

        valid_events = len(parsed)
        total_skipped = malformed_lines

        # Count invalid events and skipped unknown kinds from replay state
        invalid_events = 0
        skipped_unknown_kind = 0
        for event_dict in parsed:
            try:
                event = FleetQueueEvent.model_validate(event_dict)
            except Exception:
                invalid_events += 1
                total_skipped += 1
                continue
            if event.event_kind not in {
                FleetQueueEventKind.ENQUEUED,
                FleetQueueEventKind.CANCELLED,
                FleetQueueEventKind.STATUS_CHANGED,
                FleetQueueEventKind.SUPERSEDED_BY,
            }:
                skipped_unknown_kind += 1
                total_skipped += 1

        report = FleetQueueReplayReport(
            total_lines=total_lines,
            valid_events=valid_events,
            malformed_lines=malformed_lines,
            invalid_events=invalid_events,
            skipped_unknown_kind=skipped_unknown_kind,
            total_skipped=total_skipped,
        )
        return snapshot.model_copy(update={"replay_report": report})

    @staticmethod
    def _apply_event(state: dict[str, FleetQueueItem], event: FleetQueueEvent) -> None:
        item_id = event.queue_item_id
        ek = event.event_kind
        if ek == FleetQueueEventKind.ENQUEUED:
            try:
                item = FleetQueueItem.model_validate(event.payload)
            except Exception:
                return
            state[item_id] = item
        elif ek == FleetQueueEventKind.CANCELLED:
            if item_id in state:
                state[item_id].status = FleetQueueItemStatus.CANCELLED
                state[item_id].updated_at = event.created_at
                if "reason" in event.payload:
                    state[item_id].blocked_reason = str(event.payload["reason"])
        elif ek == FleetQueueEventKind.STATUS_CHANGED:
            if item_id in state:
                new_status = event.payload.get("status")
                if new_status:
                    state[item_id].status = str(new_status)
                    state[item_id].updated_at = event.created_at
                reason = event.payload.get("reason")
                if reason and new_status == FleetQueueItemStatus.BLOCKED:
                    state[item_id].blocked_reason = str(reason)
        elif ek == FleetQueueEventKind.SUPERSEDED_BY:
            if item_id in state:
                state[item_id].status = FleetQueueItemStatus.SUPERSEDED
                state[item_id].updated_at = event.created_at
                superseded_by = event.payload.get("superseded_by")
                if superseded_by:
                    state[item_id].superseded_by = str(superseded_by)


def _sanitise_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip forbidden raw field keys from a payload dict."""
    return {k: v for k, v in payload.items() if k not in _FORBIDDEN_RAW_FIELD_NAMES}


__all__ = [
    "FleetQueue",
    "FleetQueueEvent",
    "FleetQueueEventKind",
    "FleetQueueItem",
    "FleetQueueItemKind",
    "FleetQueueItemStatus",
    "FleetQueueReplayReport",
    "FleetQueueSnapshot",
]
