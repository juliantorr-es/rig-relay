"""Tests for OperatorHeaderWidget — dashboard header widget."""

from __future__ import annotations

from vibe.cli.textual_ui.rig_console.projections import (
    DashboardProjection,
    EvidenceRailProjection,
    SessionPaneProjection,
)
from vibe.cli.textual_ui.rig_console.widgets.operator_header import OperatorHeaderWidget


def _make_dashboard(
    title: str = "Dashboard",
    subtitle: str | None = None,
    safety_state: str | None = None,
) -> DashboardProjection:
    return DashboardProjection(
        title=title,
        subtitle=subtitle,
        session=SessionPaneProjection(session_id="s1"),
        evidence=EvidenceRailProjection(session_id="s1"),
        safety_state=safety_state,
    )


class TestOperatorHeaderWidget:
    """OperatorHeaderWidget structural and content tests."""

    def test_can_instantiate_with_projection(self) -> None:
        proj = _make_dashboard(title="Test Op")
        widget = OperatorHeaderWidget(proj)
        assert widget._projection is proj
        assert widget._projection.title == "Test Op"

    def test_compose_title_only(self) -> None:
        proj = _make_dashboard(title="Minimal")
        widget = OperatorHeaderWidget(proj)
        children = list(widget.compose())
        assert len(children) == 1  # title only

    def test_compose_with_subtitle(self) -> None:
        proj = _make_dashboard(title="Dashboard", subtitle="Active session")
        widget = OperatorHeaderWidget(proj)
        children = list(widget.compose())
        assert len(children) == 2

    def test_compose_with_safety(self) -> None:
        proj = _make_dashboard(
            title="Dashboard", subtitle="Session", safety_state="active"
        )
        widget = OperatorHeaderWidget(proj)
        children = list(widget.compose())
        assert len(children) == 3

    def test_update_projection_replaces_title(self) -> None:
        proj1 = _make_dashboard(title="First")
        proj2 = _make_dashboard(title="Second")
        widget = OperatorHeaderWidget(proj1)
        assert widget._projection.title == "First"
        widget.update_projection(proj2)
        assert widget._projection.title == "Second"

    def test_no_forbidden_raw_fields(self) -> None:
        proj = _make_dashboard()
        widget = OperatorHeaderWidget(proj)
        assert not hasattr(widget, "stdout")
        assert not hasattr(widget, "stderr")
        assert not hasattr(widget, "output")
        assert not hasattr(widget, "content")
        assert not hasattr(widget, "diff")
