"""Rig Relay Tracing — local-first structured runtime evidence.

Usage:
    from rig_relay.tracing import TraceRecorder, get_default_trace_store

    store = get_default_trace_store()
    recorder = TraceRecorder(store)

    with recorder.span("desktop.bridge.start", {"host": "127.0.0.1"}) as span:
        span.event("port_bound", {"port": 9876})
"""

from __future__ import annotations

from rig_relay.tracing.context import (
    TraceContext,
    clear_trace_context,
    get_current_trace_context,
    set_trace_context,
)
from rig_relay.tracing.golden_path import (
    TraceAuthorityKind,
    build_authority,
    build_correlation,
    build_golden_path_event,
    build_redaction,
)
from rig_relay.tracing.models import (
    TRACE_EVENT_SCHEMA,
    RigTraceEvent,
    TraceEventKind,
    TraceStatus,
    new_span_id,
    new_trace_id,
)
from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.redaction import sanitize_trace_attributes
from rig_relay.tracing.store import (
    InMemoryTraceStore,
    JSONLTraceStore,
    NullTraceStore,
    get_default_trace_store,
)

__all__ = [
    "TRACE_EVENT_SCHEMA",
    "InMemoryTraceStore",
    "JSONLTraceStore",
    "NullTraceStore",
    "RigTraceEvent",
    "TraceAuthorityKind",
    "TraceContext",
    "TraceEventKind",
    "TraceRecorder",
    "TraceStatus",
    "build_authority",
    "build_correlation",
    "build_golden_path_event",
    "build_redaction",
    "clear_trace_context",
    "get_current_trace_context",
    "get_default_trace_store",
    "new_span_id",
    "new_trace_id",
    "sanitize_trace_attributes",
    "set_trace_context",
]
