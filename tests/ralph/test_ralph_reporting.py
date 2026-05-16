from __future__ import annotations

import pytest

from rig_relay.ralph.reporting import (
    RalphReport,
    RalphReportStore,
    build_demo_ralph_reports,
)


def test_report_from_completed_lane():
    report = RalphReport(
        report_kind="completed_lane",
        ralph_lane_id="lane-1",
        branch_name="ralph/test",
        commit_shas=["abc123"],
        review_bundle_sha256="sha256:bundle1",
        title="Fix completed",
        summary="Fixed the issue",
    )
    assert report.report_kind == "completed_lane"
    assert report.merge_enabled is False
    assert report.push_enabled is False


def test_report_from_blocked_lane():
    report = RalphReport(
        report_kind="blocked_lane",
        ralph_lane_id="lane-2",
        title="Blocked: missing evidence",
        summary="Cannot proceed without source evidence",
    )
    assert report.status == "created"


def test_store_save_and_load():
    store = RalphReportStore()
    report = RalphReport(report_id="r1", title="Test")
    store.save_report(report)
    loaded = store.load_report("r1")
    assert loaded is not None
    assert loaded.title == "Test"


def test_store_pending_reports():
    store = RalphReportStore()
    store.save_report(RalphReport(report_id="r1", status="created"))
    store.save_report(RalphReport(report_id="r2", status="delivered_to_orchestrator"))
    store.save_report(RalphReport(report_id="r3", status="reviewed"))

    pending = store.list_pending_reports()
    assert len(pending) == 2
    pending_ids = [r.report_id for r in pending]
    assert "r1" in pending_ids
    assert "r2" in pending_ids
    assert "r3" not in pending_ids


def test_mark_delivered():
    store = RalphReportStore()
    report = store.save_report(RalphReport(report_id="r1"))
    updated = store.mark_delivered("r1")
    assert updated.status == "delivered_to_orchestrator"
    assert updated.delivered_at is not None


def test_mark_reviewed():
    store = RalphReportStore()
    store.save_report(RalphReport(report_id="r1"))
    updated = store.mark_reviewed("r1")
    assert updated.status == "reviewed"


def test_accepted_for_adoption_does_not_merge():
    store = RalphReportStore()
    report = store.save_report(RalphReport(report_id="r1"))
    updated = store.mark_accepted_for_adoption("r1")
    assert updated.status == "accepted_for_adoption"
    assert updated.merge_enabled is False


@pytest.mark.smoke
def test_demo_reports_exist():
    reports = build_demo_ralph_reports()
    assert len(reports) >= 1
    for r in reports:
        assert r.merge_enabled is False
        assert r.push_enabled is False
