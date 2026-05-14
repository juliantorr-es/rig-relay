"""Tests for rig_relay.desktop.execution_progress — model and aggregation.

Pure unit tests. No file I/O, no tool execution, no persistence.
"""

from __future__ import annotations

import json

from pydantic import ValidationError
import pytest

from rig_relay.desktop.execution_progress import (
    ExecutionProgressProjection,
    execution_progress_from_runtime_events,
)

# ── Helpers ────────────────────────────────────────────────────────────


def _event(kind: str, **overrides: object) -> dict[str, object]:
    """Build a dict-shaped RuntimeStreamEvent for testing."""
    base: dict[str, object] = {
        "schema_version": "rig.relay.runtime_stream_event.v1",
        "event_id": f"evt-{kind}",
        "lease_id": "lease-001",
        "request_id": "req-001",
        "event_kind": kind,
        "captured_at": "2026-05-15T10:00:00Z",
    }
    base.update(overrides)
    return base


# ── Model tests ────────────────────────────────────────────────────────


class TestExecutionProgressProjection:
    def test_unknown_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExecutionProgressProjection.model_validate({
                "unknown_field": "x",
                "status": "running",
            })

    def test_minimal_defaults(self) -> None:
        p = ExecutionProgressProjection()
        assert p.schema_version == "rig.relay.execution_progress_projection.v1"
        assert p.status == "pending"
        assert p.heartbeat_count == 0
        assert p.warning_count == 0
        assert p.stdout_truncated is False
        assert p.stderr_truncated is False
        assert p.invocation_id is None
        assert p.exit_code is None
        assert p.elapsed_ms is None

    def test_status_override(self) -> None:
        p = ExecutionProgressProjection(status="succeeded")
        assert p.status == "succeeded"

    def test_no_forbidden_raw_fields_in_model(self) -> None:
        """Model has no stdout/stderr raw fields, no chunk_text, no content, no diff."""
        p = ExecutionProgressProjection()
        d = p.model_dump()
        assert "stdout" not in d or "stdout_bytes" in d
        assert "stderr" not in d or "stderr_bytes" in d
        assert "chunk_text" not in d
        assert "content" not in d
        assert "output" not in d
        assert "diff" not in d
        assert "patch" not in d
        assert "snippet" not in d
        assert "argv" not in d


# ── Aggregation: empty / pending ───────────────────────────────────────


class TestEmptyInput:
    def test_empty_events_returns_pending(self) -> None:
        p = execution_progress_from_runtime_events([])
        assert p.status == "pending"
        assert p.heartbeat_count == 0
        assert p.warning_count == 0
        assert p.elapsed_ms is None
        assert p.last_event_at is None


# ── Aggregation: heartbeat ─────────────────────────────────────────────


class TestHeartbeat:
    def test_single_heartbeat_sets_running(self) -> None:
        events = [_event("heartbeat", elapsed_ms=100.0)]
        p = execution_progress_from_runtime_events(events)
        assert p.status == "running"
        assert p.heartbeat_count == 1
        assert p.elapsed_ms == 100.0
        assert p.last_event_at == "2026-05-15T10:00:00Z"
        assert p.lease_id == "lease-001"
        assert p.request_id == "req-001"

    def test_multiple_heartbeats_increment_count(self) -> None:
        events = [
            _event("heartbeat", elapsed_ms=10.0),
            _event("heartbeat", elapsed_ms=20.0),
            _event("heartbeat", elapsed_ms=30.0),
        ]
        p = execution_progress_from_runtime_events(events)
        assert p.status == "running"
        assert p.heartbeat_count == 3
        assert p.elapsed_ms == 30.0  # last heartbeat


# ── Aggregation: warning ───────────────────────────────────────────────


class TestWarning:
    def test_warning_increments_count_and_sets_kind(self) -> None:
        events = [
            _event("warning", warning_kind="stall_detected", message="No output for 5s")
        ]
        p = execution_progress_from_runtime_events(events)
        assert p.warning_count == 1
        assert p.latest_warning_kind == "stall_detected"
        assert p.latest_warning_message == "No output for 5s"

    def test_warning_message_sanitized(self) -> None:
        long_msg = "x" * 300
        events = [_event("warning", warning_kind="test", message=long_msg)]
        p = execution_progress_from_runtime_events(events)
        assert p.latest_warning_message is not None
        assert len(p.latest_warning_message) <= 203  # 200 + "..."


# ── Aggregation: output chunk ─────────────────────────────────────────


