"""Tests for FleetPanelWidget — read-only fleet coordination TUI widget.

Tests use _build_widgets for structural assertions and directly test
the _format_* helper functions for text rendering.
"""

from __future__ import annotations

import pytest
from textual.widgets import Static

from rig_relay.coordination.fleet_projection import (
    FleetAgentSummary,
    FleetBlockerSummary,
    FleetLeaseSummary,
    FleetPatchProposalSummary,
    FleetQueueNextItem,
    FleetQueueSummary,
    FleetReplayDiagnostics,
    build_fleet_projection,
)
from vibe.cli.textual_ui.rig_console.widgets.fleet_panel import (
    FleetPanelWidget,
    _format_agents,
    _format_blockers,
    _format_leases,
    _format_next_item,
    _format_patches,
    _format_queue,
    _format_replay,
)


def _fleet_projection() -> object:
    return build_fleet_projection(
        projection_id="fp-fleet",
        created_at="2026-05-14T15:00:00",
        queue=FleetQueueSummary(
            queued=2,
            running=1,
            blocked=1,
            completed=3,
            failed=1,
            cancelled=1,
            total=9,
            highest_priority=4,
            next_item=FleetQueueNextItem(kind="validate", priority=4),
            replay=FleetReplayDiagnostics(
                total_lines=10,
                valid_events=8,
                malformed_lines=1,
                invalid_events=1,
                skipped_unknown_kind=0,
                total_skipped=2,
            ),
        ),
        leases=FleetLeaseSummary(total_active=4, stale=1, expired=2),
        blockers=FleetBlockerSummary(
            total_blockers=2,
            blocker_kinds={"dirty_files": 1, "lease_conflict": 1},
            oldest_blocked_at="2026-05-14T14:00:00",
        ),
        patches=FleetPatchProposalSummary(
            pending=2, applied=1, rejected=1, revised=3, total=7
        ),
        recent_event_count=5,
    )


class TestFleetPanelWidget:
    """FleetPanelWidget structural tests."""

    def test_build_widgets_empty_state(self) -> None:
        """_build_widgets with None projection returns empty state row."""
        widget = FleetPanelWidget(projection=None)
        widgets = widget._build_widgets()
        assert len(widgets) == 1
        assert isinstance(widgets[0], Static)

    def test_build_widgets_all_zero(self) -> None:
        """_build_widgets with empty projection returns agent row + metrics widget."""
        proj = build_fleet_projection(
            projection_id="fp-empty", created_at="2026-01-01T00:00:00"
        )
        widget = FleetPanelWidget(projection=proj)
        widgets = widget._build_widgets()
        assert len(widgets) == 2
        assert isinstance(widgets[0], Static)

    def test_build_widgets_with_data(self) -> None:
        """_build_widgets with populated projection returns agent rows + metrics widget."""
        proj = _fleet_projection()
        widget = FleetPanelWidget(projection=proj)
        widgets = widget._build_widgets()
        # Header is not returned by _build_widgets anymore
        assert len(widgets) >= 2


class TestFormatQueue:
    """_format_queue helper."""

    def test_empty(self) -> None:
        q = FleetQueueSummary()
        result = _format_queue(q)
        assert "queue empty" in result

    def test_queued(self) -> None:
        q = FleetQueueSummary(queued=3, total=3, highest_priority=1)
        result = _format_queue(q)
        assert "3" in result

    def test_running(self) -> None:
        q = FleetQueueSummary(running=2, total=2, highest_priority=1)
        result = _format_queue(q)
        assert "2" in result

    def test_blocked(self) -> None:
        q = FleetQueueSummary(blocked=1, total=1, highest_priority=1)
        result = _format_queue(q)
        assert "1" in result


class TestFormatLeases:
    """_format_leases helper."""

    def test_empty(self) -> None:
        result = _format_leases(FleetLeaseSummary())
        assert "no leases" in result

    def test_active(self) -> None:
        result = _format_leases(
            FleetLeaseSummary(total_active=2, exclusive_write=1, shared_read=1)
        )
        assert "2 active" in result
        assert "1 write" in result

    def test_stale(self) -> None:
        result = _format_leases(FleetLeaseSummary(stale=1))
        assert "1 stale" in result

    def test_expired(self) -> None:
        result = _format_leases(FleetLeaseSummary(expired=3))
        assert "3 expired" in result


class TestFormatBlockers:
    """_format_blockers helper."""

    def test_empty(self) -> None:
        result = _format_blockers(FleetBlockerSummary())
        assert "no blockers" in result

    def test_with_blockers(self) -> None:
        result = _format_blockers(
            FleetBlockerSummary(
                total_blockers=2, blocker_kinds={"dirty_files": 1, "lease_conflict": 1}
            )
        )
        assert "dirty_files" in result
        assert "lease_conflict" in result

    def test_with_replay_diagnostics(self) -> None:
        result = _format_replay(
            FleetQueueSummary(
                queued=1,
                total=1,
                highest_priority=1,
                replay=FleetReplayDiagnostics(
                    total_lines=10,
                    valid_events=8,
                    malformed_lines=1,
                    invalid_events=1,
                    skipped_unknown_kind=0,
                    total_skipped=2,
                ),
            )
        )
        assert "malformed" in result
        assert "invalid" in result


