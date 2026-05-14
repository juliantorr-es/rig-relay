"""Transcript widget for prompt-first Rig Console sessions."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from vibe.cli.textual_ui.rig_console.session_events import (
    CodingTranscriptItemProjection,
    CodingTranscriptProjection,
)

_TRANSCRIPT_MAX_ROWS = 24
_DROPPED_MARKER_PREFIX = "dropped_items"


class TranscriptWidget(Vertical):
    DEFAULT_CSS = """
TranscriptWidget {
    width: 100%;
    height: 1fr;
    padding: 0 1;
    background: $surface;
    border: solid $border;
}

TranscriptWidget > .transcript-row {
    width: 100%;
    height: auto;
}

TranscriptWidget > .dropped-marker {
    width: 100%;
    height: auto;
    color: $text-muted;
    text-style: italic;
}
"""

    def __init__(self, projection: CodingTranscriptProjection | None = None) -> None:
        super().__init__()
        self._projection = projection or CodingTranscriptProjection(
            session_id="unknown"
        )

    def compose(self) -> ComposeResult:
        dc = self._projection.dropped_count
        if dc > 0:
            yield Static(
                f"Older transcript items hidden: {dc}", classes="dropped-marker"
            )
        for item in self._projection.items[:_TRANSCRIPT_MAX_ROWS]:
            text = item.body_text or item.title
            yield Static(f"{item.kind}: {text}", classes="transcript-row")

    def update_projection(self, projection: CodingTranscriptProjection) -> None:
        self._projection = projection
        self.refresh()

    def append_item(self, item: CodingTranscriptItemProjection) -> None:
        text = item.body_text or item.title
        row = Static(f"{item.kind}: {text}", classes="transcript-row")
        self.mount(row)
        self.scroll_end(animate=False)
        self._maybe_prune()

    def _maybe_prune(self) -> None:
        rows = [c for c in self.children if _DROPPED_MARKER_PREFIX not in (c.id or "")]
        if len(rows) > _TRANSCRIPT_MAX_ROWS:
            rows[0].remove()


__all__ = ["TranscriptWidget"]
