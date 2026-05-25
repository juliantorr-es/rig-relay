"""Real concurrency tests for the coordination digester formalization.

Tests use real CoordinationStore with real temp directories,
threading.Barrier + ThreadPoolExecutor for thread races,
and subprocess.run for cross-process tests.
"""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime, timedelta
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from rig_relay.coordination.models import (
    CoordinationSession,
    reset_path_salt_for_testing,
)
from rig_relay.coordination.store import CoordinationStore

pytestmark = pytest.mark.concurrency


def _make_store(tmp_path: Path) -> CoordinationStore:
    return CoordinationStore(tmp_path / ".build" / "rig-relay" / "coordination")


def test_expired_lease_does_not_block_reservation(tmp_path: Path) -> None:
    """P0/concurrency/real-artifact"""
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    path = "src/main.py"

    result_a = store.reserve_paths(
        session_id="old-session",
        task_id="old-task",
        mode="write",
        paths=[path],
        ttl_seconds=120,
    )
    assert result_a.allowed

    lease_dir = store.root / "leases" / "paths"
    for lease_file in lease_dir.glob("*.json"):
        data = json.loads(lease_file.read_text("utf-8"))
        data["expires_at"] = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
        lease_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    result_b = store.reserve_paths(
        session_id="new-session",
        task_id="new-task",
        mode="write",
        paths=[path],
        ttl_seconds=120,
    )
    assert result_b.allowed, f"Expired lease should not block: {result_b.warnings}"
    assert result_b.reservation is not None
    assert result_b.reservation.session_id == "new-session"


def test_expired_lease_marked_stale_on_disk(tmp_path: Path) -> None:
    """P0/concurrency/real-artifact"""
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    path = "src/main.py"

    result_a = store.reserve_paths(
        session_id="old-session",
        task_id="old-task",
        mode="write",
        paths=[path],
        ttl_seconds=120,
    )
    assert result_a.allowed

    lease_dir = store.root / "leases" / "paths"
    for lease_file in lease_dir.glob("*.json"):
        data = json.loads(lease_file.read_text("utf-8"))
        data["expires_at"] = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
        lease_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    result_b = store.reserve_paths(
        session_id="new-session",
        task_id="new-task",
        mode="write",
        paths=[path],
        ttl_seconds=120,
    )
    assert result_b.allowed

    for lease_file in lease_dir.glob("*.json"):
        data = json.loads(lease_file.read_text("utf-8"))
        if data.get("session_id") == "old-session":
            assert data.get("status") == "stale", (
                f"Old lease should be stale, got {data.get('status')}"
            )


def test_concurrent_claim_task_one_winner(tmp_path: Path) -> None:
    """P0/concurrency/real-artifact"""
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    task_id = "shared-task"

    results: list[tuple[str, bool, str | None]] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def claim(session_id: str) -> None:
        barrier.wait()
        result = store.claim_task(
            session_id=session_id, task_id=task_id, claim_kind="write", ttl_seconds=120
        )
        with results_lock:
            results.append((
                session_id,
                result.allowed,
                result.conflict.kind if result.conflict else None,
            ))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f_a = ex.submit(claim, "session-a")
        f_b = ex.submit(claim, "session-b")
        f_a.result()
        f_b.result()

    granted = [r for r in results if r[1]]
    denied = [r for r in results if not r[1]]

    assert len(granted) == 1, f"Expected 1 granted, got {len(granted)}: {results}"
    assert len(denied) == 1, f"Expected 1 denied, got {len(denied)}: {results}"
    assert denied[0][2] is not None, "Denied claim must have conflict kind"


def test_same_owner_claim_task_idempotent(tmp_path: Path) -> None:
    """P0/concurrency/real-artifact"""
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    task_id = "idempotent-task"

    result1 = store.claim_task(
        session_id="session-x", task_id=task_id, claim_kind="write", ttl_seconds=120
    )
    assert result1.allowed
    assert result1.claim is not None

    result2 = store.claim_task(
        session_id="session-x", task_id=task_id, claim_kind="write", ttl_seconds=120
    )
    assert result2.allowed, f"Same-owner retry should be allowed: {result2.warnings}"
    assert result2.claim is not None

    task_dir = store.root / "tasks"
    task_files = list(task_dir.glob("*.json"))
    assert len(task_files) == 1, f"Expected 1 task file, got {len(task_files)}"


