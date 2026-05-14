"""Evidence rail widget — content-light receipt timeline.

Renders an EvidenceRailProjection: a header with counts, then a
scrollable list of receipt item summaries. No raw logs, file contents,
diffs, or command transcripts.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

from vibe.cli.textual_ui.rig_console.projections import EvidenceRailProjection

_MAX_TOOL_LABEL_LENGTH = 16
_MAX_PATH_LENGTH = 50
_MAX_ITEMS_DISPLAY = 20


def _cap(text: str | None, max_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _format_path(path: str) -> str:
    if len(path) <= _MAX_PATH_LENGTH:
        return path
    return "..." + path[-(_MAX_PATH_LENGTH - 3) :]


class EvidenceRailWidget(Vertical):
    """Render a content-light evidence rail from an EvidenceRailProjection.

    Displays:
    - Header: "Evidence" with counts (receipts / mutations / refusals / timeouts)
    - List of recent items: tool_name, status, error_kind, path, duration

    Empty state: "No receipts yet."
    No raw logs, file contents, diffs, or command transcripts.
    """

    DEFAULT_CSS = """
EvidenceRailWidget {
    width: 1fr;
    height: auto;
    padding: 0 1;
    background: transparent;
    border: none;
}

EvidenceRailWidget > .evidence-rail-header {
    width: 100%;
    height: auto;
    text-style: bold;
    color: #7D8590;
}

EvidenceRailWidget > .evidence-rail-counts {
    width: 100%;
    height: auto;
    color: #7D8590;
}

EvidenceRailWidget > .evidence-rail-items {
    width: 100%;
    height: auto;
    color: #E6EDF3;
}
"""

    class Updated(Message):
        """Posted when the widget's projection is updated."""

        def __init__(self, projection: EvidenceRailProjection) -> None:
            self.projection = projection
            super().__init__()

    def __init__(
        self, projection: EvidenceRailProjection, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._projection = projection

    def compose(self) -> ComposeResult:
        proj = self._projection
        yield Static(
            f"Evidence  [{proj.session_id[:12]}]", classes="evidence-rail-header"
        )
        yield Static(self._build_counts_text(proj), classes="evidence-rail-counts")
        yield Static(self._build_items_text(proj), classes="evidence-rail-items")

    def update_projection(self, projection: EvidenceRailProjection) -> None:
        """Replace the projection and re-render all child widgets."""
        self._projection = projection
        self._render_all()
        self.post_message(self.Updated(projection))

    def _render_all(self) -> None:
        proj = self._projection
        self._update_static(
            "evidence-rail-header", f"Evidence  [{proj.session_id[:12]}]"
        )
        self._update_static("evidence-rail-counts", self._build_counts_text(proj))
        self._update_static("evidence-rail-items", self._build_items_text(proj))

    def _update_static(self, css_class: str, text: str) -> None:
        """Update a child Static by class name, or skip if not mounted."""
        try:
            widget = self.query_one(f".{css_class}", Static)
            widget.update(text)
        except Exception:
            pass

    def _build_counts_text(self, proj: EvidenceRailProjection) -> str:
        parts: list[str] = []
        parts.append(f"receipts: {proj.receipt_count}")
        if proj.mutation_count > 0:
            parts.append(f"mutations: {proj.mutation_count}")
        if proj.refusal_count > 0:
            parts.append(f"refusals: {proj.refusal_count}")
        if proj.timeout_count > 0:
            parts.append(f"timeouts: {proj.timeout_count}")
        return "  ".join(parts)

    def _build_items_text(self, proj: EvidenceRailProjection) -> str:
        """Build text for all items, or empty state."""
        if not proj.items:
            return "No receipts yet."
        return "\n".join(self._build_item_text(item) for item in proj.items)

    def _build_item_text(self, item: object) -> str:
        """Build a one-line summary for an EvidenceRailItemProjection.

        Uses duck-typed access to avoid coupling to the specific
        projection class at call time.
        """
        parts: list[str] = []
        tool = getattr(item, "tool_name", "?")
        status = getattr(item, "status", "?")
        error_kind = getattr(item, "error_kind", None)

        parts.append(f"{_cap(tool, _MAX_TOOL_LABEL_LENGTH):>{_MAX_TOOL_LABEL_LENGTH}}")
        parts.append(f"{status}")

        if error_kind:
            parts.append(f"[{error_kind}]")

        path = getattr(item, "path", None) or getattr(item, "file", None)
        if path:
            parts.append(_format_path(path))

        duration = getattr(item, "duration_ms", None)
        if duration is not None:
            parts.append(f"({duration:.0f}ms)")

        return "  ".join(parts)


__all__ = ["EvidenceRailWidget"]
