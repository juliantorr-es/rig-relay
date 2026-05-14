"""Queue input widget — local-only queue/steer entry bar."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static, TextArea


class _QueueEditor(TextArea):
    def __init__(
        self,
        *,
        on_submit: Callable[[], None],
        on_shift_enter: Callable[[], None],
        **kwargs: Any,
    ) -> None:
        super().__init__(soft_wrap=True, show_line_numbers=False, **kwargs)
        self._on_submit = on_submit
        self._on_shift_enter = on_shift_enter

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self._on_submit()
            return
        if event.key == "shift+enter":
            event.stop()
            event.prevent_default()
            self._on_shift_enter()
            return
        await super()._on_key(event)


class QueueInputWidget(Vertical):
    """Render a queue input bar with explicit queue vs steer semantics."""

    DEFAULT_CSS = """
QueueInputWidget {
    width: 100%;
    height: auto;
    padding: 0 1;
    margin: 0 0 1 0;
    background: $surface;
    border: solid $border;
}

QueueInputWidget > .queue-input-title {
    width: 100%;
    height: auto;
    text-style: bold;
    color: $text;
}

QueueInputWidget > .queue-input-mode {
    width: 100%;
    height: auto;
    color: $text-muted;
}

QueueInputWidget > .queue-input-editor {
    width: 100%;
    height: 5;
}

QueueInputWidget > .queue-input-help {
    width: 100%;
    height: auto;
    color: $text-muted;
}
"""

    def __init__(
        self,
        on_queue: Callable[[str], None] | None = None,
        on_steer: Callable[[str], None] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._mode = "QUEUE"
        self._on_queue = on_queue
        self._on_steer = on_steer
        self._mode_widget: Static | None = None
        self._editor: _QueueEditor | None = None

    def compose(self) -> ComposeResult:
        yield Static("Queue Input", classes="queue-input-title")
        yield Static(self.mode_label, classes="queue-input-mode")
        yield _QueueEditor(
            on_submit=self.submit_current,
            on_shift_enter=self._insert_newline,
            classes="queue-input-editor",
            placeholder="Type a message to queue. Enter queues. Shift+Enter inserts a newline.",
        )
        yield Static(
            "Queue current task: Enter | Steering: command palette or Ctrl+Enter",
            classes="queue-input-help",
        )

    def on_mount(self) -> None:
        self._mode_widget = self.query_one(".queue-input-mode", Static)
        self._editor = self.query_one(_QueueEditor)

    @property
    def mode_label(self) -> str:
        return f"{self._mode} mode"

    def set_mode(self, mode: str) -> None:
        self._mode = mode.upper()
        if self._mode_widget is not None:
            self._mode_widget.update(self.mode_label)

    def focus_editor(self) -> None:
        if self._editor is not None:
            self._editor.focus()

    def value(self) -> str:
        if self._editor is None:
            return ""
        return self._editor.text

    def set_value(self, text: str) -> None:
        if self._editor is not None:
            self._editor.text = text

    def clear(self) -> None:
        self.set_value("")
        self.set_mode("QUEUE")

    def submit_current(self) -> None:
        if self._mode == "STEER":
            self.request_steer()
            return
        self.queue_current()

    def queue_current(self) -> None:
        if self._on_queue is not None:
            self._on_queue(self.value())

    def request_steer(self) -> None:
        if self._on_steer is not None:
            self._on_steer(self.value())

    def _insert_newline(self) -> None:
        if self._editor is None:
            return
        self._editor.insert("\n")


__all__ = ["QueueInputWidget"]
