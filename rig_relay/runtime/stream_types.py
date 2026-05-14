# pyright: reportIncompatibleVariableOverride=false
"""Rig Relay Runtime Stream Event Types — Ported from Rig domain/runtime_stream.py.

Defines relay-native stream event models for subprocess execution output.
All events are Pydantic BaseModel with extra="forbid". Content-light for
completion/failure events; output chunks may include live text but are
not indexed into long-lived receipt summaries.

Event lifecycle per invocation:
  status(starting) → [chunks*] → [heartbeats*] → [warnings*] → completion | failure

Provenance (Rig-to-Relay porting doctrine):
  Porting status: reimplement (Rig source: rig/domain/runtime_stream.py).
  Adaptations: Pydantic BaseModel with extra="forbid" instead of frozen dataclass;
  relay-native RuntimeInvocationStatus vocabulary; content-light completion/failure;
  explicit chunk/stream/hash tracking.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.runtime.models import RuntimeInvocationStatus

# ── Constants ──────────────────────────────────────────────────────────

_SCHEMA_VERSION = "rig.relay.runtime_stream_event.v1"

# ── Enums ──────────────────────────────────────────────────────────────


class RuntimeStreamEventKind(StrEnum):
    """Kinds of runtime stream events emitted during execution."""

    STATUS = "status"
    STDOUT_CHUNK = "stdout_chunk"
    STDERR_CHUNK = "stderr_chunk"
    HEARTBEAT = "heartbeat"
    WARNING = "warning"
    COMPLETION = "completion"
    FAILURE = "failure"


class RuntimeStreamWarningKind(StrEnum):
    """Warning kinds for RuntimeWarningEvent."""

    TRUNCATION_APPLIED = "truncation_applied"
    OUTPUT_LIMIT_REACHED = "output_limit_reached"
    CWD_MISSING = "cwd_missing"
    LEASE_INVALID = "lease_invalid"
    GOVERNANCE_BLOCKED = "governance_blocked"
    STALL_DETECTED = "stall_detected"


# ── Event models ──────────────────────────────────────────────────────


class RuntimeStreamEventBase(BaseModel):
    """Base fields shared by all stream events."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION
    event_id: str
    lease_id: str
    request_id: str
    event_kind: RuntimeStreamEventKind
    captured_at: str


class RuntimeStatusEvent(RuntimeStreamEventBase):
    """Emitted when the execution status changes.

    event_kind = status
    """

    event_kind: Literal[RuntimeStreamEventKind.STATUS] = RuntimeStreamEventKind.STATUS
    status: RuntimeInvocationStatus
    message: str | None = None


class RuntimeOutputChunkEvent(RuntimeStreamEventBase):
    """A chunk of captured stdout or stderr text.

    chunk_text is present only for live streaming; it is NOT indexed
    into long-lived receipt summaries. Final byte counts and SHA256
    hashes cover all bytes drained, even after truncation.

    event_kind = stdout_chunk | stderr_chunk
    """

    event_kind: RuntimeStreamEventKind  # stdout_chunk or stderr_chunk
    stream: str  # "stdout" or "stderr"
    chunk_index: int
    chunk_text: str | None = None
    chunk_sha256: str
    chunk_bytes: int
    truncated: bool = False


class RuntimeHeartbeatEvent(RuntimeStreamEventBase):
    """Periodic heartbeat emitted during execution.

    event_kind = heartbeat
    """

    event_kind: Literal[RuntimeStreamEventKind.HEARTBEAT] = (
        RuntimeStreamEventKind.HEARTBEAT
    )
    elapsed_ms: float


class RuntimeWarningEvent(RuntimeStreamEventBase):
    """Non-fatal warning during execution.

    event_kind = warning
    """

    event_kind: Literal[RuntimeStreamEventKind.WARNING] = RuntimeStreamEventKind.WARNING
    warning_kind: str
    message: str


class RuntimeCompletionEvent(RuntimeStreamEventBase):
    """Successful completion of execution.

    Content-light: no raw stdout/stderr text, only hashes and byte counts.
    event_kind = completion
    """

    event_kind: Literal[RuntimeStreamEventKind.COMPLETION] = (
        RuntimeStreamEventKind.COMPLETION
    )
    status: Literal[RuntimeInvocationStatus.SUCCEEDED, RuntimeInvocationStatus.FAILED]
    exit_code: int
    duration_ms: float
    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class RuntimeFailureEvent(RuntimeStreamEventBase):
    """Execution failed, timed out, or was blocked/cancelled.

    Content-light: no raw stdout/stderr text.
    event_kind = failure
    """

    event_kind: Literal[RuntimeStreamEventKind.FAILURE] = RuntimeStreamEventKind.FAILURE
    status: RuntimeInvocationStatus  # failed | timed_out | cancelled | blocked
    error_kind: str
    refusal_reason: str | None = None
    duration_ms: float | None = None
    exit_code: int | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    stdout_bytes: int | None = None
    stderr_bytes: int | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False


# ── Union type for typing consumers ────────────────────────────────────


RuntimeStreamEvent = Annotated[
    RuntimeStatusEvent
    | RuntimeOutputChunkEvent
    | RuntimeHeartbeatEvent
    | RuntimeWarningEvent
    | RuntimeCompletionEvent
    | RuntimeFailureEvent,
    Field(discriminator="event_kind"),
]

__all__ = [
    "RuntimeCompletionEvent",
    "RuntimeFailureEvent",
    "RuntimeHeartbeatEvent",
    "RuntimeOutputChunkEvent",
    "RuntimeStatusEvent",
    "RuntimeStreamEvent",
    "RuntimeStreamEventBase",
    "RuntimeStreamEventKind",
    "RuntimeStreamWarningKind",
    "RuntimeWarningEvent",
]
