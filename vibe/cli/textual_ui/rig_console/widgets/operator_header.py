"""Operator header widget — title, subtitle, and safety badge.

Renders a DashboardProjection's title, optional subtitle, and optional
safety state badge. No raw logs, file contents, diffs, or transcripts.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Static

from vibe.cli.textual_ui.rig_console.projections import DashboardProjection


class OperatorHeaderWidget(Horizontal):
    """Render a dashboard header: title, subtitle, and safety badge.

    Projection-driven: receives a DashboardProjection and renders its
    header fields.
    """

    DEFAULT_CSS = """
OperatorHeaderWidget {
    width: 100%;
    height: auto;
    padding: 0 1;
    margin: 0 0 1 0;
    background: $surface;
    border: solid $border;
}

OperatorHeaderWidget > .header-title {
    width: 100%;
    height: auto;
    text-style: bold;
    color: $text;
}

OperatorHeaderWidget > .header-subtitle {
    width: 100%;
    height: auto;
    color: $text-muted;
    margin: 0 0 0 1;
}

OperatorHeaderWidget > .header-safety {
    width: auto;
    height: auto;
    color: $success;
    text-style: bold;
    margin: 0 0 0 2;
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
        yield Static(proj.title, classes="header-title")
        if proj.subtitle:
            yield Static(proj.subtitle, classes="header-subtitle")
        if proj.safety_state:
            yield Static(f"⚡ {proj.safety_state}", classes="header-safety")

    def update_projection(self, projection: DashboardProjection) -> None:
        """Replace the projection and re-render all child widgets."""
        self._projection = projection
        self._render_all()
        self.post_message(self.Updated(projection))

    def _render_all(self) -> None:
        proj = self._projection
        self._update_static("header-title", proj.title)
        self._update_static("header-subtitle", proj.subtitle or "")
        self._update_static(
            "header-safety", f"⚡ {proj.safety_state}" if proj.safety_state else ""
        )

    def _update_static(self, css_class: str, text: str) -> None:
        """Update a child Static by class name, or skip if not mounted."""
        try:
            widget = self.query_one(f".{css_class}", Static)
            widget.update(text)
        except Exception:
            pass


__all__ = ["OperatorHeaderWidget"]
