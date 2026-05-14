"""Notification panel widget — renders recovery hints and transient notices."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class NotificationPanelWidget(Vertical):
    """Render transient notifications and recovery hints."""

    DEFAULT_CSS = """
NotificationPanelWidget {
    width: 40;
    height: auto;
    padding: 1 2;
    background: $surface;
    border: solid $warning;
    display: none;
    layer: help;
    dock: right;
    margin: 1;
}

NotificationPanelWidget.visible {
    display: block;
}

NotificationPanelWidget > .notification-header {
    width: 100%;
    height: auto;
    text-style: bold;
    color: $warning;
    margin-bottom: 1;
}

NotificationPanelWidget > .notification-body {
    width: 100%;
    height: auto;
    color: $text;
}
"""

    def compose(self) -> ComposeResult:
        yield Static("NOTICE", classes="notification-header")
        yield Static("", classes="notification-body")

    def notify(self, title: str, message: str) -> None:
        self.query_one(".notification-header", Static).update(title.upper())
        self.query_one(".notification-body", Static).update(message)
        self.add_class("visible")
        # Auto-hide after some time could be added here if needed

    def clear(self) -> None:
        self.remove_class("visible")


__all__ = ["NotificationPanelWidget"]
