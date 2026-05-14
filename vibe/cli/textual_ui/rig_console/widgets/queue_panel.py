"""Queue panel widget — renders content-light queue state."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from vibe.cli.textual_ui.rig_console.projections import QueueProjection


def _cap(text: str, max_chars: int = 32) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _format_counts(queue: QueueProjection) -> str:
    parts: list[str] = []
    if queue.queued_count:
        parts.append(f"[blue]{queue.queued_count} queued[/]")
    if queue.running_count:
        parts.append(f"[green]{queue.running_count} running[/]")
    if queue.blocked_count:
        parts.append(f"[red]{queue.blocked_count} blocked[/]")
    if queue.completed_count:
        parts.append(f"[dim]{queue.completed_count} done[/]")
    if queue.failed_count:
        parts.append(f"[red]{queue.failed_count} failed[/]")
    if queue.cancelled_count:
        parts.append(f"[dim]{queue.cancelled_count} cancelled[/]")
    return "  ".join(parts) if parts else "[dim]queue empty[/]"


def _format_item(item: Any) -> str:
    bits = [item.kind, item.status, _cap(item.title)]
    return "  ".join(bit for bit in bits if bit)


class QueuePanelWidget(Vertical):
    """Render read-only queue state from a QueueProjection."""

    DEFAULT_CSS = """
QueuePanelWidget {
    width: 100%;
    height: auto;
    padding: 0 1;
    margin: 0 0 1 0;
    background: $surface;
    border: solid $border;
}

QueuePanelWidget > .queue-header {
    width: 100%;
    height: auto;
    text-style: bold;
    color: $text;
}

QueuePanelWidget > .queue-row {
    width: 100%;
    height: auto;
}
"""

    def __init__(self, projection: QueueProjection | None = None) -> None:
        super().__init__()
        self._projection = projection

    def compose(self) -> ComposeResult:
        for line in self._render_lines():
            yield Static(line, classes="queue-row")

    def update_projection(self, projection: QueueProjection | None) -> None:
        self._projection = projection
        self.remove_children()
        for child in self._build_widgets():
            self.mount(child)

    def _build_widgets(self) -> list[Static]:
        return [Static(line, classes="queue-row") for line in self._render_lines()]

    def _render_lines(self) -> list[str]:
        lines = ["Queue Panel"]
        if self._projection is None:
            lines.append("[dim]no queue data[/]")
            return lines
        proj = self._projection
        lines.append(f"Counts: {_format_counts(proj)}")
        running = proj.running_item
        if running is not None:
            lines.append(f"Running: {_format_item(running)}")
        selected = proj.selected_item
        if selected is None:
            lines.append(f"[dim]{proj.empty_state}[/]")
            return lines
        lines.append(
            f"Selected: {selected.kind} {selected.status} {_cap(selected.title)}"
        )
        lines.append(f"Created: {selected.created_at or 'unknown'}")
        if selected.blocked_reason:
            lines.append(f"Blocked: {_cap(selected.blocked_reason)}")
        refs: list[str] = []
        if selected.receipt_sha256:
            refs.append(f"receipt {selected.receipt_sha256}")
        if selected.runtime_result_sha256:
            refs.append(f"runtime {selected.runtime_result_sha256}")
        if refs:
            lines.append("Refs: " + "  ".join(refs))
        blocked = [item for item in proj.items if item.status == "blocked"][:3]
        if blocked:
            lines.append(
                "Blocked: " + " | ".join(_format_item(item) for item in blocked)
            )
        recent_terminal = [
            item
            for item in proj.items
            if item.status in {"completed", "failed", "cancelled"}
        ][:3]
        if recent_terminal:
            lines.append(
                "Recent: " + " | ".join(_format_item(item) for item in recent_terminal)
            )
        return lines


__all__ = ["QueuePanelWidget"]
