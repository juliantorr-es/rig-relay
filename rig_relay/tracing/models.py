"""Rig-owned local tracing substrate — models.

Schema version: rig.trace_event.v1

A trace event answers: what operation, where, which parent, how long,
whether it passed/failed, what safe attributes explain the outcome.
"""

from __future__ import annotations

from enum import StrEnum
import time
import uuid

TRACE_EVENT_SCHEMA = "rig.trace_event.v1"


class TraceStatus(StrEnum):
    ok = "ok"
    error = "error"
    refused = "refused"
    degraded = "degraded"
    cancelled = "cancelled"
    timed_out = "timed_out"
    skipped = "skipped"


class TraceEventKind(StrEnum):
    span_start = "span.start"
    span_end = "span.end"
    span_event = "span.event"
    span_error = "span.error"


class RigTraceEvent:
    __slots__ = (
        "schema_version",
        "trace_id",
        "span_id",
        "parent_span_id",
        "event_kind",
        "name",
        "status",
        "timestamp",
        "started_at",
        "ended_at",
        "duration_ms",
        "attributes",
        "error_type",
        "error_message",
        "receipt_sha256",
        "correlation",
        "authority",
        "redaction",
    )

    def __init__(  # noqa: PLR0913
        self,
        *,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None = None,
        event_kind: TraceEventKind,
        name: str,
        event_type: str | None = None,
        status: TraceStatus | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        duration_ms: int | None = None,
        attributes: dict[str, object] | None = None,
        payload: dict[str, object] | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        receipt_sha256: str | None = None,
        correlation: dict[str, object] | None = None,
        authority: dict[str, object] | None = None,
        redaction: dict[str, object] | None = None,
    ) -> None:
        self.schema_version = TRACE_EVENT_SCHEMA
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.event_kind = event_kind
        self.name = event_type or name
        self.status = status
        self.timestamp = _iso_now()
        self.started_at = started_at
        self.ended_at = ended_at
        self.duration_ms = duration_ms
        self.attributes = payload or attributes or {}
        self.error_type = error_type
        self.error_message = error_message
        self.receipt_sha256 = receipt_sha256
        self.correlation = correlation
        self.authority = authority
        self.redaction = redaction

    @property
    def event_type(self) -> str:
        return self.name

    @property
    def payload(self) -> dict[str, object]:
        return self.attributes

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "schema_version": self.schema_version,
            "event_type": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "event_kind": self.event_kind.value,
            "timestamp": self.timestamp,
        }
        if self.parent_span_id is not None:
            d["parent_span_id"] = self.parent_span_id
        if self.status is not None:
            d["status"] = self.status.value
        if self.started_at is not None:
            d["started_at"] = self.started_at
        if self.ended_at is not None:
            d["ended_at"] = self.ended_at
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        if self.attributes:
            d["payload"] = self.attributes
        if self.error_type is not None:
            d["error_type"] = self.error_type
        if self.error_message is not None:
            d["error_message"] = self.error_message
        if self.receipt_sha256 is not None:
            d["receipt_sha256"] = self.receipt_sha256
        if self.correlation:
            d["correlation"] = self.correlation
        if self.authority:
            d["authority"] = self.authority
        if self.redaction:
            d["redaction"] = self.redaction
        return d


def new_trace_id() -> str:
    return uuid.uuid4().hex


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


__all__ = [
    "TRACE_EVENT_SCHEMA",
    "RigTraceEvent",
    "TraceEventKind",
    "TraceStatus",
    "new_span_id",
    "new_trace_id",
]
