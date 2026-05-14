"""Status bar widget — renders current cockpit mode and action status."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from vibe.cli.textual_ui.rig_console.projections import DashboardProjection


class StatusBarWidget(Horizontal):
    """Render a persistent status bar with cockpit mode and last action result."""

    DEFAULT_CSS = """
StatusBarWidget {
    width: 100%;
    height: 1;
    background: $accent;
    color: $text;
    padding: 0 1;
}

StatusBarWidget > .status-left {
    width: 25%;
    text-style: bold;
}

StatusBarWidget > .status-center {
    width: 50%;
    text-align: center;
}

StatusBarWidget > .status-right {
    width: 25%;
    text-align: right;
}
"""

    def __init__(self, projection: DashboardProjection | None = None) -> None:
        super().__init__()
        self._projection = projection

    def compose(self) -> ComposeResult:
        yield Static(self._render_mode(), classes="status-left")
        yield Static(self._render_hint(), classes="status-center")
        yield Static(self._render_counts(), classes="status-right")

    def update_projection(self, projection: DashboardProjection) -> None:
        self._projection = projection
        self.query_one(".status-left", Static).update(self._render_mode())
        self.query_one(".status-center", Static).update(self._render_hint())
        self.query_one(".status-right", Static).update(self._render_counts())

    def _render_mode(self) -> str:
        if not self._projection:
            return "BOOTING"
        status = self._projection.session.status or "READY"
        return f"MODE: {status.upper()}"

    def _render_hint(self) -> str:
        if not self._projection:
            return ""
        return self._projection.footer_hint or "Ready"

    def _render_counts(self) -> str:
        if not self._projection:
            return ""
        q = self._projection.queue
        return f"Q: {q.queued_count}  R: {q.running_count}  B: {q.blocked_count}"


__all__ = ["StatusBarWidget"]
