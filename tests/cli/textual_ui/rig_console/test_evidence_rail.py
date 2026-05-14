"""Tests for EvidenceRail projection models, adapter, and widget."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from rig_relay.evidence.receipt_index import ToolReceiptIndexRecord
from vibe.cli.textual_ui.rig_console.projections import (
    EvidenceRailItemProjection,
    EvidenceRailProjection,
    evidence_rail_from_receipt_index,
)
from vibe.cli.textual_ui.rig_console.widgets.evidence_rail import EvidenceRailWidget


class TestEvidenceRailItemProjection:
    """EvidenceRailItemProjection model tests."""

    def test_rejects_forbidden_raw_fields(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceRailItemProjection.model_validate({
                "tool_name": "bash",
                "status": "success",
                "stdout": "should_not_exist",
            })

    def test_minimal_construction(self) -> None:
        item = EvidenceRailItemProjection(tool_name="bash", status="success")
        assert item.tool_name == "bash"
        assert item.status == "success"
        assert item.event_id is None
        assert item.captured_at is None
        assert item.error_kind is None
        assert item.path is None
        assert item.changed is None
        assert item.duration_ms is None

    def test_full_construction(self) -> None:
        item = EvidenceRailItemProjection(
            event_id="evt-001",
            captured_at="2026-05-14T15:30:00",
            tool_name="search_replace",
            status="success",
            error_kind=None,
            path="src/file.py",
            changed=True,
            duration_ms=450.0,
        )
        assert item.tool_name == "search_replace"
        assert item.status == "success"
        assert item.path == "src/file.py"
        assert item.changed is True
        assert item.duration_ms == 450.0

    def test_no_raw_field_names(self) -> None:
        """Ensure no field names match forbidden patterns."""
        forbidden = (
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
            "file_contents",
            "chunk_text",
        )
        for field_name in EvidenceRailItemProjection.model_fields:
            lower = field_name.lower()
            for prefix in forbidden:
                assert not lower.startswith(prefix), (
                    f"Field '{field_name}' starts with forbidden prefix '{prefix}'"
                )


class TestEvidenceRailProjection:
    """EvidenceRailProjection model tests."""

    def test_defaults(self) -> None:
        proj = EvidenceRailProjection(session_id="test")
        assert proj.session_id == "test"
        assert proj.receipt_count == 0
        assert proj.mutation_count == 0
        assert proj.refusal_count == 0
        assert proj.timeout_count == 0
        assert proj.items == []

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceRailProjection.model_validate({
                "session_id": "test",
                "raw_output": "should_not_exist",
            })

    def test_with_items(self) -> None:
        items = [
            EvidenceRailItemProjection(tool_name="bash", status="success"),
            EvidenceRailItemProjection(tool_name="validate", status="passed"),
        ]
        proj = EvidenceRailProjection(
            session_id="test", receipt_count=2, mutation_count=1, items=items
        )
        assert len(proj.items) == 2
        assert proj.receipt_count == 2
        assert proj.mutation_count == 1


class TestEvidenceRailAdapter:
    """evidence_rail_from_receipt_index adapter tests."""

    def _make_record(
        self,
        tool_name: str = "bash",
        status: str = "success",
        *,
        changed: bool | None = None,
        error_kind: str | None = None,
        captured_at: str | None = None,
        path: str | None = None,
        duration_ms: float | None = None,
        event_id: str | None = None,
    ) -> ToolReceiptIndexRecord:
        return ToolReceiptIndexRecord(
            session_id="test-session",
            tool_name=tool_name,
            status=status,
            changed=changed,
            error_kind=error_kind,
            captured_at=captured_at,
            path=path,
            duration_ms=duration_ms,
            event_id=event_id,
        )

    def test_builds_from_empty_records(self) -> None:
        proj = evidence_rail_from_receipt_index([], session_id="empty-session")
        assert proj.session_id == "empty-session"
        assert proj.receipt_count == 0
        assert proj.mutation_count == 0
        assert proj.refusal_count == 0
        assert proj.timeout_count == 0
        assert proj.items == []

    def test_builds_from_single_record(self) -> None:
        records = [self._make_record(tool_name="bash", status="success")]
        proj = evidence_rail_from_receipt_index(records, session_id="s1")
        assert proj.receipt_count == 1
        assert proj.mutation_count == 0
        assert len(proj.items) == 1
        assert proj.items[0].tool_name == "bash"
        assert proj.items[0].status == "success"

    def test_counts_mutations(self) -> None:
        records = [
            self._make_record(
                tool_name="search_replace", status="success", changed=True
            ),
            self._make_record(
                tool_name="search_replace", status="success", changed=True
            ),
            self._make_record(tool_name="bash", status="success"),
        ]
        proj = evidence_rail_from_receipt_index(records, session_id="s1")
        assert proj.mutation_count == 2
        assert proj.receipt_count == 3

    def test_counts_refusals(self) -> None:
        records = [
            self._make_record(tool_name="write_file", status="refused"),
            self._make_record(tool_name="bash", status="refused"),
            self._make_record(tool_name="validate", status="success"),
        ]
        proj = evidence_rail_from_receipt_index(records, session_id="s1")
        assert proj.refusal_count == 2
        assert proj.receipt_count == 3

    def test_counts_timeouts(self) -> None:
        records = [
            self._make_record(tool_name="bash", status="timed_out"),
            self._make_record(tool_name="bash", status="error", error_kind="timeout"),
        ]
        proj = evidence_rail_from_receipt_index(records, session_id="s1")
        assert proj.timeout_count == 2
        assert proj.receipt_count == 2

    def test_caps_items(self) -> None:
        records = [
            self._make_record(tool_name="bash", status=f"item-{i}") for i in range(25)
        ]
        proj = evidence_rail_from_receipt_index(records, session_id="s1", max_items=5)
        assert len(proj.items) == 5
        assert proj.receipt_count == 5

    def test_orders_by_captured_at_descending(self) -> None:
        records = [
            self._make_record(
                tool_name="bash", status="old", captured_at="2026-05-14T12:00:00"
            ),
            self._make_record(
                tool_name="validate", status="new", captured_at="2026-05-14T15:00:00"
            ),
            self._make_record(tool_name="bash", status="no_ts"),
        ]
        proj = evidence_rail_from_receipt_index(records, session_id="s1")
        assert proj.items[0].status == "new"
        assert proj.items[1].status == "old"
        # None timestamp last
        assert proj.items[2].status == "no_ts"

    def test_preserves_all_fields(self) -> None:
        records = [
            self._make_record(
                tool_name="search_replace",
                status="success",
                changed=True,
                path="src/file.py",
                duration_ms=500.0,
                event_id="evt-001",
                captured_at="2026-05-14T15:30:00",
                error_kind=None,
            )
        ]
        proj = evidence_rail_from_receipt_index(records, session_id="s1")
        item = proj.items[0]
        assert item.tool_name == "search_replace"
        assert item.status == "success"
        assert item.changed is True
        assert item.path == "src/file.py"
        assert item.duration_ms == 500.0
        assert item.event_id == "evt-001"
        assert item.captured_at == "2026-05-14T15:30:00"


class TestEvidenceRailWidget:
    """EvidenceRailWidget structural and content tests."""

    def test_empty_state_renders_cleanly(self) -> None:
        proj = EvidenceRailProjection(session_id="empty-session")
        widget = EvidenceRailWidget(proj)
        children = list(widget.compose())
        # header + counts + empty message = 3
        assert len(children) == 3

    def test_renders_counts(self) -> None:
        items = [EvidenceRailItemProjection(tool_name="bash", status="success")]
        proj = EvidenceRailProjection(
            session_id="s1",
            receipt_count=1,
            mutation_count=0,
            refusal_count=0,
            timeout_count=0,
            items=items,
        )
        widget = EvidenceRailWidget(proj)
        text = widget._build_counts_text(proj)
        assert "receipts: 1" in text
        # Zero-value counts should not appear
        assert "mutations:" not in text
        assert "refusals:" not in text
        assert "timeouts:" not in text

    def test_renders_positive_counts_only(self) -> None:
        items = [
            EvidenceRailItemProjection(tool_name="search_replace", status="success")
        ]
        proj = EvidenceRailProjection(
            session_id="s1",
            receipt_count=1,
            mutation_count=2,
            refusal_count=0,
            timeout_count=1,
            items=items,
        )
        widget = EvidenceRailWidget(proj)
        text = widget._build_counts_text(proj)
        assert "mutations: 2" in text
        assert "timeouts: 1" in text
        assert "refusals: 0" not in text

    def test_renders_item_status_and_tool(self) -> None:
        items = [EvidenceRailItemProjection(tool_name="bash", status="success")]
        proj = EvidenceRailProjection(session_id="s1", receipt_count=1, items=items)
        widget = EvidenceRailWidget(proj)
        text = widget._build_item_text(items[0])
        assert "bash" in text or "bash" in text
        assert "success" in text

    def test_renders_item_path_and_duration(self) -> None:
        items = [
            EvidenceRailItemProjection(
                tool_name="bash",
                status="success",
                path="src/script.sh",
                duration_ms=1200.0,
            )
        ]
        widget = EvidenceRailWidget(
            EvidenceRailProjection(session_id="s1", receipt_count=1, items=items)
        )
        text = widget._build_item_text(items[0])
        assert "src/script.sh" in text
        assert "1200ms" in text

    def test_no_forbidden_raw_field_names(self) -> None:
        """Widget should not reference forbidden raw fields."""
        proj = EvidenceRailProjection(session_id="s1")
        widget = EvidenceRailWidget(proj)
        assert not hasattr(widget, "stdout")
        assert not hasattr(widget, "stderr")
        assert not hasattr(widget, "output")
        assert not hasattr(widget, "content")
        assert not hasattr(widget, "diff")
        assert not hasattr(widget, "patch")
