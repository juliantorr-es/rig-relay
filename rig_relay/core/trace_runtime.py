from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace

from rig_relay.core.logger import logger
from rig_relay.core.tracing import (
    agent_span as _agent_span,
    set_tool_result as _set_tool_result,
    tool_span as _tool_span,
)


@dataclass(slots=True)
class TraceRuntime:
    """Owns correlation IDs and OTel propagation.

    Ensures session_id, turn_id, tool_call_id, receipt_sha256,
    baseline_id survive all paths incl. refusal and degradation.
    """

    session_id: str = ""
    trace_recorder: Any | None = None

    _current_turn_id: str = field(default="", repr=False)
    _current_tool_call_id: str = field(default="", repr=False)
    _baseline_id: str = field(default="", repr=False)
    _receipt_sha256: str = field(default="", repr=False)

    def get_correlation_context(self) -> dict[str, str]:
        return {
            "session_id": self.session_id,
            "turn_id": self._current_turn_id,
            "tool_call_id": self._current_tool_call_id,
            "baseline_id": self._baseline_id,
        }

    @asynccontextmanager
    async def agent_span(
        self, model: str = "", **attrs: Any
    ) -> AsyncGenerator[trace.Span]:
        async with _agent_span(
            model=model or None, session_id=self.session_id or None
        ) as span:
            yield span

    @asynccontextmanager
    async def tool_span(
        self, tool_name: str = "", call_id: str = "", arguments: str = "", **attrs: Any
    ) -> AsyncGenerator[trace.Span]:
        self._current_tool_call_id = call_id
        async with _tool_span(
            tool_name=tool_name, call_id=call_id, arguments=arguments
        ) as span:
            yield span

    @staticmethod
    def set_tool_result(span: trace.Span, text: str) -> None:
        _set_tool_result(span, text)

    def capture_trace_id(self) -> str:
        try:
            span = trace.get_current_span()
            ctx = span.get_span_context() if span else None
            if ctx is not None and ctx.is_valid:
                return format(ctx.trace_id, "032x")
        except Exception:
            logger.debug("Failed to capture trace_id", exc_info=True)
        return ""

    def emit_lifecycle_event(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            tracer = trace.get_tracer("rig_relay")
            with tracer.start_as_current_span(
                f"lifecycle.{event_type}", attributes=payload
            ):
                pass
        except Exception:
            logger.debug(
                "Failed to emit lifecycle event: %s", event_type, exc_info=True
            )
