"""Inspector drawer widget — selected content-light item details."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

from vibe.cli.textual_ui.rig_console.projections import InspectorProjection


class InspectorDrawerWidget(Vertical):
    """Render a selected inspector item and content-light summary."""

    DEFAULT_CSS = """
InspectorDrawerWidget {
    width: 100%;
    height: 1fr;
    padding: 0 1;
    background: transparent;
    border: none;
    display: none;
}

InspectorDrawerWidget.visible {
    display: block;
}

InspectorDrawerWidget > .inspector-title {
    width: 100%;
    height: auto;
    text-style: bold;
    color: #7D8590;
    margin-bottom: 0;
}

InspectorDrawerWidget > .inspector-state {
    width: 100%;
    height: auto;
    color: #7D8590;
    margin-bottom: 1;
}

InspectorDrawerWidget > .inspector-detail {
    width: 100%;
    height: auto;
    color: #E6EDF3;
}
"""

    class Updated(Message):
        """Posted when the widget's projection is updated."""

        def __init__(self, projection: InspectorProjection) -> None:
            self.projection = projection
            super().__init__()

    def __init__(
        self, projection: InspectorProjection, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._projection = projection

    def compose(self) -> ComposeResult:
        if self._projection.visible:
            self.add_class("visible")
        yield Static("ITEM INSPECTOR", classes="inspector-title")
        yield Static(self._build_state_text(), classes="inspector-state")
        yield Static(self._build_detail_text(), classes="inspector-detail")

    def update_projection(self, projection: InspectorProjection) -> None:
        self._projection = projection
        self.set_class(projection.visible, "visible")
        self._render_all()

    def _render_all(self) -> None:
        self._update_static("inspector-state", self._build_state_text())
        self._update_static("inspector-detail", self._build_detail_text())

    def _update_static(self, css_class: str, text: str) -> None:
        try:
            widget = self.query_one(f".{css_class}", Static)
            widget.update(text)
        except Exception:
            pass

    def _build_state_text(self) -> str:
        proj = self._projection
        if not proj.visible:
            return "Inspector closed"
        if not proj.items:
            return proj.empty_state
        selected = proj.selected_item
        if selected is None:
            return proj.empty_state
        position = min(proj.selected_index + 1, len(proj.items))
        return f"[dim]{selected.source_kind.upper()}[/]  -  {position} of {len(proj.items)}"

    def _build_detail_text(self) -> str:
        proj = self._projection
        if not proj.visible:
            return "Press 'i' to open inspector."
        item = proj.selected_item
        if item is None:
            return proj.empty_state

        lines = [
            f"[bold]Title:[/]   {item.title}",
            f"[bold]ID:[/]      {item.item_id}",
        ]
        if item.status:
            lines.append(f"[bold]Status:[/]  {item.status}")
        if item.tool_name:
            lines.append(f"[bold]Tool:[/]    {item.tool_name}")
        if item.created_at:
            lines.append(f"[bold]Created:[/] {item.created_at}")
        if item.duration_ms is not None:
            lines.append(f"[bold]Time:[/]    {item.duration_ms:.0f}ms")
        if item.changed_paths:
            lines.append(f"[bold]Paths:[/]   {', '.join(item.changed_paths[:3])}")
        if item.receipt_sha256:
            lines.append(f"[bold]Receipt:[/] {item.receipt_sha256}")
        if item.runtime_result_sha256:
            lines.append(f"[bold]Result:[/]  {item.runtime_result_sha256}")
        if item.error_kind:
            lines.append(f"[bold]Error:[/]   [red]{item.error_kind}[/]")
        if item.refusal_reason:
            lines.append(f"[bold]Refusal:[/] [red]{item.refusal_reason}[/]")
        if item.summary:
            lines.append(f"\n[bold]Summary:[/]\n{item.summary}")
        
        return "\n".join(lines)


__all__ = ["InspectorDrawerWidget"]
