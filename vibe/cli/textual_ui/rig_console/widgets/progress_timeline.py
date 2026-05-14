"""Progress timeline widget — content-light runtime execution progress.

Renders an ExecutionProgressProjection: status, timing, identity, output
summary, warnings, and terminal state. No raw stdout/stderr/chunk_text.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

from rig_relay.desktop.execution_progress import ExecutionProgressProjection

_MAX_MESSAGE_LENGTH = 200


class ProgressTimelineWidget(Vertical):
    """Render a content-light progress timeline from an ExecutionProgressProjection.

    Displays:
    - Empty state: "No runtime execution yet."
    - Status line: status + elapsed_ms
    - Identity line: short invocation/lease/request IDs
    - Heartbeat count
    - Output line: stdout_bytes/stderr_bytes + truncation badges
    - Warning line: latest_warning_kind/message
    - Terminal line: exit_code/error_kind/refusal_reason

    No raw logs, file contents, diffs, or command transcripts.
    """

    DEFAULT_CSS = """
ProgressTimelineWidget {
    width: 100%;
    height: auto;
    padding: 0 1;
    margin: 0 0 1 0;
    background: $surface;
    border: solid $border;
}

ProgressTimelineWidget > .progress-timeline-header {
    width: 100%;
    height: auto;
    text-style: bold;
    color: $text;
}

ProgressTimelineWidget > .progress-timeline-body {
    width: 100%;
    height: auto;
    color: $text;
    padding: 0 0 0 1;
}
"""

    class Updated(Message):
        """Posted when the widget's projection is updated."""

        def __init__(self, projection: ExecutionProgressProjection) -> None:
            self.projection = projection
            super().__init__()

    def __init__(
        self,
        projection: ExecutionProgressProjection | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._projection = projection or ExecutionProgressProjection()

    def compose(self) -> ComposeResult:
        yield Static("Progress", classes="progress-timeline-header")
        yield Static(
            self._build_body_text(self._projection), classes="progress-timeline-body"
        )

    def update_projection(self, projection: ExecutionProgressProjection) -> None:
        """Replace the projection and re-render all child widgets."""
        self._projection = projection
        self._render_all()
        self.post_message(self.Updated(projection))

    def _render_all(self) -> None:
        self._update_static(
            "progress-timeline-body", self._build_body_text(self._projection)
        )

    def _update_static(self, css_class: str, text: str) -> None:
        """Update a child Static by class name, or skip if not mounted."""
        try:
            widget = self.query_one(f".{css_class}", Static)
            widget.update(text)
        except Exception:
            pass

    def _build_body_text(self, proj: ExecutionProgressProjection) -> str:
        """Build the multi-line body text from the projection."""
        if self._is_empty(proj):
            return "No runtime execution yet."

        lines: list[str] = []
        self._add_status_line(lines, proj)
        self._add_identity_line(lines, proj)
        self._add_heartbeat_line(lines, proj)
        self._add_output_line(lines, proj)
        self._add_warning_line(lines, proj)
        self._add_terminal_lines(lines, proj)
        return "\n".join(lines)

    def _add_status_line(
        self, lines: list[str], proj: ExecutionProgressProjection
    ) -> None:
        status_line = f"status: {proj.status}"
        if proj.elapsed_ms is not None:
            status_line += f"  {proj.elapsed_ms:.0f}ms"
        lines.append(status_line)

    def _add_identity_line(
        self, lines: list[str], proj: ExecutionProgressProjection
    ) -> None:
        id_parts: list[str] = []
        if proj.invocation_id:
            id_parts.append(f"inv: {proj.invocation_id[:12]}")
        if proj.lease_id:
            id_parts.append(f"lease: {proj.lease_id[:12]}")
        if proj.request_id:
            id_parts.append(f"req: {proj.request_id[:12]}")
        if id_parts:
            lines.append("  ".join(id_parts))

    def _add_heartbeat_line(
        self, lines: list[str], proj: ExecutionProgressProjection
    ) -> None:
        if proj.heartbeat_count > 0:
            lines.append(f"heartbeats: {proj.heartbeat_count}")

    def _add_output_line(
        self, lines: list[str], proj: ExecutionProgressProjection
    ) -> None:
        out_parts: list[str] = []
        if proj.stdout_bytes is not None:
            label = f"stdout: {proj.stdout_bytes}b"
            if proj.stdout_truncated:
                label += " (truncated)"
            out_parts.append(label)
        if proj.stderr_bytes is not None:
            label = f"stderr: {proj.stderr_bytes}b"
            if proj.stderr_truncated:
                label += " (truncated)"
            out_parts.append(label)
        if out_parts:
            lines.append("  ".join(out_parts))

    def _add_warning_line(
        self, lines: list[str], proj: ExecutionProgressProjection
    ) -> None:
        if proj.warning_count > 0:
            warn = f"warnings: {proj.warning_count}"
            if proj.latest_warning_kind:
                warn += f"  [{proj.latest_warning_kind}]"
            if proj.latest_warning_message:
                msg = proj.latest_warning_message[:_MAX_MESSAGE_LENGTH]
                warn += f"  {msg}"
            lines.append(warn)

    def _add_terminal_lines(
        self, lines: list[str], proj: ExecutionProgressProjection
    ) -> None:
        if proj.exit_code is not None:
            lines.append(f"exit: {proj.exit_code}")
        if proj.error_kind:
            lines.append(f"error: {proj.error_kind}")
        if proj.refusal_reason:
            lines.append(f"refused: {proj.refusal_reason}")

    def _is_empty(self, proj: ExecutionProgressProjection) -> bool:
        """Return True if the projection has no meaningful data."""
        return not (
            proj.status != "pending"
            or proj.invocation_id is not None
            or proj.lease_id is not None
            or proj.request_id is not None
            or proj.heartbeat_count > 0
            or proj.warning_count > 0
            or proj.last_event_at is not None
            or proj.exit_code is not None
            or proj.error_kind is not None
            or proj.refusal_reason is not None
            or proj.stdout_bytes is not None
            or proj.stderr_bytes is not None
            or proj.elapsed_ms is not None
        )


__all__ = ["ProgressTimelineWidget"]
