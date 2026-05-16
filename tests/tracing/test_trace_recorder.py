from __future__ import annotations

import pytest

from rig_relay.tracing.context import clear_trace_context
from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.store import InMemoryTraceStore, NullTraceStore


@pytest.fixture(autouse=True)
def _clear_context() -> None:
    clear_trace_context()


class TestTraceRecorder:
    def test_recorder_writes_start_and_end(self) -> None:
        store = InMemoryTraceStore()
        rec = TraceRecorder(store)
        with rec.span("test.span", {"k": "v"}):
            pass
        assert len(store.events) == 2
        assert store.events[0]["event_kind"] == "span.start"
        assert store.events[0]["name"] == "test.span"
        assert store.events[1]["event_kind"] == "span.end"
        assert store.events[1]["name"] == "test.span"

    def test_recorder_emits_event_inside_span(self) -> None:
        store = InMemoryTraceStore()
        rec = TraceRecorder(store)
        with rec.span("parent") as span:
            span.event("child.event", {"key": 1})
        kinds = [e["event_kind"] for e in store.events]
        assert kinds == ["span.start", "span.event", "span.end"]

    def test_recorder_error_on_exception(self) -> None:
        store = InMemoryTraceStore()
        rec = TraceRecorder(store)
        with pytest.raises(ValueError, match="boom"):
            with rec.span("failing.span"):
                raise ValueError("boom")
        assert len(store.events) == 2
        end_event = store.events[1]
        assert end_event["status"] == "error"
        assert "boom" in end_event.get("error_message", "")

    def test_recorder_event_outside_span(self) -> None:
        store = InMemoryTraceStore()
        rec = TraceRecorder(store)
        rec.event("standalone", {"ok": True})
        assert len(store.events) == 1
        assert store.events[0]["event_kind"] == "span.event"

    def test_recorder_error_outside_span(self) -> None:
        store = InMemoryTraceStore()
        rec = TraceRecorder(store)
        rec.error("fatal", "something broke", {"code": 500})
        assert len(store.events) == 1
        e = store.events[0]
        assert e["event_kind"] == "span.error"
        assert e["status"] == "error"
        assert e["error_type"] == "fatal"

    def test_null_store_is_noop(self) -> None:
        rec = TraceRecorder(NullTraceStore())
        with rec.span("noop"):
            pass
        rec.event("noop.event")
        rec.error("noop.error", "nothing")
        # No exceptions


class TestNestedSpanParents:
    def test_nested_spans_preserve_parent_span_id(self) -> None:
        store = InMemoryTraceStore()
        rec = TraceRecorder(store)
        with rec.span("root") as root:
            with rec.span("child") as child:
                child.event("leaf")
        parent_ids = [e.get("parent_span_id") for e in store.events]
        assert parent_ids[0] is None  # root has no parent
        assert parent_ids[1] == root.span_id  # child's parent is root
        assert parent_ids[2] == child.span_id  # leaf's parent is child

    def test_same_trace_id_across_nested_spans(self) -> None:
        store = InMemoryTraceStore()
        rec = TraceRecorder(store)
        with rec.span("a"):
            with rec.span("b"):
                pass
        trace_ids = {e["trace_id"] for e in store.events}
        assert len(trace_ids) == 1  # all share one trace_id
