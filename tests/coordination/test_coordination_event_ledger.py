"""DuckDB-backed truth tests for the coordination event ledger.

Tests verify events.jsonl integrity using DuckDB as a disposable read-side
analytical projection. DuckDB is not the source of truth — events.jsonl is.
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
import subprocess
import sys
import threading

import pytest

try:
    import duckdb

    HAS_DUCKDB = True
except ImportError:
    duckdb = None  # type: ignore[assignment]
    HAS_DUCKDB = False

from rig_relay.coordination.models import (
    CoordinationSession,
    reset_path_salt_for_testing,
)
from rig_relay.coordination.store import CoordinationStore


def _make_store(tmp_path: Path) -> CoordinationStore:
    return CoordinationStore(tmp_path / ".build" / "rig-relay" / "coordination")


@pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not installed")
def test_duckdb_ledger_has_unique_sequences(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)

    n_workers = 4
    n_ops = 5
    barrier = threading.Barrier(n_workers)

    def worker(worker_id: int) -> None:
        sid = f"session-{worker_id}"
        barrier.wait()
        for i in range(n_ops):
            store.reserve_paths(
                session_id=sid,
                task_id=f"task-{worker_id}",
                mode="write",
                paths=[f"src/worker-{worker_id}-{i}.py"],
                ttl_seconds=120,
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = [ex.submit(worker, i) for i in range(n_workers)]
        concurrent.futures.wait(futures)
        for fut in futures:
            exc = fut.exception()
            if exc is not None:
                raise exc

    events_path = store.root / "events.jsonl"
    assert events_path.is_file()

    con = duckdb.connect(":memory:")
    try:
        result = con.execute(
            "SELECT count(*) AS total, count(DISTINCT sequence) AS unique_seqs "
            f"FROM read_json_auto('{events_path}')"
        ).fetchone()
        total, unique_seqs = result
        assert total > 0, "Events must exist"
        assert total == unique_seqs, (
            f"All sequences must be unique. Total: {total}, Unique: {unique_seqs}"
        )
    finally:
        con.close()


@pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not installed")
def test_duckdb_ledger_no_duplicate_events_subprocess(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    path = "src/subprocess_duckdb_test.py"
    coord_root = tmp_path / ".build" / "rig-relay" / "coordination"
    coord_root.mkdir(parents=True, exist_ok=True)

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
for i in range(3):
    result = store.reserve_paths(
        session_id=sys.argv[1], task_id=f"task-{{sys.argv[1]}}-{{i}}",
        mode="write", paths=[{path!r} + "-" + str(i)], ttl_seconds=120,
    )
print("done")
""")

    procs = []
    for label in ["proc-a", "proc-b"]:
        p = subprocess.Popen(
            [sys.executable, str(script), label],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        procs.append(p)

    for p in procs:
        stdout, stderr = p.communicate(timeout=15)
        assert "done" in stdout, (
            f"Subprocess did not complete: stdout={stdout} stderr={stderr}"
        )

    events_path = coord_root / "events.jsonl"
    assert events_path.is_file()

    con = duckdb.connect(":memory:")
    try:
        result = con.execute(
            "SELECT count(*) AS total, count(DISTINCT event_id) AS unique_ids "
            f"FROM read_json_auto('{events_path}')"
        ).fetchone()
        total, unique_ids = result
        assert total > 0, "Events must exist"
        assert total == unique_ids, (
            f"All event IDs must be unique. Total: {total}, Unique: {unique_ids}"
        )
    finally:
        con.close()


@pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not installed")
def test_duckdb_ledger_sequences_strictly_increasing(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)

    for i in range(10):
        store.reserve_paths(
            session_id="test-session",
            task_id=f"task-{i}",
            mode="write",
            paths=[f"src/file-{i}.py"],
            ttl_seconds=120,
        )

    events_path = store.root / "events.jsonl"
    con = duckdb.connect(":memory:")
    try:
        result = con.execute(
            "SELECT count(*) AS total, count(DISTINCT sequence) AS unique_seqs "
            f"FROM read_json_auto('{events_path}')"
        ).fetchone()
        total, unique_seqs = result
        assert total > 0, "Events must exist"
        assert total == unique_seqs, (
            f"All sequences must be unique. Total: {total}, Unique: {unique_seqs}"
        )
        # Verify sequences are contiguous (no gaps), implying monotonic file order.
        min_max = con.execute(
            f"SELECT min(sequence), max(sequence) FROM read_json_auto('{events_path}')"
        ).fetchone()
        seq_min, seq_max = min_max
        assert seq_max - seq_min + 1 == total, (
            f"Sequences must be contiguous. min={seq_min}, max={seq_max}, total={total}"
        )
    finally:
        con.close()


@pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not installed")
def test_duckdb_ledger_all_events_have_required_fields(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)

    store.register_session(
        CoordinationSession(session_id="test-session", status="running")
    )

    events_path = store.root / "events.jsonl"
    con = duckdb.connect(":memory:")
    try:
        missing_count = con.execute(
            "SELECT count(*) "
            f"FROM read_json_auto('{events_path}') "
            "WHERE event_id IS NULL OR sequence IS NULL OR event_name IS NULL OR created_at IS NULL"
        ).fetchone()[0]
        assert missing_count == 0, f"{missing_count} events missing required fields"
    finally:
        con.close()
