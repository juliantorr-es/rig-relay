"""Cross-cutting trace emission helpers extracted from ConversationRuntime.

Architecture boundary: must NOT import desktop, ralph, scripts,
duckdb, or analytics.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from rig_relay.core.conversation_runtime.models import PhaseTraceAttributes

if TYPE_CHECKING:
    from rig_relay.core.conversation_runtime.models import PhaseTraceHook


def build_trace_attrs(
    session_id: str,
    turn_id: str,
    phase: str,
    *,
    previous: str | None = None,
    status: str | None = None,
    reason: str | None = None,
    tool_call_count: int | None = None,
    start_time: float | None = None,
    trace_id: str | None = None,
) -> PhaseTraceAttributes:
    """Build JSON-safe trace attributes for a phase transition."""
    duration_ms: float | None = None
    if start_time is not None and start_time >= 0:
        duration_ms = (time.monotonic() - start_time) * 1000
    return PhaseTraceAttributes(
        conversation_session_id=session_id,
        conversation_turn_id=turn_id or None,
        conversation_phase=phase,
        conversation_previous_phase=previous,
        conversation_status=status,
        conversation_reason=reason,
        conversation_tool_call_count=tool_call_count,
        conversation_duration_ms=duration_ms,
        trace_id=trace_id,
    )


def emit_phase_event(trace_hook: PhaseTraceHook, attrs: PhaseTraceAttributes) -> None:
    """Invoke the on_phase_event callback with trace attributes."""
    trace_hook.on_phase_event(attrs)


def emit_result_event(trace_hook: PhaseTraceHook, attrs: PhaseTraceAttributes) -> None:
    """Invoke the on_result callback with trace attributes."""
    trace_hook.on_result(attrs)


def capture_trace_id() -> str | None:
    """Capture the current OTel span's trace_id, or None if unavailable."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx is not None and ctx.is_valid:
            return format(ctx.trace_id, "032x")
    except Exception:
        pass
    return None
