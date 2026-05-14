"""Footer status widget — footer hint and backlog items.

Renders a DashboardProjection's footer_hint and capped backlog_items.
No raw logs, file contents, diffs, or transcripts.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

from vibe.cli.textual_ui.rig_console.projections import DashboardProjection


class FooterStatusWidget(Vertical):
    """Render a dashboard footer: hint text and backlog items.

    Projection-driven: receives a DashboardProjection and renders its
    footer_hint and backlog_items (capped at _DASHBOARD_BACKLOG_CAP).
    Empty state when no backlog.
    """

    DEFAULT_CSS = """
FooterStatusWidget {
    width: 100%;
    height: auto;
    padding: 0 1;
    margin: 1 0 0 0;
    background: $surface;
    border: solid $border;
}

FooterStatusWidget > .footer-hint {
    width: 100%;
    height: auto;
    color: $text-muted;
}

FooterStatusWidget > .footer-backlog {
    width: 100%;
    height: auto;
    color: $text;
}
"""

    class Updated(Message):
        """Posted when the widget's projection is updated."""

        def __init__(self, projection: DashboardProjection) -> None:
            self.projection = projection
            super().__init__()

    def __init__(
        self, projection: DashboardProjection, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._projection = projection

    def compose(self) -> ComposeResult:
        proj = self._projection
        if proj.footer_hint:
            yield Static(proj.footer_hint, classes="footer-hint")
        yield Static(self._build_backlog_text(proj), classes="footer-backlog")

    def update_projection(self, projection: DashboardProjection) -> None:
        """Replace the projection and re-render all child widgets."""
        self._projection = projection
        self._render_all()
        self.post_message(self.Updated(projection))

    def _render_all(self) -> None:
        proj = self._projection
        if proj.footer_hint:
            self._update_static("footer-hint", proj.footer_hint)
        self._update_static("footer-backlog", self._build_backlog_text(proj))

    def _update_static(self, css_class: str, text: str) -> None:
        """Update a child Static by class name, or skip if not mounted."""
        try:
            widget = self.query_one(f".{css_class}", Static)
            widget.update(text)
        except Exception:
            pass

    def _build_backlog_text(self, proj: DashboardProjection) -> str:
        """Build text for the backlog section, or empty state."""
        capped = proj.backlog_capped
        if not capped:
            return "no backlog"
        lines = ["backlog:"]
        for item in capped:
            lines.append(f"  {item}")
        return "\n".join(lines)


__all__ = ["FooterStatusWidget"]
