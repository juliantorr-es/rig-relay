"""Tests for SessionPaneProjection — content-light projection model."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from vibe.cli.textual_ui.rig_console.projections import SessionPaneProjection


class TestSessionPaneProjection:
    """SessionPaneProjection field and method tests."""

    def test_default_values(self) -> None:
        proj = SessionPaneProjection(session_id="test-session")
        assert proj.session_id == "test-session"
        assert proj.lane_id is None
        assert proj.task_title is None
        assert proj.status == "unknown"
        assert proj.branch_name is None
        assert proj.worktree_path is None
        assert proj.last_heartbeat_at is None
        assert proj.current_step is None
        assert proj.validate_status is None
        assert proj.blocker_summary == {}
        assert proj.receipt_count == 0
        assert proj.latest_receipt_kind is None
        assert proj.changed_paths == []
        assert proj.pending_user_action is None

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            SessionPaneProjection.model_validate({
                "session_id": "test",
                "raw_stdout": "should_not_exist",
            })

    def test_with_heartbeat_sets_iso_timestamp(self) -> None:
        proj = SessionPaneProjection(session_id="test")
        now = datetime(2026, 5, 14, 15, 30, 0, tzinfo=UTC)
        updated = proj.with_heartbeat(now=now)
        assert updated.last_heartbeat_at == "2026-05-14T15:30:00+00:00"

    def test_with_heartbeat_does_not_mutate_original(self) -> None:
        proj = SessionPaneProjection(session_id="test")
        now = datetime(2026, 5, 14, 15, 30, 0, tzinfo=UTC)
        updated = proj.with_heartbeat(now=now)
        assert proj.last_heartbeat_at is None
        assert updated.last_heartbeat_at is not None

    def test_with_blocker_sets_status_and_summary(self) -> None:
        proj = SessionPaneProjection(session_id="test")
        updated = proj.with_blocker({"dirty_files": 3, "policy_guard": 1})
        assert updated.blocker_summary == {"dirty_files": 3, "policy_guard": 1}
        assert updated.validate_status == "blocked"

    def test_with_receipt_increments_count(self) -> None:
        proj = SessionPaneProjection(session_id="test")
        updated = proj.with_receipt("bash").with_receipt("validate")
        assert updated.receipt_count == 2
        assert updated.latest_receipt_kind == "validate"

    def test_sort_changed_paths_caps_at_default(self) -> None:
        proj = SessionPaneProjection(
            session_id="test",
            changed_paths=[
                "z_file.py",
                "a_file.py",
                "m_file.py",
                "b_file.py",
                "c_file.py",
                "d_file.py",
            ],
        )
        updated = proj.sort_changed_paths(max_paths=3)
        assert updated.changed_paths == ["a_file.py", "b_file.py", "c_file.py"]

    def test_sort_changed_paths_does_not_mutate_original(self) -> None:
        original_paths = ["z_file.py", "a_file.py"]
        proj = SessionPaneProjection(
            session_id="test", changed_paths=list(original_paths)
        )
        updated = proj.sort_changed_paths(max_paths=5)
        assert proj.changed_paths == original_paths
        assert updated.changed_paths == ["a_file.py", "z_file.py"]

    def test_to_display_dict_excludes_none(self) -> None:
        proj = SessionPaneProjection(session_id="test", status="active")
        d = proj.to_display_dict()
        assert "session_id" in d
        assert "status" in d
        assert "lane_id" not in d
        assert "task_title" not in d
        assert "branch_name" not in d

    def test_to_display_dict_includes_non_none(self) -> None:
        proj = SessionPaneProjection(
            session_id="test",
            status="active",
            lane_id="main",
            branch_name="feature/x",
            receipt_count=3,
        )
        d = proj.to_display_dict()
        assert d["lane_id"] == "main"
        assert d["branch_name"] == "feature/x"
        assert d["receipt_count"] == 3

    def test_no_raw_fields_in_projection(self) -> None:
        """Ensure projection has no field names matching forbidden patterns."""
        forbidden_prefixes = (
            "stdout",
            "stderr",
            "output",
            "content",
            "diff",
            "snippet",
            "patch",
            "prompt",
            "secret",
            "argv",
            "file_",
            "old_",
            "new_",
            "chunk_",
        )
        for field_name in SessionPaneProjection.model_fields:
            lower = field_name.lower()
            for prefix in forbidden_prefixes:
                assert not lower.startswith(prefix), (
                    f"Field '{field_name}' starts with forbidden prefix '{prefix}'"
                )

    def test_empty_blocker_receipt_state_renders_cleanly(self) -> None:
        """Minimal projection should be constructable and dumpable."""
        proj = SessionPaneProjection(session_id="idle-session")
        d = proj.to_display_dict()
        assert d["session_id"] == "idle-session"
        assert d["status"] == "unknown"
        assert d["receipt_count"] == 0
        assert d["changed_paths"] == []

    def test_full_projection(self) -> None:
        proj = SessionPaneProjection(
            session_id="full-session",
            lane_id="lane-1",
            task_title="Refactor auth",
            status="active",
            branch_name="feature/auth",
            worktree_path="/repo",
            last_heartbeat_at="2026-05-14T15:30:00",
            current_step="Running tests",
            validate_status="passed",
            blocker_summary={},
            receipt_count=5,
            latest_receipt_kind="bash",
            changed_paths=["src/auth.py", "tests/test_auth.py"],
            pending_user_action="approve_mutation",
        )
        assert proj.session_id == "full-session"
        assert proj.receipt_count == 5
        assert proj.pending_user_action == "approve_mutation"
