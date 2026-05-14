"""Help overlay widget — shows available keybindings."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class HelpOverlayWidget(Vertical):
    """Render a help overlay with keybindings and descriptions."""

    DEFAULT_CSS = """
HelpOverlayWidget {
    width: 60;
    height: auto;
    padding: 1 2;
    background: $surface;
    border: double $accent;
    display: none;
    layer: help;
}

HelpOverlayWidget.visible {
    display: block;
}

HelpOverlayWidget > .help-header {
    width: 100%;
    height: auto;
    text-style: bold;
    color: $accent;
    margin-bottom: 1;
}

HelpOverlayWidget > .help-row {
    width: 100%;
    height: auto;
}
"""

    BINDINGS_HELP = [
        ("q", "Quit"),
        ("r", "Refresh"),
        ("?", "Toggle Help"),
        ("Enter", "Focus Prompt"),
        ("x", "Run Next Item"),
        ("v", "Run Validate"),
        ("i", "Toggle Inspector"),
        ("u", "Toggle Queue Panel"),
        ("f", "Toggle Fleet Panel"),
        ("j / k", "Next / Previous Queue"),
        ("n / p", "Next / Previous Item"),
        ("a", "Approve Mission Plan"),
        ("Esc", "Discard Plan / Close Overlay"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("COCKPIT CONTROLS", classes="help-header")
        for key, desc in self.BINDINGS_HELP:
            yield Static(f"{key:10} [dim]—[/] {desc}", classes="help-row")
        yield Static("\nPress '?' or 'Esc' to close", classes="help-row")

    def toggle(self) -> None:
        self.set_class(not self.has_class("visible"), "visible")


__all__ = ["HelpOverlayWidget"]
