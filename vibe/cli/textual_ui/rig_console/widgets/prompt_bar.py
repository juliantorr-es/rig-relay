"""Prompt bar widget — single-line queue input using Textual Input.

Phase 0: Enter queues a message. No steer mode. No raw mutation.
Missing roots are safe — shows disabled/refused status.
"""

from __future__ import annotations

from collections.abc import Callable

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input, Static


class PromptBar(Horizontal):
    """Single-line prompt bar for queueing instructions.

    Uses Textual Input (not TextArea) for simplicity.
    Enter submits the input. Empty/whitespace does nothing.
    Styling is optimized for high visibility and clear focus.
    """

    DEFAULT_CSS = """
PromptBar {
    width: 100%;
    height: 3;
    padding: 0 1;
    margin: 1 0;
    background: $surface;
    border: tall $accent;
}

PromptBar > .prompt-input {
    width: 1fr;
    height: 1;
    border: none;
    background: transparent;
    color: $text;
}

PromptBar:focus-within {
    border: tall $accent-lighten-2;
}
"""

    def __init__(
        self,
        on_submit: Callable[[str], None] | None = None,
        placeholder: str = "Type mission or instruction; Enter to plan/queue...",
        disabled: bool = False,
    ) -> None:
        super().__init__()
        self._on_submit = on_submit
        self._placeholder = placeholder
        self._disabled = disabled
        self._input: Input | None = None

    def compose(self) -> ComposeResult:
        self._input = Input(
            placeholder=self._placeholder,
            classes="prompt-input",
            disabled=self._disabled,
        )
        yield self._input

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in the input field."""
        event.stop()
        text = event.value.strip()
        if not text:
            return
        if self._on_submit is not None:
            self._on_submit(text)
            # We don't auto-clear here; the screen handles it on success
            # to avoid losing input on transient routing errors.

    def clear_input(self) -> None:
        if self._input is not None:
            self._input.value = ""

    def set_disabled(self, disabled: bool) -> None:
        self._disabled = disabled
        if self._input is not None:
            self._input.disabled = disabled

    def focus_input(self) -> None:
        if self._input is not None and not self._input.disabled:
            self._input.focus()

    @property
    def value(self) -> str:
        if self._input is None:
            return ""
        return self._input.value.strip()

    @value.setter
    def value(self, text: str) -> None:
        if self._input is not None:
            self._input.value = text


__all__ = ["PromptBar"]
