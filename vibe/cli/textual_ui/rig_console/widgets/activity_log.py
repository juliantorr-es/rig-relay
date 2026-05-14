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
    height: 10;
    padding: 0 1;
    background: transparent;
    border-top: solid #1B2129;
    overflow-y: scroll;
}

ActivityLogWidget > .log-header {
    width: 100%;
    height: auto;
    text-style: bold;
    color: #7D8590;
    margin-bottom: 0;
}

ActivityLogWidget > .log-row {
    width: 100%;
    height: auto;
    color: #E6EDF3;
}
"""

    def __init__(self) -> None:
        super().__init__()
        self._logs: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static("SYSTEM ACTIVITY", classes="log-header")

    def add_log(self, status: str, action: str, message: str | None = None) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        
        # Color mapping for glass terminal palette
        color = "dim"
        if status.lower() in ("ok", "success", "completed", "done"):
            color = "green"
        elif status.lower() in ("running", "active", "started"):
            color = "cyan"
        elif status.lower() in ("warning", "waiting", "retry", "blocked"):
            color = "yellow"
        elif status.lower() in ("error", "failed", "refused"):
            color = "red"
            
        log = f"[dim]{ts}[/]  [bold][{color}]{status.upper():10}[/][/]  {action}"
        if message:
            # Content-light check: avoid raw payloads
            if "{" in message and "}" in message:
                message = "payload hidden (use inspector)"
            log += f": [dim]{message}[/]"
            
        self._logs.append(log)
        if len(self._logs) > 100:
            self._logs.pop(0)
        
        self.mount(Static(log, classes="log-row"))
        self.scroll_end(animate=False)


__all__ = ["ActivityLogWidget"]
