"""Tests for QueuePanelWidget — read-only queue coordination widget."""

from __future__ import annotations

from pathlib import Path

import pytest
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
        assert "sha256:receipt" in text
        assert "sha256:result" in text
