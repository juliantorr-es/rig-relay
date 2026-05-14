"""Tests for DashboardProjection — content-light dashboard model."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from rig_relay.runtime.runtime_audit_event import RuntimeAuditEvent
from rig_relay.runtime.runtime_supervisor_projection import RuntimeSupervisorProjection
from vibe.cli.textual_ui.rig_console.projections import (
    DashboardProjection,
    EvidenceRailProjection,
    InspectorProjection,
    SessionPaneProjection,
    build_inspector_projection,
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
        assert isinstance(proj.inspector, InspectorProjection)
        assert proj.inspector.items == []

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
            "prompt",
            "secret",
            "argv",
            "file_contents",
            "chunk_text",
            "old_text",
            "new_text",
        )
        for field_name in DashboardProjection.model_fields:
            lower = field_name.lower()
            for prefix in forbidden:
                assert not lower.startswith(prefix), (
                    f"Field '{field_name}' starts with forbidden prefix '{prefix}'"
                )

    def test_inspector_projection_is_content_light(self) -> None:
        session = SessionPaneProjection(
            session_id="s1", blocker_summary={"dirty_files": 2}
        )
        evidence = EvidenceRailProjection(session_id="s1", items=[], receipt_count=0)
        supervisor = RuntimeSupervisorProjection(
            schema_version="rig.relay.runtime_supervisor_projection.v1",
            projection_id="proj-1",
            created_at="2026-05-14T15:00:00",
            total_invocations=1,
            status_counts={"completed": 1},
            recent_invocations=[
                RuntimeAuditEvent(
                    schema_version="rig.relay.runtime_audit_event.v1",
                    audit_event_id="aev-1",
                    invocation_id="inv-1",
                    tool_name="validate",
                    status="completed",
                    receipt_sha256="sha256:receipt",
                    runtime_result_sha256="sha256:result",
                    changed_paths=["src/main.py"],
                    duration_ms=10.0,
                    created_at="2026-05-14T15:00:00",
                )
            ],
            changed_path_count=1,
            changed_path_hashes=["sha256:result"],
        )
        inspector = build_inspector_projection(session, evidence, None, supervisor)

        assert inspector.items[0].source_kind == "runtime_audit"
        assert inspector.items[0].receipt_sha256 == "sha256:receipt"
        assert inspector.items[0].runtime_result_sha256 == "sha256:result"
        assert inspector.items[1].source_kind == "lease_blocker"
        assert inspector.items[1].refusal_reason == "2 dirty_files"

    def test_inspector_projection_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            InspectorProjection.model_validate({
                "visible": True,
                "items": [],
                "stdout": "nope",
            })