def test_concurrent_release_and_reserve_consistent_state(tmp_path: Path) -> None:
    """P0/concurrency/real-artifact"""
    reset_path_salt_for_testing()
    path = "src/main.py"

    store_a = _make_store(tmp_path)
    result_a = store_a.reserve_paths(
        session_id="session-a",
        task_id="task-a",
        mode="write",
        paths=[path],
        ttl_seconds=120,
    )
    assert result_a.allowed

    results: list[tuple[str, str, bool]] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def release(session_id: str) -> None:
        store = _make_store(tmp_path)
        barrier.wait()
        store.release_paths(session_id=session_id, task_id="task-a", paths=[path])
        with results_lock:
            results.append(("release", session_id, True))

    def reserve(session_id: str) -> None:
        store = _make_store(tmp_path)
        barrier.wait()
        result = store.reserve_paths(
            session_id=session_id,
            task_id=f"task-{session_id}",
            mode="write",
            paths=[path],
            ttl_seconds=120,
        )
        with results_lock:
            results.append(("reserve", session_id, result.allowed))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        ex.submit(release, "session-a")
        ex.submit(reserve, "session-b")

    store_final = _make_store(tmp_path)
    projection = store_final.read_state_projection()

    active_leases = list(projection.active_path_reservations.values())
    assert len(active_leases) in (0, 1), (
        f"Expected 0 or 1 active leases, got {len(active_leases)}: {active_leases}"
    )
    if active_leases:
        assert active_leases[0].session_id in ("session-a", "session-b")


def test_same_process_instances_wait_for_lock_release(tmp_path: Path) -> None:
    """P0/concurrency/real-artifact"""
    reset_path_salt_for_testing()
    store_a = _make_store(tmp_path)
    store_b = _make_store(tmp_path)
    lock_fd = (store_a.root / ".digester.lock").open("r+b")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        completed = threading.Event()

        def register_session() -> None:
            store_b.register_session(
                CoordinationSession(session_id="session-b", status="running")
            )
            completed.set()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(register_session)
            assert not completed.wait(0.2), (
                "A second store instance should wait until the lock is released"
            )
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            future.result(timeout=5)
    finally:
        lock_fd.close()

    assert completed.is_set()
    assert (store_b.root / "sessions" / "session-b.json").is_file()


def test_subprocess_reserve_paths_one_winner(tmp_path: Path) -> None:
    """P0/concurrency/real-artifact — cross-process via subprocess"""
    reset_path_salt_for_testing()
    path = "src/subprocess_test.py"
    coord_root = tmp_path / ".build" / "rig-relay" / "coordination"

    project_root = Path(__file__).resolve().parent.parent.parent

    script = tmp_path / "claim_script.py"
    script.write_text(f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(project_root)!r})
from rig_relay.coordination.store import CoordinationStore
from rig_relay.coordination.models import reset_path_salt_for_testing

reset_path_salt_for_testing()
store = CoordinationStore(Path({str(coord_root)!r}))
result = store.reserve_paths(
    session_id=sys.argv[1], task_id=f"task-{{sys.argv[1]}}",
    mode="write", paths=[{path!r}], ttl_seconds=120,
)
print(json.dumps({{"session": sys.argv[1], "allowed": result.allowed}}))
""")

    proc_a = subprocess.Popen(
        [sys.executable, str(script), "proc-a"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    proc_b = subprocess.Popen(
        [sys.executable, str(script), "proc-b"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    out_a, err_a = proc_a.communicate(timeout=15)
    out_b, err_b = proc_b.communicate(timeout=15)

    result_a = json.loads(out_a.strip())
    result_b = json.loads(out_b.strip())

    allowed = [r for r in [result_a, result_b] if r["allowed"]]
    denied = [r for r in [result_a, result_b] if not r["allowed"]]

    assert len(allowed) == 1, (
        f"Expected 1 winner, got {len(allowed)}: {result_a}, {result_b}"
    )
    assert len(denied) == 1, (
        f"Expected 1 denied, got {len(denied)}: {result_a}, {result_b}"
    )
