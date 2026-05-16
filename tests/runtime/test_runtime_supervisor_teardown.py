from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import gc
from pathlib import Path

import pytest

from rig_relay.coordination.execution_lease import ExecutionLease, ExecutionLeaseStatus
from rig_relay.runtime.execution_request import ExecutionRequest
from rig_relay.runtime.stream_types import RuntimeFailureEvent
from rig_relay.runtime.supervisor import RuntimeSupervisor, _finalize_subprocess


def _request(*, argv: list[str], cwd: Path, timeout_ms: int = 10_000) -> ExecutionRequest:
    return ExecutionRequest(
        request_id="req-teardown-001",
        argv=argv,
        cwd=str(cwd),
        timeout_ms=timeout_ms,
        purpose="teardown test",
    )


def _lease(request: ExecutionRequest, *, expires_delta: timedelta = timedelta(hours=1)) -> ExecutionLease:
    now = datetime.now(UTC)
    return ExecutionLease(
        lease_id=request.request_id,
        request=request,
        acquired_at=now.isoformat(),
        expires_at=(now + expires_delta).isoformat(),
        status=ExecutionLeaseStatus.ACTIVE,
    )


async def _collect(supervisor: RuntimeSupervisor, lease: ExecutionLease):
    events = []
    async for event in supervisor.execute(lease):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_timeout_cleanup_no_unraisable_warning(tmp_path: Path) -> None:
    supervisor = RuntimeSupervisor()
    lease = _lease(
        _request(
            argv=["python", "-c", "import time; time.sleep(2)"],
            cwd=tmp_path,
            timeout_ms=100,
        )
    )

    events = await _collect(supervisor, lease)
    assert isinstance(events[-1], RuntimeFailureEvent)
    assert events[-1].status.value == "timed_out"
    gc.collect()


@pytest.mark.asyncio
async def test_finalize_subprocess_is_idempotent(tmp_path: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        "print('ok')",
        cwd=str(tmp_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await _finalize_subprocess(proc)
    await _finalize_subprocess(proc)
    assert proc.returncode is not None
