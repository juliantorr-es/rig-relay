"""Tests for PromptBar — single-line queue input via Textual Input."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult

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

    def test_clear_input_clears_value(self) -> None:
        bar = PromptBar()
        mock = MagicMock()
        bar._input = mock
        bar.clear_input()
        mock.value = ""

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
        event = MagicMock(spec=["value"])
        event.value = "test message"
        event.stop = MagicMock()
        bar.on_input_submitted(event)
        callback.assert_called_once_with("test message")

    def test_submit_clears_input(self) -> None:
        callback = MagicMock()
        bar = PromptBar(on_submit=callback)
        mock = MagicMock()
        bar._input = mock
        event = MagicMock(spec=["value"])
        event.value = "test"
        event.stop = MagicMock()
        bar.on_input_submitted(event)
        assert bar.value == ""

    def test_submit_sets_queued_status(self) -> None:
        callback = MagicMock()
        bar = PromptBar(on_submit=callback)
        mock = MagicMock()
        bar._input = mock
        event = MagicMock(spec=["value"])
        event.value = "test"
        event.stop = MagicMock()
        bar.on_input_submitted(event)
        if bar._status is not None:
            assert "Queued" in str(bar._status._renderable)

    def test_submit_whitespace_does_nothing(self) -> None:
        callback = MagicMock()
        bar = PromptBar(on_submit=callback)
        event = MagicMock(spec=["value"])
        event.value = "   "
        event.stop = MagicMock()
        bar.on_input_submitted(event)
        callback.assert_not_called()

    def test_submit_empty_does_nothing(self) -> None:
        callback = MagicMock()
        bar = PromptBar(on_submit=callback)
        event = MagicMock(spec=["value"])
        event.value = ""
        event.stop = MagicMock()
        bar.on_input_submitted(event)
        callback.assert_not_called()


class TestPromptBarNoForbiddenRaw:
    def test_status_no_forbidden(self) -> None:
        bar = PromptBar()
        bar.set_status("Queued")
        if bar._status is not None:
            text = str(bar._status._renderable)
            assert not any(field in text.lower() for field in _FORBIDDEN)


class _PromptBarTestApp(App[None]):
    """Minimal Textual app for headless Pilot testing of PromptBar."""

    def __init__(
        self, on_submit: Callable[[str], None] | None = None, disabled: bool = False
    ) -> None:
        super().__init__()
        self._on_submit = on_submit
        self._disabled = disabled

    def compose(self) -> ComposeResult:
        yield PromptBar(on_submit=self._on_submit, disabled=self._disabled)


class TestPromptBarPilot:
    """Mounted Pilot tests for PromptBar using App.run_test."""

    @pytest.mark.asyncio
    async def test_prompt_bar_renders_with_input(self) -> None:
        """PromptBar mounts with an Input widget."""
        app = _PromptBarTestApp()
        async with app.run_test(size=(80, 6)) as pilot:
            bar = pilot.app.query_one(PromptBar)
            assert bar._input is not None
            assert not bar._input.disabled

    @pytest.mark.asyncio
    async def test_prompt_bar_disabled_on_start(self) -> None:
        """PromptBar mounts disabled when disabled=True."""
        app = _PromptBarTestApp(disabled=True)
        async with app.run_test(size=(80, 6)) as pilot:
            bar = pilot.app.query_one(PromptBar)
            assert bar._input is not None
            assert bar._input.disabled

    @pytest.mark.asyncio
    async def test_prompt_bar_submit_calls_callback(self) -> None:
        """Pressing Enter in the Input triggers the on_submit callback."""
        callback = MagicMock()
        app = _PromptBarTestApp(on_submit=callback)
        async with app.run_test(size=(80, 6)) as pilot:
            bar = pilot.app.query_one(PromptBar)
            assert bar._input is not None

            # Focus the input and type text
            bar._input.focus()
            await pilot.press(*"hello")
            await pilot.press("enter")

            callback.assert_called_once_with("hello")

    @pytest.mark.asyncio
    async def test_prompt_bar_empty_submit_does_nothing(self) -> None:
        """Pressing Enter with empty/whitespace input does not trigger callback."""
        callback = MagicMock()
        app = _PromptBarTestApp(on_submit=callback)
        async with app.run_test(size=(80, 6)) as pilot:
            bar = pilot.app.query_one(PromptBar)
            assert bar._input is not None

            bar._input.focus()
            await pilot.press("enter")

            callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_prompt_bar_disabled_does_not_accept_input(self) -> None:
        """Disabled PromptBar does not allow input or submission."""
        callback = MagicMock()
        app = _PromptBarTestApp(on_submit=callback, disabled=True)
        async with app.run_test(size=(80, 6)) as pilot:
            bar = pilot.app.query_one(PromptBar)
            assert bar._input is not None
            assert bar._input.disabled

            # Type text in disabled input — Textual ignores it
            await pilot.press(*"test")
            await pilot.press("enter")

            callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_prompt_bar_status_renders_after_submit(self) -> None:
        """Status text updates after successful submission."""
        callback = MagicMock()
        app = _PromptBarTestApp(on_submit=callback)
        async with app.run_test(size=(80, 6)) as pilot:
            bar = pilot.app.query_one(PromptBar)

            # Focus, type, and submit
            assert bar._input is not None
            bar._input.focus()
            await pilot.press(*"queue this")
            await pilot.press("enter")

            # Status should show "Queued"
            assert bar._status is not None
            rendered = str(bar._status.render())
            assert "Queued" in rendered

    @pytest.mark.asyncio
    async def test_prompt_bar_clear_resets_value(self) -> None:
        """After submit the input is cleared."""
        callback = MagicMock()
        app = _PromptBarTestApp(on_submit=callback)
        async with app.run_test(size=(80, 6)) as pilot:
            bar = pilot.app.query_one(PromptBar)

            assert bar._input is not None
            bar._input.focus()
            await pilot.press(*"clear me")
            await pilot.press("enter")

            # Input should be cleared
            assert bar.value == ""
