"""Activity log widget — renders a rolling history of cockpit actions."""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class ActivityLogWidget(Vertical):
    """Render a rolling activity log of cockpit actions and events."""

    DEFAULT_CSS = """
ActivityLogWidget {
    width: 100%;
    height: 8;
    padding: 0 1;
    margin: 1 0;
    background: $surface;
    border: solid $accent;
    overflow-y: scroll;
}

ActivityLogWidget > .log-header {
    width: 100%;
    height: auto;
    text-style: bold;
    color: $accent;
    margin-bottom: 0;
}

ActivityLogWidget > .log-row {
    width: 100%;
    height: auto;
}
"""

    def __init__(self) -> None:
        super().__init__()
        self._logs: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static("ACTIVITY LOG", classes="log-header")

    def add_log(self, status: str, action: str, message: str | None = None) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        log = f"[dim]{ts}[/] [bold][{status.upper()}][/] {action}"
        if message:
            log += f": {message}"
        self._logs.append(log)
        if len(self._logs) > 50:
            self._logs.pop(0)
        
        self.mount(Static(log, classes="log-row"))
        self.scroll_end(animate=False)


__all__ = ["ActivityLogWidget"]
