"""Session pane widget — renders one session card from a SessionPaneProjection.

This widget is projection-first: it only displays content-light projection
data. It never reads raw logs, file contents, diffs, or tool output
directly. It is not a scrollback viewer.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

from vibe.cli.textual_ui.rig_console.projections import SessionPaneProjection

_CHANGED_PATH_CAP = 5
_MAX_TITLE_LENGTH = 60
_MAX_STEP_LENGTH = 80
_MAX_PATH_LENGTH = 50


def _cap(text: str | None, max_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _format_path(path: str) -> str:
    """Return a display-friendly short path."""
    if len(path) <= _MAX_PATH_LENGTH:
        return path
    return "..." + path[-(_MAX_PATH_LENGTH - 3) :]


def _format_blocker_summary(blockers: dict[str, int]) -> str:
    """Format a structured blocker dict into a stable display string.

    Produces output like: "3 dirty files, 1 policy guard"
    Keys are sorted alphabetically. Zero-value entries are skipped.
    """
    parts: list[str] = []
    for key in sorted(blockers.keys()):
        count = blockers[key]
        if count > 0:
            label = key.replace("_", " ")
            label = label[:20]
            parts.append(f"{count} {label}")
    return ", ".join(parts)


class SessionPaneWidget(Vertical):
    """Render one session card from a SessionPaneProjection.

    Default view is compact and calm: header row, metadata row,
    step/validate row, receipt summary, capped changed paths,
    and a pending-action badge if present.

    No raw logs, file contents, diffs, or command transcripts.
    """

    DEFAULT_CSS = """
SessionPaneWidget {
    width: 1fr;
    height: auto;
    padding: 0 1;
    background: transparent;
    border: none;
    border-right: solid #1B2129;
}

SessionPaneWidget > .session-pane-header {
    width: 100%;
    height: auto;
    text-style: bold;
    color: #7D8590;
}

SessionPaneWidget > .session-pane-metadata {
    width: 100%;
    height: auto;
    color: #7D8590;
}

SessionPaneWidget > .session-pane-step {
    width: 100%;
    height: auto;
    color: #E6EDF3;
}

SessionPaneWidget > .session-pane-validate {
    width: 100%;
    height: auto;
}

SessionPaneWidget > .session-pane-receipts {
    width: 100%;
    height: auto;
    color: $text-muted;
}

SessionPaneWidget > .session-pane-paths {
    width: 100%;
    height: auto;
    color: $text-muted;
}

