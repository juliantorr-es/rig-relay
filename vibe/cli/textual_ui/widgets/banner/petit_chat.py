from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.timer import Timer
from textual.widgets import Static

from vibe.cli.textual_ui.widgets.braille_renderer import render_braille

WIDTH = 18
HEIGHT = 10
BASE_DOTS = {
    1j + 4,
    1j + 5,
    1j + 6,
    1j + 11,
    1j + 12,
    2j + 3,
    2j + 7,
    2j + 10,
    2j + 14,
    3j + 2,
    3j + 8,
    3j + 9,
    3j + 15,
    4j + 2,
    4j + 8,
    4j + 9,
    4j + 15,
    5j + 2,
    5j + 8,
    5j + 9,
    5j + 15,
    6j + 3,
    6j + 7,
    6j + 10,
    6j + 14,
    7j + 4,
    7j + 5,
    7j + 6,
    7j + 11,
    7j + 12,
}
PULSE_OFFSETS = (
    set[int](),
    {3j + 4, 3j + 13, 4j + 4, 4j + 13, 5j + 4, 5j + 13, 6j + 4, 6j + 13},
    {2j + 5, 2j + 12, 3j + 5, 3j + 12, 4j + 5, 4j + 12, 5j + 5, 5j + 12},
    {1j + 6, 1j + 11, 2j + 6, 2j + 11, 3j + 6, 3j + 11, 4j + 6, 4j + 11},
)


class PetitChat(Static):
    def __init__(self, animate: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs, classes="banner-chat")
        self._dots = set(BASE_DOTS)
        self._pulse_index = 0
        self._do_animate = animate
        self._freeze_requested = False
        self._timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static(render_braille(self._dots, WIDTH, HEIGHT), classes="petit-chat")

    def on_mount(self) -> None:
        self._inner = self.query_one(".petit-chat", Static)
        if self._do_animate:
            self._timer = self.set_interval(0.18, self._apply_next_pulse)

    def freeze_animation(self) -> None:
        self._freeze_requested = True

    def _apply_next_pulse(self) -> None:
        if self._freeze_requested and self._pulse_index == 0:
            if self._timer:
                self._timer.stop()
            self._timer = None
            return

        self._dots = set(BASE_DOTS)
        self._dots |= PULSE_OFFSETS[self._pulse_index]
        self._pulse_index = (self._pulse_index + 1) % len(PULSE_OFFSETS)
        self._inner.update(render_braille(self._dots, WIDTH, HEIGHT))
