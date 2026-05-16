from __future__ import annotations
import pytest

pytestmark = [pytest.mark.integration]


from rig_relay.desktop.events import (
    DesktopEventRecord,
    InMemoryDesktopEventSink,
    NoOpDesktopEventSink,
)


def test_noop_sink_does_not_crash():
    sink = NoOpDesktopEventSink()
    event = DesktopEventRecord(event_name="rig.desktop.ralph.scan.completed")
    sink.emit(event)


def test_inmemory_sink_stores_events():
    sink = InMemoryDesktopEventSink()
    sink.emit(DesktopEventRecord(event_name="rig.desktop.ralph.scan.requested"))
    sink.emit(DesktopEventRecord(event_name="rig.desktop.ralph.scan.completed"))

    assert len(sink.events) == 2
    assert sink.events[0].event_name == "rig.desktop.ralph.scan.requested"


def test_event_sha256_computed():
    event = DesktopEventRecord(
        event_id="fixed-id",
        event_name="rig.desktop.ralph.scan.completed",
        ok=True,
        status="completed",
        execution_enabled=False,
    )

    sha = event.compute_sha256()
    assert len(sha) == 64


def test_event_sha256_stable():
    e1 = DesktopEventRecord(
        event_id="fixed-id",
        event_name="rig.desktop.ralph.scan.completed",
        ok=True,
        status="completed",
        execution_enabled=False,
    )
    e2 = DesktopEventRecord(
        event_id="fixed-id",
        event_name="rig.desktop.ralph.scan.completed",
        ok=True,
        status="completed",
        execution_enabled=False,
    )

    assert e1.compute_sha256() == e2.compute_sha256()


def test_execution_always_disabled():
    """Desktop events: execution_enabled defaults to False."""
    event = DesktopEventRecord(
        event_name="rig.desktop.ralph.approval.accepted",
        ok=True,
        status="completed",
    )
    assert event.execution_enabled is False


def test_event_carries_optional_run_info():
    event = DesktopEventRecord(
        event_name="rig.desktop.ralph.approval.accepted",
        run_id="run-1",
        scan_id="scan-1",
        panel_sha256="a" * 64,
        mission_candidate_sha256="b" * 64,
        ok=True,
        status="completed",
        execution_enabled=False,
    )

    assert event.run_id == "run-1"
    assert event.panel_sha256 == "a" * 64


def test_refusal_event_carries_error_code():
    event = DesktopEventRecord(
        event_name="rig.desktop.ralph.approval.refused",
        ok=False,
        status="refused",
        error_code="stale_panel_hash",
        execution_enabled=False,
    )

    assert event.error_code == "stale_panel_hash"
    assert event.ok is False


def test_clear_sink_empties_events():
    sink = InMemoryDesktopEventSink()
    sink.emit(DesktopEventRecord(event_name="rig.desktop.ralph.scan.completed"))
    assert len(sink.events) == 1

    sink.clear()
    assert len(sink.events) == 0
