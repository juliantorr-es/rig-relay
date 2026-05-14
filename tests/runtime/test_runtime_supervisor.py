"""Tests for rig_relay.runtime.supervisor — P2b RuntimeSupervisor implementation.

Uses the current Python executable with -c snippets to test subprocess
supervision without depending on external tools. All tests use short
timeouts to keep execution fast.
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
from rig_relay.evidence.audit_trail import (
    AuditActionKind,
    AuditDecisionKind,
    AuditTrailStore,
)
from rig_relay.governance.governance_engine import GovernanceEngine
from rig_relay.runtime.execution_request import ExecutionRequest
from rig_relay.runtime.models import (
    RuntimeCapabilityKind,
    RuntimeInvocationStatus,
    RuntimeProviderStatus,
    RuntimeProviderTrustTier,
)
from rig_relay.runtime.stream_types import (
    RuntimeCompletionEvent,
    RuntimeFailureEvent,
    RuntimeHeartbeatEvent,
    RuntimeStatusEvent,
    RuntimeStreamEvent,
    RuntimeStreamEventKind,
    RuntimeStreamWarningKind,
    RuntimeWarningEvent,
)
from rig_relay.runtime.supervisor import RuntimeSupervisor

PYTHON = sys.executable


def _request(**overrides: object) -> ExecutionRequest:
    kwargs: dict[str, object] = {
        "request_id": "req-sup-001",
        "argv": [PYTHON, "-c", "print('hello')"],
        "cwd": str(Path.cwd()),
        "timeout_ms": 15000,
        "purpose": "Test supervisor execution",
    }
    kwargs.update(overrides)
    return ExecutionRequest(**kwargs)  # type: ignore[arg-type]


def _make_lease(
    request: ExecutionRequest,
    status: ExecutionLeaseStatus = ExecutionLeaseStatus.ACTIVE,
    expires_delta: timedelta | None = None,
) -> ExecutionLease:
    """Create a lease for testing. Default: active, expires 1 hour from now."""
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
    """Helper to collect all events from an execution."""
    events: list[RuntimeStreamEvent] = []
    async for event in supervisor.execute(lease):
        events.append(event)
    return events


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _patch_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Work in a temporary directory for all tests."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def lease_store(tmp_path: Path) -> ExecutionLeaseStore:
    return ExecutionLeaseStore(tmp_path / "leases")


# ── Lease validation tests ────────────────────────────────────────────


class TestLeaseValidation:
    async def test_inactive_lease_refused(
        self, lease_store: ExecutionLeaseStore
    ) -> None:
        req = _request()
        lease = _make_lease(req, status=ExecutionLeaseStatus.PENDING)
        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)
        assert len(events) == 1
        evt = events[0]
        assert isinstance(evt, RuntimeFailureEvent)
        assert evt.status == RuntimeInvocationStatus.BLOCKED
        assert evt.error_kind == "lease_inactive"

    async def test_expired_lease_refused(
        self, lease_store: ExecutionLeaseStore
    ) -> None:
        req = _request()
        lease = _make_lease(
            req,
            status=ExecutionLeaseStatus.ACTIVE,
            expires_delta=timedelta(seconds=-10),
        )
        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)
        assert len(events) == 1
        evt = events[0]
        assert isinstance(evt, RuntimeFailureEvent)
        assert evt.status == RuntimeInvocationStatus.BLOCKED
        assert evt.error_kind == "lease_expired"

    async def test_invalid_expiry_refused(
        self, lease_store: ExecutionLeaseStore
    ) -> None:
        req = _request()
        now_str = datetime.now(UTC).isoformat()
        lease = ExecutionLease(
            lease_id=req.request_id,
            request=req,
            acquired_at=now_str,
            expires_at="not-a-date",
            status=ExecutionLeaseStatus.ACTIVE,
        )
        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)
        assert len(events) == 1
        evt = events[0]
        assert isinstance(evt, RuntimeFailureEvent)
        assert evt.status == RuntimeInvocationStatus.BLOCKED
        assert evt.error_kind == "invalid_expiry"


# ── CWD resolution tests ──────────────────────────────────────────────


class TestCwdResolution:
    async def test_nonexistent_cwd_refused(
        self, lease_store: ExecutionLeaseStore
    ) -> None:
        req = _request(cwd="/nonexistent/path/xyz123")
        lease = _make_lease(req)
        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)
        assert len(events) == 1
        evt = events[0]
        assert isinstance(evt, RuntimeFailureEvent)
        assert evt.error_kind == "cwd_not_found"


# ── Successful execution tests ────────────────────────────────────────


class TestSuccessfulExecution:
    async def test_simple_stdout(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(argv=[PYTHON, "-c", "print('hello world')"], cwd=str(tmp_path))
        lease = _make_lease(req)
        # Acquire lease in store so release has something to release
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        # Events should be: STATUS(starting), STATUS(running), chunks..., COMPLETION
        assert len(events) >= 3
        assert isinstance(events[0], RuntimeStatusEvent)
        assert events[0].status == RuntimeInvocationStatus.STARTING
        assert isinstance(events[1], RuntimeStatusEvent)
        assert events[1].status == RuntimeInvocationStatus.RUNNING

        # Last event should be completion
        last = events[-1]
        assert isinstance(last, RuntimeCompletionEvent)
        assert last.status == RuntimeInvocationStatus.SUCCEEDED
        assert last.exit_code == 0
        assert last.stdout_bytes > 0
        assert last.stderr_bytes == 0

    async def test_no_shell(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Verify that shell operators are NOT interpreted (no shell=True)."""
        req = _request(
            argv=[PYTHON, "-c", "import sys; print(sys.argv)"], cwd=str(tmp_path)
        )
        lease = _make_lease(req)
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        last = events[-1]
        assert isinstance(last, RuntimeCompletionEvent)
        assert last.status == RuntimeInvocationStatus.SUCCEEDED

    async def test_cwd_resolved_from_worktree_path(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """worktree_path takes priority over cwd."""
        req = _request(
            argv=[PYTHON, "-c", "import os; print(os.getcwd())"],
            cwd=str(tmp_path / "should_not_exist"),
            worktree_path=str(tmp_path),
        )
        lease = _make_lease(req)
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        last = events[-1]
        assert isinstance(last, RuntimeCompletionEvent)
        assert last.status == RuntimeInvocationStatus.SUCCEEDED

    async def test_env_overlay(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "import os; print(os.environ['MY_TEST_VAR'])"],
            cwd=str(tmp_path),
            env_overlay={"MY_TEST_VAR": "hello_from_supervisor"},
        )
        lease = _make_lease(req)
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        last = events[-1]
        assert isinstance(last, RuntimeCompletionEvent)
        assert last.status == RuntimeInvocationStatus.SUCCEEDED


