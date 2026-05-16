from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from rig_relay.coordination.execution_lease import ExecutionLease, ExecutionLeaseStatus
from rig_relay.runtime.execution_request import ExecutionRequest
from rig_relay.runtime.stream_types import RuntimeCompletionEvent, RuntimeFailureEvent
from rig_relay.runtime.supervisor import RuntimeSupervisor
from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.store import InMemoryTraceStore


def _request(
    *, argv: list[str], cwd: Path, timeout_ms: int = 10_000
) -> ExecutionRequest:
    return ExecutionRequest(
        request_id="req-trace-001",
        argv=argv,
        cwd=str(cwd),
        timeout_ms=timeout_ms,
        purpose="trace test",
    )


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


def _lease(
    request: ExecutionRequest, *, expires_delta: timedelta = timedelta(hours=1)
) -> ExecutionLease:
    now = datetime.now(UTC)
    return ExecutionLease(
        lease_id=request.request_id,
        request=request,
        acquired_at=now.isoformat(),
        expires_at=(now + expires_delta).isoformat(),
        status=ExecutionLeaseStatus.ACTIVE,
    )


@pytest.mark.asyncio
async def test_successful_subprocess_emits_trace_span(tmp_dir: Path) -> None:
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    supervisor = RuntimeSupervisor(trace_recorder=recorder)
    lease = _lease(_request(argv=["python", "-c", "print('ok')"], cwd=tmp_dir))

    events = [event async for event in supervisor.execute(lease)]
    assert isinstance(events[-1], RuntimeCompletionEvent)
    assert events[-1].status.value == "succeeded"
    assert any(event["name"] == "runtime.subprocess.execute" for event in store.events)


@pytest.mark.asyncio
async def test_nonzero_exit_emits_failure_status(tmp_dir: Path) -> None:
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    supervisor = RuntimeSupervisor(trace_recorder=recorder)
    lease = _lease(
        _request(argv=["python", "-c", "import sys; sys.exit(3)"], cwd=tmp_dir)
    )

    events = [event async for event in supervisor.execute(lease)]
    assert isinstance(events[-1], RuntimeCompletionEvent)
    assert events[-1].status.value == "failed"
    assert any(
        event["status"] == "error"
        for event in store.events
        if event["event_kind"] == "span.end"
    )


@pytest.mark.asyncio
async def test_timeout_emits_timed_out_status(tmp_dir: Path) -> None:
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    supervisor = RuntimeSupervisor(trace_recorder=recorder)
    lease = _lease(
        _request(
            argv=["python", "-c", "import time; time.sleep(2)"],
            cwd=tmp_dir,
            timeout_ms=100,
        )
    )

    events = [event async for event in supervisor.execute(lease)]
    assert isinstance(events[-1], RuntimeFailureEvent)
    assert events[-1].status.value == "timed_out"
    assert any(
        event["status"] == "timed_out"
        for event in store.events
        if event["event_kind"] == "span.end"
    )


@pytest.mark.asyncio
async def test_trace_has_no_raw_stdout_or_stderr(tmp_dir: Path) -> None:
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    supervisor = RuntimeSupervisor(trace_recorder=recorder)
    lease = _lease(
        _request(argv=["python", "-c", "print('secret-output')"], cwd=tmp_dir)
    )

    await _collect(supervisor, lease)
    dumped = [str(event) for event in store.events]
    assert not any("secret-output" in item for item in dumped)


@pytest.mark.asyncio
async def test_trace_emits_byte_counts(tmp_dir: Path) -> None:
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    supervisor = RuntimeSupervisor(trace_recorder=recorder)
    lease = _lease(_request(argv=["python", "-c", "print('hello')"], cwd=tmp_dir))

    await _collect(supervisor, lease)
    ends = [event for event in store.events if event["event_kind"] == "span.end"]
    assert ends
    attrs = cast(dict[str, Any], ends[0]["attributes"])
    assert attrs["stdout_bytes"] > 0
    assert attrs["stderr_bytes"] == 0


@pytest.mark.asyncio
async def test_trace_carries_trace_id_to_child_span(tmp_dir: Path) -> None:
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    supervisor = RuntimeSupervisor(trace_recorder=recorder)
    lease = _lease(_request(argv=["python", "-c", "print('ok')"], cwd=tmp_dir))

    await _collect(supervisor, lease)
    trace_ids = {event["trace_id"] for event in store.events}
    assert len(trace_ids) == 1


async def _collect(supervisor: RuntimeSupervisor, lease):
    events = []
    async for event in supervisor.execute(lease):
        events.append(event)
    return events
