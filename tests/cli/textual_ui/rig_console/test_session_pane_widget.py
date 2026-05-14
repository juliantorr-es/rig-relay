"""Tests for SessionPaneWidget — projection-first session card widget."""

from __future__ import annotations

from vibe.cli.textual_ui.rig_console.projections import SessionPaneProjection
from vibe.cli.textual_ui.rig_console.widgets.session_pane import (
    SessionPaneWidget,
    _cap,
    _format_path,
)


def _make_projection(
    session_id: str = "test-session-123",
    status: str = "active",
    task_title: str | None = None,
    branch_name: str | None = None,
    worktree_path: str | None = None,
    current_step: str | None = None,
    validate_status: str | None = None,
    blocker_summary: dict[str, int] | None = None,
    receipt_count: int = 0,
    latest_receipt_kind: str | None = None,
    changed_paths: list[str] | None = None,
    pending_user_action: str | None = None,
    lane_id: str | None = None,
) -> SessionPaneProjection:
    return SessionPaneProjection(
        session_id=session_id,
        lane_id=lane_id,
        task_title=task_title,
        status=status,
        branch_name=branch_name,
        worktree_path=worktree_path,
        last_heartbeat_at="2026-05-14T15:30:00",
        current_step=current_step,
        validate_status=validate_status,
        blocker_summary=blocker_summary or {},
        receipt_count=receipt_count,
        latest_receipt_kind=latest_receipt_kind,
        changed_paths=changed_paths or [],
        pending_user_action=pending_user_action,
    )


class TestCap:
    """_cap() helper tests."""

    def test_none_returns_empty(self) -> None:
        assert _cap(None, 10) == ""

    def test_short_text_unchanged(self) -> None:
        assert _cap("hello", 10) == "hello"

    def test_long_text_truncated(self) -> None:
        result = _cap("hello world this is long", 12)
        assert result == "hello wor..."
        assert len(result) == 12

    def test_exact_length_unchanged(self) -> None:
        assert _cap("12345", 5) == "12345"


class TestFormatPath:
    """_format_path() helper tests."""

    def test_short_path_unchanged(self) -> None:
        assert _format_path("src/file.py") == "src/file.py"

    def test_long_path_truncated(self) -> None:
        long_path = "/very/long/path/that/exceeds/fifty/characters/file_name.py"
        result = _format_path(long_path)
        assert len(result) <= 50
        assert result.startswith("...")

    def test_exact_fifty_characters(self) -> None:
        path = "a" * 50
        assert _format_path(path) == path


class TestSessionPaneWidget:
    """SessionPaneWidget structural and content tests."""

    def test_can_instantiate_with_projection(self) -> None:
        proj = _make_projection()
        widget = SessionPaneWidget(proj)
        assert widget._projection is proj
        assert widget._projection.session_id == "test-session-123"

    def test_compose_does_not_raise(self) -> None:
        """Widget compose() should produce children without error."""
        proj = _make_projection()
        widget = SessionPaneWidget(proj)
        children = list(widget.compose())
        assert len(children) >= 3  # header + metadata + at least one content row

    def test_compose_with_full_projection(self) -> None:
        proj = _make_projection(
            session_id="full-session",
            status="active",
            task_title="Refactor auth",
            branch_name="feature/auth",
            worktree_path="/repo",
            current_step="Running preflight checks",
            validate_status="passed",
            receipt_count=5,
            latest_receipt_kind="bash",
            changed_paths=["src/auth.py", "tests/test_auth.py"],
            pending_user_action="approve_mutation",
            lane_id="main",
        )
        widget = SessionPaneWidget(proj)
        children = list(widget.compose())
        assert (
            len(children) == 7
        )  # header + meta + step + validate + receipts + paths + badge

    def test_compose_minimal_state(self) -> None:
        """Minimal projection should produce valid children."""
        proj = _make_projection(session_id="idle-session")
        widget = SessionPaneWidget(proj)
        children = list(widget.compose())
        assert len(children) >= 3

    def test_no_raw_forbidden_fields(self) -> None:
        """Widget should not expose raw output fields."""
        proj = _make_projection()
        widget = SessionPaneWidget(proj)
        # The widget only stores a projection, never raw data
        assert not hasattr(widget, "stdout")
        assert not hasattr(widget, "stderr")
        assert not hasattr(widget, "output")
        assert not hasattr(widget, "content")
        assert not hasattr(widget, "diff")

    def test_changed_paths_capped_in_text(self) -> None:
        """_build_paths_text should cap at _CHANGED_PATH_CAP."""
        proj = _make_projection(changed_paths=[f"path_{i}.py" for i in range(10)])
        widget = SessionPaneWidget(proj)
        text = widget._build_paths_text(proj)
        lines = text.strip().split("\n")
        assert "changed paths (10):" in lines[0]
        # Header + 5 capped paths
        assert len(lines) == 6

    def test_empty_blocker_renders_cleanly(self) -> None:
        proj = _make_projection(validate_status="passed", blocker_summary=None)
        widget = SessionPaneWidget(proj)
        text = widget._build_validate_text(proj)
        assert text == "validate: passed"

    def test_blocker_without_validate_status(self) -> None:
        proj = _make_projection(
            validate_status=None, blocker_summary={"dirty_files": 3, "policy_guard": 1}
        )
        widget = SessionPaneWidget(proj)
        text = widget._build_validate_text(proj)
        assert "blocked: 3 dirty files, 1 policy guard" in text

    def test_empty_receipt_renders_cleanly(self) -> None:
        proj = _make_projection(receipt_count=0)
        widget = SessionPaneWidget(proj)
        text = widget._build_receipt_text(proj)
        assert text == ""

    def test_receipt_text_with_count_only(self) -> None:
        proj = _make_projection(receipt_count=3)
        widget = SessionPaneWidget(proj)
        text = widget._build_receipt_text(proj)
        assert "receipts: 3" in text

    def test_empty_paths_renders_cleanly(self) -> None:
        proj = _make_projection(changed_paths=[])
        widget = SessionPaneWidget(proj)
        text = widget._build_paths_text(proj)
        assert text == ""

    def test_update_projection_replaces_data(self) -> None:
        proj1 = _make_projection(session_id="session-1", status="active")
        proj2 = _make_projection(session_id="session-2", status="blocked")
        widget = SessionPaneWidget(proj1)
        assert widget._projection.session_id == "session-1"
        widget.update_projection(proj2)
        assert widget._projection.session_id == "session-2"
        assert widget._projection.status == "blocked"
