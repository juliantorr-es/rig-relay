from __future__ import annotations

import json
from pathlib import Path

from rig_relay.tracing.models import (
    RigTraceEvent,
    TraceEventKind,
    new_span_id,
    new_trace_id,
)
from rig_relay.tracing.store import InMemoryTraceStore, JSONLTraceStore, NullTraceStore


class TestNullStore:
    def test_drops_events(self) -> None:
        store = NullTraceStore()
        event = RigTraceEvent(
            trace_id=new_trace_id(),
            span_id=new_span_id(),
            event_kind=TraceEventKind.span_event,
            name="test",
        )
        store.write(event)
        store.close()


class TestInMemoryStore:
    def test_stores_events(self) -> None:
        store = InMemoryTraceStore()
        event = RigTraceEvent(
            trace_id=new_trace_id(),
            span_id=new_span_id(),
            event_kind=TraceEventKind.span_start,
            name="test",
        )
        store.write(event)
        assert len(store.events) == 1
        assert store.events[0]["name"] == "test"


class TestJSONLStore:
    def test_writes_append_only(self, tmp_path: Path) -> None:
        p = tmp_path / "traces" / "trace_events.jsonl"
        store = JSONLTraceStore(p)
        e1 = RigTraceEvent(
            trace_id=new_trace_id(),
            span_id=new_span_id(),
            event_kind=TraceEventKind.span_start,
            name="e1",
        )
        e2 = RigTraceEvent(
            trace_id=new_trace_id(),
            span_id=new_span_id(),
            event_kind=TraceEventKind.span_end,
            name="e2",
        )
        store.write(e1)
        store.write(e2)
        store.close()

        lines = p.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["name"] == "e1"
        assert json.loads(lines[1])["name"] == "e2"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "deep" / "nested" / "trace_events.jsonl"
        store = JSONLTraceStore(p)
        event = RigTraceEvent(
            trace_id=new_trace_id(),
            span_id=new_span_id(),
            event_kind=TraceEventKind.span_event,
            name="test",
        )
        store.write(event)
        store.close()
        assert p.exists()