class TestOutputChunk:
    def test_chunk_does_not_copy_chunk_text(self) -> None:
        events = [
            _event(
                "stdout_chunk",
                stream="stdout",
                chunk_index=0,
                chunk_text="hello world",
                chunk_sha256="sha256:abc",
                chunk_bytes=11,
            )
        ]
        p = execution_progress_from_runtime_events(events)
        assert p.status == "running"
        # chunk_text must NOT appear in projection dump
        d = p.model_dump()
        assert "chunk_text" not in d
        assert "hello world" not in str(d)

    def test_multiple_chunks_set_last_event_at(self) -> None:
        events = [
            _event(
                "stdout_chunk",
                stream="stdout",
                chunk_index=0,
                chunk_sha256="a",
                chunk_bytes=5,
                captured_at="2026-05-15T10:00:01Z",
            ),
            _event(
                "stderr_chunk",
                stream="stderr",
                chunk_index=1,
                chunk_sha256="b",
                chunk_bytes=3,
                captured_at="2026-05-15T10:00:02Z",
            ),
        ]
        p = execution_progress_from_runtime_events(events)
        assert p.last_event_at == "2026-05-15T10:00:02Z"
        assert p.status == "running"


# ── Aggregation: completion ────────────────────────────────────────────


class TestCompletion:
    def test_completion_populates_terminal_fields(self) -> None:
        events = [
            _event(
                "completion",
                status="succeeded",
                exit_code=0,
                duration_ms=1500.0,
                stdout_sha256="sha256:out",
                stderr_sha256="sha256:err",
                stdout_bytes=1024,
                stderr_bytes=0,
                stdout_truncated=False,
                stderr_truncated=False,
                event_id="evt-completion-001",
            )
        ]
        p = execution_progress_from_runtime_events(events)
        assert p.status == "succeeded"
        assert p.exit_code == 0
        assert p.elapsed_ms == 1500.0
        assert p.stdout_bytes == 1024
        assert p.stderr_bytes == 0
        assert p.stdout_truncated is False
        assert p.stderr_truncated is False
        assert p.terminal_event_id == "evt-completion-001"
        assert p.evidence_sha256 == "sha256:out"

    def test_completion_wins_over_previous_status(self) -> None:
        events = [
            _event("status", status="running", captured_at="2026-05-15T10:00:00Z"),
            _event("heartbeat", elapsed_ms=100.0),
            _event(
                "completion",
                status="failed",
                exit_code=1,
                duration_ms=5000.0,
                stdout_sha256="s256",
                stderr_sha256="s256",
                stdout_bytes=512,
                stderr_bytes=128,
                stdout_truncated=True,
                event_id="evt-final",
            ),
        ]
        p = execution_progress_from_runtime_events(events)
        assert p.status == "failed"
        assert p.exit_code == 1
        assert p.elapsed_ms == 5000.0
        assert p.stdout_truncated is True


# ── Aggregation: failure ──────────────────────────────────────────────


class TestFailure:
    def test_failure_populates_error_and_refusal(self) -> None:
        events = [
            _event(
                "failure",
                status="timed_out",
                error_kind="timeout",
                refusal_reason="Exceeded 30s timeout",
                duration_ms=30000.0,
                exit_code=None,
                stdout_sha256="s256",
                stderr_sha256="s256",
                stdout_bytes=200,
                stderr_bytes=50,
            )
        ]
        p = execution_progress_from_runtime_events(events)
        assert p.status == "timed_out"
        assert p.error_kind == "timeout"
        assert p.refusal_reason == "Exceeded 30s timeout"
        assert p.elapsed_ms == 30000.0
        assert p.stdout_bytes == 200
        assert p.stderr_bytes == 50

    def test_failure_wins_over_running_status(self) -> None:
        events = [
            _event("status", status="running"),
            _event("heartbeat", elapsed_ms=50.0),
            _event(
                "failure",
                status="cancelled",
                error_kind="cancelled",
                duration_ms=2000.0,
                stdout_sha256="s",
                stderr_sha256="s",
                stdout_bytes=0,
                stderr_bytes=0,
                event_id="evt-cancel",
            ),
        ]
        p = execution_progress_from_runtime_events(events)
        assert p.status == "cancelled"
        assert p.error_kind == "cancelled"
        assert p.terminal_event_id == "evt-cancel"


# ── Aggregation: last terminal wins ────────────────────────────────────


