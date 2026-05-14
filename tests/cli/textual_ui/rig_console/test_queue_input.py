"""Tests for the queue input bar."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from pydantic import ValidationError
import pytest
from textual import events

from vibe.cli.textual_ui.rig_console.console_app import RigConsoleApp
from vibe.cli.textual_ui.rig_console.projections import QueueItemProjection
from vibe.cli.textual_ui.rig_console.screens.dashboard import DashboardScreen
from vibe.cli.textual_ui.rig_console.widgets.queue_input import (
    QueueInputWidget,
    _QueueEditor,
)
from vibe.cli.textual_ui.rig_console.widgets.queue_panel import QueuePanelWidget


class TestQueueInputWidget:
    def test_enter_queues_not_steer(self) -> None:
        queued: list[str] = []
        steered: list[str] = []
        widget = QueueInputWidget(queued.append, steered.append)
        editor = _QueueEditor(
            on_submit=widget.queue_current, on_shift_enter=lambda: None
        )
        cast(Any, widget)._editor = editor
        widget.set_value("hello queue")
        widget.submit_current()
        assert queued == ["hello queue"]
        assert steered == []

    def test_shift_enter_inserts_newline(self) -> None:
        widget = QueueInputWidget()
        editor = _QueueEditor(on_submit=lambda: None, on_shift_enter=lambda: None)
        editor.text = "hello"
        cast(Any, widget)._editor = editor
        widget._insert_newline()
        assert "\n" in widget.value()
        assert widget.value().replace("\n", "") == "hello"

    @pytest.mark.asyncio
    async def test_queue_message_appears_in_queue_panel(self) -> None:
        app = RigConsoleApp(mode="fixture")
        async with app.run_test(size=(120, 40)) as pilot:
            screen = cast(DashboardScreen, pilot.app.screen)
            widget = screen.query_one(QueueInputWidget)
            panel = screen.query_one(QueuePanelWidget)
            widget.set_value("queue this message")
            screen.action_queue_message()
            await pilot.pause()
            assert screen._projection.queue.items[-1].kind == "message"
            assert screen._projection.queue.items[-1].payload_ref is not None
            text = "\n".join(panel._render_lines())
            assert "Payload:" in text
            assert "local://queue/" in text

    @pytest.mark.asyncio
    async def test_steer_action_is_safe_and_distinct(self) -> None:
        app = RigConsoleApp(mode="fixture")
        async with app.run_test(size=(120, 40)) as pilot:
            screen = cast(DashboardScreen, pilot.app.screen)
            widget = screen.query_one(QueueInputWidget)
            widget.set_value("steer me")
            screen.action_steer_current_task()
            await pilot.pause()
            assert widget.mode_label == "STEER mode"
            assert (
                "not implemented yet" in (screen._projection.footer_hint or "").lower()
            )

    @pytest.mark.asyncio
    async def test_input_errors_are_sanitized(self) -> None:
        app = RigConsoleApp(mode="fixture")
        async with app.run_test(size=(120, 40)) as pilot:
            screen = cast(DashboardScreen, pilot.app.screen)
            widget = screen.query_one(QueueInputWidget)
            widget.set_value("")
            screen.action_queue_message()
            await pilot.pause()
            footer = screen._projection.footer_hint or ""
            forbidden = (
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
            )
            assert not any(name in footer.lower() for name in forbidden)

    def test_enter_key_routes_to_submit(self) -> None:
        queued: list[str] = []
        steered: list[str] = []
        editor = _QueueEditor(
            on_submit=lambda: queued.append("queue"),
            on_shift_enter=lambda: steered.append("steer"),
        )
        asyncio.run(editor._on_key(events.Key("enter", None)))
        assert queued == ["queue"]
        asyncio.run(editor._on_key(events.Key("shift+enter", None)))
        assert steered == ["steer"]

    def test_queue_item_projection_rejects_raw_prompt(self) -> None:
        with pytest.raises(ValidationError):
            QueueItemProjection.model_validate({
                "queue_item_id": "q-1",
                "kind": "message",
                "status": "queued",
                "title": "Queue message",
                "prompt": "raw prompt",
            })
