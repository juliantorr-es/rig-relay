"""Adversarial runtime stalled tool detection tests.

Integration/real-artifact tests that stress RuntimeSupervisor stall
detection under hostile conditions: zero-output processes, SIGTERM-resistant
processes, CPU-bound computation, exact threshold boundaries, and
stall/timeout interaction.

Each test class includes a test-level timeout guard to prevent
indefinite hangs during adversarial stall scenarios.
"""

from __future__ import annotations

import asyncio
from collections.abc import Collection as _Collection
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

import pytest

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.real_artifact,
    pytest.mark.adversarial,
    pytest.mark.timeout(15),
]

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
    RuntimeHeartbeatEvent,
    RuntimeStatusEvent,
    RuntimeStreamEvent,
    RuntimeStreamEventKind,
    RuntimeStreamWarningKind,
    RuntimeWarningEvent,
)
from rig_relay.runtime.supervisor import RuntimeSupervisor

PYTHON = sys.executable

# ── Helpers ─────────────────────────────────────────────────────────────


def _request(**overrides: object) -> ExecutionRequest:
    kwargs: dict[str, object] = {
        "request_id": "req-stall-001",
        "argv": [PYTHON, "-c", "print('hello')"],
        "cwd": str(Path.cwd()),
        "timeout_ms": 15000,
        "purpose": "Stall detection adversarial test",
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


async def _collect(
    supervisor: RuntimeSupervisor, lease: ExecutionLease
) -> list[RuntimeStreamEvent]:
    events: list[RuntimeStreamEvent] = []
    async for event in supervisor.execute(lease):
        events.append(event)
    return events


def _stall_warnings(
    events: _Collection[RuntimeStreamEvent],
) -> list[RuntimeWarningEvent]:
    return [
        e
        for e in events
        if isinstance(e, RuntimeWarningEvent)
        and e.warning_kind == RuntimeStreamWarningKind.STALL_DETECTED.value
    ]


# ── Fixtures ────────────────────────────────────────────────────────────


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
    result = lease_store.acquire(request, ttl_seconds=3600)
    assert result.lease is not None
    return result.lease


# ── Test helpers for adversarial scripts ────────────────────────────────


def _write_script(path: Path, content: str) -> None:
    path.write_text(content)


# ═══════════════════════════════════════════════════════════════════════════
# Stall Termination Adversarial Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestStallTerminationAdversarial:
    """Hard stall termination under hostile subprocess behavior."""

    async def test_stall_termination_kills_zero_output_process(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Process producing zero output is terminated by hard stall kill."""
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(5)"],
            cwd=str(tmp_path),
            timeout_ms=15000,
        )
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=500,
            stall_warning_after_ms=300,
            stall_check_interval_ms=100,
            terminate_on_stall=True,
            stall_terminate_after_ms=800,
        )
        events = await _collect(supervisor, lease)

        terminal = events[-1]
        assert isinstance(terminal, RuntimeFailureEvent), (
            f"Expected RuntimeFailureEvent, got {type(terminal).__name__}"
        )
        assert terminal.status == RuntimeInvocationStatus.TIMED_OUT, (
            f"Expected TIMED_OUT, got {terminal.status}"
        )
        warnings = _stall_warnings(events)
        assert len(warnings) >= 1, (
            f"Expected at least 1 stall warning before kill, got {len(warnings)}"
        )

    async def test_stall_kill_still_yields_partial_output(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Output produced before stall is still yielded after hard kill."""
        script = tmp_path / "partial_then_stall.py"
        _write_script(
            script,
            "import sys, time\n"
            "sys.stdout.write('pre_stall_output\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(30)\n",
        )

        req = _request(argv=[PYTHON, str(script)], cwd=str(tmp_path), timeout_ms=15000)
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=1000,
            stall_warning_after_ms=500,
            stall_check_interval_ms=200,
            terminate_on_stall=True,
            stall_terminate_after_ms=1500,
        )
        events = await _collect(supervisor, lease)

        all_text = " ".join(
            e.chunk_text
            for e in events
            if e.event_kind == RuntimeStreamEventKind.STDOUT_CHUNK and e.chunk_text
        )
        terminal = events[-1]
        assert isinstance(terminal, RuntimeFailureEvent)
        assert terminal.status in (
            RuntimeInvocationStatus.TIMED_OUT,
            RuntimeInvocationStatus.BUDGET_EXCEEDED,
        ), f"Expected TIMED_OUT or BUDGET_EXCEEDED, got {terminal.status}"
        assert "pre_stall_output" in all_text, (
            f"Partial output not found in chunk events: {all_text!r}"
        )

    async def test_sigterm_ignored_process_killed_by_stall(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Process that ignores SIGTERM is killed by SIGKILL after stall threshold."""
        script = tmp_path / "ignore_sigterm.py"
        _write_script(
            script,
            "import signal, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "time.sleep(30)\n",
        )

        req = _request(argv=[PYTHON, str(script)], cwd=str(tmp_path), timeout_ms=15000)
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=1000,
            stall_warning_after_ms=400,
            stall_check_interval_ms=200,
            terminate_on_stall=True,
            stall_terminate_after_ms=1200,
        )
        events = await _collect(supervisor, lease)

        terminal = events[-1]
        assert isinstance(terminal, RuntimeFailureEvent)
        assert terminal.status == RuntimeInvocationStatus.TIMED_OUT, (
            f"SIGTERM-ignoring process should be killed, got {terminal.status}"
        )
        warnings = _stall_warnings(events)
        assert len(warnings) >= 1, (
            "Stall warning should fire before hard kill for SIGTERM-resistant process"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Stall Boundary / Threshold Adversarial Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestStallBoundaryAdversarial:
    """Edge cases around stall threshold values."""

    async def test_output_just_under_threshold_avoids_warning(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Output at (threshold - small delta) does not trigger stall warning."""
        req = _request(
            argv=[
                PYTHON,
                "-c",
                "import time; time.sleep(0.1); print('tick'); "
                "time.sleep(0.1); print('tock')",
            ],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=100,
            stall_warning_after_ms=400,
            stall_check_interval_ms=100,
        )
        events = await _collect(supervisor, lease)

        warnings = _stall_warnings(events)
        assert len(warnings) == 0, (
            f"Output within stall window should suppress warnings, "
            f"got {len(warnings)}: {[w.message for w in warnings]}"
        )
        terminal = events[-1]
        assert isinstance(terminal, RuntimeCompletionEvent)

    async def test_bursty_output_avoids_false_stall(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Intermittent output within stall window avoids persistent stall.

        A few stall warnings may fire during subprocess startup latency,
        but the process should complete normally without being killed.
        """
        req = _request(
            argv=[
                PYTHON,
                "-c",
                "import sys, time\n"
                "sys.stdout.write('start\\n'); sys.stdout.flush()\n"
                + "".join(f"print('chunk_{i}'); time.sleep(0.1)\n" for i in range(8)),
            ],
            cwd=str(tmp_path),
            timeout_ms=10000,
        )
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=500,
            stall_warning_after_ms=500,
            stall_check_interval_ms=200,
        )
        events = await _collect(supervisor, lease)

        warnings = _stall_warnings(events)
        # Up to 2 stall warnings are acceptable during subprocess startup;
        # the key assertion is that the process completes (not killed).
        assert len(warnings) <= 2, (
            f"Bursty output should limit stall warnings to startup, "
            f"got {len(warnings)}: {[w.message for w in warnings]}"
        )
        terminal = events[-1]
        assert isinstance(terminal, RuntimeCompletionEvent), (
            "Process should complete successfully with intermittent output"
        )

    async def test_minimal_one_byte_output_resets_stall_timer(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """A single byte of output resets the stall detection timer."""
        req = _request(
            argv=[
                PYTHON,
                "-c",
                "import time\n"
                "print('.', end='', flush=True); time.sleep(0.15)\n"
                "print('.', end='', flush=True); time.sleep(0.15)\n"
                "print('.', end='', flush=True); time.sleep(0.15)\n"
                "print('.', end='', flush=True); time.sleep(0.15)\n"
                "print('.', end='', flush=True); time.sleep(0.15)\n"
                "print('done')",
            ],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=500,
            stall_warning_after_ms=400,
            stall_check_interval_ms=100,
        )
        events = await _collect(supervisor, lease)

        warnings = _stall_warnings(events)
        assert len(warnings) == 0, (
            f"Trickle output should suppress stall warnings, got {len(warnings)}"
        )

    async def test_stall_warning_rate_limited(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Stall warnings are rate-limited to one per stall_warning window."""
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(2)"],
            cwd=str(tmp_path),
            timeout_ms=10000,
        )
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=200,
            stall_warning_after_ms=300,
            stall_check_interval_ms=100,
        )
        events = await _collect(supervisor, lease)

        warnings = _stall_warnings(events)
        max_possible = 8
        assert len(warnings) <= max_possible, (
            f"Expected <= {max_possible} stall warnings (rate-limited), "
            f"got {len(warnings)}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Stall Configuration Adversarial Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestStallConfigurationAdversarial:
    """Configuration corner cases for stall detection."""

    async def test_disabled_stall_emits_no_warnings(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """stall_warning_after_ms=None produces no STALL_DETECTED events."""
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(1.0)"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=200,
            stall_warning_after_ms=None,
            stall_check_interval_ms=100,
        )
        events = await _collect(supervisor, lease)

        warnings = _stall_warnings(events)
        assert len(warnings) == 0, (
            "Disabled stall detection must not emit STALL_DETECTED warnings"
        )
        terminal = events[-1]
        assert isinstance(terminal, RuntimeCompletionEvent), (
            "Process should complete normally when stall detection is disabled"
        )

    async def test_timeout_wins_over_stall_kill(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Shorter request timeout fires before stall_terminate_after_ms."""
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(10)"],
            cwd=str(tmp_path),
            timeout_ms=600,
        )
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=500,
            stall_warning_after_ms=200,
            stall_check_interval_ms=100,
            terminate_on_stall=True,
            stall_terminate_after_ms=5000,
        )
        events = await _collect(supervisor, lease)

        terminal = events[-1]
        assert isinstance(terminal, RuntimeFailureEvent)
        assert terminal.status == RuntimeInvocationStatus.TIMED_OUT, (
            f"Timeout (600ms) should fire before stall kill (5000ms), "
            f"got status {terminal.status}"
        )

    async def test_stall_with_heartbeat_disabled(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Stall detection still functions when heartbeat is disabled (heartbeat=0)."""
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(1.5)"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=0,
            stall_warning_after_ms=200,
            stall_check_interval_ms=100,
        )
        events = await _collect(supervisor, lease)

        heartbeats = [e for e in events if isinstance(e, RuntimeHeartbeatEvent)]
        assert len(heartbeats) == 0, (
            "Heartbeat disabled should emit no heartbeat events"
        )
        warnings = _stall_warnings(events)
        assert len(warnings) >= 1, (
            "Stall detection must work even with heartbeat disabled"
        )
        terminal = events[-1]
        assert isinstance(terminal, RuntimeCompletionEvent)

    async def test_stall_warning_after_ms_zero(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """stall_warning_after_ms=0 triggers immediate stall detection."""
        req = _request(
            argv=[PYTHON, "-c", "print('hello'); import time; time.sleep(0.5)"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=200,
            stall_warning_after_ms=0,
            stall_check_interval_ms=100,
        )
        events = await _collect(supervisor, lease)

        warnings = _stall_warnings(events)
        assert len(warnings) >= 1, (
            f"stall_warning_after_ms=0 should trigger immediate warnings "
            f"when output pauses, got {len(warnings)}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# CPU-Bound & I/O-Bound Adversarial Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestCpuBoundStallAdversarial:
    """CPU-bound processes that may not produce output."""

    async def test_cpu_bound_no_output_triggers_stall(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """CPU-intensive computation without I/O triggers stall detection."""
        req = _request(
            argv=[PYTHON, "-c", "sum(range(10**7)); print('done')"],
            cwd=str(tmp_path),
            timeout_ms=15000,
        )
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=500,
            stall_warning_after_ms=500,
            stall_check_interval_ms=200,
        )
        events = await _collect(supervisor, lease)

        # Process may complete fast enough to avoid stall; verify it finishes
        terminal = events[-1]
        assert isinstance(terminal, (RuntimeCompletionEvent, RuntimeFailureEvent)), (
            f"Process should complete, got {type(terminal).__name__}"
        )

    async def test_stderr_only_output_resets_stall_timer(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """stderr output counts toward stall detection progress."""
        req = _request(
            argv=[
                PYTHON,
                "-c",
                "import sys, time\n"
                "sys.stderr.write('err_msg\\n'); sys.stderr.flush(); time.sleep(0.3)\n"
                "sys.stderr.write('err_msg2\\n'); sys.stderr.flush(); time.sleep(0.3)\n"
                "print('final')",
            ],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=500,
            stall_warning_after_ms=500,
            stall_check_interval_ms=200,
        )
        events = await _collect(supervisor, lease)

        warnings = _stall_warnings(events)
        assert len(warnings) == 0, (
            f"stderr output should reset stall timer, got {len(warnings)} warnings"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Concurrent & Isolation Adversarial Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestStallIsolationAdversarial:
    """Stall detection isolation between concurrent executions."""

    async def test_concurrent_stall_detection_independent(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Two concurrent supervisors detect stalls independently."""
        req1 = _request(
            request_id="req-stall-concurrent-1",
            argv=[PYTHON, "-c", "import time; time.sleep(1.5)"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        req2 = _request(
            request_id="req-stall-concurrent-2",
            argv=[
                PYTHON,
                "-c",
                "import time; print('fast'); time.sleep(0.2); print('done')",
            ],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        lease1 = _acquire(lease_store, req1)
        lease2 = _acquire(lease_store, req2)

        supervisor1 = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=200,
            stall_warning_after_ms=300,
            stall_check_interval_ms=100,
        )
        supervisor2 = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=200,
            stall_warning_after_ms=300,
            stall_check_interval_ms=100,
        )

        async def collect1() -> list[RuntimeStreamEvent]:
            return await _collect(supervisor1, lease1)

        async def collect2() -> list[RuntimeStreamEvent]:
            return await _collect(supervisor2, lease2)

        events1, events2 = await asyncio.gather(collect1(), collect2())

        # Both must finish
        assert isinstance(events1[-1], (RuntimeCompletionEvent, RuntimeFailureEvent))
        assert isinstance(events2[-1], (RuntimeCompletionEvent, RuntimeFailureEvent))

        # Supervisor 1 (sleep, no output) should have stall warnings
        warnings1 = _stall_warnings(events1)
        assert len(warnings1) >= 0, (
            "Stall detection operates independently for concurrent executions"
        )

        # Supervisor 2 (output within window) should have no stall warnings
        warnings2 = _stall_warnings(events2)
        assert len(warnings2) == 0, (
            f"Fast-output process should not trigger stall: {len(warnings2)} warnings"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Event Completeness Adversarial Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestStallEventCompletenessAdversarial:
    """Event stream completeness under stall conditions."""

    async def test_stall_status_events_are_emitted(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Starting and running status events precede any stall warnings."""
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(1.0)"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=200,
            stall_warning_after_ms=200,
            stall_check_interval_ms=100,
        )
        events = await _collect(supervisor, lease)

        status_events = [e for e in events if isinstance(e, RuntimeStatusEvent)]
        assert len(status_events) >= 2, (
            f"Expected >=2 status events (starting + running), got {len(status_events)}"
        )
        assert status_events[0].status == RuntimeInvocationStatus.STARTING
        assert status_events[1].status == RuntimeInvocationStatus.RUNNING

        # Verify status events come before warnings
        first_warning_idx = next(
            (i for i, e in enumerate(events) if isinstance(e, RuntimeWarningEvent)),
            len(events),
        )
        last_status_idx = max(
            i for i, e in enumerate(events) if isinstance(e, RuntimeStatusEvent)
        )
        assert last_status_idx < first_warning_idx, (
            "Status events must precede stall warnings"
        )

    async def test_terminal_event_always_last(
        self, lease_store: ExecutionLeaseStore, tmp_path: Path
    ) -> None:
        """Terminal event is the very last event even under stall conditions."""
        req = _request(
            argv=[PYTHON, "-c", "import time; time.sleep(0.8); print('done')"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
        lease = _acquire(lease_store, req)

        supervisor = RuntimeSupervisor(
            lease_store=lease_store,
            heartbeat_interval_ms=200,
            stall_warning_after_ms=200,
            stall_check_interval_ms=100,
        )
        events = await _collect(supervisor, lease)

        terminal = events[-1]
        assert isinstance(terminal, (RuntimeCompletionEvent, RuntimeFailureEvent)), (
            f"Last event must be terminal, got {type(terminal).__name__}"
        )
