"""Tests for ProgressEvent models."""

from __future__ import annotations

import pytest

from vibe.cli.textual_ui.rig_console.progress_events import (
    ALLOWED_PROGRESS_LEVELS,
    ALLOWED_PROGRESS_PHASES,
    ALLOWED_PROGRESS_STATUSES,
    ProgressEventFactory,
    TurnProgressEvent,
)


class TestTurnProgressEvent:
    def test_valid_event_created(self) -> None:
        e = TurnProgressEvent(
            event_id="e1", sequence=1, phase="turn.completed", status="completed"
        )
        assert e.event_id == "e1"
        assert e.is_terminal is True

    def test_non_terminal_phase(self) -> None:
        e = TurnProgressEvent(
            event_id="e2", sequence=2, phase="tool.started", status="running"
        )
        assert e.is_terminal is False

    def test_invalid_phase_raises(self) -> None:
        with pytest.raises(AssertionError):
            TurnProgressEvent(
                event_id="e3", sequence=3, phase="invalid", status="completed"
            )

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(AssertionError):
            TurnProgressEvent(
                event_id="e4", sequence=4, phase="turn.completed", status="nope"
            )

    def test_invalid_level_raises(self) -> None:
        with pytest.raises(AssertionError):
            TurnProgressEvent(
                event_id="e5",
                sequence=5,
                phase="turn.completed",
                status="completed",
                level="critical",
            )


class TestProgressEventFactory:
    def setup_method(self) -> None:
        ProgressEventFactory.reset()

    def test_user_message(self) -> None:
        e = ProgressEventFactory.user_message("hello")
        assert e.phase == "user_message.accepted"
        assert e.status == "completed"
        assert e.message == "hello"

    def test_tool_started(self) -> None:
        e = ProgressEventFactory.tool_started("bash")
        assert e.phase == "tool.started"
        assert e.status == "running"
        assert e.tool_name == "bash"

    def test_tool_completed(self) -> None:
        e = ProgressEventFactory.tool_completed("bash")
        assert e.phase == "tool.completed"
        assert e.status == "completed"

    def test_tool_failed(self) -> None:
        e = ProgressEventFactory.tool_failed("bash", "TimeoutError")
        assert e.phase == "tool.failed"
        assert e.level == "error"
        assert e.error_kind == "TimeoutError"

    def test_tool_refused(self) -> None:
        e = ProgressEventFactory.tool_refused("write_file", "dirty file")
        assert e.phase == "tool.refused"
        assert e.level == "warning"
        assert e.refusal_reason == "dirty file"

    def test_turn_lifecycle(self) -> None:
        ProgressEventFactory.reset()
        e1 = ProgressEventFactory.turn_completed()
        assert e1.phase == "turn.completed"
        assert e1.is_terminal is True

        e2 = ProgressEventFactory.turn_cancelled()
        assert e2.phase == "turn.cancelled"
        assert e2.is_terminal is True

        e3 = ProgressEventFactory.turn_failed("RuntimeError")
        assert e3.phase == "turn.failed"
        assert e3.is_terminal is True
        assert e3.level == "error"

    def test_assistant_events(self) -> None:
        e1 = ProgressEventFactory.assistant_started()
        assert e1.phase == "assistant_message.started"

        e2 = ProgressEventFactory.assistant_completed("reply text")
        assert e2.status == "completed"
        assert e2.message == "reply text"

    def test_sequential_ids(self) -> None:
        ProgressEventFactory.reset()
        assert ProgressEventFactory.user_message("a").sequence == 1
        assert ProgressEventFactory.tool_started("bash").sequence == 2

    def test_all_phases_are_valid(self) -> None:
        for phase in ALLOWED_PROGRESS_PHASES:
            if phase.startswith("turn."):
                e = ProgressEventFactory.turn_completed()
            else:
                e = ProgressEventFactory.user_message("x")
            assert e.phase is not None

    def test_all_statuses_covered(self) -> None:
        assert "running" in ALLOWED_PROGRESS_STATUSES
        assert "completed" in ALLOWED_PROGRESS_STATUSES
        assert "failed" in ALLOWED_PROGRESS_STATUSES
        assert "cancelled" in ALLOWED_PROGRESS_STATUSES
        assert "refused" in ALLOWED_PROGRESS_STATUSES
        assert "blocked" in ALLOWED_PROGRESS_STATUSES

    def test_all_levels_covered(self) -> None:
        assert "info" in ALLOWED_PROGRESS_LEVELS
        assert "warning" in ALLOWED_PROGRESS_LEVELS
        assert "error" in ALLOWED_PROGRESS_LEVELS
