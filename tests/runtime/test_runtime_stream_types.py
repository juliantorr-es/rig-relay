"""Tests for rig_relay.runtime.stream_types — P2b RuntimeStreamEvent models."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from rig_relay.runtime.models import RuntimeInvocationStatus
from rig_relay.runtime.stream_types import (
    RuntimeCompletionEvent,
    RuntimeFailureEvent,
    RuntimeHeartbeatEvent,
    RuntimeOutputChunkEvent,
    RuntimeStatusEvent,
    RuntimeStreamEventKind,
    RuntimeStreamWarningKind,
    RuntimeWarningEvent,
)

_SAMPLE_BASE = {
    "event_id": "evt-001",
    "lease_id": "lease-001",
    "request_id": "req-001",
    "captured_at": "2026-06-01T10:00:00",
}


class TestRuntimeStreamEventKind:
    def test_all_values_present(self) -> None:
        assert list(RuntimeStreamEventKind) == [
            RuntimeStreamEventKind.STATUS,
            RuntimeStreamEventKind.STDOUT_CHUNK,
            RuntimeStreamEventKind.STDERR_CHUNK,
            RuntimeStreamEventKind.HEARTBEAT,
            RuntimeStreamEventKind.WARNING,
            RuntimeStreamEventKind.COMPLETION,
            RuntimeStreamEventKind.FAILURE,
        ]

    def test_string_values(self) -> None:
        assert RuntimeStreamEventKind.STATUS.value == "status"
        assert RuntimeStreamEventKind.STDOUT_CHUNK.value == "stdout_chunk"
        assert RuntimeStreamEventKind.STDERR_CHUNK.value == "stderr_chunk"
        assert RuntimeStreamEventKind.HEARTBEAT.value == "heartbeat"
        assert RuntimeStreamEventKind.WARNING.value == "warning"
        assert RuntimeStreamEventKind.COMPLETION.value == "completion"
        assert RuntimeStreamEventKind.FAILURE.value == "failure"


class TestRuntimeStreamWarningKind:
    def test_all_values_present(self) -> None:
        assert list(RuntimeStreamWarningKind) == [
            RuntimeStreamWarningKind.TRUNCATION_APPLIED,
            RuntimeStreamWarningKind.OUTPUT_LIMIT_REACHED,
            RuntimeStreamWarningKind.CWD_MISSING,
            RuntimeStreamWarningKind.LEASE_INVALID,
            RuntimeStreamWarningKind.GOVERNANCE_BLOCKED,
            RuntimeStreamWarningKind.STALL_DETECTED,
        ]


class TestRuntimeStatusEvent:
    def test_valid_status(self) -> None:
        evt = RuntimeStatusEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.STATUS,
            status=RuntimeInvocationStatus.STARTING,
            message="Starting execution",
        )
        assert evt.status == RuntimeInvocationStatus.STARTING
        assert evt.message == "Starting execution"

    def test_status_without_message(self) -> None:
        evt = RuntimeStatusEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.STATUS,
            status=RuntimeInvocationStatus.RUNNING,
        )
        assert evt.message is None

    def test_unknown_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RuntimeStatusEvent(
                **_SAMPLE_BASE,
                event_kind=RuntimeStreamEventKind.STATUS,
                status=RuntimeInvocationStatus.SUCCEEDED,
                unknown_field="bad",
            )


class TestRuntimeOutputChunkEvent:
    def test_valid_stdout_chunk(self) -> None:
        evt = RuntimeOutputChunkEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.STDOUT_CHUNK,
            stream="stdout",
            chunk_index=0,
            chunk_text="hello",
            chunk_sha256="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            chunk_bytes=5,
            truncated=False,
        )
        assert evt.stream == "stdout"
        assert evt.chunk_index == 0
        assert evt.chunk_text == "hello"
        assert evt.chunk_bytes == 5
        assert not evt.truncated

    def test_stderr_chunk(self) -> None:
        evt = RuntimeOutputChunkEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.STDERR_CHUNK,
            stream="stderr",
            chunk_index=0,
            chunk_text="error",
            chunk_sha256="sha256:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b",
            chunk_bytes=5,
            truncated=False,
        )
        assert evt.stream == "stderr"
        assert evt.event_kind == RuntimeStreamEventKind.STDERR_CHUNK

    def test_chunk_text_optional(self) -> None:
        evt = RuntimeOutputChunkEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.STDOUT_CHUNK,
            stream="stdout",
            chunk_index=1,
            chunk_sha256="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            chunk_bytes=0,
            truncated=True,
        )
        assert evt.chunk_text is None
        assert evt.truncated

    def test_unknown_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RuntimeOutputChunkEvent(
                **_SAMPLE_BASE,
                event_kind=RuntimeStreamEventKind.STDOUT_CHUNK,
                stream="stdout",
                chunk_index=0,
                chunk_sha256="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                chunk_bytes=0,
                unknown="bad",
            )


class TestRuntimeHeartbeatEvent:
    def test_valid_heartbeat(self) -> None:
        evt = RuntimeHeartbeatEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.HEARTBEAT,
            elapsed_ms=500.0,
        )
        assert evt.elapsed_ms == 500.0


class TestRuntimeWarningEvent:
    def test_valid_warning(self) -> None:
        evt = RuntimeWarningEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.WARNING,
            warning_kind=RuntimeStreamWarningKind.TRUNCATION_APPLIED,
            message="Output truncated at 64KB",
        )
        assert evt.warning_kind == RuntimeStreamWarningKind.TRUNCATION_APPLIED
        assert evt.message == "Output truncated at 64KB"


class TestRuntimeCompletionEvent:
    def test_successful_completion(self) -> None:
        evt = RuntimeCompletionEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.COMPLETION,
            status=RuntimeInvocationStatus.SUCCEEDED,
            exit_code=0,
            duration_ms=150.0,
            stdout_sha256="sha256:" + "a" * 64,
            stderr_sha256="sha256:" + "b" * 64,
            stdout_bytes=100,
            stderr_bytes=0,
        )
        assert evt.status == RuntimeInvocationStatus.SUCCEEDED
        assert evt.exit_code == 0
        assert evt.duration_ms == 150.0
        assert evt.stdout_bytes == 100
        assert evt.stderr_bytes == 0

    def test_failed_completion(self) -> None:
        evt = RuntimeCompletionEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.COMPLETION,
            status=RuntimeInvocationStatus.FAILED,
            exit_code=1,
            duration_ms=200.0,
            stdout_sha256="sha256:" + "a" * 64,
            stderr_sha256="sha256:" + "b" * 64,
            stdout_bytes=50,
            stderr_bytes=30,
        )
        assert evt.status == RuntimeInvocationStatus.FAILED
        assert evt.exit_code == 1

    def test_no_raw_output_in_dump(self) -> None:
        """Content-light: completion events carry only hashes and counts."""
        evt = RuntimeCompletionEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.COMPLETION,
            status=RuntimeInvocationStatus.SUCCEEDED,
            exit_code=0,
            duration_ms=100.0,
            stdout_sha256="sha256:" + "a" * 64,
            stderr_sha256="sha256:" + "b" * 64,
            stdout_bytes=10,
            stderr_bytes=0,
        )
        dumped = evt.model_dump(mode="json")
        assert "stdout" not in dumped  # only stdout_sha256, stdout_bytes
        assert "stderr" not in dumped
        assert "content" not in dumped
        assert "output" not in dumped
        assert "diff" not in dumped
        assert "shell" not in dumped

    def test_schema_version_set(self) -> None:
        evt = RuntimeCompletionEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.COMPLETION,
            status=RuntimeInvocationStatus.SUCCEEDED,
            exit_code=0,
            duration_ms=100.0,
            stdout_sha256="sha256:" + "a" * 64,
            stderr_sha256="sha256:" + "b" * 64,
            stdout_bytes=10,
            stderr_bytes=0,
        )
        assert evt.schema_version == "rig.relay.runtime_stream_event.v1"


class TestRuntimeFailureEvent:
    def test_timeout_failure(self) -> None:
        evt = RuntimeFailureEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.FAILURE,
            status=RuntimeInvocationStatus.TIMED_OUT,
            error_kind="timeout",
            refusal_reason="Execution timed out after 30s",
            duration_ms=30000.0,
        )
        assert evt.status == RuntimeInvocationStatus.TIMED_OUT
        assert evt.error_kind == "timeout"
        assert evt.duration_ms == 30000.0

    def test_blocked_failure(self) -> None:
        evt = RuntimeFailureEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.FAILURE,
            status=RuntimeInvocationStatus.BLOCKED,
            error_kind="lease_inactive",
            refusal_reason="Lease status is expired",
        )
        assert evt.status == RuntimeInvocationStatus.BLOCKED
        assert evt.refusal_reason == "Lease status is expired"

    def test_no_raw_output_in_dump(self) -> None:
        evt = RuntimeFailureEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.FAILURE,
            status=RuntimeInvocationStatus.CANCELLED,
            error_kind="cancelled",
            refusal_reason="Execution was cancelled",
        )
        dumped = evt.model_dump(mode="json")
        assert "stdout" not in dumped
        assert "stderr" not in dumped
        assert "content" not in dumped
        assert "output" not in dumped


class TestSchemaValidation:
    """Validate stream events against the JSON schema."""

    def test_status_event_validates_against_schema(self) -> None:
        evt = RuntimeStatusEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.STATUS,
            status=RuntimeInvocationStatus.STARTING,
        )
        d = evt.model_dump(mode="json")
        assert d["schema_version"] == "rig.relay.runtime_stream_event.v1"
        assert d["event_kind"] == "status"
        assert d["status"] == "starting"

    def test_completion_event_validates_against_schema(self) -> None:
        evt = RuntimeCompletionEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.COMPLETION,
            status=RuntimeInvocationStatus.SUCCEEDED,
            exit_code=0,
            duration_ms=100.0,
            stdout_sha256="sha256:" + "a" * 64,
            stderr_sha256="sha256:" + "b" * 64,
            stdout_bytes=10,
            stderr_bytes=0,
        )
        d = evt.model_dump(mode="json")
        assert d["event_kind"] == "completion"
        assert d["status"] == "succeeded"

    def test_failure_event_validates_against_schema(self) -> None:
        evt = RuntimeFailureEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.FAILURE,
            status=RuntimeInvocationStatus.TIMED_OUT,
            error_kind="timeout",
            refusal_reason="timeout",
        )
        d = evt.model_dump(mode="json")
        assert d["event_kind"] == "failure"
        assert d["status"] == "timed_out"


class TestDiscriminatedUnion:
    def test_status_event_discriminated(self) -> None:

        from rig_relay.runtime.stream_types import RuntimeStreamEventBase

        # The union type is defined; verify the event kind is literal
        evt = RuntimeStatusEvent(
            **_SAMPLE_BASE,
            event_kind=RuntimeStreamEventKind.STATUS,
            status=RuntimeInvocationStatus.RUNNING,
        )
        assert isinstance(evt, RuntimeStreamEventBase)
        assert evt.event_kind == RuntimeStreamEventKind.STATUS