class TestMultipleTerminal:
    def test_last_completion_wins(self) -> None:
        events = [
            _event(
                "completion",
                status="succeeded",
                exit_code=0,
                duration_ms=100.0,
                stdout_sha256="s1",
                stderr_sha256="s1",
                stdout_bytes=10,
                stderr_bytes=0,
                event_id="first",
            ),
            _event(
                "completion",
                status="failed",
                exit_code=1,
                duration_ms=200.0,
                stdout_sha256="s2",
                stderr_sha256="s2",
                stdout_bytes=20,
                stderr_bytes=5,
                event_id="second",
            ),
        ]
        p = execution_progress_from_runtime_events(events)
        assert p.status == "failed"
        assert p.exit_code == 1
        assert p.terminal_event_id == "second"

    def test_last_failure_wins(self) -> None:
        events = [
            _event(
                "failure",
                status="timed_out",
                error_kind="timeout",
                duration_ms=5000.0,
                stdout_sha256="s",
                stderr_sha256="s",
                stdout_bytes=0,
                stderr_bytes=0,
            ),
            _event(
                "failure",
                status="cancelled",
                error_kind="cancelled",
                duration_ms=6000.0,
                stdout_sha256="s",
                stderr_sha256="s",
                stdout_bytes=0,
                stderr_bytes=0,
            ),
        ]
        p = execution_progress_from_runtime_events(events)
        assert p.status == "cancelled"
        assert p.error_kind == "cancelled"


# ── Aggregation: malformed/unknown events ──────────────────────────────


class TestMalformed:
    def test_unknown_event_kind_skipped(self) -> None:
        events = [
            _event("heartbeat", elapsed_ms=10.0),
            _event("unknown_kind_123", some_field="x"),
        ]
        p = execution_progress_from_runtime_events(events)
        # First event processed, second skipped
        assert p.heartbeat_count == 1

    def test_totally_malformed_event_skipped(self) -> None:
        events = [{"not_an_event": True}, _event("heartbeat", elapsed_ms=5.0)]
        p = execution_progress_from_runtime_events(events)
        assert p.heartbeat_count == 1


# ── Aggregation: status event ──────────────────────────────────────────


class TestStatusEvent:
    def test_status_sets_started_at(self) -> None:
        events = [
            _event("status", status="starting", captured_at="2026-05-15T10:00:00Z")
        ]
        p = execution_progress_from_runtime_events(events)
        assert p.status == "starting"
        assert p.started_at == "2026-05-15T10:00:00Z"

    def test_started_at_from_first_status(self) -> None:
        events = [
            _event("heartbeat", elapsed_ms=10.0),
            _event("status", status="starting", captured_at="2026-05-15T10:00:05Z"),
        ]
        p = execution_progress_from_runtime_events(events)
        assert p.started_at == "2026-05-15T10:00:05Z"


# ── Schema validation ──────────────────────────────────────────────────


class TestSchemaValidation:
    SCHEMA_PATH = str(
        __import__("pathlib").Path(__file__).resolve().parent.parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.execution_progress_projection.v1.schema.json"
    )

    def test_prepared_envelope_validates(self) -> None:
        events = [
            _event("status", status="starting"),
            _event("heartbeat", elapsed_ms=50.0),
            _event(
                "completion",
                status="succeeded",
                exit_code=0,
                duration_ms=200.0,
                stdout_sha256="s",
                stderr_sha256="s",
                stdout_bytes=100,
                stderr_bytes=10,
            ),
        ]
        p = execution_progress_from_runtime_events(events)
        d = p.model_dump(mode="json")
        schema_path = __import__("pathlib").Path(self.SCHEMA_PATH)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        import jsonschema

        jsonschema.validate(instance=d, schema=schema)

    def test_pending_envelope_validates(self) -> None:
        p = ExecutionProgressProjection()
        d = p.model_dump(mode="json")
        schema_path = __import__("pathlib").Path(self.SCHEMA_PATH)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        import jsonschema

        jsonschema.validate(instance=d, schema=schema)

    def test_schema_rejects_unknown_fields(self) -> None:
        schema_path = __import__("pathlib").Path(self.SCHEMA_PATH)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        import jsonschema

        bad = {
            "schema_version": "rig.relay.execution_progress_projection.v1",
            "status": "running",
            "heartbeat_count": 0,
            "warning_count": 0,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "unknown_field": "should be rejected",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_schema_rejects_raw_output_fields(self) -> None:
        schema_path = __import__("pathlib").Path(self.SCHEMA_PATH)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        import jsonschema

        bad = {
            "schema_version": "rig.relay.execution_progress_projection.v1",
            "status": "running",
            "heartbeat_count": 0,
            "warning_count": 0,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "chunk_text": "should not be here",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)
