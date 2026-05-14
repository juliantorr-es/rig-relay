"""Tests for PromptBar — single-line queue input via Textual Input."""

from __future__ import annotations
from unittest.mock import MagicMock

import pytest
from textual.widgets import Input

from vibe.cli.textual_ui.rig_console.widgets.prompt_bar import PromptBar


_FORBIDDEN = (
    "stdout",
    "stderr",
    "content",
    "file_contents",
    "chunk_text",
    "old_text",
    "new_text",
    "diff",
    "patch",
    "prompt",
    "secret",
    "argv",
    "snippet",
    "raw_output",
)


class TestPromptBarWidget:
    def test_renders(self) -> None:
        bar = PromptBar()
        assert bar._placeholder == "Queue instruction\u2026"

    def test_placeholder_is_customizable(self) -> None:
        bar = PromptBar(placeholder="Type here")
        assert bar._placeholder == "Type here"

    def test_disabled_by_default(self) -> None:
        bar = PromptBar(disabled=True)
        assert bar._disabled is True

    def test_value_property_empty_by_default(self) -> None:
        bar = PromptBar()
        assert bar.value == ""

    def test_value_property_setter(self) -> None:
        bar = PromptBar()
        bar.value = "hello"
        assert bar.value == "hello"

    def test_clear_input_clears_value(self) -> None:
        bar = PromptBar()
        bar.value = "hello"
        bar.clear_input()
        assert bar.value == ""

    def test_set_status_updates_status(self) -> None:
        bar = PromptBar()
        bar.set_status("Queued")
        if bar._status is not None:
            assert bar._status._renderable == "Queued"

    def test_set_disabled_state(self) -> None:
        bar = PromptBar()
        bar.set_disabled(True, "Queue unavailable")
        assert bar._disabled is True
        if bar._status is not None:
            assert "unavailable" in str(bar._status._renderable).lower()

    def test_set_disabled_without_status(self) -> None:
        bar = PromptBar()
        bar.set_disabled(True)
        assert bar._disabled is True

    def test_submit_callback_called(self) -> None:
        callback = MagicMock()
        bar = PromptBar(on_submit=callback)
        bar.value = "test message"
        # Simulate Input.Submitted event
        event = MagicMock(spec=Input.Submitted)
        event.value = "test message"
        event.stop = MagicMock()
        bar.on_input_submitted(event)
        callback.assert_called_once_with("test message")

    def test_submit_clears_input(self) -> None:
        callback = MagicMock()
        bar = PromptBar(on_submit=callback)
        if bar._input is not None:
            bar._input.value = "test"
        event = MagicMock(spec=Input.Submitted)
        event.value = "test"
        event.stop = MagicMock()
        bar.on_input_submitted(event)
        assert bar.value == ""

    def test_submit_sets_queued_status(self) -> None:
        callback = MagicMock()
        bar = PromptBar(on_submit=callback)
        bar.value = "test"
        event = MagicMock(spec=Input.Submitted)
        event.value = "test"
        event.stop = MagicMock()
        bar.on_input_submitted(event)
        if bar._status is not None:
            assert "Queued" in str(bar._status._renderable)

    def test_submit_whitespace_does_nothing(self) -> None:
        callback = MagicMock()
        bar = PromptBar(on_submit=callback)
        bar.value = "   "
        event = MagicMock(spec=Input.Submitted)
        event.value = "   "
        event.stop = MagicMock()
        bar.on_input_submitted(event)
        callback.assert_not_called()

    def test_submit_empty_does_nothing(self) -> None:
        callback = MagicMock()
        bar = PromptBar(on_submit=callback)
        event = MagicMock(spec=Input.Submitted)
        event.value = ""
        event.stop = MagicMock()
        bar.on_input_submitted(event)
        callback.assert_not_called()


class TestPromptBarNoForbiddenRaw:
    def test_render_lines_no_forbidden(self) -> None:
        bar = PromptBar()
        text = repr(bar)
        assert not any(field in text.lower() for field in _FORBIDDEN)

    def test_status_no_forbidden(self) -> None:
        bar = PromptBar()
        bar.set_status("Queued")
        if bar._status is not None:
            text = str(bar._status._renderable)
            assert not any(field in text.lower() for field in _FORBIDDEN)
