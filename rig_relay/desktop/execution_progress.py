"""ExecutionProgressProjection — content-light read model from runtime stream events.

Pure aggregation: transforms a sequence of RuntimeStreamEvent into a compact,
content-light summary suitable for UI/projection consumers.

No file reads, no tool execution, no persistence. All fields are safe to render.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from rig_relay.runtime.stream_types import RuntimeStreamEventKind


class ExecutionProgressProjection(BaseModel):
    """Content-light runtime execution summary for UI/projection consumers.

    Never contains: chunk_text, stdout/stderr (raw), content, diff, snippet,
    argv, or file contents.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.execution_progress_projection.v1"
    invocation_id: str | None = None
    lease_id: str | None = None
    request_id: str | None = None
    workspace_id: str | None = None
    worktree_path: str | None = None
    status: str = "pending"
    started_at: str | None = None
    last_event_at: str | None = None
    elapsed_ms: float | None = None
    heartbeat_count: int = 0
    warning_count: int = 0
    latest_warning_kind: str | None = None
    latest_warning_message: str | None = None
    stdout_bytes: int | None = None
    stderr_bytes: int | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    exit_code: int | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None
    terminal_event_id: str | None = None
    evidence_sha256: str | None = None


def _sanitize_message(message: str | None, max_chars: int = 200) -> str | None:
    """Truncate warning/refusal messages to safe length."""
    if message is None:
        return None
    if len(message) > max_chars:
        return message[:max_chars] + "..."
    return message


_MALFORMED_THRESHOLD = 0.5


def execution_progress_from_runtime_events(
    events: Sequence[Any],
) -> ExecutionProgressProjection:
    """Aggregate a sequence of RuntimeStreamEvent into a content-light projection.

    Accepts RuntimeStreamEvent model instances or dict-like dumps. Malformed
    or unknown events are skipped without crashing. Events are processed in
    provided order (assumed chronological).
    """
    projection = ExecutionProgressProjection()
    total = 0
    skipped = 0

    for event in events:
        total += 1
        try:
            _process_event(projection, event)
        except (ValueError, TypeError, KeyError, AttributeError):
            skipped += 1

    if total > 0 and skipped / total > _MALFORMED_THRESHOLD:
        projection.status = "degraded"

    return projection


def _process_event(projection: ExecutionProgressProjection, event: Any) -> None:
    """Process a single event and update projection in place."""
    kind = _get_event_kind(event)
    if kind is None:
        raise ValueError("Unknown event kind")

    # Update identity fields from any event
    _maybe_set(projection, "invocation_id", _get(event, "event_id"))
    _maybe_set(projection, "lease_id", _get(event, "lease_id"))
    _maybe_set(projection, "request_id", _get(event, "request_id"))

    captured_at = _get(event, "captured_at")
    if captured_at:
        projection.last_event_at = captured_at

    match kind:
        case RuntimeStreamEventKind.STATUS:
            _process_status(projection, event)
        case RuntimeStreamEventKind.HEARTBEAT:
            _process_heartbeat(projection, event)
        case RuntimeStreamEventKind.WARNING:
            _process_warning(projection, event)
        case RuntimeStreamEventKind.STDOUT_CHUNK | RuntimeStreamEventKind.STDERR_CHUNK:
            _process_chunk(projection, event)
        case RuntimeStreamEventKind.COMPLETION:
            _process_completion(projection, event)
        case RuntimeStreamEventKind.FAILURE:
            _process_failure(projection, event)
        case _:
            raise ValueError(f"Unsupported event kind: {kind}")


def _get_event_kind(event: Any) -> RuntimeStreamEventKind | None:
    """Extract event_kind from a model instance or dict."""
    raw = getattr(event, "event_kind", None)
    if raw is None and isinstance(event, dict):
        raw = event.get("event_kind")
    if raw is None:
        return None
    if isinstance(raw, RuntimeStreamEventKind):
        return raw
    try:
        return RuntimeStreamEventKind(raw)
    except ValueError:
        return None


def _get(event: Any, field: str, default: Any = None) -> Any:
    """Safely extract a field from model instance or dict."""
    if hasattr(event, field):
        return getattr(event, field, default)
    if isinstance(event, dict):
        return event.get(field, default)
    return default


def _maybe_set(projection: ExecutionProgressProjection, field: str, value: Any) -> None:
    """Set a projection field if value is not None and not already set."""
    if value is not None:
        current = getattr(projection, field, None)
        if current is None:
            setattr(projection, field, value)


