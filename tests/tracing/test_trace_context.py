from __future__ import annotations

import pytest

from rig_relay.tracing.context import (
    TraceContext,
    child_trace_context,
    clear_trace_context,
    get_current_trace_context,
    set_trace_context,
)
from rig_relay.tracing.models import new_span_id, new_trace_id


@pytest.fixture(autouse=True)
def _clear_context() -> None:
    clear_trace_context()


class TestContextPropagation:
    def test_nested_spans_get_parent_span_id(self) -> None:
        root = TraceContext(trace_id=new_trace_id(), span_id=new_span_id())
        set_trace_context(root)

        child = child_trace_context()
        assert child.trace_id == root.trace_id
        assert child.span_id != root.span_id
        assert child.parent_span_id == root.span_id

    def test_clear_context(self) -> None:
        ctx = TraceContext(trace_id=new_trace_id(), span_id=new_span_id())
        set_trace_context(ctx)
        current = get_current_trace_context()
        assert current.trace_id == ctx.trace_id

        clear_trace_context()
        empty = get_current_trace_context()
        assert empty.trace_id == ""

    def test_child_context_keeps_session(self) -> None:
        root = TraceContext(
            trace_id=new_trace_id(),
            span_id=new_span_id(),
            session_id="session-1",
            mission_id="mission-1",
        )
        set_trace_context(root)
        child = child_trace_context()
        assert child.session_id == "session-1"
        assert child.mission_id == "mission-1"

    @pytest.mark.asyncio
    async def test_context_propagates_across_async(self) -> None:
        root = TraceContext(
            trace_id=new_trace_id(), span_id=new_span_id(), session_id="async-session"
        )
        set_trace_context(root)

        async def inner() -> TraceContext:
            return child_trace_context()

        child = await inner()
        assert child.trace_id == root.trace_id
        assert child.session_id == "async-session"
