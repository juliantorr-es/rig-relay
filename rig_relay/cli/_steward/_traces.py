"""Trace instrumentation for the OpenCode Idle Steward.

Owns: correlated trace context creation, span lifecycle, trace event emission.
Delegates to rig_relay.tracing for the canonical trace infrastructure.
Provides symmetric correlation across steward → opencode → tool boundaries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rig_relay.cli._steward._constants import sha256
from rig_relay.tracing.context import (
    TraceContext,
    child_trace_context,
    clear_trace_context,
    get_current_trace_context,
    set_trace_context,
)
from rig_relay.tracing.golden_path import build_golden_path_event
from rig_relay.tracing.models import new_span_id, new_trace_id
from rig_relay.tracing.store import get_default_trace_store


class StewardTrace:
    """Root trace carrier for a single steward invocation.

    Creates a root trace on init, emits lifecycle events at each phase,
    and propagates the trace context via contextvars so downstream code
    (e.g. capsule assembly, opencode events) can pick it up.
    """

    def __init__(self, task_id: str = "", project_root: str = "") -> None:
        self.trace_id = new_trace_id()
        self.root_span_id = new_span_id()
        self.task_id = task_id
        self.project_root = project_root
        self._store = get_default_trace_store()
        self._phase_spans: dict[str, str] = {}
        self._started_at = datetime.now(UTC)

    def start(self) -> None:
        ctx = TraceContext(
            trace_id=self.trace_id,
            span_id=self.root_span_id,
            session_id=self.task_id,
            lane_id=self.task_id,
        )
        set_trace_context(ctx)
        self._emit(
            "steward.invocation.started",
            {"task_id": self.task_id, "project_root_sha256": sha256(self.project_root)},
        )

    def span(self, phase: str) -> None:
        ctx = child_trace_context()
        self._phase_spans[phase] = ctx.span_id
        set_trace_context(ctx)
        self._emit(f"steward.phase.{phase}.started", {})

    def end_span(self, phase: str) -> None:
        span_id = self._phase_spans.pop(phase, "")
        self._emit(f"steward.phase.{phase}.completed", {"span_id": span_id})

    def event(self, name: str, payload: dict[str, Any] | None = None) -> None:
        self._emit(f"steward.{name}", payload or {})

    def finish(self, state: str, exit_code: int | None = None) -> None:
        duration_ms = int((datetime.now(UTC) - self._started_at).total_seconds() * 1000)
        self._emit(
            "steward.invocation.finished",
            {"state": state, "exit_code": exit_code, "duration_ms": duration_ms},
        )
        clear_trace_context()

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            ctx = get_current_trace_context()
            event = build_golden_path_event(
                event_type=event_type,
                correlation={
                    "trace_id": ctx.trace_id,
                    "span_id": ctx.span_id,
                    "session_id": ctx.session_id,
                },
                payload=payload,
            )
            self._store.write(event)
        except Exception:
            pass


__all__ = ["StewardTrace"]