# ── Output cap tests ──────────────────────────────────────────────────


class TestOutputCap:
    async def test_small_output_not_truncated(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(argv=[PYTHON, "-c", "print('x' * 100)"], cwd=str(tmp_path))
        lease = _make_lease(req)
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store, max_stdout_bytes=500)
        events = await _collect_events(supervisor, lease)

        last = events[-1]
        assert isinstance(last, RuntimeCompletionEvent)
        assert last.stdout_truncated is False
        assert last.stdout_bytes == 101  # 100 + newline

    async def test_large_output_truncated(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Output larger than max_stdout_bytes should set truncated flag."""
        req = _request(argv=[PYTHON, "-c", "print('x' * 5000)"], cwd=str(tmp_path))
        lease = _make_lease(req)
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store, max_stdout_bytes=100)
        events = await _collect_events(supervisor, lease)

        last = events[-1]
        assert isinstance(last, RuntimeCompletionEvent)
        assert last.stdout_truncated is True
        # Total bytes should reflect full output, not capped
        assert last.stdout_bytes > 100


# ── Non-zero exit tests ───────────────────────────────────────────────


class TestNonZeroExit:
    async def test_failed_exit_code(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "import sys; sys.exit(42)"], cwd=str(tmp_path)
        )
        lease = _make_lease(req)
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        last = events[-1]
        assert isinstance(last, RuntimeCompletionEvent)
        assert last.status == RuntimeInvocationStatus.FAILED
        assert last.exit_code == 42


# ── Timeout tests ─────────────────────────────────────────────────────


class TestTimeout:
    async def test_slow_command_timed_out(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Command that sleeps beyond timeout should produce TIMED_OUT failure."""
        req = _request(
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

        last = events[-1]
        assert isinstance(last, RuntimeFailureEvent)
        assert last.status == RuntimeInvocationStatus.TIMED_OUT
        assert last.error_kind == "timeout"


# ── Command not found tests ───────────────────────────────────────────


class TestCommandNotFound:
    async def test_nonexistent_command(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(argv=["/nonexistent/command_xyz"], cwd=str(tmp_path))
        lease = _make_lease(req)
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        assert len(events) >= 1
        last = events[-1]
        assert isinstance(last, RuntimeFailureEvent)
        assert last.error_kind == "command_not_found"


# ── Lease release tests ───────────────────────────────────────────────


class TestLeaseRelease:
    async def test_lease_released_on_success(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(argv=[PYTHON, "-c", "print('ok')"], cwd=str(tmp_path))
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        await _collect_events(supervisor, lease)

        # Lease should now be released
        stored = lease_store.read(lease.lease_id)
        assert stored is not None
        assert stored.status == ExecutionLeaseStatus.RELEASED


# ── Content-light summary tests ───────────────────────────────────────


class TestContentLight:
    async def test_completion_no_raw_output(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Completion events must not contain raw stdout/stderr text."""
        req = _request(argv=[PYTHON, "-c", "print('secret data')"], cwd=str(tmp_path))
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        for evt in events:
            dumped = evt.model_dump(mode="json")
            if isinstance(evt, (RuntimeCompletionEvent, RuntimeFailureEvent)):
                # These must not contain raw output content
                assert "chunk_text" not in dumped or dumped["chunk_text"] is None
                assert "stdout" not in dumped  # only stdout_* keys
                assert "stderr" not in dumped

    async def test_failure_no_raw_output(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "print('x'); import sys; sys.exit(1)"],
            cwd=str(tmp_path),
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)

        last = events[-1]
        assert isinstance(last, RuntimeCompletionEvent)
        assert last.status == RuntimeInvocationStatus.FAILED
        dumped = last.model_dump(mode="json")
        assert "chunk_text" not in dumped or dumped["chunk_text"] is None
        assert "stdout" not in dumped
        assert "stderr" not in dumped


class TestGovernanceGate:
    async def test_no_capability_execution_allowed(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "print('ok')"],
            cwd=str(tmp_path),
            requested_capabilities=[],
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        engine = GovernanceEngine()
        supervisor = RuntimeSupervisor(
            lease_store=lease_store, governance_engine=engine
        )
        events = await _collect_events(supervisor, lease)
        last = events[-1]
        assert isinstance(last, RuntimeCompletionEvent)
        assert last.status == RuntimeInvocationStatus.SUCCEEDED

    async def test_mutation_requires_review(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "print('mutate')"],
            cwd=str(tmp_path),
            requested_capabilities=[RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        engine = GovernanceEngine()
        supervisor = RuntimeSupervisor(
            lease_store=lease_store, governance_engine=engine, allow_mutation=False
        )
        events = await _collect_events(supervisor, lease)
        assert len(events) == 1
        evt = events[0]
        assert isinstance(evt, RuntimeFailureEvent)
        assert evt.status == RuntimeInvocationStatus.BLOCKED
        assert evt.error_kind == "requires_review"

    async def test_mutation_allowed_when_allow_mutation_true(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "print('mutate allowed')"],
            cwd=str(tmp_path),
            requested_capabilities=[RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        engine = GovernanceEngine()
        supervisor = RuntimeSupervisor(
            lease_store=lease_store, governance_engine=engine, allow_mutation=True
        )
        events = await _collect_events(supervisor, lease)
        last = events[-1]
        assert isinstance(last, RuntimeCompletionEvent)
        assert last.status == RuntimeInvocationStatus.SUCCEEDED

    async def test_network_requires_review(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "print('no net')"],
            cwd=str(tmp_path),
            requested_capabilities=[RuntimeCapabilityKind.NETWORK_FETCH_PROPOSAL],
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        engine = GovernanceEngine()
        supervisor = RuntimeSupervisor(
            lease_store=lease_store, governance_engine=engine, allow_network=False
        )
        events = await _collect_events(supervisor, lease)
        assert len(events) == 1
        evt = events[0]
        assert isinstance(evt, RuntimeFailureEvent)
        assert evt.status == RuntimeInvocationStatus.BLOCKED
        assert evt.error_kind == "requires_review"

    async def test_blocked_provider_trust_tier(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(argv=[PYTHON, "-c", "print('blocked')"], cwd=str(tmp_path))
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        engine = GovernanceEngine()
        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            governance_engine=engine,
            provider_trust_tier=RuntimeProviderTrustTier.BLOCKED,
        )
        events = await _collect_events(supervisor, lease)
        assert len(events) == 1
        evt = events[0]
        assert isinstance(evt, RuntimeFailureEvent)
        assert evt.status == RuntimeInvocationStatus.BLOCKED

    async def test_blocked_provider_status(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "print('blocked status')"],
            cwd=str(tmp_path),
            requested_capabilities=[RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        engine = GovernanceEngine()
        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            governance_engine=engine,
            provider_status=RuntimeProviderStatus.BLOCKED,
        )
        events = await _collect_events(supervisor, lease)
        assert len(events) == 1
        evt = events[0]
        assert isinstance(evt, RuntimeFailureEvent)
        assert evt.status == RuntimeInvocationStatus.BLOCKED

    async def test_governance_blocked_event_is_content_light(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "print('secret')"],
            cwd=str(tmp_path),
            requested_capabilities=[RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        engine = GovernanceEngine()
        supervisor = RuntimeSupervisor(
            lease_store=lease_store, governance_engine=engine, allow_mutation=False
        )
        events = await _collect_events(supervisor, lease)
        assert len(events) == 1
        evt = events[0]
        assert isinstance(evt, RuntimeFailureEvent)
        dumped = evt.model_dump(mode="json")
        # No raw output in failure events
        assert "chunk_text" not in dumped or dumped["chunk_text"] is None
        assert "stdout" not in dumped
        assert "stderr" not in dumped
        assert dumped["error_kind"] in {"governance_blocked", "requires_review"}

    async def test_governance_blocked_releases_lease(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "print('x')"],
            cwd=str(tmp_path),
            requested_capabilities=[RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease
        lease_id = lease.lease_id

        engine = GovernanceEngine()
        supervisor = RuntimeSupervisor(
            lease_store=lease_store, governance_engine=engine, allow_mutation=False
        )
        await _collect_events(supervisor, lease)

        # Lease should be released
        stored = lease_store.read(lease_id)
        assert stored is not None
        assert stored.status == ExecutionLeaseStatus.RELEASED


class TestHeartbeatEmission:
    """Tests for RuntimeSupervisor heartbeat emission."""

    async def test_heartbeat_emitted_during_long_running(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(1.5)"],
            cwd=str(tmp_path),
            timeout_ms=10000,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store, heartbeat_interval_ms=100
        )
        events = await _collect_events(supervisor, lease)
        heartbeats = [
            e for e in events if e.event_kind == RuntimeStreamEventKind.HEARTBEAT
        ]
        assert len(heartbeats) >= 3, f"Expected >=3 heartbeats, got {len(heartbeats)}"

    async def test_heartbeat_disabled_when_interval_zero(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(0.3)"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store, heartbeat_interval_ms=0)
        events = await _collect_events(supervisor, lease)
        heartbeats = [
            e for e in events if e.event_kind == RuntimeStreamEventKind.HEARTBEAT
        ]
        assert len(heartbeats) == 0

    async def test_heartbeat_stops_after_completion(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "print('done')"], cwd=str(tmp_path), timeout_ms=5000
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store, heartbeat_interval_ms=50
        )
        events = await _collect_events(supervisor, lease)
        # Verify no heartbeats after terminal event
        last_event = events[-1]
        assert isinstance(last_event, (RuntimeCompletionEvent, RuntimeFailureEvent))
        assert last_event.event_kind != RuntimeStreamEventKind.HEARTBEAT

    async def test_heartbeat_contains_correct_ids(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(0.5)"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease
        lease_id = lease.lease_id
        request_id = lease.request.request_id

        supervisor = RuntimeSupervisor(
            lease_store=lease_store, heartbeat_interval_ms=100
        )
        events = await _collect_events(supervisor, lease)
        heartbeats = [
            e for e in events if e.event_kind == RuntimeStreamEventKind.HEARTBEAT
        ]
        assert len(heartbeats) >= 1
        hb = heartbeats[0]
        assert isinstance(hb, RuntimeHeartbeatEvent)
        assert hb.lease_id == lease_id
        assert hb.request_id == request_id
        assert hb.elapsed_ms >= 0

    async def test_heartbeat_and_chunks_coexist(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "import time; print('a'); time.sleep(0.5); print('b')"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store, heartbeat_interval_ms=100
        )
        events = await _collect_events(supervisor, lease)
        heartbeats = [
            e for e in events if e.event_kind == RuntimeStreamEventKind.HEARTBEAT
        ]
        chunks = [
            e
            for e in events
            if e.event_kind
            in (
                RuntimeStreamEventKind.STDOUT_CHUNK,
                RuntimeStreamEventKind.STDERR_CHUNK,
            )
        ]
        assert len(heartbeats) >= 1
        assert len(chunks) >= 1
        for evt in events:
            assert hasattr(evt, "schema_version")

    async def test_heartbeat_stops_after_timeout(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(10)"],
            cwd=str(tmp_path),
            timeout_ms=500,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store, heartbeat_interval_ms=50
        )
        events = await _collect_events(supervisor, lease)
        last_event = events[-1]
        assert isinstance(last_event, RuntimeFailureEvent)
        assert last_event.status == RuntimeInvocationStatus.TIMED_OUT
        assert last_event.event_kind != RuntimeStreamEventKind.HEARTBEAT


class TestStallDetection:
    """Tests for RuntimeSupervisor stall detection."""

    async def test_stall_warning_emitted_for_no_output(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(1.0)"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=50,
            stall_warning_after_ms=200,
            stall_check_interval_ms=100,
        )
        events = await _collect_events(supervisor, lease)
        stall_warnings = [
            e
            for e in events
            if isinstance(e, RuntimeWarningEvent)
            and e.warning_kind == RuntimeStreamWarningKind.STALL_DETECTED.value
        ]
        assert len(stall_warnings) >= 1, (
            f"Expected >=1 stall warning, got {len(stall_warnings)}. "
            f"Events: {[e.event_kind.value for e in events]}"
        )

    async def test_stall_warning_not_emitted_when_output_arrives(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[
                PYTHON,
                "-c",
                "import time; print('tick'); time.sleep(0.3); print('tock')",
            ],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=50,
            stall_warning_after_ms=1000,
            stall_check_interval_ms=100,
        )
        events = await _collect_events(supervisor, lease)
        stall_warnings = [
            e
            for e in events
            if isinstance(e, RuntimeWarningEvent)
            and e.warning_kind == RuntimeStreamWarningKind.STALL_DETECTED.value
        ]
        assert len(stall_warnings) == 0

    async def test_stall_warning_does_not_prevent_completion(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(0.5); print('done')"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=50,
            stall_warning_after_ms=150,
            stall_check_interval_ms=100,
        )
        events = await _collect_events(supervisor, lease)
        last_event = events[-1]
        assert isinstance(last_event, RuntimeCompletionEvent)

    async def test_stall_warning_no_spam(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(1.5)"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=50,
            stall_warning_after_ms=200,
            stall_check_interval_ms=100,
        )
        events = await _collect_events(supervisor, lease)
        stall_warnings = [
            e
            for e in events
            if isinstance(e, RuntimeWarningEvent)
            and e.warning_kind == RuntimeStreamWarningKind.STALL_DETECTED.value
        ]
        assert len(stall_warnings) <= 12, (
            f"Expected <=12 stall warnings (rate-limited to 1 per 200ms), got {len(stall_warnings)}"
        )


class TestHeartbeatAndTimeout:
    """Tests that timeout/cancellation still work with heartbeat enabled."""

    async def test_timeout_with_heartbeat(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(10)"],
            cwd=str(tmp_path),
            timeout_ms=300,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store, heartbeat_interval_ms=50
        )
        events = await _collect_events(supervisor, lease)
        last_event = events[-1]
        assert isinstance(last_event, RuntimeFailureEvent)
        assert last_event.status == RuntimeInvocationStatus.TIMED_OUT
        dumped = last_event.model_dump(mode="json")
        assert "stdout" not in dumped
        assert "stderr" not in dumped
        assert "content" not in dumped

    async def test_final_events_content_light_with_heartbeat(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        req = _request(
            argv=[PYTHON, "-c", "print('hello world')"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store, heartbeat_interval_ms=50
        )
        events = await _collect_events(supervisor, lease)
        terminal = events[-1]
        assert isinstance(terminal, (RuntimeCompletionEvent, RuntimeFailureEvent))
        dumped = terminal.model_dump(mode="json")
        assert "stdout" not in dumped
        assert "stderr" not in dumped
        assert "content" not in dumped


class TestAuditIntegration:
    """Tests for optional audit trail integration in RuntimeSupervisor."""

    async def test_supervisor_without_audit_store_unchanged(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Supervisor without audit store behaves identically to before."""
        req = _request(
            argv=[PYTHON, "-c", "print('no audit')"], cwd=str(tmp_path), timeout_ms=5000
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(lease_store=lease_store)
        events = await _collect_events(supervisor, lease)
        assert len(events) >= 1
        terminal = events[-1]
        assert isinstance(terminal, RuntimeCompletionEvent)
        assert terminal.exit_code == 0

    async def test_successful_execution_appends_audit(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Successful execution appends one audit event with completed decision."""
        audit_path = tmp_path / "audit.jsonl"
        audit_store = AuditTrailStore(audit_path)

        req = _request(
            argv=[PYTHON, "-c", "print('audit me')"], cwd=str(tmp_path), timeout_ms=5000
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store, audit_trail_store=audit_store
        )
        events = await _collect_events(supervisor, lease)
        terminal = events[-1]
        assert isinstance(terminal, RuntimeCompletionEvent)
        assert terminal.status == RuntimeInvocationStatus.SUCCEEDED

        # Audit store should have one event
        audit_events, errors = audit_store.read_events()
        assert len(errors) == 0
        assert len(audit_events) == 1
        audit_event = audit_events[0]
        assert audit_event.action == AuditActionKind.EXECUTION_COMPLETED
        assert audit_event.decision == AuditDecisionKind.COMPLETED

        # Content-light: envelope should have hashes, not raw data
        assert audit_event.envelope is not None
        envelope = audit_event.envelope
        assert envelope.output is not None
        assert envelope.output.output_sha256 is not None
        assert envelope.output.output_bytes is not None
        assert "stdout" not in envelope.model_dump(mode="json")

    async def test_nonzero_exit_appends_failed_audit(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Non-zero exit code appends audit event with failed decision."""
        audit_path = tmp_path / "audit.jsonl"
        audit_store = AuditTrailStore(audit_path)

        req = _request(
            argv=[PYTHON, "-c", "import sys; sys.exit(1)"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store, audit_trail_store=audit_store
        )
        events = await _collect_events(supervisor, lease)
        terminal = events[-1]
        assert isinstance(terminal, RuntimeCompletionEvent)
        assert terminal.status == RuntimeInvocationStatus.FAILED

        audit_events, errors = audit_store.read_events()
        assert len(errors) == 0
        assert len(audit_events) == 1
        assert audit_events[0].decision == AuditDecisionKind.FAILED

    async def test_timeout_appends_failed_audit(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Timeout terminal event appends audit event with failed decision."""
        audit_path = tmp_path / "audit.jsonl"
        audit_store = AuditTrailStore(audit_path)

        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(10)"],
            cwd=str(tmp_path),
            timeout_ms=200,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store, audit_trail_store=audit_store
        )
        events = await _collect_events(supervisor, lease)
        terminal = events[-1]
        assert isinstance(terminal, RuntimeFailureEvent)
        assert terminal.status == RuntimeInvocationStatus.TIMED_OUT

        audit_events, errors = audit_store.read_events()
        assert len(errors) == 0
        assert len(audit_events) == 1
        assert audit_events[0].decision == AuditDecisionKind.FAILED

    async def test_audit_event_has_no_raw_stdout_stderr(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Audit event contains only hashes/bytes/status, not raw output."""
        audit_path = tmp_path / "audit.jsonl"
        audit_store = AuditTrailStore(audit_path)

        req = _request(
            argv=[PYTHON, "-c", "print('secret data')"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store, audit_trail_store=audit_store
        )
        await _collect_events(supervisor, lease)

        audit_events, errors = audit_store.read_events()
        assert len(errors) == 0
        assert len(audit_events) == 1

        dumped = audit_events[0].model_dump(mode="json")
        assert "stdout" not in dumped
        assert "stderr" not in dumped
        assert "content" not in dumped
        assert "chunk_text" not in dumped
        assert "secret data" not in str(dumped)

    async def test_audit_actor_respected(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Audit actor is included in the envelope when provided."""
        from rig_relay.evidence.receipt_envelope import ReceiptActor, ReceiptActorKind

        audit_path = tmp_path / "audit.jsonl"
        audit_store = AuditTrailStore(audit_path)

        audit_actor = ReceiptActor(
            actor_id="test-agent",
            actor_kind=ReceiptActorKind.AGENT,
            display_name="Test Agent",
            is_authoritative=False,
        )

        req = _request(
            argv=[PYTHON, "-c", "print('hello')"], cwd=str(tmp_path), timeout_ms=5000
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            audit_trail_store=audit_store,
            audit_actor=audit_actor,
        )
        await _collect_events(supervisor, lease)

        audit_events, errors = audit_store.read_events()
        assert len(errors) == 0
        assert len(audit_events) == 1
        assert audit_events[0].actor is not None
        assert audit_events[0].actor.actor_id == "test-agent"
        assert audit_events[0].actor.actor_kind == ReceiptActorKind.AGENT

    async def test_audit_append_failure_does_not_hide_terminal(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """If audit append fails, terminal event is still emitted."""
        # Use a store pointing at a path where parent is a file, triggering failure
        parent_file = tmp_path / "blocking_file"
        parent_file.write_text("")
        bad_store = AuditTrailStore(parent_file / "audit.jsonl")

        req = _request(
            argv=[PYTHON, "-c", "print('ignore audit failure')"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        store_result = lease_store.acquire(req, ttl_seconds=3600)
        assert store_result.lease is not None
        lease = store_result.lease

        supervisor = RuntimeSupervisor(
            lease_store=lease_store, audit_trail_store=bad_store
        )
        events = await _collect_events(supervisor, lease)
        # Terminal event should be present (audit failure yields warning AFTER terminal)
        terminal_events = [
            e
            for e in events
            if isinstance(e, (RuntimeCompletionEvent, RuntimeFailureEvent))
        ]
        assert len(terminal_events) >= 1
        assert terminal_events[-1].exit_code == 0
        # A warning about audit failure should be emitted
        audit_warnings = [
            e
            for e in events
            if isinstance(e, RuntimeWarningEvent)
            and e.warning_kind == "audit_append_failed"
        ]
        assert len(audit_warnings) >= 1
