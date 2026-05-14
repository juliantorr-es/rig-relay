"""Tests for FleetPanelWidget — read-only fleet coordination TUI widget."""

from __future__ import annotations

from textual.widgets import Static

from rig_relay.coordination.fleet_projection import (
    FleetBlockerSummary,
    FleetLeaseSummary,
    FleetQueueSummary,
    build_fleet_projection,
)
from vibe.cli.textual_ui.rig_console.widgets.fleet_panel import FleetPanelWidget


class TestFleetPanelWidget:
    """FleetPanelWidget rendering tests."""

    def test_build_widgets_empty_state(self) -> None:
        """_build_widgets with None projection shows 'no fleet data'."""
        widget = FleetPanelWidget(projection=None)
        widgets = widget._build_widgets()
        text = _extract_texts(widgets)
        assert "Fleet Panel" in text
        assert "no fleet data" in text

    def test_build_widgets_all_zero(self) -> None:
        """_build_widgets with empty projection shows dim 'no X' labels."""
        proj = build_fleet_projection(
            projection_id="fp-empty",
            created_at="2026-01-01T00:00:00",
        )
        widget = FleetPanelWidget(projection=proj)
        widgets = widget._build_widgets()
        text = _extract_texts(widgets)
        assert "Fleet Panel" in text
        assert "queue empty" in text
        assert "no leases" in text
        assert "no blockers" in text
        assert "no patches" in text
        assert "no agents" in text

    def test_build_widgets_with_data(self) -> None:
        """_build_widgets with populated projection shows colored counts."""
        proj = build_fleet_projection(
            projection_id="fp-active",
            created_at="2026-01-01T00:00:00",
            queue=FleetQueueSummary(
                queued=2, running=1, completed=5, total=8, highest_priority=3
            ),
            leases=FleetLeaseSummary(
                total_active=3,
                exclusive_write=2,
                shared_read=1,
                path_count=7,
            ),
            blockers=FleetBlockerSummary(
                total_blockers=1,
                blocker_kinds={"dirty_files": 2},
                oldest_blocked_at="2026-01-01T09:00:00",
            ),
        )
        widget = FleetPanelWidget(projection=proj)
        widgets = widget._build_widgets()
        text = _extract_texts(widgets)
        assert "Queue:" in text
        assert "2 queued" in text
        assert "1 running" in text
        assert "Leases:" in text
        assert "3 active" in text
        assert "2 write" in text
        assert "Blockers:" in text
        assert "dirty_files" in text
        assert "no patches" in text
        assert "no agents" in text

    def test_update_projection_replaces(self) -> None:
        """update_projection replaces empty state with populated state."""
        widget = FleetPanelWidget(projection=None)
        empty_text = _extract_texts(widget._build_widgets())
        assert "no fleet data" in empty_text

        proj = build_fleet_projection(
            projection_id="fp-updated",
            created_at="2026-01-01T00:00:00",
            queue=FleetQueueSummary(queued=1, total=1, highest_priority=1),
        )
        widget.update_projection(proj)
        updated_text = _extract_texts(widget._build_widgets())
        assert "Fleet Panel" in updated_text
        assert "1 queued" in updated_text
        assert "no fleet data" not in updated_text

    def test_update_projection_to_none(self) -> None:
        """update_projection with None shows empty state."""
        proj = build_fleet_projection(
            projection_id="fp-active",
            created_at="2026-01-01T00:00:00",
            queue=FleetQueueSummary(queued=1, total=1, highest_priority=1),
        )
        widget = FleetPanelWidget(projection=proj)
        populated_text = _extract_texts(widget._build_widgets())
        assert "1 queued" in populated_text

        widget.update_projection(None)
        none_text = _extract_texts(widget._build_widgets())
        assert "no fleet data" in none_text


# ── Helper ─────────────────────────────────────────────────────────────


def _extract_texts(widgets: list) -> str:
    """Extract text content from a flat list of widgets.

    Handles both Static widgets and Horizontal containers.
    """
    parts: list[str] = []
    for w in widgets:
        if isinstance(w, Static):
            # Different Textual versions store renderable differently
            renderable = getattr(w, "renderable", None) or getattr(w, "_renderable", str(w))
            parts.append(str(renderable))
        elif hasattr(w, "__iter__"):
            for child in w:
                if isinstance(child, Static):
                    renderable = getattr(child, "renderable", None) or getattr(child, "_renderable", str(child))
                    parts.append(str(renderable))
    return "\n".join(parts)
