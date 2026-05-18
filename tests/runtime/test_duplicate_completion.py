"""Runtime Duplicate Completion Detection — sabotage tests.

Proves the RuntimeSupervisor cannot emit duplicate completion events
for the same subprocess invocation and prevents lease reuse.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

import pytest

pytestmark = pytest.mark.asyncio

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
    RuntimeStreamEventKind,
)
from rig_relay.runtime.supervisor import RuntimeSupervisor

PYTHON = sys.executable


def _quick_request(**overrides: object) -> ExecutionRequest:
    kwargs: dict[str, object] = {
        "request_id": "req-dup-001",
        "argv": [PYTHON, "-c", "print('hello')"],
        "cwd": str(Path.cwd()),
        "timeout_ms": 15000,
        "purpose": "Duplicate completion test",
    }
    kwargs.update(overrides)
    return ExecutionRequest(**kwargs)  # type: ignore[arg-type]


def _make_lease(
    request: ExecutionRequest,
    status: ExecutionLeaseStatus = ExecutionLeaseStatus.ACTIVE,
    expires_delta: timedelta | None = None,
) -> ExecutionLease:
    now = datetime.now(UTC)
    if expires_delta is None:
        expires_delta = timedelta(hours=1)
    return ExecutionLease(
        lease_id=request.request_id,
        request=request,
        acquired_at=now.isoformat(),
        expires_at=(now + expires_delta).isoformat(),
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


# ── No double finalization ──────────────────────────────────────────


class TestNoDoubleFinalization:
    async def test_single_completion_yields_exactly_one_terminal_event(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(cwd=str(tmp_path))
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        terminals = [
            e
            for e in events
            if isinstance(e, (RuntimeCompletionEvent, RuntimeFailureEvent))
        ]
        comp = [e for e in terminals if isinstance(e, RuntimeCompletionEvent)]
        fail = [e for e in terminals if isinstance(e, RuntimeFailureEvent)]

        assert len(terminals) == 1, (
            f"Expected exactly 1 terminal event, got {len(terminals)}: "
            f"completions={len(comp)}, failures={len(fail)}"
        )
        assert len(comp) == 1
        assert comp[0].status == RuntimeInvocationStatus.SUCCEEDED

    async def test_failed_execution_yields_exactly_one_failure_event(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(
            argv=[PYTHON, "-c", "import sys; sys.exit(42)"], cwd=str(tmp_path)
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        terminals = [
            e
            for e in events
            if isinstance(e, (RuntimeCompletionEvent, RuntimeFailureEvent))
        ]
        assert len(terminals) == 1, f"Expected 1 terminal event, got {len(terminals)}"
        assert isinstance(terminals[0], RuntimeCompletionEvent)
        assert terminals[0].status == RuntimeInvocationStatus.FAILED
        assert terminals[0].exit_code == 42

    async def test_generator_exhausted_after_terminal_event(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(cwd=str(tmp_path))
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        gen = supervisor.execute(lease)

        terminal_seen = False
        async for event in gen:
            if isinstance(event, (RuntimeCompletionEvent, RuntimeFailureEvent)):
                terminal_seen = True
        assert terminal_seen

        # Generator should be exhausted — next anext raises StopAsyncIteration
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    async def test_timeout_exactly_one_failure_event(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(
            argv=[PYTHON, "-c", "import time; time.sleep(30)"],
            cwd=str(tmp_path),
            timeout_ms=200,
        )
        lease = _make_lease(req)
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        terminals = [
            e
            for e in events
            if isinstance(e, (RuntimeCompletionEvent, RuntimeFailureEvent))
        ]
        assert len(terminals) == 1
        assert isinstance(terminals[0], RuntimeFailureEvent)
        assert terminals[0].status == RuntimeInvocationStatus.TIMED_OUT

    async def test_command_not_found_exactly_one_failure_event(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(argv=["/nonexistent/cmd_xyz_dup"], cwd=str(tmp_path))
        lease = _make_lease(req)
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        terminals = [
            e
            for e in events
            if isinstance(e, (RuntimeCompletionEvent, RuntimeFailureEvent))
        ]
        assert len(terminals) == 1
        assert isinstance(terminals[0], RuntimeFailureEvent)
        assert terminals[0].error_kind == "command_not_found"

    async def test_no_duplicate_in_events_stream(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(
            argv=[PYTHON, "-c", "import time; time.sleep(0.5); print('done')"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        terminal_kinds = {
            RuntimeStreamEventKind.COMPLETION,
            RuntimeStreamEventKind.FAILURE,
        }
        terminal_count = sum(1 for e in events if e.event_kind in terminal_kinds)
        assert terminal_count == 1, f"Expected 1 terminal event, got {terminal_count}"

    async def test_same_generator_cannot_emit_two_terminal_events(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(
            argv=[PYTHON, "-c", "print('one and done')"], cwd=str(tmp_path)
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        gen = supervisor.execute(lease)

        terminal_count = 0
        async for event in gen:
            if isinstance(event, (RuntimeCompletionEvent, RuntimeFailureEvent)):
                terminal_count += 1
        assert terminal_count == 1, (
            f"Generator emitted {terminal_count} terminal events"
        )


# ── No double span closure ───────────────────────────────────────────


class _SpanEndCounter:
    """Spy trace recorder that counts calls to start_span and end_span."""

    def __init__(self) -> None:
        self.start_count = 0
        self.end_count = 0

    def start_span(
        self, name: str, attributes: dict | None = None, context: dict | None = None
    ) -> object:
        self.start_count += 1
        return _FakeSpan(self)

    def end_span(
        self,
        span: object,
        status: object = None,
        attributes: dict | None = None,
        error: str | None = None,
    ) -> None:
        self.end_count += 1

    def event(
        self,
        name: str,
        attributes: dict | None = None,
        context_override: dict | None = None,
    ) -> None:
        pass


class _FakeSpan:
    __slots__ = (
        "_recorder",
        "name",
        "span_id",
        "trace_id",
        "parent_span_id",
        "started_at",
    )

    def __init__(self, recorder: _SpanEndCounter) -> None:
        import time

        self._recorder = recorder
        self.name = "runtime.subprocess.execute"
        self.span_id = "span-1"
        self.trace_id = "trace-1"
        self.parent_span_id = None
        self.started_at = time.time()


class TestNoDoubleSpanClosure:
    async def test_span_closed_exactly_once_on_completion(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(cwd=str(tmp_path))
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        spy = _SpanEndCounter()
        supervisor = RuntimeSupervisor(lease_store=lease_store, trace_recorder=spy)  # type: ignore[arg-type]
        await _collect_events(supervisor, lease)

        assert spy.start_count == 1, (
            f"Expected 1 start_span call, got {spy.start_count}"
        )
        assert spy.end_count == 1, f"Expected 1 end_span call, got {spy.end_count}"

    async def test_span_closed_exactly_once_on_failure(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(
            argv=[PYTHON, "-c", "import sys; sys.exit(1)"], cwd=str(tmp_path)
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        spy = _SpanEndCounter()
        supervisor = RuntimeSupervisor(lease_store=lease_store, trace_recorder=spy)  # type: ignore[arg-type]
        await _collect_events(supervisor, lease)

        assert spy.start_count == 1
        assert spy.end_count == 1

    async def test_span_closed_exactly_once_on_timeout(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(
            argv=[PYTHON, "-c", "import time; time.sleep(30)"],
            cwd=str(tmp_path),
            timeout_ms=200,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        spy = _SpanEndCounter()
        supervisor = RuntimeSupervisor(lease_store=lease_store, trace_recorder=spy)  # type: ignore[arg-type]
        await _collect_events(supervisor, lease)

        assert spy.start_count == 1
        assert spy.end_count == 1

    async def test_span_closed_exactly_once_on_command_not_found(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(argv=["/nonexistent/cmd_span"], cwd=str(tmp_path))
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        spy = _SpanEndCounter()
        supervisor = RuntimeSupervisor(lease_store=lease_store, trace_recorder=spy)  # type: ignore[arg-type]
        await _collect_events(supervisor, lease)

        assert spy.start_count == 1
        assert spy.end_count == 1


# ── Lease state prevents re-execution ────────────────────────────────


class TestLeaseStatePreventsReExecution:
    async def test_pending_lease_is_refused(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(cwd=str(tmp_path))
        lease = _make_lease(req, status=ExecutionLeaseStatus.PENDING)
        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        assert len(events) == 1
        assert isinstance(events[0], RuntimeFailureEvent)
        assert events[0].status == RuntimeInvocationStatus.BLOCKED
        assert events[0].error_kind == "lease_inactive"

    async def test_released_lease_is_refused(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(cwd=str(tmp_path))
        lease = _make_lease(req, status=ExecutionLeaseStatus.RELEASED)
        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        assert len(events) == 1
        assert isinstance(events[0], RuntimeFailureEvent)
        assert events[0].status == RuntimeInvocationStatus.BLOCKED
        assert events[0].error_kind == "lease_inactive"

    async def test_expired_lease_is_refused(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(cwd=str(tmp_path))
        lease = _make_lease(req, status=ExecutionLeaseStatus.EXPIRED)
        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        assert len(events) == 1
        assert isinstance(events[0], RuntimeFailureEvent)
        assert events[0].status == RuntimeInvocationStatus.BLOCKED
        assert events[0].error_kind == "lease_inactive"

    async def test_cancelled_lease_is_refused(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(cwd=str(tmp_path))
        lease = _make_lease(req, status=ExecutionLeaseStatus.CANCELLED)
        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        assert len(events) == 1
        assert isinstance(events[0], RuntimeFailureEvent)
        assert events[0].status == RuntimeInvocationStatus.BLOCKED
        assert events[0].error_kind == "lease_inactive"

    async def test_failed_lease_is_refused(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(cwd=str(tmp_path))
        lease = _make_lease(req, status=ExecutionLeaseStatus.FAILED)
        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        assert len(events) == 1
        assert isinstance(events[0], RuntimeFailureEvent)
        assert events[0].status == RuntimeInvocationStatus.BLOCKED
        assert events[0].error_kind == "lease_inactive"

    async def test_store_reloaded_lease_refused_after_completion(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(cwd=str(tmp_path))
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        await _collect_events(supervisor, lease)

        # Reload from store — it's now RELEASED
        reloaded = lease_store.read(lease.lease_id)
        assert reloaded is not None
        assert reloaded.status == ExecutionLeaseStatus.RELEASED

        # Attempt to execute the reloaded released lease
        events = await _collect_events(supervisor, reloaded)
        assert len(events) == 1
        assert isinstance(events[0], RuntimeFailureEvent)
        assert events[0].status == RuntimeInvocationStatus.BLOCKED
        assert events[0].error_kind == "lease_inactive"

    async def test_store_reloaded_lease_refused_after_timeout(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _quick_request(
            argv=[PYTHON, "-c", "import time; time.sleep(30)"],
            cwd=str(tmp_path),
            timeout_ms=200,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        await _collect_events(supervisor, lease)

        reloaded = lease_store.read(lease.lease_id)
        assert reloaded is not None
        assert reloaded.status == ExecutionLeaseStatus.RELEASED

        events = await _collect_events(supervisor, reloaded)
        assert len(events) == 1
        assert isinstance(events[0], RuntimeFailureEvent)
        assert events[0].status == RuntimeInvocationStatus.BLOCKED
        assert events[0].error_kind == "lease_inactive"
