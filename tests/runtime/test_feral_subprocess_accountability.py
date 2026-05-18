"""Adversarial runtime feral subprocess accountability tests.

Integration/real-artifact tests that stress the RuntimeSupervisor under
hostile conditions: timeouts with partial output, non-zero exits with stderr,
cancellation integrity, large-output bounding, and orphan process detection.

Uses real subprocesses (temporary Python scripts) with real timeouts and
cancellation to verify correctness under adversarial scenarios.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import sys

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration, pytest.mark.real_artifact]

from rig_relay.coordination.execution_lease import (
    ExecutionLease,
    ExecutionLeaseStatus,
    ExecutionLeaseStore,
)
from rig_relay.runtime.execution_request import ExecutionRequest
from rig_relay.runtime.models import RuntimeInvocationStatus
from rig_relay.runtime.stream_types import (
    RuntimeCompletionEvent,
    RuntimeFailureEvent,
    RuntimeStreamEvent,
)
from rig_relay.runtime.supervisor import RuntimeSupervisor

PYTHON = sys.executable


def _request(**overrides: object) -> ExecutionRequest:
    kwargs: dict[str, object] = {
        "request_id": "req-feral-001",
        "argv": [PYTHON, "-c", "print('hello')"],
        "cwd": str(Path.cwd()),
        "timeout_ms": 15000,
        "purpose": "Feral subprocess accountability adversarial test",
    }
    kwargs.update(overrides)
    return ExecutionRequest(**kwargs)  # type: ignore[arg-type]


def _make_lease(
    request: ExecutionRequest,
    status: ExecutionLeaseStatus = ExecutionLeaseStatus.ACTIVE,
) -> ExecutionLease:
    now = datetime.now(UTC)
    return ExecutionLease(
        lease_id=request.request_id,
        request=request,
        acquired_at=now.isoformat(),
        expires_at=(now + timedelta(hours=1)).isoformat(),
        status=status,
    )


async def _collect_events(
    supervisor: RuntimeSupervisor, lease: ExecutionLease
) -> list[RuntimeStreamEvent]:
    events: list[RuntimeStreamEvent] = []
    async for event in supervisor.execute(lease):
        events.append(event)
    return events


@pytest.fixture(autouse=True)
def _patch_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def lease_store(tmp_path: Path) -> ExecutionLeaseStore:
    return ExecutionLeaseStore(tmp_path / "leases")


def _acquire(
    lease_store: ExecutionLeaseStore, request: ExecutionRequest
) -> ExecutionLease:
    """Acquire a lease in the store and return the active lease."""
    result = lease_store.acquire(request, ttl_seconds=3600)
    assert result.lease is not None
    return result.lease


# ── Test 1: Timeout produces partial output with bounded hashing ───────


@pytest.mark.asyncio
async def test_timeout_produces_partial_output_with_hash(
    lease_store: ExecutionLeaseStore, tmp_path: Path
) -> None:
    """integration/real-artifact/adversarial — timeout captures bounded partial output."""
    # Close stdout immediately after writing so the drain task sees EOF
    # and finalizes the result before the timeout fires.
    script = tmp_path / "slow_writer.py"
    script.write_text(
        "import sys, os, time\n"
        "sys.stdout.write('HELLO_WORLD_OUTPUT\\n')\n"
        "sys.stdout.flush()\n"
        "os.close(sys.stdout.fileno())\n"
        "time.sleep(30)\n"
    )

    req = _request(argv=[PYTHON, str(script)], cwd=str(tmp_path), timeout_ms=800)
    lease = _acquire(lease_store, req)

    supervisor = RuntimeSupervisor(lease_store=lease_store)
    events = await _collect_events(supervisor, lease)

    terminal = events[-1]
    assert isinstance(terminal, RuntimeFailureEvent)
    assert terminal.status == RuntimeInvocationStatus.TIMED_OUT
    assert terminal.error_kind == "timeout"
    assert terminal.stdout_sha256 is not None, "stdout hash must not be empty"
    assert terminal.stdout_bytes is not None and terminal.stdout_bytes > 0

    # Content-light: terminal event must not contain raw output
    dumped = terminal.model_dump(mode="json")
    assert "chunk_text" not in dumped or dumped["chunk_text"] is None
    assert "stdout" not in dumped


# ── Test 2: Nonzero exit captures stderr with bounded hashing ──────────


@pytest.mark.asyncio
async def test_nonzero_exit_captures_stderr_with_hash(
    lease_store: ExecutionLeaseStore, tmp_path: Path
) -> None:
    """integration/real-artifact/adversarial — nonzero exit records stderr hash."""
    # Close stderr after writing so the drain task sees EOF and finalizes
    # before the process exit is detected by the poll loop.
    script = tmp_path / "stderr_writer.py"
    script.write_text(
        "import sys, os, time\n"
        "sys.stderr.write('ERROR_MESSAGE_FERAL_XYZ\\n')\n"
        "sys.stderr.flush()\n"
        "os.close(sys.stderr.fileno())\n"
        "time.sleep(0.3)\n"
        "sys.exit(42)\n"
    )

    req = _request(argv=[PYTHON, str(script)], cwd=str(tmp_path), timeout_ms=5000)
    lease = _acquire(lease_store, req)

    supervisor = RuntimeSupervisor(lease_store=lease_store)
    events = await _collect_events(supervisor, lease)

    terminal = events[-1]
    assert isinstance(terminal, RuntimeCompletionEvent)
    assert terminal.status == RuntimeInvocationStatus.FAILED
    assert terminal.exit_code == 42
    assert terminal.stderr_sha256 is not None, "stderr hash must not be empty"
    assert terminal.stderr_bytes is not None and terminal.stderr_bytes > 0

    # Content-light: terminal event must not contain raw stderr text
    dumped = terminal.model_dump(mode="json")
    assert "stderr" not in dumped
    assert "chunk_text" not in dumped or dumped["chunk_text"] is None


# ── Test 3: Cancellation produces exactly one terminal event ───────────


@pytest.mark.asyncio
async def test_cancellation_produces_one_terminal_event(
    lease_store: ExecutionLeaseStore, tmp_path: Path
) -> None:
    """integration/real-artifact/sabotage — cancel produces exactly one terminal event."""
    script = tmp_path / "forever.py"
    script.write_text("import time; time.sleep(9999)\n")

    req = _request(argv=[PYTHON, str(script)], cwd=str(tmp_path), timeout_ms=120000)
    lease = _acquire(lease_store, req)

    supervisor = RuntimeSupervisor(lease_store=lease_store)

    task = asyncio.ensure_future(_collect_events(supervisor, lease))
    await asyncio.sleep(0.3)
    task.cancel()

    try:
        events = await task
    except asyncio.CancelledError:
        events = []

    terminal_events = [
        e
        for e in events
        if isinstance(e, (RuntimeCompletionEvent, RuntimeFailureEvent))
    ]
    assert len(terminal_events) == 1, (
        f"Expected exactly 1 terminal event, got {len(terminal_events)}: "
        f"{[type(e).__name__ for e in terminal_events]}"
    )
    te = terminal_events[0]
    assert isinstance(te, RuntimeFailureEvent)
    assert te.status == RuntimeInvocationStatus.CANCELLED
    assert te.error_kind == "cancelled"

    # Verify lease was released (no dangling state)
    stored = lease_store.read(lease.lease_id)
    if stored is not None:
        assert stored.status == ExecutionLeaseStatus.RELEASED, (
            f"Lease should be released after cancellation, got {stored.status}"
        )


# ── Test 4: Process death (non-zero exit) recorded as failed ───────────


@pytest.mark.asyncio
async def test_process_exit_nonzero_recorded_as_failed(
    lease_store: ExecutionLeaseStore, tmp_path: Path
) -> None:
    """integration/real-artifact/adversarial — exit(1) recorded as failed_nonzero."""
    req = _request(
        argv=[PYTHON, "-c", "import sys; sys.exit(1)"],
        cwd=str(tmp_path),
        timeout_ms=5000,
    )
    lease = _acquire(lease_store, req)

    supervisor = RuntimeSupervisor(lease_store=lease_store)
    events = await _collect_events(supervisor, lease)

    terminal = events[-1]
    assert isinstance(terminal, RuntimeCompletionEvent)
    assert terminal.status == RuntimeInvocationStatus.FAILED
    assert terminal.exit_code == 1


# ── Test 5: Large stdout is bounded and truncated flag is set ──────────


@pytest.mark.asyncio
async def test_large_stdout_is_bounded_and_truncated(
    lease_store: ExecutionLeaseStore, tmp_path: Path
) -> None:
    """integration/real-artifact/adversarial — large output bounded with truncated flag."""
    # Write large output then close stdout so the drain task finalizes
    # before the process exit triggers cancellation.
    script = tmp_path / "large_writer.py"
    script.write_text(
        "import sys, os, time\n"
        "sys.stdout.write('X' * 200000 + '\\n')\n"
        "sys.stdout.flush()\n"
        "os.close(sys.stdout.fileno())\n"
        "time.sleep(0.2)\n"
    )

    req = _request(argv=[PYTHON, str(script)], cwd=str(tmp_path), timeout_ms=15000)
    lease = _acquire(lease_store, req)

    supervisor = RuntimeSupervisor(lease_store=lease_store, max_stdout_bytes=10000)
    events = await _collect_events(supervisor, lease)

    terminal = events[-1]
    assert isinstance(terminal, RuntimeCompletionEvent)
    assert terminal.stdout_truncated is True, (
        "stdout_truncated must be True for large output"
    )
    assert terminal.stdout_bytes > 10000, (
        f"stdout_bytes={terminal.stdout_bytes} should exceed cap 10000"
    )
    assert terminal.stdout_sha256 is not None

    # Content-light: terminal event must not contain raw output
    dumped = terminal.model_dump(mode="json")
    assert "chunk_text" not in dumped or dumped["chunk_text"] is None
    assert "stdout" not in dumped


# ── Test 6: Cancelled subprocess does not leave orphaned process ───────


@pytest.mark.asyncio
async def test_cancelled_subprocess_does_not_leave_orphan(
    lease_store: ExecutionLeaseStore, tmp_path: Path
) -> None:
    """integration/real-artifact/sabotage — cancel kills subprocess, no orphan."""
    pid_file = tmp_path / "feral_pid.txt"
    script = tmp_path / "write_pid_and_sleep.py"
    script.write_text(
        f"""import os, time
with open({str(pid_file)!r}, 'w') as f:
    f.write(str(os.getpid()))
    f.flush()
time.sleep(9999)
"""
    )

    req = _request(argv=[PYTHON, str(script)], cwd=str(tmp_path), timeout_ms=120000)
    lease = _acquire(lease_store, req)

    supervisor = RuntimeSupervisor(lease_store=lease_store)

    task = asyncio.ensure_future(_collect_events(supervisor, lease))

    # Wait for the process to start and write its PID
    for _ in range(50):
        if pid_file.exists():
            break
        await asyncio.sleep(0.1)
    assert pid_file.exists(), "Pid file must exist before cancellation"

    pid = int(pid_file.read_text().strip())
    assert pid > 0

    # Cancel the supervision task
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Give the supervisor time to kill the process
    await asyncio.sleep(0.5)

    # Verify process is dead
    try:
        os.kill(pid, 0)
        pytest.fail(f"Subprocess PID {pid} is still alive after cancellation (orphan)")
    except ProcessLookupError:
        pass  # Expected: process no longer exists
