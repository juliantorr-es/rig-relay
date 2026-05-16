from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from rig_relay.runtime.supervisor_invoker import SupervisorCommandInvoker
from rig_relay.runtime.supervisor_result import (
    RuntimeSupervisorCommandDigest,
    RuntimeSupervisorOutputDigest,
    RuntimeSupervisorResourceUsage,
    RuntimeSupervisorResultClassification,
    RuntimeSupervisorTiming,
    build_runtime_supervisor_result_envelope,
)
from rig_relay.tracing.models import TraceStatus
from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.store import InMemoryTraceStore


def _invoker(
    *, trace_recorder: TraceRecorder | None = None
) -> SupervisorCommandInvoker:
    return SupervisorCommandInvoker(trace_recorder=trace_recorder)


def test_builder_is_pure_and_privacy_safe() -> None:
    envelope = build_runtime_supervisor_result_envelope(
        command=RuntimeSupervisorCommandDigest(
            executable="python",
            argv_hash="sha256:" + "a" * 64,
            argc=3,
            cwd_hash="sha256:" + "b" * 64,
            cwd_kind="repo",
        ),
        cwd={"cwd_hash": "sha256:" + "b" * 64, "cwd_kind": "repo"},
        state_projection={
            "current_state": "completed",
            "previous_state": "draining",
            "last_event": "drain_completed",
            "transition_count": 7,
            "exit_code": 0,
            "timed_out": False,
            "killed": False,
            "stdout_bytes": 3,
            "stderr_bytes": 0,
        },
        classification=RuntimeSupervisorResultClassification.COMPLETED,
        resource_usage=RuntimeSupervisorResourceUsage(exit_code=0, pid=1234),
        output=RuntimeSupervisorOutputDigest(
            stdout_sha256="sha256:" + "c" * 64,
            stderr_sha256="sha256:" + "d" * 64,
            stdout_bytes=3,
            stderr_bytes=0,
        ),
        timing=RuntimeSupervisorTiming(
            started_at="2026-05-16T00:00:00Z",
            completed_at="2026-05-16T00:00:01Z",
            duration_ms=1000.0,
        ),
        context=None,
    )
    dumped = envelope.model_dump(mode="json")
    assert dumped["classification"] == "completed"
    assert dumped["state"] == "completed"
    assert dumped["result_id"].startswith("sha256:")
    assert "print('secret')" not in envelope.model_dump_json()
    assert "stdout_text" not in dumped
    assert "stderr_text" not in dumped
    assert dumped["cwd"]["cwd_kind"] == "repo"


@pytest.mark.asyncio
async def test_success_envelope(tmp_path: Path) -> None:
    result = await _invoker().invoke(
        ["python", "-c", "print('ok')"], cwd=tmp_path, timeout_seconds=5
    )
    assert result.status == "completed"
    assert result.result_envelope is not None
    assert (
        result.result_envelope.classification
        == RuntimeSupervisorResultClassification.COMPLETED
    )
    assert result.result_envelope.state == "completed"


@pytest.mark.asyncio
async def test_nonzero_timeout_and_spawn_failure_envelopes(tmp_path: Path) -> None:
    invoker = _invoker()

    nonzero = await invoker.invoke(
        ["python", "-c", "import sys; sys.exit(3)"], cwd=tmp_path, timeout_seconds=5
    )
    assert nonzero.result_envelope is not None
    assert (
        nonzero.result_envelope.classification
        == RuntimeSupervisorResultClassification.FAILED
    )

    timed_out = await invoker.invoke(
        ["python", "-c", "import time; time.sleep(2)"],
        cwd=tmp_path,
        timeout_seconds=0.1,
    )
    assert timed_out.result_envelope is not None
    assert (
        timed_out.result_envelope.classification
        == RuntimeSupervisorResultClassification.TIMED_OUT
    )
    assert timed_out.result_envelope.resource_usage.timed_out is True

    spawn_failed = await invoker.invoke(
        ["definitely-not-a-real-binary-12345"], cwd=tmp_path, timeout_seconds=1
    )
    assert spawn_failed.result_envelope is not None
    assert (
        spawn_failed.result_envelope.classification
        == RuntimeSupervisorResultClassification.SPAWN_FAILED
    )


@pytest.mark.asyncio
async def test_cancelled_envelope_and_trace_alignment(tmp_path: Path) -> None:
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    invoker = _invoker(trace_recorder=recorder)

    task = asyncio.create_task(
        invoker.invoke(
            ["python", "-c", "import time; time.sleep(2)"],
            cwd=tmp_path,
            timeout_seconds=5,
        )
    )
    asyncio.get_running_loop().call_later(0.05, task.cancel)
    result = await task
    assert result.status == "failed"
    assert result.refusal_code == "cancelled"
    assert result.result_envelope is not None
    assert (
        result.result_envelope.classification
        == RuntimeSupervisorResultClassification.CANCELLED
    )
    span_ends = [event for event in store.events if event["event_kind"] == "span.end"]
    assert span_ends
    assert any(
        event["status"] in {TraceStatus.cancelled.value, TraceStatus.error.value}
        for event in span_ends
    )
