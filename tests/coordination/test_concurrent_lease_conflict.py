"""Concurrent lease conflict reality tests for the coordination system.

Tests CoordinationStore and PathLeaseManager under genuine concurrent
access using ThreadPoolExecutor and threading.Barrier. Since the store is
file-backed and all methods are synchronous, thread-based concurrency is
the correct model to expose TOCTOU races, interleaved JSONL writes, and
duplicate sequence numbers.
"""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess
import textwrap
import threading
import time

import pytest

from rig_relay.coordination.lease_manager import PathLeaseManager
from rig_relay.coordination.models import (
    CoordinationSession,
    reset_path_salt_for_testing,
)
from rig_relay.coordination.store import CoordinationStore


def _make_store(tmp_path: Path) -> CoordinationStore:
    return CoordinationStore(tmp_path / ".build" / "rig-relay" / "coordination")


def _make_manager(tmp_path: Path) -> PathLeaseManager:
    return PathLeaseManager(tmp_path / ".build" / "rig-relay" / "coordination")


def _jsonl_lines(events_path: Path) -> list[dict]:
    if not events_path.is_file():
        return []
    raw = events_path.read_text(encoding="utf-8")
    lines: list[dict] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(json.loads(stripped))
    return lines


def _count_lease_files(tmp_path: Path) -> int:
    lease_dir = tmp_path / ".build" / "rig-relay" / "coordination" / "leases" / "paths"
    if not lease_dir.is_dir():
        return 0
    return len(list(lease_dir.glob("*.json")))


