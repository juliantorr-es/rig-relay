"""Tests for DashboardProjection — content-light dashboard model."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from vibe.cli.textual_ui.rig_console.projections import (
    DashboardProjection,
    EvidenceRailProjection,
    SessionPaneProjection,
)


class TestDashboardProjection:
    """DashboardProjection model tests."""

    def _minimal(self) -> DashboardProjection:
        return DashboardProjection(
            title="Test Dashboard",
            session=SessionPaneProjection(session_id="s1"),
            evidence=EvidenceRailProjection(session_id="s1"),
        )

    def test_defaults(self) -> None:
        proj = self._minimal()
        assert proj.title == "Test Dashboard"
        assert proj.subtitle is None
        assert proj.safety_state is None
        assert proj.footer_hint is None
        assert proj.backlog_items == []
        assert proj.backlog_capped == []

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            DashboardProjection.model_validate({
                "title": "x",
                "session": {"session_id": "s1"},
                "evidence": {"session_id": "s1"},
                "raw_output": "should_not_exist",
            })

    def test_full_construction(self) -> None:
        session = SessionPaneProjection(
            session_id="s1", status="active", task_title="Refactor auth"
        )
        evidence = EvidenceRailProjection(session_id="s1", receipt_count=3)
        proj = DashboardProjection(
            title="Operator View",
            subtitle="Active session",
            session=session,
            evidence=evidence,
            safety_state="active",
            footer_hint="q: quit",
            backlog_items=["item 1", "item 2", "item 3", "item 4", "item 5", "item 6"],
        )
        assert proj.title == "Operator View"
        assert proj.subtitle == "Active session"
        assert proj.safety_state == "active"
        assert proj.footer_hint == "q: quit"
        assert len(proj.backlog_items) == 6
        assert len(proj.backlog_capped) == 5  # _DASHBOARD_BACKLOG_CAP

    def test_backlog_capped_at_five(self) -> None:
        proj = DashboardProjection(
            title="x",
            session=SessionPaneProjection(session_id="s1"),
            evidence=EvidenceRailProjection(session_id="s1"),
            backlog_items=[f"item {i}" for i in range(10)],
        )
        assert len(proj.backlog_capped) == 5

    def test_backlog_capped_under_five(self) -> None:
        proj = DashboardProjection(
            title="x",
            session=SessionPaneProjection(session_id="s1"),
            evidence=EvidenceRailProjection(session_id="s1"),
            backlog_items=["only one"],
        )
        assert proj.backlog_capped == ["only one"]

    def test_no_raw_field_names(self) -> None:
        forbidden = (
            "stdout",
            "stderr",
            "output",
            "content",
            "diff",
            "snippet",
            "patch",
        )
        for field_name in DashboardProjection.model_fields:
            lower = field_name.lower()
            for prefix in forbidden:
                assert not lower.startswith(prefix), (
                    f"Field '{field_name}' starts with forbidden prefix '{prefix}'"
                )