SessionPaneWidget > .session-pane-action-badge {
    width: auto;
    height: auto;
    background: $accent;
    color: $text;
    text-style: bold;
    padding: 0 1;
}
"""

    class Updated(Message):
        """Posted when the widget's projection is updated."""

        def __init__(self, projection: SessionPaneProjection) -> None:
            self.projection = projection
            super().__init__()

    def __init__(
        self, projection: SessionPaneProjection, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._projection = projection
        self._header: Static | None = None
        self._metadata: Static | None = None
        self._step: Static | None = None
        self._validate: Static | None = None
        self._receipts: Static | None = None
        self._paths: Static | None = None
        self._action_badge: Static | None = None

    def compose(self) -> ComposeResult:
        proj = self._projection

        # Header: session/lane/status
        header_parts = [proj.session_id[:12]]
        if proj.lane_id:
            header_parts.append(f" [{proj.lane_id}]")
        header_parts.append(f"  {proj.status}")
        if proj.task_title:
            header_parts.append(f"  {_cap(proj.task_title, _MAX_TITLE_LENGTH)}")
        yield Static("".join(header_parts), classes="session-pane-header")

        # Metadata row: branch / worktree / heartbeat
        meta_parts: list[str] = []
        if proj.branch_name:
            meta_parts.append(f" {proj.branch_name}")
        if proj.worktree_path:
            meta_parts.append(f"📁 {proj.worktree_path}")
        if proj.last_heartbeat_at:
            meta_parts.append(f"❤ {proj.last_heartbeat_at[:19].replace('T', ' ')}")
        yield Static("  ".join(meta_parts), classes="session-pane-metadata")

        # Current step
        if proj.current_step:
            yield Static(
                _cap(proj.current_step, _MAX_STEP_LENGTH), classes="session-pane-step"
            )
        else:
            yield Static("", classes="session-pane-step")

        # Validate status
        validate_text = self._build_validate_text(proj)
        yield Static(validate_text, classes="session-pane-validate")

        # Receipt summary
        receipt_text = self._build_receipt_text(proj)
        yield Static(receipt_text, classes="session-pane-receipts")

        # Changed paths (capped)
        paths_text = self._build_paths_text(proj)
        yield Static(paths_text, classes="session-pane-paths")

        # Pending action badge
        if proj.pending_user_action:
            yield Static(
                f"⏳ {proj.pending_user_action}", classes="session-pane-action-badge"
            )

    def update_projection(self, projection: SessionPaneProjection) -> None:
        """Replace the projection and re-render all child widgets."""
        self._projection = projection
        self._render_all()
        self.post_message(self.Updated(projection))

    def _render_all(self) -> None:
        proj = self._projection

        # Rebuild header
        header_parts = [proj.session_id[:12]]
        if proj.lane_id:
            header_parts.append(f" [{proj.lane_id}]")
        header_parts.append(f"  {proj.status}")
        if proj.task_title:
            header_parts.append(f"  {_cap(proj.task_title, _MAX_TITLE_LENGTH)}")
        self._update_static("session-pane-header", "".join(header_parts))

        # Metadata
        meta_parts: list[str] = []
        if proj.branch_name:
            meta_parts.append(f" {proj.branch_name}")
        if proj.worktree_path:
            meta_parts.append(f"📁 {proj.worktree_path}")
        if proj.last_heartbeat_at:
            meta_parts.append(f"❤ {proj.last_heartbeat_at[:19].replace('T', ' ')}")
        self._update_static("session-pane-metadata", "  ".join(meta_parts))

        # Step
        step_text = (
            _cap(proj.current_step, _MAX_STEP_LENGTH) if proj.current_step else ""
        )
        self._update_static("session-pane-step", step_text)

        # Validate
        self._update_static("session-pane-validate", self._build_validate_text(proj))

        # Receipts
        self._update_static("session-pane-receipts", self._build_receipt_text(proj))

        # Paths
        self._update_static("session-pane-paths", self._build_paths_text(proj))

        # Action badge
        if proj.pending_user_action:
            self._update_static(
                "session-pane-action-badge", f"⏳ {proj.pending_user_action}"
            )
        else:
            self._update_static("session-pane-action-badge", "")

    def _update_static(self, css_class: str, text: str) -> None:
        """Update a child Static by class name, or skip if not mounted."""
        try:
            widget = self.query_one(f".{css_class}", Static)
            widget.update(text)
        except Exception:
            pass

    def _build_validate_text(self, proj: SessionPaneProjection) -> str:
        parts: list[str] = []
        vs = proj.validate_status
        if vs:
            parts.append(f"validate: {vs}")
        if proj.blocker_summary:
            formatted = _format_blocker_summary(proj.blocker_summary)
            if formatted:
                parts.append(f"blocked: {formatted}")
        if proj.blocker_summary and not vs:
            parts.append("blocked")
        return "  ".join(parts) if parts else ""

    def _build_receipt_text(self, proj: SessionPaneProjection) -> str:
        parts: list[str] = []
        if proj.receipt_count > 0:
            parts.append(f"receipts: {proj.receipt_count}")
        if proj.latest_receipt_kind:
            parts.append(f"latest: {proj.latest_receipt_kind}")
        return "  ".join(parts) if parts else ""

    def _build_paths_text(self, proj: SessionPaneProjection) -> str:
        if not proj.changed_paths:
            return ""
        capped = sorted(proj.changed_paths)[:_CHANGED_PATH_CAP]
        lines: list[str] = []
        lines.append(f"changed paths ({len(proj.changed_paths)}):")
        for p in capped:
            lines.append(f"  {_format_path(p)}")
        return "\n".join(lines)
