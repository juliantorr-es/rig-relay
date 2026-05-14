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
    """Render read-only queue state from a QueueProjection.

    Layout:
    - Counts by status (Queued, Running, Blocked, etc.)
    - Currently running item if any
    - Selected item details if any
    - Recent terminal items summary
    """

    DEFAULT_CSS = """
QueuePanelWidget {
    width: 100%;
    height: 1fr;
    padding: 0 1;
    background: transparent;
    border-top: solid #1B2129;
    display: none;
}

QueuePanelWidget.visible {
    display: block;
}

QueuePanelWidget > .queue-header {
    width: 100%;
    height: auto;
    text-style: bold;
    color: #7D8590;
    margin-bottom: 0;
}

QueuePanelWidget > .queue-row {
    width: 100%;
    height: auto;
    color: #E6EDF3;
}

QueuePanelWidget > .queue-section {
    width: 100%;
    height: auto;
    margin-top: 1;
    border-top: solid $surface-lighten-1;
    padding-top: 1;
}
"""

    def __init__(self, projection: QueueProjection | None = None) -> None:
        super().__init__()
        self._projection = projection

    def compose(self) -> ComposeResult:
        if self._projection and self._projection.visible:
            self.add_class("visible")
        yield Static("QUEUE ORCHESTRATION", classes="queue-header")
        for widget in self._build_widgets():
            yield widget

    def update_projection(self, projection: QueueProjection | None) -> None:
        self._projection = projection
        if projection:
            self.set_class(projection.visible, "visible")
        self.remove_children()
        self.mount(Static("QUEUE ORCHESTRATION", classes="queue-header"))
        self.mount_all(self._build_widgets())

    def _render_lines(self) -> list[str]:
        """Build the list of lines to render for compatibility with old tests."""
        header = "Queue Panel"
        if self._projection is None:
            return [header, "[dim]no queue data[/]"]
        
        proj = self._projection
        lines = [header, f"Counts: {_format_counts(proj)}"]
        
        running = proj.running_item
        if running is not None:
            lines.append(f"Running: {_format_item(running)}")
            
        selected = proj.selected_item
        if selected is not None:
            lines.append(f"Selected: {selected.kind} {selected.status} {_cap(selected.title)}")
            if selected.payload_ref:
                lines.append(f"  Payload: {selected.payload_ref}")
            if selected.receipt_sha256:
                lines.append(f"  Receipt: {selected.receipt_sha256}")
            if selected.runtime_result_sha256:
                lines.append(f"  Result:  {selected.runtime_result_sha256}")
            if selected.summary:
                lines.append(f"Summary: {_cap(selected.summary)}")
            if selected.blocked_reason:
                lines.append(f"Blocked: {_cap(selected.blocked_reason)}")
        
        recent_terminal = [
            item
            for item in proj.items
            if item.status in {"completed", "failed", "cancelled"}
        ][:3]
        if recent_terminal:
            lines.append("Recent: " + " | ".join(_format_item(item) for item in recent_terminal))
                
        return lines

    def _build_widgets(self) -> list[Static]:
        if self._projection is None:
            return [Static("[dim]no queue data[/]", classes="queue-row")]

        proj = self._projection
        widgets = [Static(f"STATUS: {_format_counts(proj)}", classes="queue-row")]

        running = proj.running_item
        if running is not None:
            widgets.append(Static(f"[green]RUNNING:[/] {_format_item(running)}", classes="queue-section"))

        selected = proj.selected_item
        if selected is not None:
            details = [
                f"[accent]SELECTED:[/] {selected.kind} - {selected.status}",
                f"  Title:   {_cap(selected.title, 60)}",
                f"  Created: {selected.created_at or 'unknown'}",
            ]
            if selected.summary:
                details.append(f"  Summary: {_cap(selected.summary, 60)}")
            if selected.blocked_reason:
                details.append(f"  Blocked: [red]{_cap(selected.blocked_reason, 60)}[/]")
            
            widgets.append(Static("\n".join(details), classes="queue-section"))

        recent_terminal = [
            item
            for item in proj.items
            if item.status in {"completed", "failed", "cancelled"}
        ][:3]
        if recent_terminal:
            recent_line = "RECENT: " + " | ".join(_format_item(item) for item in recent_terminal)
            widgets.append(Static(recent_line, classes="queue-section"))

        if not proj.items:
            widgets.append(Static(f"[dim]{proj.empty_state}[/]", classes="queue-row"))

        return widgets


__all__ = ["QueuePanelWidget"]
