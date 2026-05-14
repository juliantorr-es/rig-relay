"""Tests for the inspector drawer widget."""

from __future__ import annotations

from vibe.cli.textual_ui.rig_console.projections import (
    InspectorItemProjection,
    InspectorProjection,
)
from vibe.cli.textual_ui.rig_console.widgets.inspector_drawer import (
    InspectorDrawerWidget,
)


def _projection(
    *,
    visible: bool = True,
    items: list[InspectorItemProjection] | None = None,
    selected_index: int = 0,
) -> InspectorProjection:
    return InspectorProjection(
        visible=visible, selected_index=selected_index, items=items or []
    )


class TestInspectorDrawerWidget:
    def test_empty_state_renders(self) -> None:
        widget = InspectorDrawerWidget(_projection())
        assert "No item selected" in widget._build_detail_text()

    def test_hidden_state_renders_closed(self) -> None:
        widget = InspectorDrawerWidget(_projection(visible=False))
        assert "Inspector closed" in widget._build_state_text()

    def test_selected_item_renders_metadata(self) -> None:
        item = InspectorItemProjection(
            item_id="aev-1",
            source_kind="runtime_audit",
            title="Audit validate",
            status="completed",
            tool_name="validate",
            created_at="2026-05-14T15:00:00",
            duration_ms=12.0,
            changed_paths=["src/main.py"],
            receipt_sha256="sha256:receipt",
            runtime_result_sha256="sha256:result",
            error_kind="blocked",
            refusal_reason="dirty_files",
            summary="completed validate",
        )
        widget = InspectorDrawerWidget(_projection(items=[item]))
        text = widget._build_detail_text()
        assert "Audit validate" in text
        assert "sha256:receipt" in text
        assert "sha256:result" in text
        assert "blocked" in text

    def test_no_forbidden_raw_fields(self) -> None:
        item = InspectorItemProjection(
            item_id="receipt-1", source_kind="receipt", title="Receipt validate"
        )
        widget = InspectorDrawerWidget(_projection(items=[item]))
        text = widget._build_detail_text().lower()
        forbidden = (
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
        assert not any(name in text for name in forbidden)