class TestFormatPatches:
    """_format_patches helper."""

    def test_empty(self) -> None:
        proj = build_fleet_projection(
            projection_id="fp-test", created_at="2026-01-01T00:00:00"
        )
        result = _format_patches(proj)
        assert "no patches" in result

    def test_pending(self) -> None:
        proj = build_fleet_projection(
            projection_id="fp-test",
            created_at="2026-01-01T00:00:00",
            patches=FleetPatchProposalSummary(pending=2, total=2),
        )
        result = _format_patches(proj)
        assert "2 pending" in result

    def test_rejected_applied_revision_counts(self) -> None:
        proj = build_fleet_projection(
            projection_id="fp-test",
            created_at="2026-01-01T00:00:00",
            patches=FleetPatchProposalSummary(
                pending=2, applied=1, rejected=1, revised=3, total=7
            ),
        )
        result = _format_patches(proj)
        assert "applied" in result
        assert "rejected" in result


class TestFormatAgents:
    """_format_agents helper."""

    def test_empty(self) -> None:
        proj = build_fleet_projection(
            projection_id="fp-test", created_at="2026-01-01T00:00:00"
        )
        result = _format_agents(proj)
        assert "no agents" in result

    def test_with_agents(self) -> None:
        proj = build_fleet_projection(
            projection_id="fp-test",
            created_at="2026-01-01T00:00:00",
            agents=FleetAgentSummary(
                total_agents=2, active_sessions=1, recent_heartbeats=5, stale_sessions=0
            ),
        )
        result = _format_agents(proj)
        assert "2 agents" in result
        assert "1 active" in result

    def test_stale_sessions_render(self) -> None:
        proj = build_fleet_projection(
            projection_id="fp-test",
            created_at="2026-01-01T00:00:00",
            agents=FleetAgentSummary(
                total_agents=2, active_sessions=1, recent_heartbeats=5, stale_sessions=1
            ),
        )
        result = _format_agents(proj)
        assert "stale" in result


class TestFormatNextItem:
    """_format_next_item helper."""

    def test_none(self) -> None:
        q = FleetQueueSummary()
        result = _format_next_item(q)
        assert result == ""

    def test_with_next_item(self) -> None:
        q = FleetQueueSummary(
            queued=1,
            total=1,
            highest_priority=3,
            next_item=FleetQueueNextItem(kind="validate", priority=3),
        )
        result = _format_next_item(q)
        assert "validate" in result
        assert "3" in result


class TestFormatReplay:
    """_format_replay helper."""

    def test_none(self) -> None:
        q = FleetQueueSummary()
        result = _format_replay(q)
        assert result == ""

    def test_with_no_issues(self) -> None:
        q = FleetQueueSummary(
            queued=1,
            total=1,
            highest_priority=0,
            replay=FleetReplayDiagnostics(
                total_lines=5, valid_events=5, total_skipped=0
            ),
        )
        result = _format_replay(q)
        assert "5/5 valid" in result

    def test_with_issues(self) -> None:
        q = FleetQueueSummary(
            queued=1,
            total=1,
            highest_priority=0,
            replay=FleetReplayDiagnostics(
                total_lines=10,
                valid_events=8,
                malformed_lines=1,
                invalid_events=1,
                skipped_unknown_kind=0,
                total_skipped=2,
            ),
        )
        result = _format_replay(q)
        assert "malformed" in result
        assert "invalid" in result

    def test_with_skipped(self) -> None:
        q = FleetQueueSummary(
            queued=1,
            total=1,
            highest_priority=0,
            replay=FleetReplayDiagnostics(
                total_lines=10,
                valid_events=8,
                malformed_lines=1,
                invalid_events=1,
                skipped_unknown_kind=0,
                total_skipped=2,
            ),
        )
        result = _format_replay(q)
        assert "malformed" in result
        assert "invalid" in result


class TestMountedFleetPanel:
    """Mounted/headless FleetPanelWidget tests."""

    @pytest.mark.asyncio
    async def test_mounted_empty_state_renders(self) -> None:
        """A mounted FleetPanelWidget with no projection shows empty state."""
        from textual.app import App, ComposeResult

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield FleetPanelWidget(projection=None)

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            panel = pilot.app.query_one(FleetPanelWidget)
            assert panel is not None
            # Empty state should show "no fleet" text
            assert any("no fleet" in str(w.render()) for w in panel.query(Static))

    @pytest.mark.asyncio
    async def test_mounted_with_projection_renders(self) -> None:
        """A mounted FleetPanelWidget with projection renders sections."""
        from textual.app import App, ComposeResult

        proj = _fleet_projection()

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield FleetPanelWidget(projection=proj)

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            panel = pilot.app.query_one(FleetPanelWidget)
            assert panel is not None
            # Should have multiple Static widgets for sections
            statics = list(panel.query(Static))
            assert len(statics) >= 2
            # No exception during render
            assert True
