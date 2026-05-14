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
    height: auto;
    padding: 0 1;
    margin: 0 0 1 0;
    background: $surface;
    border: solid $border;
}

InspectorDrawerWidget > .inspector-title {
    width: 100%;
    height: auto;
    text-style: bold;
    color: $text;
}

InspectorDrawerWidget > .inspector-state {
    width: 100%;
    height: auto;
    color: $text-muted;
}

InspectorDrawerWidget > .inspector-detail {
    width: 100%;
    height: auto;
    color: $text;
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
        yield Static("Inspector", classes="inspector-title")
        yield Static(self._build_state_text(), classes="inspector-state")
        yield Static(self._build_detail_text(), classes="inspector-detail")

    def update_projection(self, projection: InspectorProjection) -> None:
        self._projection = projection
        self._render_all()
        self.post_message(self.Updated(projection))

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
        return f"{selected.source_kind}  {position}/{len(proj.items)}"

    def _build_detail_text(self) -> str:
        proj = self._projection
        if not proj.visible:
            return "Press i to open the inspector."
        item = proj.selected_item
        if item is None:
            return proj.empty_state

        lines = [f"{item.title}", f"id: {item.item_id}", f"source: {item.source_kind}"]
        if item.status:
            lines.append(f"status: {item.status}")
        if item.tool_name:
            lines.append(f"tool: {item.tool_name}")
        if item.created_at:
            lines.append(f"created: {item.created_at}")
        if item.duration_ms is not None:
            lines.append(f"duration: {item.duration_ms:.0f}ms")
        if item.changed_paths:
            lines.append(f"paths: {', '.join(item.changed_paths[:3])}")
        if item.receipt_sha256:
            lines.append(f"receipt: {item.receipt_sha256}")
        if item.runtime_result_sha256:
            lines.append(f"result: {item.runtime_result_sha256}")
        if item.error_kind:
            lines.append(f"error: {item.error_kind}")
        if item.refusal_reason:
            lines.append(f"refusal: {item.refusal_reason}")
        if item.summary:
            lines.append(f"summary: {item.summary}")
        return "\n".join(lines)


__all__ = ["InspectorDrawerWidget"]
