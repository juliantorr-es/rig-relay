"""Tests for FooterStatusWidget — dashboard footer widget."""

from __future__ import annotations

from vibe.cli.textual_ui.rig_console.projections import (
    DashboardProjection,
    EvidenceRailProjection,
    SessionPaneProjection,
)
from vibe.cli.textual_ui.rig_console.widgets.footer_status import FooterStatusWidget


def _make_dashboard(
    footer_hint: str | None = None, backlog_items: list[str] | None = None
) -> DashboardProjection:
    return DashboardProjection(
        title="Dashboard",
        session=SessionPaneProjection(session_id="s1"),
        evidence=EvidenceRailProjection(session_id="s1"),
        footer_hint=footer_hint,
        backlog_items=backlog_items or [],
    )


class TestFooterStatusWidget:
    """FooterStatusWidget structural and content tests."""

    def test_can_instantiate_with_projection(self) -> None:
        proj = _make_dashboard()
        widget = FooterStatusWidget(proj)
        assert widget._projection is proj

    def test_compose_empty_state(self) -> None:
        proj = _make_dashboard()
        widget = FooterStatusWidget(proj)
        children = list(widget.compose())
        assert len(children) == 2

    def test_compose_with_hint(self) -> None:
        proj = _make_dashboard(footer_hint="q: quit")
        widget = FooterStatusWidget(proj)
        children = list(widget.compose())
        assert len(children) == 3

    def test_compose_with_backlog(self) -> None:
        proj = _make_dashboard(backlog_items=["Approve change", "Review report"])
        widget = FooterStatusWidget(proj)
        children = list(widget.compose())
        assert len(children) == 2

    def test_compose_with_hint_and_backlog(self) -> None:
        proj = _make_dashboard(
            footer_hint="q: quit", backlog_items=["Approve change", "Review report"]
        )
        widget = FooterStatusWidget(proj)
        children = list(widget.compose())
        assert len(children) == 3

    def test_build_backlog_text_empty(self) -> None:
        proj = _make_dashboard()
        widget = FooterStatusWidget(proj)
        text = widget._build_backlog_text(proj)
        assert text == "no backlog"

    def test_build_backlog_text_with_items(self) -> None:
        proj = _make_dashboard(backlog_items=["Item A", "Item B"])
        widget = FooterStatusWidget(proj)
        text = widget._build_backlog_text(proj)
        assert "backlog:" in text
        assert "Item A" in text
        assert "Item B" in text

    def test_update_projection_replaces_data(self) -> None:
        proj1 = _make_dashboard(footer_hint="old hint")
        proj2 = _make_dashboard(footer_hint="new hint")
        widget = FooterStatusWidget(proj1)
        assert widget._projection.footer_hint == "old hint"
        widget.update_projection(proj2)
        assert widget._projection.footer_hint == "new hint"

    def test_no_forbidden_raw_fields(self) -> None:
        proj = _make_dashboard()
        widget = FooterStatusWidget(proj)
        assert not hasattr(widget, "stdout")
        assert not hasattr(widget, "stderr")
        assert not hasattr(widget, "output")
        assert not hasattr(widget, "content")
        assert not hasattr(widget, "diff")