def _process_status(projection: ExecutionProgressProjection, event: Any) -> None:
    """Process a STATUS event."""
    status = _get(event, "status")
    if isinstance(status, str):
        projection.status = status
    elif hasattr(status, "value"):
        projection.status = status.value
    elif status is not None:
        projection.status = str(status)

    captured_at = _get(event, "captured_at")
    projection.last_event_at = captured_at
    # First event that is starting sets started_at
    if projection.started_at is None:
        projection.started_at = captured_at


def _process_heartbeat(projection: ExecutionProgressProjection, event: Any) -> None:
    """Process a HEARTBEAT event."""
    projection.heartbeat_count += 1
    elapsed = _get(event, "elapsed_ms")
    if elapsed is not None:
        projection.elapsed_ms = float(elapsed)
    if projection.status == "pending":
        projection.status = "running"


def _process_warning(projection: ExecutionProgressProjection, event: Any) -> None:
    """Process a WARNING event."""
    projection.warning_count += 1
    warning_kind = _get(event, "warning_kind")
    if warning_kind is not None:
        projection.latest_warning_kind = str(warning_kind)
    message = _get(event, "message")
    if message is not None:
        projection.latest_warning_message = _sanitize_message(str(message))


def _process_chunk(projection: ExecutionProgressProjection, event: Any) -> None:
    """Process an output chunk event — NEVER copy chunk_text."""
    if projection.status == "pending":
        projection.status = "running"
    # Update last_event_at from captured_at (already set in _process_event)


def _process_completion(projection: ExecutionProgressProjection, event: Any) -> None:
    """Process a COMPLETION event — terminal."""
    status = _get(event, "status")
    if isinstance(status, str):
        projection.status = status
    elif hasattr(status, "value"):
        projection.status = status.value
    elif status is not None:
        projection.status = str(status)
    else:
        projection.status = "succeeded"

    exit_code = _get(event, "exit_code")
    if exit_code is not None:
        projection.exit_code = int(exit_code)

    duration = _get(event, "duration_ms")
    if duration is not None:
        projection.elapsed_ms = float(duration)

    stdout_bytes = _get(event, "stdout_bytes")
    if stdout_bytes is not None:
        projection.stdout_bytes = int(stdout_bytes)

    stderr_bytes = _get(event, "stderr_bytes")
    if stderr_bytes is not None:
        projection.stderr_bytes = int(stderr_bytes)

    truncated = _get(event, "stdout_truncated", False)
    if truncated:
        projection.stdout_truncated = True
    truncated = _get(event, "stderr_truncated", False)
    if truncated:
        projection.stderr_truncated = True

    event_id = _get(event, "event_id")
    if event_id is not None:
        projection.terminal_event_id = str(event_id)

    # Evidence SHA256 — use stdout_sha256 as proxy for terminal evidence
    evidence = _get(event, "stdout_sha256")
    if evidence is not None:
        projection.evidence_sha256 = str(evidence)


def _process_failure(projection: ExecutionProgressProjection, event: Any) -> None:
    """Process a FAILURE event — terminal."""
    status = _get(event, "status")
    if isinstance(status, str):
        projection.status = status
    elif hasattr(status, "value"):
        projection.status = status.value
    elif status is not None:
        projection.status = str(status)
    else:
        projection.status = "failed"

    error_kind = _get(event, "error_kind")
    if error_kind is not None:
        projection.error_kind = str(error_kind)

    refusal = _get(event, "refusal_reason")
    if refusal is not None:
        projection.refusal_reason = _sanitize_message(str(refusal))

    duration = _get(event, "duration_ms")
    if duration is not None:
        projection.elapsed_ms = float(duration)

    exit_code = _get(event, "exit_code")
    if exit_code is not None:
        projection.exit_code = int(exit_code)

    stdout_bytes = _get(event, "stdout_bytes")
    if stdout_bytes is not None:
        projection.stdout_bytes = int(stdout_bytes)

    stderr_bytes = _get(event, "stderr_bytes")
    if stderr_bytes is not None:
        projection.stderr_bytes = int(stderr_bytes)

    truncated = _get(event, "stdout_truncated", False)
    if truncated:
        projection.stdout_truncated = True
    truncated = _get(event, "stderr_truncated", False)
    if truncated:
        projection.stderr_truncated = True

    event_id = _get(event, "event_id")
    if event_id is not None:
        projection.terminal_event_id = str(event_id)

    evidence = _get(event, "stdout_sha256")
    if evidence is not None:
        projection.evidence_sha256 = str(evidence)


__all__ = ["ExecutionProgressProjection", "execution_progress_from_runtime_events"]
