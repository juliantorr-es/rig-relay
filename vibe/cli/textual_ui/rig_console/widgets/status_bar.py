"""Status bar widget — renders current cockpit mode and action status."""

from __future__ import annotations

from typing import Any

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
    width: 20%;
    text-style: bold;
}

StatusBarWidget > .status-center {
    width: 45%;
    text-align: center;
}

StatusBarWidget > .status-right {
    width: 35%;
    text-align: right;
}
"""

    def __init__(self, projection: DashboardProjection | None = None) -> None:
        super().__init__()
        self._projection = projection
        self._context_envelope: Any | None = None

    def compose(self) -> ComposeResult:
        yield Static(self._render_mode(), classes="status-left")
        yield Static(self._render_hint(), classes="status-center")
        yield Static(self._render_metrics(), classes="status-right")

    def update_projection(self, projection: DashboardProjection) -> None:
        self._projection = projection
        self.query_one(".status-left", Static).update(self._render_mode())
        self.query_one(".status-center", Static).update(self._render_hint())
        self.query_one(".status-right", Static).update(self._render_metrics())

    def set_context_envelope(self, envelope: Any | None) -> None:
        self._context_envelope = envelope
        try:
            self.query_one(".status-right", Static).update(self._render_metrics())
        except Exception:
            pass

    def _render_mode(self) -> str:
        if not self._projection:
            return "BOOTING"
        status = self._projection.session.status or "READY"
        return f"MODE: {status.upper()}"

    def _render_hint(self) -> str:
        if not self._projection:
            return ""

        hint = self._projection.footer_hint or "Ready"

        econ = self._projection.validation_economy
        if econ:
            skipped_sec = econ.work_skipped_ms / 1000
            hint = f"{hint}  |  [green]Cache Hits:[/] {econ.cache_hits} ([dim]saved {skipped_sec:.1f}s[/])"

        return hint

    def _render_metrics(self) -> str:
        parts: list[str] = []
        if self._context_envelope:
            env = self._context_envelope
            cache = "hit" if env.is_cached else "miss"
            parts.append(f"CTX: {env.section_count}s·{cache}")
        q = self._projection.queue if self._projection else None
        if q:
            parts.append(f"Q: {q.queued_count} R: {q.running_count} B: {q.blocked_count}")
        return "  ".join(parts) if parts else ""


__all__ = ["StatusBarWidget"]
