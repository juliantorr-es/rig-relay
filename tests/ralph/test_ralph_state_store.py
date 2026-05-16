from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]


from rig_relay.ralph.state_store import (
    FilesystemRalphRunStateStore,
    InMemoryRalphRunStateStore,
    RalphRunStateRecord,
    RalphRunStateStore,
)


def test_inmemory_save_load_roundtrip():
    store = InMemoryRalphRunStateStore()
    record = RalphRunStateRecord(
        run_id="run-1",
        scan_id="scan-1",
        status="ready",
        phase="scan",
        approval_state="pending",
        panel_sha256="a" * 64,
        mission_candidate_sha256="b" * 64,
        decision_required=True,
        execution_enabled=False,
    )

    store.save_run_state(record)
    loaded = store.load_run_state("run-1")

    assert loaded is not None
    assert loaded.run_id == "run-1"
    assert loaded.panel_sha256 == "a" * 64
    assert loaded.execution_enabled is False


def test_current_run_pointer():
    store = InMemoryRalphRunStateStore()

    r1 = RalphRunStateRecord(run_id="run-1", scan_id="scan-1", status="ready")
    r2 = RalphRunStateRecord(run_id="run-2", scan_id="scan-2", status="ready")

    store.save_run_state(r1)
    store.save_run_state(r2)
    store.mark_current_run("run-1")

    current = store.load_current_run_state()
    assert current is not None
    assert current.run_id == "run-1"


def test_rescan_invalidates_old_current():
    store = InMemoryRalphRunStateStore()

    r1 = RalphRunStateRecord(
        run_id="run-1", scan_id="scan-1", status="ready", approval_state="pending"
    )
    store.save_run_state(r1)
    store.mark_current_run("run-1")

    r2 = RalphRunStateRecord(
        run_id="run-2", scan_id="scan-2", status="ready", approval_state="pending"
    )
    store.save_run_state(r2)
    store.mark_current_run("run-2")

    current = store.load_current_run_state()
    assert current is not None
    assert current.run_id == "run-2"

    old = store.load_run_state("run-1")
    assert old is not None
    assert old.run_id == "run-1"


def test_expire_run_state():
    store = InMemoryRalphRunStateStore()
    record = RalphRunStateRecord(
        run_id="run-1", scan_id="scan-1", status="ready", approval_state="pending"
    )
    store.save_run_state(record)

    store.expire_run_state("run-1", "test expiration")

    loaded = store.load_run_state("run-1")
    assert loaded.approval_state == "expired"
    assert loaded.status == "expired"


def test_list_run_states():
    store = InMemoryRalphRunStateStore()

    for i in range(5):
        store.save_run_state(
            RalphRunStateRecord(run_id=f"run-{i}", scan_id=f"scan-{i}", status="ready")
        )

    listed = store.list_run_states(limit=3)
    assert len(listed) == 3


def test_clear_current_run():
    store = InMemoryRalphRunStateStore()
    record = RalphRunStateRecord(run_id="run-1", scan_id="scan-1", status="ready")
    store.save_run_state(record)
    store.mark_current_run("run-1")

    store.clear_current_run()
    assert store.load_current_run_state() is None


def test_filesystem_save_load_roundtrip(tmp_path):
    root = tmp_path / ".rig" / "ralph"
    store = FilesystemRalphRunStateStore(root=root)

    record = RalphRunStateRecord(
        run_id="fs-run-1",
        scan_id="scan-1",
        status="ready",
        panel_sha256="c" * 64,
        mission_candidate_sha256="d" * 64,
        execution_enabled=False,
    )
    store.save_run_state(record)

    loaded = store.load_run_state("fs-run-1")
    assert loaded is not None
    assert loaded.run_id == "fs-run-1"
    assert loaded.panel_sha256 == "c" * 64


def test_filesystem_current_run_pointer(tmp_path):
    root = tmp_path / ".rig" / "ralph"
    store = FilesystemRalphRunStateStore(root=root)

    r1 = RalphRunStateRecord(run_id="fs-cur-1", scan_id="scan-1", status="ready")
    store.save_run_state(r1)
    store.mark_current_run("fs-cur-1")

    current = store.load_current_run_state()
    assert current is not None
    assert current.run_id == "fs-cur-1"


def test_load_nonexistent_returns_none():
    store = InMemoryRalphRunStateStore()
    assert store.load_run_state("nonexistent") is None
    assert store.load_current_run_state() is None


def test_store_protocol():
    store = InMemoryRalphRunStateStore()
    assert isinstance(store, RalphRunStateStore)


def test_execution_always_disabled():
    """State store records: execution_enabled defaults to False."""
    store = InMemoryRalphRunStateStore()
    record = RalphRunStateRecord(run_id="run-1", scan_id="scan-1", status="ready")
    assert record.execution_enabled is False

    store.save_run_state(record)
    loaded = store.load_run_state("run-1")
    assert loaded.execution_enabled is False
