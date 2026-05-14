"""Tests for desktop projection runtime event aggregation (P4b.1).

Tests that build_projection() correctly wires execution_progress_from_runtime_events
into the desktop projection output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from rig_relay.desktop.projection import build_projection


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


SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.relay.desktop_projection.v1.schema.json"
)


def _load_schema() -> dict[str, object]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_schema(projection: dict[str, Any]) -> list[str]:
    schema = _load_schema()
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(projection)]


class TestDesktopProjectionNoRuntimeEvents:
    """build_projection without runtime_events should omit execution_progress."""

    def test_no_runtime_events_omits_field(self, tmp_path: Path) -> None:
        proj = build_projection(build_root=tmp_path)
        assert "execution_progress" not in proj

    def test_no_runtime_events_still_builds(self, tmp_path: Path) -> None:
        proj = build_projection(build_root=tmp_path)
        assert proj["schema_version"] == "rig.relay.desktop_projection.v1"
        assert isinstance(proj["source_status"], dict)
        assert isinstance(proj["warnings"], list)

    def test_no_runtime_events_validates_against_schema(self, tmp_path: Path) -> None:
        proj = build_projection(build_root=tmp_path)
        errors = _validate_schema(proj)
        assert not errors, f"Schema errors: {errors}"


class TestDesktopProjectionEmptyRuntimeEvents:
    """build_projection with empty events should include pending execution_progress."""

    def test_empty_events_includes_field(self, tmp_path: Path) -> None:
        proj = build_projection(build_root=tmp_path, runtime_events=[])
        assert "execution_progress" in proj

    def test_empty_events_shows_pending(self, tmp_path: Path) -> None:
        proj = build_projection(build_root=tmp_path, runtime_events=[])
        ep = proj["execution_progress"]
        assert ep["status"] == "pending"
        assert ep["heartbeat_count"] == 0
        assert ep["warning_count"] == 0

    def test_empty_events_validates_against_schema(self, tmp_path: Path) -> None:
        proj = build_projection(build_root=tmp_path, runtime_events=[])
        errors = _validate_schema(proj)
        assert not errors, f"Schema errors: {errors}"


class TestDesktopProjectionCompletionEvent:
    """Runtime completion event produces succeeded execution_progress."""

    def test_completion_shows_succeeded(self, tmp_path: Path) -> None:
        events = [
            _event(
                "completion",
                status="succeeded",
                exit_code=0,
                duration_ms=1500.0,
                stdout_sha256="abc123",
                stderr_sha256="def456",
                stdout_bytes=1024,
                stderr_bytes=0,
            )
        ]
        proj = build_projection(build_root=tmp_path, runtime_events=events)
        ep = proj["execution_progress"]
        assert ep["status"] == "succeeded"
        assert ep["exit_code"] == 0
        assert ep["elapsed_ms"] == 1500.0
        assert ep["stdout_bytes"] == 1024
        assert ep["stderr_bytes"] == 0
        assert ep["terminal_event_id"] == "evt-completion"

    def test_completion_validates_against_schema(self, tmp_path: Path) -> None:
        events = [
            _event(
                "completion",
                status="succeeded",
                exit_code=0,
                duration_ms=500.0,
                stdout_sha256="abc",
                stderr_sha256="def",
                stdout_bytes=256,
                stderr_bytes=0,
            )
        ]
        proj = build_projection(build_root=tmp_path, runtime_events=events)
        errors = _validate_schema(proj)
        assert not errors, f"Schema errors: {errors}"


class TestDesktopProjectionFailureEvent:
    """Runtime failure event produces failed execution_progress."""

    def test_failure_shows_failed(self, tmp_path: Path) -> None:
        events = [
            _event(
                "failure",
                status="failed",
                error_kind="execution_error",
                refusal_reason="Command exited with code 1",
                duration_ms=800.0,
                exit_code=1,
                stdout_bytes=0,
                stderr_bytes=512,
            )
        ]
        proj = build_projection(build_root=tmp_path, runtime_events=events)
        ep = proj["execution_progress"]
        assert ep["status"] == "failed"
        assert ep["error_kind"] == "execution_error"
        assert ep["refusal_reason"] == "Command exited with code 1"
        assert ep["exit_code"] == 1
        assert ep["stdout_bytes"] == 0
        assert ep["stderr_bytes"] == 512

    def test_failure_validates_against_schema(self, tmp_path: Path) -> None:
        events = [
            _event(
                "failure",
                status="timed_out",
                error_kind="timeout",
                duration_ms=10000.0,
                stdout_sha256="abc",
                stderr_sha256="def",
            )
        ]
        proj = build_projection(build_root=tmp_path, runtime_events=events)
        errors = _validate_schema(proj)
        assert not errors, f"Schema errors: {errors}"


class TestDesktopProjectionContentLight:
    """No raw chunk_text leaks into projection."""

    def test_chunk_text_not_copied(self, tmp_path: Path) -> None:
        events = [
            _event(
                "stdout_chunk",
                stream="stdout",
                chunk_index=0,
                chunk_text="secret output content",
                chunk_sha256="hash123",
                chunk_bytes=22,
            ),
            _event(
                "completion",
                status="succeeded",
                exit_code=0,
                duration_ms=100.0,
                stdout_sha256="hash123",
                stderr_sha256="",
                stdout_bytes=22,
                stderr_bytes=0,
            ),
        ]
        proj = build_projection(build_root=tmp_path, runtime_events=events)
        ep = proj["execution_progress"]
        # No raw text in projection
        for key in ep:
            assert key not in ("chunk_text", "stdout", "stderr", "output", "content")
        # Content-light fields only
        assert "stdout_bytes" in ep
        assert "stderr_bytes" in ep
        assert ep["stdout_bytes"] == 22


class TestDesktopProjectionMalformedEvents:
    """Malformed runtime events degrade safely, don't crash."""

    def test_malformed_event_does_not_crash(self, tmp_path: Path) -> None:
        events: list[object] = [
            {"not": "a proper event"},
            _event(
                "completion",
                status="succeeded",
                exit_code=0,
                duration_ms=100.0,
                stdout_sha256="h",
                stderr_sha256="",
                stdout_bytes=1,
                stderr_bytes=0,
            ),
        ]
        proj = build_projection(build_root=tmp_path, runtime_events=events)
        ep = proj["execution_progress"]
        # Second event was valid, projection should reflect it
        assert ep["status"] == "succeeded"
        assert ep["exit_code"] == 0

    def test_all_malformed_events_degrades(self, tmp_path: Path) -> None:
        events: list[object] = [{"not": "an event"}, {"also": "not valid"}]
        proj = build_projection(build_root=tmp_path, runtime_events=events)
        ep = proj["execution_progress"]
        # > 50% malformed → status = "degraded"
        assert ep["status"] == "degraded"


class TestDesktopProjectionMultipleEvents:
    """Multiple events are aggregated correctly."""

    def test_status_then_completion(self, tmp_path: Path) -> None:
        events = [
            _event("status", status="starting", captured_at="2026-05-15T10:00:00Z"),
            _event(
                "completion",
                status="succeeded",
                exit_code=0,
                duration_ms=2000.0,
                stdout_sha256="abc",
                stderr_sha256="def",
                stdout_bytes=512,
                stderr_bytes=0,
            ),
        ]
        proj = build_projection(build_root=tmp_path, runtime_events=events)
        ep = proj["execution_progress"]
        # Last terminal wins
        assert ep["status"] == "succeeded"
        assert ep["started_at"] is not None
        assert ep["last_event_at"] is not None
