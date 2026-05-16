"""Trace recorder — start/end spans, emit events, context manager support."""

from __future__ import annotations

from contextlib import contextmanager
import time

from rig_relay.tracing.context import (
    child_trace_context,
    get_current_trace_context,
    set_trace_context,
)
from rig_relay.tracing.models import (
    RigTraceEvent,
    TraceEventKind,
    TraceStatus,
    new_span_id,
    new_trace_id,
)
from rig_relay.tracing.store import TraceStore, get_default_trace_store


class _ActiveSpan:
    __slots__ = (
        "_recorder",
        "name",
        "span_id",
        "trace_id",
        "parent_span_id",
        "started_at",
    )

    def __init__(
        self,
        recorder: TraceRecorder,
        name: str,
        span_id: str,
        trace_id: str,
        parent_span_id: str | None,
    ) -> None:
        self._recorder = recorder
        self.name = name
        self.span_id = span_id
        self.trace_id = trace_id
        self.parent_span_id = parent_span_id
        self.started_at = time.time()

    def set_status(self, status: TraceStatus, error: str | None = None) -> None:
        attrs: dict[str, object] = {"status": status.value}
        if error:
            attrs["error"] = error
        self._recorder.event(
            "status",
            attributes=attrs,
            context_override={"span_id": self.span_id, "trace_id": self.trace_id},
        )

    def event(self, name: str, attributes: dict[str, object] | None = None) -> None:
        self._recorder.event(
            name,
            attributes=attributes,
            context_override={
                "span_id": self.span_id,
                "trace_id": self.trace_id,
                "parent_span_id": self.span_id,
            },
        )


class TraceRecorder:
    def __init__(self, store: TraceStore | None = None) -> None:
        self._store = store

    @property
    def store(self) -> TraceStore:
        if self._store is None:
            self._store = get_default_trace_store()
        return self._store

    def start_span(
        self,
        name: str,
        attributes: dict[str, object] | None = None,
        context: dict[str, str] | None = None,
    ) -> _ActiveSpan:
        ctx = child_trace_context()
        span_id = ctx.span_id
        trace_id = ctx.trace_id
        parent_span_id = ctx.parent_span_id

        if context:
            if "span_id" in context:
                span_id = context["span_id"]
            if "trace_id" in context:
                trace_id = context["trace_id"]

        set_trace_context(ctx)

        event = RigTraceEvent(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            event_kind=TraceEventKind.span_start,
            name=name,
            attributes=attributes or {},
        )
        self.store.write(event)

        return _ActiveSpan(self, name, span_id, trace_id, parent_span_id)

    def end_span(
        self,
        span: _ActiveSpan,
        status: TraceStatus = TraceStatus.ok,
        attributes: dict[str, object] | None = None,
        error: str | None = None,
        receipt_sha256: str | None = None,
    ) -> None:
        duration_ms = int((time.time() - span.started_at) * 1000)
        final_status = TraceStatus.error if error else status

        event = RigTraceEvent(
            trace_id=span.trace_id,
            span_id=span.span_id,
            parent_span_id=span.parent_span_id,
            event_kind=TraceEventKind.span_end,
            name=span.name,
            status=final_status,
            started_at=_iso(span.started_at),
            ended_at=_iso(time.time()),
            duration_ms=duration_ms,
            attributes=attributes or {},
            error_type=error,
            error_message=error,
            receipt_sha256=receipt_sha256,
        )
        self.store.write(event)

    def event(
        self,
        name: str,
        attributes: dict[str, object] | None = None,
        context_override: dict[str, str] | None = None,
    ) -> None:
        ctx = get_current_trace_context()
        trace_id = ctx.trace_id or new_trace_id()
        span_id = ctx.span_id or new_span_id()
        parent_span_id = ctx.parent_span_id

        if context_override:
            if "trace_id" in context_override:
                trace_id = context_override["trace_id"]
            if "span_id" in context_override:
                span_id = context_override["span_id"]
            if "parent_span_id" in context_override:
                parent_span_id = context_override["parent_span_id"]

        event = RigTraceEvent(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            event_kind=TraceEventKind.span_event,
            name=name,
            attributes=attributes or {},
        )
        self.store.write(event)

    def error(
        self,
        name: str,
        error: str,
        attributes: dict[str, object] | None = None,
        context_override: dict[str, str] | None = None,
    ) -> None:
        ctx = get_current_trace_context()
        trace_id = ctx.trace_id or new_trace_id()
        span_id = ctx.span_id or new_span_id()

        if context_override:
            if "trace_id" in context_override:
                trace_id = context_override["trace_id"]
            if "span_id" in context_override:
                span_id = context_override["span_id"]

        event = RigTraceEvent(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=ctx.parent_span_id,
            event_kind=TraceEventKind.span_error,
            name=name,
            status=TraceStatus.error,
            error_type=name,
            error_message=error[:500],
            attributes=attributes or {},
        )
        self.store.write(event)

    @contextmanager  # type: ignore[arg-type]
    def span(  # noqa: ANN201
        self, name: str, attributes: dict[str, object] | None = None
    ):
        active = self.start_span(name, attributes)
        try:
            yield active
            self.end_span(active, TraceStatus.ok)
        except Exception as exc:
            self.end_span(active, TraceStatus.error, error=str(exc)[:500])
            raise


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))


__all__ = ["TraceRecorder", "_ActiveSpan"]