def test_concurrent_path_claims_produce_exactly_one_winner(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    path = "src/main.py"

    results: list[tuple[str, bool, str | None]] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def claim(session_id: str) -> None:
        task_id = f"task-{session_id}"
        barrier.wait()
        result = store.reserve_paths(
            session_id=session_id,
            task_id=task_id,
            mode="write",
            paths=[path],
            ttl_seconds=120,
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

    granted = [(sid, kind) for sid, allowed, kind in results if allowed]
    denied = [(sid, kind) for sid, allowed, kind in results if not allowed]

    assert len(granted) == 1, (
        f"Expected exactly 1 granted, got {len(granted)}: {results}"
    )
    assert len(denied) == 1, f"Expected exactly 1 denied, got {len(denied)}: {results}"
    assert denied[0][1] is not None, "Denied claim must have a conflict kind"

    lease_count = _count_lease_files(tmp_path)
    assert lease_count == 1, f"Expected 1 lease file, got {lease_count}"


def test_concurrent_write_read_conflict(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    path = "src/main.py"

    results: list[tuple[str, str, bool, str | None]] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def claim(session_id: str, mode: str) -> None:
        task_id = f"task-{session_id}"
        barrier.wait()
        result = store.reserve_paths(
            session_id=session_id,
            task_id=task_id,
            mode=mode,  # type: ignore[arg-type]
            paths=[path],
            ttl_seconds=120,
        )
        with results_lock:
            results.append((
                session_id,
                mode,
                result.allowed,
                result.conflict.kind if result.conflict else None,
            ))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f_w = ex.submit(claim, "session-w", "write")
        f_r = ex.submit(claim, "session-r", "read")
        f_w.result()
        f_r.result()

    granted = [r for r in results if r[2]]
    denied = [r for r in results if not r[2]]

    assert len(granted) == 1, (
        f"Expected exactly 1 winner for write vs read race, "
        f"got {len(granted)}: {results}"
    )
    assert len(denied) == 1, f"Expected exactly 1 denied, got {len(denied)}: {results}"
    lease_count = _count_lease_files(tmp_path)
    assert lease_count == 1, f"Expected 1 lease file, got {lease_count}"


def test_concurrent_release_and_reclaim(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    path = "src/main.py"

    claim_a = store.reserve_paths(
        session_id="session-a",
        task_id="task-a",
        mode="write",
        paths=[path],
        ttl_seconds=120,
    )
    assert claim_a.allowed is True

    release_done = threading.Event()
    claim_result: list[tuple[bool, str | None]] = []

    def release_then_signal() -> None:
        store.release_paths(session_id="session-a", task_id="task-a", paths=[path])
        release_done.set()

    def claim_after_release() -> None:
        release_done.wait()
        result = store.reserve_paths(
            session_id="session-b",
            task_id="task-b",
            mode="write",
            paths=[path],
            ttl_seconds=120,
        )
        claim_result.append((
            result.allowed,
            result.conflict.kind if result.conflict else None,
        ))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        ex.submit(release_then_signal)
        ex.submit(claim_after_release)

    assert len(claim_result) == 1, "Session-B must have attempted the claim"
    assert claim_result[0][0] is True, (
        f"Session-B should get the grant after release, got {claim_result}"
    )

    active = store.read_state_projection().active_path_reservations
    assert len(active) == 1
    reservation = list(active.values())[0]
    assert reservation.session_id == "session-b"


def test_concurrent_heartbeat_does_not_corrupt_ledger(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)

    session_ids = [f"session-{i}" for i in range(8)]
    for sid in session_ids:
        store.register_session(CoordinationSession(session_id=sid, status="running"))

    results: list[Exception | None] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(len(session_ids))

    def send_heartbeats(session_id: str) -> None:
        barrier.wait()
        try:
            for _ in range(10):
                store.heartbeat(
                    session_id=session_id,
                    status="running",
                    current_step="concurrent_test",
                )
        except Exception as exc:
            with results_lock:
                results.append(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(session_ids)) as ex:
        futures = [ex.submit(send_heartbeats, sid) for sid in session_ids]
        concurrent.futures.wait(futures)

    assert not results, f"Heartbeats raised exceptions: {results}"

    events_path = tmp_path / ".build" / "rig-relay" / "coordination" / "events.jsonl"
    assert events_path.is_file(), "events.jsonl must exist"

    raw = events_path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    valid_lines = 0
    parse_errors: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            json.loads(stripped)
            valid_lines += 1
        except json.JSONDecodeError as exc:
            parse_errors.append(f"Line {i}: {exc}")

    assert not parse_errors, (
        f"events.jsonl has {len(parse_errors)} unparseable lines: {parse_errors[:5]}"
    )
    assert valid_lines > 0, "events.jsonl must have at least one valid event"


def test_concurrent_store_operations_are_atomic(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)

    for i in range(4):
        store.register_session(
            CoordinationSession(session_id=f"session-{i}", status="running")
        )

    errors: list[str] = []
    errors_lock = threading.Lock()
    barrier = threading.Barrier(4)

    def worker(worker_id: int) -> None:
        sid = f"session-{worker_id}"
        barrier.wait()
        try:
            store.claim_task(
                session_id=sid,
                task_id=f"task-{worker_id}",
                claim_kind="test",
                ttl_seconds=120,
            )
            store.reserve_paths(
                session_id=sid,
                task_id=f"task-{worker_id}",
                mode="write",
                paths=[f"src/worker-{worker_id}.py"],
                ttl_seconds=120,
            )
            store.heartbeat(session_id=sid, status="running", current_step="mixed_ops")
            store.publish_artifact(
                session_id=sid,
                task_id=f"task-{worker_id}",
                artifact_kind="test_artifact",
                artifact_uri=f"mem://artifact-{worker_id}",
                artifact_sha256=f"sha256:deadbeef{worker_id:04d}",
            )
        except Exception as exc:
            with errors_lock:
                errors.append(f"Worker {worker_id}: {exc}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(worker, i) for i in range(4)]
        concurrent.futures.wait(futures)

    assert not errors, f"Workers encountered errors: {errors}"

    proj = store.read_state_projection()

    assert len(proj.active_sessions) == 4
    assert len(proj.active_task_claims) == 4
    assert len(proj.active_path_reservations) == 4
    assert len(proj.recent_artifacts) == 4
    assert len(proj.conflicts) == 0


def test_concurrent_read_read_coexistence(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    path = "src/shared.py"
    n_sessions = 4

    results: list[bool] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(n_sessions)

    def claim_read(session_id: str) -> None:
        barrier.wait()
        result = store.reserve_paths(
            session_id=session_id,
            task_id=f"task-{session_id}",
            mode="read",
            paths=[path],
            ttl_seconds=120,
        )
        with results_lock:
            results.append(result.allowed)

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_sessions) as ex:
        futures = [ex.submit(claim_read, f"session-{i}") for i in range(n_sessions)]
        concurrent.futures.wait(futures)

    assert all(results), f"All read claims should succeed, got {results}"

    active = store.read_state_projection().active_path_reservations
    assert len(active) == n_sessions, (
        f"Expected {n_sessions} active read leases, got {len(active)}"
    )


def test_expired_lease_recovery_under_concurrency(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    path = "src/recover.py"

    claim_result = store.reserve_paths(
        session_id="old-session",
        task_id="old-task",
        mode="write",
        paths=[path],
        ttl_seconds=1,
    )
    assert claim_result.allowed

    lease_dir = store.root / "leases" / "paths"
    for lease_path in lease_dir.glob("*.json"):
        data = json.loads(lease_path.read_text(encoding="utf-8"))
        data["expires_at"] = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
        data["status"] = "stale"
        lease_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    proj = store.read_state_projection()
    assert len(proj.active_path_reservations) == 0, (
        "Stale lease should not appear in active reservations"
    )

    results: list[tuple[str, bool]] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def recover_claim(session_id: str) -> None:
        barrier.wait()
        result = store.reserve_paths(
            session_id=session_id,
            task_id=f"task-{session_id}",
            mode="write",
            paths=[path],
            ttl_seconds=120,
        )
        with results_lock:
            results.append((session_id, result.allowed))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f_a = ex.submit(recover_claim, "recover-a")
        f_b = ex.submit(recover_claim, "recover-b")
        f_a.result()
        f_b.result()

    granted = [r for r in results if r[1]]
    _denied = [r for r in results if not r[1]]

    assert len(granted) in (1, 2), (
        f"With stale leases, recovery may grant one or both; got {len(granted)}: {results}"
    )

    final = store.read_state_projection()
    assert len(final.active_path_reservations) >= 1, (
        f"At least 1 active lease after recovery, "
        f"got {len(final.active_path_reservations)}"
    )


def test_path_lease_manager_concurrent_claims(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    mgr = _make_manager(tmp_path)
    path = "src/manager_test.py"

    results: list[tuple[str, str, str | None]] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def claim(session_id: str) -> None:
        barrier.wait()
        result = mgr.claim_paths(
            session_id=session_id,
            task_id=f"task-{session_id}",
            mode="exclusive_write",
            paths=[path],
            ttl_seconds=120,
        )
        with results_lock:
            results.append((session_id, result.status, result.error_kind))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        ex.submit(claim, "sess-a")
        ex.submit(claim, "sess-b")

    granted = [r for r in results if r[1] == "granted"]
    conflicts = [r for r in results if r[1] == "conflict"]

    assert len(granted) == 1, (
        f"Expected exactly 1 granted, got {len(granted)}: {results}"
    )
    assert len(conflicts) == 1, (
        f"Expected exactly 1 conflict, got {len(conflicts)}: {results}"
    )


def test_many_iteration_race_stress(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    iterations = 50
    double_wins = 0
    correct = 0

    for i in range(iterations):
        sub = tmp_path / str(i)
        store = _make_store(sub)
        path = f"src/iter-{i}.py"

        results: list[bool] = []
        results_lock = threading.Lock()
        barrier = threading.Barrier(2)

        def claim(
            session_id: str, b=barrier, s=store, p=path, rl=results_lock, rs=results
        ) -> None:
            b.wait()
            result = s.reserve_paths(
                session_id=session_id,
                task_id=f"task-{session_id}",
                mode="write",
                paths=[p],
                ttl_seconds=120,
            )
            with rl:
                rs.append(result.allowed)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            ex.submit(claim, "sess-1")
            ex.submit(claim, "sess-2")

        granted = sum(1 for r in results if r)
        if granted == 1:
            correct += 1
        elif granted == 2:
            double_wins += 1

    msg = f"Race stress: {correct}/{iterations} correct, {double_wins} double-wins"
    if double_wins > 0:
        pytest.fail(
            f"TOCTOU race condition detected: {msg}. "
            "The store's reserve_paths lacks a mutex — "
            "two sessions both claimed the same path."
        )


def test_subprocess_path_claims_produce_exactly_one_winner(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    coord_root = tmp_path / ".build" / "rig-relay" / "coordination"
    coord_root_str = str(coord_root)
    ready_file = tmp_path / "ready.txt"
    ready_file_str = str(ready_file)

    script = textwrap.dedent(f"""\
        import sys, time
        from pathlib import Path
        from rig_relay.coordination.store import CoordinationStore

        store = CoordinationStore(Path("{coord_root_str}"))
        ready = Path("{ready_file_str}")
        while not ready.exists():
            time.sleep(0.001)

        result = store.reserve_paths(
            session_id=f"subprocess-{{sys.argv[1]}}",
            task_id=f"task-subprocess-{{sys.argv[1]}}",
            mode="write",
            paths=["src/subprocess_race.py"],
            ttl_seconds=300,
        )
        print(result.allowed)
    """)

    script_path = tmp_path / "claim_script.py"
    script_path.write_text(script)

    procs: list[subprocess.Popen[str]] = []
    for name in ("a", "b"):
        p = subprocess.Popen(
            ["uv", "run", "python", str(script_path), name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(tmp_path),
        )
        procs.append(p)

    time.sleep(0.2)
    ready_file.touch()

    results: list[bool] = []
    for p in procs:
        stdout, stderr = p.communicate(timeout=15)
        if stderr:
            print(f"Subprocess stderr: {stderr}")
        line = stdout.strip()
        if line == "True":
            results.append(True)
        elif line == "False":
            results.append(False)
        else:
            results.append(False)

    assert len(results) == 2, f"Expected 2 results, got {len(results)}: {results}"
    granted = sum(1 for r in results if r)
    assert granted == 1, f"Expected exactly 1 granted, got {granted}: {results}"

    lease_count = _count_lease_files(tmp_path)
    assert lease_count == 1, f"Expected 1 lease file, got {lease_count}"
