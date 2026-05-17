"""Tests for Phase 1 blocker fixes: lease manager lock safety and task claim event emission."""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path
import threading

from rig_relay.coordination.models import reset_path_salt_for_testing
from rig_relay.coordination.store import CoordinationStore


def _make_store(tmp_path: Path) -> CoordinationStore:
    return CoordinationStore(tmp_path / ".build" / "rig-relay" / "coordination")


def test_task_claim_refusal_emits_event(tmp_path: Path) -> None:
    """P0/concurrency/real-artifact — denied task claim emits coord.task.claim_refused event."""
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    task_id = "blocked-task"

    # First session claims the task
    result1 = store.claim_task(
        session_id="session-a", task_id=task_id, claim_kind="write", ttl_seconds=120
    )
    assert result1.allowed

    # Second session tries to claim — should be denied
    result2 = store.claim_task(
        session_id="session-b", task_id=task_id, claim_kind="write", ttl_seconds=120
    )
    assert not result2.allowed
    assert result2.conflict is not None

    # Verify the refusal event is in events.jsonl
    events_path = store.root / "events.jsonl"
    events_text = events_path.read_text("utf-8")
    events = [json.loads(line) for line in events_text.splitlines() if line.strip()]

    refusal_events = [
        e for e in events if e["event_name"] == "coord.task.claim_refused"
    ]
    assert len(refusal_events) >= 1, (
        f"Expected at least 1 coord.task.claim_refused event, "
        f"found {len(refusal_events)}. Event names: {[e['event_name'] for e in events]}"
    )
    refusal = refusal_events[0]
    assert refusal["payload"]["task_id"] == task_id
    assert refusal["payload"]["conflict_kind"] == "task_already_claimed"


def test_task_claim_refusal_event_has_unique_sequence(tmp_path: Path) -> None:
    """P0/concurrency/real-artifact — refusal event sequences are unique."""
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    task_id = "seq-test-task"

    store.claim_task(
        session_id="session-a", task_id=task_id, claim_kind="write", ttl_seconds=120
    )
    store.claim_task(
        session_id="session-b", task_id=task_id, claim_kind="write", ttl_seconds=120
    )

    events_path = store.root / "events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text("utf-8").splitlines()
        if line.strip()
    ]
    sequences = [e["sequence"] for e in events]
    assert len(sequences) == len(set(sequences)), (
        f"Duplicate sequences found: {sequences}"
    )


from rig_relay.coordination.lease_manager import PathLeaseManager


def test_lease_manager_release_uses_store_lock(tmp_path: Path) -> None:
    """P0/concurrency/real-artifact — lease manager release is store-backed and lock-safe."""
    reset_path_salt_for_testing()
    mgr = PathLeaseManager(tmp_path / ".build" / "rig-relay" / "coordination")
    path = "src/manager_lock_test.py"

    # Acquire a lease
    claim_result = mgr.claim_paths(
        session_id="sess-a",
        task_id="task-a",
        mode="exclusive_write",
        paths=[path],
        ttl_seconds=120,
    )
    assert claim_result.status == "granted", (
        f"Expected granted, got {claim_result.status}"
    )

    # Release via manager
    release_result = mgr.release_paths(
        session_id="sess-a", task_id="task-a", paths=[path]
    )
    assert release_result.status == "granted", (
        f"Expected granted, got {release_result.status}: {release_result.refusal_reason}"
    )

    # Verify the lease file on disk shows released status
    lease_dir = mgr._store.root / "leases" / "paths"
    lease_files = list(lease_dir.glob("*.json"))
    if lease_files:
        for lf in lease_files:
            data = json.loads(lf.read_text("utf-8"))
            if data.get("session_id") == "sess-a":
                assert data.get("status") in ("released", "stale"), (
                    f"Lease should be released, got status={data.get('status')}"
                )

    # Verify events.jsonl has a coord.path.released event
    events_path = mgr._store.root / "events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text("utf-8").splitlines()
        if line.strip()
    ]
    release_events = [e for e in events if e["event_name"] == "coord.path.released"]
    assert len(release_events) >= 1, (
        f"Expected coord.path.released event, found {len(release_events)}"
    )


def test_concurrent_manager_release_and_store_reserve_no_corruption(
    tmp_path: Path,
) -> None:
    """P1/concurrency/real-artifact — concurrent release via manager + reserve via store."""
    reset_path_salt_for_testing()
    path = "src/concurrent_mgr_test.py"
    coord_root = tmp_path / ".build" / "rig-relay" / "coordination"

    # Pre-create a lease
    store_setup = CoordinationStore(coord_root)
    result = store_setup.reserve_paths(
        session_id="owner",
        task_id="owner-task",
        mode="write",
        paths=[path],
        ttl_seconds=120,
    )
    assert result.allowed

    results: list[str] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def do_release() -> None:
        mgr = PathLeaseManager(coord_root)
        barrier.wait()
        res = mgr.release_paths(session_id="owner", task_id="owner-task", paths=[path])
        with results_lock:
            results.append(f"release: {res.status}")

    def do_reserve() -> None:
        store = CoordinationStore(coord_root)
        barrier.wait()
        res = store.reserve_paths(
            session_id="claimer",
            task_id="claimer-task",
            mode="write",
            paths=[path],
            ttl_seconds=120,
        )
        with results_lock:
            results.append(f"reserve: {res.allowed}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        ex.submit(do_release)
        ex.submit(do_reserve)

    # Verify final state: no corrupted lease files, events.jsonl is valid JSONL
    store_final = CoordinationStore(coord_root)
    events_path = store_final.root / "events.jsonl"
    for line in events_path.read_text("utf-8").splitlines():
        if line.strip():
            json.loads(line)  # Must parse as valid JSON

    proj = store_final.read_state_projection()
    active_leases = list(proj.active_path_reservations.values())
    assert len(active_leases) in (0, 1), (
        f"Expected 0 or 1 active leases, got {len(active_leases)}"
    )
