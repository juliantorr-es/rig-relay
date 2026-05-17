from __future__ import annotations

import concurrent.futures
import json
import threading
from pathlib import Path

import pytest

from rig_relay.coordination.models import (
    CoordinationSession,
    reset_path_salt_for_testing,
)
from rig_relay.coordination.store import CoordinationStore

pytestmark = pytest.mark.concurrency


def _make_store(root: Path) -> CoordinationStore:
    return CoordinationStore(root / ".build" / "rig-relay" / "coordination")


# ── Test 1: P1/concurrency/real-artifact ────────────────────────────────


def test_event_sequence_unique_under_concurrent_mutations(tmp_path: Path) -> None:
    """P1/concurrency/real-artifact — all coordination event sequences are unique"""
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    n_workers = 4
    n_ops = 5

    errors: list[str] = []
    errors_lock = threading.Lock()
    barrier = threading.Barrier(n_workers)

    def worker(worker_id: int) -> None:
        sid = f"session-{worker_id}"
        tid = f"task-{worker_id}"
        barrier.wait()
        try:
            for i in range(n_ops):
                store.reserve_paths(
                    session_id=sid,
                    task_id=tid,
                    mode="write",
                    paths=[f"src/worker-{worker_id}-op-{i}.py"],
                    ttl_seconds=120,
                )
        except Exception as exc:
            with errors_lock:
                errors.append(f"Worker {worker_id}: {exc}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = [ex.submit(worker, i) for i in range(n_workers)]
        concurrent.futures.wait(futures)

    assert not errors, f"Workers encountered errors: {errors}"

    events_path = store.root / "events.jsonl"
    assert events_path.is_file()

    sequences: list[int] = []
    parse_errors: list[str] = []
    for line in events_path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line.strip())
            seq = event.get("sequence")
            if seq is not None:
                sequences.append(seq)
        except json.JSONDecodeError as exc:
            parse_errors.append(f"Parse error: {exc}")

    assert not parse_errors, f"JSON parse errors: {parse_errors[:5]}"
    assert len(sequences) > 0, "No events found"
    assert len(sequences) == len(set(sequences)), (
        f"Sequence numbers must be unique. Total: {len(sequences)}, "
        f"Unique: {len(set(sequences))}. "
        f"Duplicates: {[s for s in sequences if sequences.count(s) > 1][:5]}"
    )


# ── Test 2: P2/concurrency/real-artifact ────────────────────────────────


def test_concurrent_heartbeat_same_session_no_corruption(tmp_path: Path) -> None:
    """P2/concurrency/real-artifact"""
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    session_id = "shared-session"

    store.register_session(CoordinationSession(session_id=session_id, status="running"))

    errors: list[str] = []
    errors_lock = threading.Lock()
    n_workers = 4
    barrier = threading.Barrier(n_workers)

    def send_heartbeats(worker_id: int) -> None:
        barrier.wait()
        try:
            for _ in range(5):
                store.heartbeat(
                    session_id=session_id,
                    status="running",
                    current_step=f"worker-{worker_id}",
                )
        except Exception as exc:
            with errors_lock:
                errors.append(f"Worker {worker_id}: {exc}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = [ex.submit(send_heartbeats, i) for i in range(n_workers)]
        concurrent.futures.wait(futures)

    assert not errors, f"Heartbeat workers encountered errors: {errors}"

    session_path = store.root / "sessions" / f"{session_id}.json"
    assert session_path.is_file()
    try:
        data = json.loads(session_path.read_text("utf-8"))
        assert data.get("status") == "running"
    except json.JSONDecodeError as exc:
        pytest.fail(f"Session file corrupted: {exc}")


# ── Test 3: P1/concurrency/real-artifact ────────────────────────────────


def test_mark_lease_stale_no_race_with_reserve(tmp_path: Path) -> None:
    """P1/concurrency/real-artifact"""
    reset_path_salt_for_testing()
    path = "src/protected.py"

    store_prep = _make_store(tmp_path)
    result = store_prep.reserve_paths(
        session_id="session-stale",
        task_id="task-stale",
        mode="write",
        paths=[path],
        ttl_seconds=120,
    )
    assert result.allowed

    results: list[str] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def mark_stale() -> None:
        store = _make_store(tmp_path)
        barrier.wait()
        try:
            store.mark_lease_stale(
                session_id="session-stale",
                task_id="task-stale",
                reason="test_stale_marking",
            )
            with results_lock:
                results.append("stale_done")
        except Exception as exc:
            with results_lock:
                results.append(f"stale_error: {exc}")

    def do_reserve() -> None:
        store = _make_store(tmp_path)
        barrier.wait()
        try:
            result = store.reserve_paths(
                session_id="session-new",
                task_id="task-new",
                mode="write",
                paths=[path],
                ttl_seconds=120,
            )
            with results_lock:
                results.append(f"reserve: {result.allowed}")
        except Exception as exc:
            with results_lock:
                results.append(f"reserve_error: {exc}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        ex.submit(mark_stale)
        ex.submit(do_reserve)

    store_final = _make_store(tmp_path)
    proj = store_final.read_state_projection()

    active_leases = list(proj.active_path_reservations.values())
    stale_count = sum(1 for r in results if "stale" in str(r))
    error_count = sum(1 for r in results if "error" in str(r))

    assert error_count == 0, f"Errors during concurrent ops: {results}"
    assert len(active_leases) in (0, 1), (
        f"Expected 0 or 1 active leases, got {len(active_leases)}"
    )


# ── Test 4: P1/concurrency/contract ─────────────────────────────────────


def test_read_state_projection_does_not_append_events(tmp_path: Path) -> None:
    """P1/concurrency/contract — read must not mutate canonical state"""
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)

    store.register_session(CoordinationSession(session_id="test-session", status="running"))

    events_path = store.root / "events.jsonl"
    count_before = 0
    if events_path.is_file():
        count_before = len([l for l in events_path.read_text("utf-8").splitlines() if l.strip()])

    for _ in range(3):
        proj = store.read_state_projection()
        assert proj is not None
        assert proj.projection_sha256 is not None

    count_after = 0
    if events_path.is_file():
        count_after = len([l for l in events_path.read_text("utf-8").splitlines() if l.strip()])

    assert count_after == count_before, (
        f"read_state_projection must not append events. "
        f"Before: {count_before}, After: {count_after}"
    )


# ── Test 5: P0/concurrency/real-artifact ────────────────────────────────


def test_concurrent_same_owner_claim_task_idempotent(tmp_path: Path) -> None:
    """P0/concurrency/real-artifact"""
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    task_id = "shared-idempotent-task"
    session_id = "session-same"

    n_workers = 3
    results: list[bool] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(n_workers)

    def claim() -> None:
        barrier.wait()
        result = store.claim_task(
            session_id=session_id,
            task_id=task_id,
            claim_kind="write",
            ttl_seconds=120,
        )
        with results_lock:
            results.append(result.allowed)

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = [ex.submit(claim) for _ in range(n_workers)]
        concurrent.futures.wait(futures)

    assert all(results), f"All same-owner claims should succeed: {results}"

    task_dir = store.root / "tasks"
    task_files = list(task_dir.glob("*.json"))
    assert len(task_files) == 1, f"Expected 1 task file, got {len(task_files)}"
