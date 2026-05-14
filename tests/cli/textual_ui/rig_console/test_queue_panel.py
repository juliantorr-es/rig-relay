"""Tests for QueuePanelWidget — read-only queue coordination widget."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from vibe.cli.textual_ui.rig_console.projections import (
    QueueItemProjection,
    QueueProjection,
)
from vibe.cli.textual_ui.rig_console.providers import RuntimeDashboardProjectionProvider
from vibe.cli.textual_ui.rig_console.widgets.queue_panel import QueuePanelWidget

_FORBIDDEN = (
    "stdout",
    "stderr",
    "content",
    "file_contents",
    "chunk_text",
    "old_text",
    "new_text",
    "diff",
    "patch",
    "prompt",
    "secret",
    "argv",
    "snippet",
)


def _queue_projection() -> QueueProjection:
    return QueueProjection(
        visible=True,
        selected_index=1,
        queued_count=2,
        running_count=1,
        blocked_count=1,
        completed_count=1,
        failed_count=1,
        cancelled_count=1,
        items=[
            QueueItemProjection(
                queue_item_id="q-1",
                kind="message",
                status="queued",
                title="Queue message",
            ),
            QueueItemProjection(
                queue_item_id="q-2",
                kind="validate",
                status="running",
                title="Validate quick",
                payload_ref="local://queue/q-2",
                receipt_sha256="sha256:receipt",
                runtime_result_sha256="sha256:result",
            ),
            QueueItemProjection(
                queue_item_id="q-3",
                kind="handoff_note",
                status="blocked",
                title="Blocked note",
                blocked_reason="lease conflict",
            ),
            QueueItemProjection(
                queue_item_id="q-4",
                kind="message",
                status="completed",
                title="Completed task",
            ),
            QueueItemProjection(
                queue_item_id="q-5",
                kind="message",
                status="failed",
                title="Failed task",
            ),
            QueueItemProjection(
                queue_item_id="q-6",
                kind="message",
                status="cancelled",
                title="Cancelled task",
            ),
        ],
    )


class TestQueuePanelWidget:
    def test_empty_state_renders_cleanly(self) -> None:
        widget = QueuePanelWidget(None)
        lines = widget._render_lines()
        assert lines[0] == "Queue Panel"
        assert "no queue data" in lines[1].lower()

    def test_projection_renders_status_buckets(self) -> None:
        widget = QueuePanelWidget(_queue_projection())
        text = "\n".join(widget._render_lines())
        assert "queue panel" in text.lower()
        assert "queued" in text.lower()
        assert "running" in text.lower()
        assert "blocked" in text.lower()
        assert "recent" in text.lower()

    def test_no_forbidden_raw_fields(self) -> None:
        widget = QueuePanelWidget(_queue_projection())
        text = "\n".join(widget._render_lines()).lower()
        assert not any(field in text for field in _FORBIDDEN)

    @pytest.mark.asyncio
    async def test_missing_queue_roots_do_not_crash(self, tmp_path: Path) -> None:
        provider = RuntimeDashboardProjectionProvider(
            session_id="session-queue",
            session_path=tmp_path / "missing",
            workspace_root=tmp_path,
        )
        projection = await provider.dashboard_projection()
        widget = QueuePanelWidget(projection.queue)
        assert len(widget._render_lines()) >= 2

    def test_selected_item_has_safe_refs(self) -> None:
        projection = _queue_projection()
        widget = QueuePanelWidget(projection)
        text = "\n".join(widget._render_lines())
        assert "local://queue/q-2" in text
        assert "sha256:receipt" in text
        assert "sha256:result" in text


class _QueuePanelTestApp(App[None]):
    """Minimal Textual app for headless Pilot testing of QueuePanelWidget."""

    def __init__(self, projection: QueueProjection | None = None) -> None:
        super().__init__()
        self._projection = projection

    def compose(self) -> ComposeResult:
        yield QueuePanelWidget(self._projection)


class TestQueuePanelPilot:
    """Mounted Pilot tests for QueuePanelWidget using App.run_test."""

    @pytest.mark.asyncio
    async def test_queue_panel_mounts_empty(self) -> None:
        """QueuePanel mounts with no projection (empty state)."""
        app = _QueuePanelTestApp()
        async with app.run_test(size=(80, 12)) as pilot:
            panel = pilot.app.query_one(QueuePanelWidget)
            assert panel._projection is None

    @pytest.mark.asyncio
    async def test_queue_panel_mounts_with_projection(self) -> None:
        """QueuePanel mounts with a populated projection."""
        projection = _queue_projection()
        app = _QueuePanelTestApp(projection)
        async with app.run_test(size=(80, 12)) as pilot:
            panel = pilot.app.query_one(QueuePanelWidget)
            assert panel._projection is not None
            assert panel._projection.queued_count == 2

    @pytest.mark.asyncio
    async def test_queue_panel_shows_counts(self) -> None:
        """QueuePanel renders queued/running/blocked/done counts."""
        projection = _queue_projection()
        app = _QueuePanelTestApp(projection)
        async with app.run_test(size=(80, 12)) as pilot:
            panel = pilot.app.query_one(QueuePanelWidget)
            text = "\n".join(panel._render_lines()).lower()
            assert "2 queued" in text
            assert "1 running" in text
            assert "1 blocked" in text
            assert "1 done" in text

    @pytest.mark.asyncio
    async def test_queue_panel_update_projection(self) -> None:
        """QueuePanel updates projection and re-renders."""
        empty = QueueProjection(visible=True, empty_state="empty")
        populated = _queue_projection()
        app = _QueuePanelTestApp(empty)
        async with app.run_test(size=(80, 12)) as pilot:
            panel = pilot.app.query_one(QueuePanelWidget)

            # Start empty
            text = "\n".join(panel._render_lines()).lower()
            assert "empty" in text

            # Update with populated
            panel.update_projection(populated)
            text = "\n".join(panel._render_lines()).lower()
            assert "2 queued" in text
