"""Rig Relay RuntimeSupervisor — Ported from Rig domain/runtime_supervisor.py.

Subprocess supervision with bounded output, timeout, cancellation, and
structured stream events. Requires an active ExecutionLease before execution.

Core behavior:
- Accepts an active ExecutionLease with an ExecutionRequest
- Uses asyncio.create_subprocess_exec(*argv) — NO shell, NO shell strings
- Drains stdout/stderr concurrently with bounded buffers
- Emits relay-native RuntimeStreamEvent objects
- Enforces timeout_ms from lease.request.timeout_ms
- Supports cancellation (terminate -> kill)
- Releases lease on terminal events if lease_store is provided
- Content-light completion/failure summaries (hashes, byte counts, truncated flags)

Provenance (Rig-to-Relay porting doctrine):
  Porting status: reimplement (Rig source: rig/domain/runtime_supervisor.py).
  Adaptations: Relay-native Pydantic stream events; lease-gated execution;
  simplified (no forbidden-command lists, no RuntimeProvider integration);
  bounded concurrent drain with hash tracking beyond truncation.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import time

from rig_relay.coordination._canonical_json import dump_canonical_json
from rig_relay.coordination.execution_lease import (
    ExecutionLease,
    ExecutionLeaseStatus,
    ExecutionLeaseStore,
)
from rig_relay.core.tools.security import sanitize_env_for_subprocess
from rig_relay.evidence.audit_trail import (
    AuditActionKind,
    AuditDecisionKind,
    AuditTrailStore,
)
from rig_relay.evidence.receipt_envelope import (
    ReceiptActor,
    ReceiptActorKind,
    ReceiptDecision,
    ReceiptEnvelope,
    ReceiptEvidence,
    ReceiptEvidenceKind,
    ReceiptInput,
    ReceiptOutput,
    ReceiptSubject,
    ReceiptSubjectKind,
    build_receipt_envelope,
)
from rig_relay.governance.decisions import GovernanceDecisionKind
from rig_relay.governance.governance_engine import GovernanceEngine
from rig_relay.runtime.models import (
    RuntimeInvocationStatus,
    RuntimeProviderStatus,
    RuntimeProviderTrustTier,
)
from rig_relay.runtime.stream_types import (
    RuntimeCompletionEvent,
    RuntimeFailureEvent,
    RuntimeHeartbeatEvent,
    RuntimeOutputChunkEvent,
    RuntimeStatusEvent,
    RuntimeStreamEvent,
    RuntimeStreamEventKind,
    RuntimeStreamWarningKind,
    RuntimeWarningEvent,
)
from rig_relay.tracing.models import TraceStatus
from rig_relay.tracing.recorder import TraceRecorder


def _now_str() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _hash_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_argv(argv: list[str]) -> str:
    return "sha256:" + hashlib.sha256("|".join(argv).encode("utf-8")).hexdigest()


class StreamDrainResult:
    """Collects the result of draining a subprocess stream."""

    def __init__(self) -> None:
        self.final_hash: str = _sha256_bytes(b"")
        self.total_bytes: int = 0
        self.truncated: bool = False


async def _drain_stream_collect(
    stream: asyncio.StreamReader,
    stream_name: str,
    max_bytes: int,
    chunk_size: int,
    event_id: str,
    lease_id: str,
    request_id: str,
    result: StreamDrainResult,
    events: list[RuntimeOutputChunkEvent],
    progress: _StreamProgress | None = None,
) -> None:
    """Drain a stream, appending chunk events and writing final stats to *result*.

    Continues SHA256 hashing and byte counting after the cap is reached
    so completion/failure summaries reflect total output even when truncated.

    If *progress* is provided, updates last_output_at on each chunk.
    """
    hasher = hashlib.sha256()
    total_bytes = 0
    chunk_index = 0
    truncated = False

    while True:
        data = await stream.read(chunk_size)
        if not data:
            break

        total_bytes += len(data)
        hasher.update(data)

        # Update progress timestamps for stall detection
        if progress is not None:
            now = datetime.now(UTC)
            progress.last_output_at = now
            if stream_name == "stdout":
                progress.last_stdout_at = now
            else:
                progress.last_stderr_at = now

        # Emit chunk_text only up to the cap
        if not truncated:
            if total_bytes <= max_bytes:
                text = data.decode("utf-8", errors="replace")
                events.append(
                    RuntimeOutputChunkEvent(
                        event_id=f"{event_id}_{stream_name}_{chunk_index}",
                        lease_id=lease_id,
                        request_id=request_id,
                        event_kind=(
                            RuntimeStreamEventKind.STDOUT_CHUNK
                            if stream_name == "stdout"
                            else RuntimeStreamEventKind.STDERR_CHUNK
                        ),
                        captured_at=_now_str(),
                        stream=stream_name,
                        chunk_index=chunk_index,
                        chunk_text=text,
                        chunk_sha256=_sha256_bytes(data),
                        chunk_bytes=len(data),
                        truncated=False,
                    )
                )
            else:
                # First chunk crossing the cap — emit truncated
                truncated = True
                excess = total_bytes - max_bytes
                capped_len = len(data) - excess
                if capped_len > 0:
                    text = data[:capped_len].decode("utf-8", errors="replace")
                    events.append(
                        RuntimeOutputChunkEvent(
                            event_id=f"{event_id}_{stream_name}_{chunk_index}",
                            lease_id=lease_id,
                            request_id=request_id,
                            event_kind=(
                                RuntimeStreamEventKind.STDOUT_CHUNK
                                if stream_name == "stdout"
                                else RuntimeStreamEventKind.STDERR_CHUNK
                            ),
                            captured_at=_now_str(),
                            stream=stream_name,
                            chunk_index=chunk_index,
                            chunk_text=text,
                            chunk_sha256=_sha256_bytes(data),
                            chunk_bytes=len(data),
                            truncated=True,
                        )
                    )

        chunk_index += 1

    result.final_hash = _sha256_bytes(hasher.digest())
    result.total_bytes = total_bytes
    result.truncated = truncated


async def _finalize_subprocess(
    proc: asyncio.subprocess.Process, *, timeout_seconds: float = 5.0
) -> None:
    if proc.returncode is None:
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
            except TimeoutError:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
        except ProcessLookupError:
            pass
    transport = getattr(proc, "_transport", None)
    if transport is not None:
        transport.close()


@dataclass
class _StreamProgress:
    """Tracks output progress for stall detection."""

    start_time: datetime
    last_output_at: datetime
    last_stdout_at: datetime | None = None
    last_stderr_at: datetime | None = None


# ruff: noqa: PLR0911, PLR0912, PLR0913, PLR0914, PLR0915, PLR0917, PLR1702


class RuntimeSupervisor:
    """Supervises a bounded subprocess execution under an active lease.

    Usage:
        supervisor = RuntimeSupervisor(lease_store=store)
        async for event in supervisor.execute(lease):
            # handle event
    """

    def __init__(
        self,
        lease_store: ExecutionLeaseStore | None = None,
        max_stdout_bytes: int = 65536,
        max_stderr_bytes: int = 65536,
        chunk_size: int = 4096,
        heartbeat_interval_ms: int = 1000,
        stall_warning_after_ms: int | None = None,
        stall_check_interval_ms: int = 1000,
        terminate_on_stall: bool = False,
        stall_terminate_after_ms: int | None = None,
        governance_engine: GovernanceEngine | None = None,
        provider_trust_tier: RuntimeProviderTrustTier = RuntimeProviderTrustTier.EXECUTOR_CANDIDATE,
        provider_status: RuntimeProviderStatus = RuntimeProviderStatus.AVAILABLE,
        allow_mutation: bool = False,
        allow_network: bool = False,
        dirty_policy_satisfied: bool = True,
        audit_trail_store: AuditTrailStore | None = None,
        audit_actor: ReceiptActor | None = None,
        trace_recorder: TraceRecorder | None = None,
    ) -> None:
        self._lease_store = lease_store
        self._max_stdout_bytes = max_stdout_bytes
        self._max_stderr_bytes = max_stderr_bytes
        self._chunk_size = chunk_size
        self._heartbeat_interval_ms = heartbeat_interval_ms
        self._stall_warning_after_ms = stall_warning_after_ms
        self._stall_check_interval_ms = stall_check_interval_ms
        self._terminate_on_stall = terminate_on_stall
        self._stall_terminate_after_ms = stall_terminate_after_ms
        self._governance_engine = governance_engine
        self._provider_trust_tier = provider_trust_tier
        self._provider_status = provider_status
        self._allow_mutation = allow_mutation
        self._allow_network = allow_network
        self._dirty_policy_satisfied = dirty_policy_satisfied
        self._audit_trail_store = audit_trail_store
        self._audit_actor = audit_actor
        self._trace_recorder = trace_recorder

    async def execute(self, lease: ExecutionLease) -> AsyncIterator[RuntimeStreamEvent]:
        """Execute the lease's request under supervision.

        Validates lease state, resolves cwd, spawns subprocess, drains
        streams with bounded buffers, enforces timeout, handles cancellation,
        and emits structured events throughout.

        Yields stream events. The final event is always a completion or
        failure event.
        """
        request = lease.request
        lease_id = lease.lease_id
        request_id = request.request_id
        event_base = f"exec_{lease_id}"

        # ── Validate lease ──────────────────────────────────────────
        if lease.status != ExecutionLeaseStatus.ACTIVE:
            yield _make_failure(
                event_base,
                lease_id,
                request_id,
                RuntimeInvocationStatus.BLOCKED,
                "lease_inactive",
                f"Lease status is {lease.status.value}, expected active",
            )
            return

        # Check lease expiry
        try:
            expires = datetime.fromisoformat(lease.expires_at.replace("Z", "+00:00"))
            if expires <= datetime.now(UTC):
                yield _make_failure(
                    event_base,
                    lease_id,
                    request_id,
                    RuntimeInvocationStatus.BLOCKED,
                    "lease_expired",
                    f"Lease expired at {lease.expires_at}",
                )
                return
        except (ValueError, TypeError):
            yield _make_failure(
                event_base,
                lease_id,
                request_id,
                RuntimeInvocationStatus.BLOCKED,
                "invalid_expiry",
                "Lease has invalid expires_at",
            )
            return

        # ── Resolve cwd ─────────────────────────────────────────────
        cwd: str | None = request.worktree_path or request.cwd
        if not cwd:
            yield _make_failure(
                event_base,
                lease_id,
                request_id,
                RuntimeInvocationStatus.BLOCKED,
                "cwd_missing",
                "No working directory specified in request",
            )
            return

        cwd_path = Path(cwd)
        if not cwd_path.is_dir():
            yield _make_failure(
                event_base,
                lease_id,
                request_id,
                RuntimeInvocationStatus.BLOCKED,
                "cwd_not_found",
                f"Cwd directory does not exist: {cwd}",
            )
            return

        recorder = self._trace_recorder
        trace_span = None
        if recorder is not None:
            trace_span = recorder.start_span(
                "runtime.subprocess.execute",
                attributes={
                    "executable": request.argv[0],
                    "argv_hash": _hash_argv(request.argv),
                    "argv_count": len(request.argv),
                    "cwd_hash": _hash_text(cwd),
                    "timeout_seconds": request.timeout_ms / 1000.0,
                    "lease_id": lease_id,
                    "lane_id": request.workspace_id,
                    "shell_used": False,
                },
            )

        def trace_event(name: str, attributes: dict[str, object] | None = None) -> None:
            if recorder is None or trace_span is None:
                return
            recorder.event(name, attributes=attributes)

        def trace_end(
            *,
            status: TraceStatus,
            attributes: dict[str, object] | None = None,
            error: str | None = None,
        ) -> None:
            if recorder is None or trace_span is None:
                return
            recorder.end_span(
                trace_span, status=status, attributes=attributes, error=error
            )

        # ── Governance evaluation ───────────────────────────────────
        if self._governance_engine is not None:
            decision = self._governance_engine.evaluate_action_legality(
                workspace_id=request.workspace_id,
                intent_id=request_id,
                intent_kind="runtime_execution",
                requested_capabilities=request.requested_capabilities,
                provider_trust_tier=self._provider_trust_tier,
                provider_status=self._provider_status,
                allow_mutation=self._allow_mutation,
                allow_network=self._allow_network,
                dirty_policy_satisfied=self._dirty_policy_satisfied,
            )

            if decision.decision == GovernanceDecisionKind.BLOCKED:
                yield _make_failure(
                    event_base,
                    lease_id,
                    request_id,
                    RuntimeInvocationStatus.BLOCKED,
                    "governance_blocked",
                    decision.reasons[0].message
                    if decision.reasons
                    else "Governance blocked",
                )
                await _release_lease(self._lease_store, lease_id)
                trace_end(status=TraceStatus.error, attributes={"status": "blocked"})
                return

            if decision.decision == GovernanceDecisionKind.REQUIRES_REVIEW:
                yield _make_failure(
                    event_base,
                    lease_id,
                    request_id,
                    RuntimeInvocationStatus.BLOCKED,
                    "requires_review",
                    decision.reasons[0].message
                    if decision.reasons
                    else "Governance requires review",
                )
                await _release_lease(self._lease_store, lease_id)
                trace_end(status=TraceStatus.error, attributes={"status": "blocked"})
                return

        # ── Build env ───────────────────────────────────────────────
        # Strip sensitive env vars (API keys, tokens) before passing
        # to the subprocess.
        base_env = sanitize_env_for_subprocess()
        env = {**base_env, **request.env_overlay}

        # ── Emit starting status ────────────────────────────────────
        yield RuntimeStatusEvent(
            event_id=f"{event_base}_starting",
            lease_id=lease_id,
            request_id=request_id,
            event_kind=RuntimeStreamEventKind.STATUS,
            captured_at=_now_str(),
            status=RuntimeInvocationStatus.STARTING,
            message=f"Starting: {' '.join(request.argv)}",
        )
        trace_event(
            "runtime.subprocess.spawn.start",
            attributes={"executable": request.argv[0], "argv_count": len(request.argv)},
        )

        # ── Spawn subprocess ────────────────────────────────────────
        start_time = datetime.now(UTC)

        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *request.argv,
                cwd=str(cwd_path),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            elapsed = (datetime.now(UTC) - start_time).total_seconds() * 1000
            trace_event("runtime.subprocess.spawn.ok", attributes={"spawned": False})
            trace_end(
                status=TraceStatus.error,
                attributes={"status": "failed", "error_kind": "command_not_found"},
            )
            yield _make_failure(
                event_base,
                lease_id,
                request_id,
                RuntimeInvocationStatus.FAILED,
                "command_not_found",
                f"Command not found: {request.argv[0]}",
                elapsed,
            )
            await _release_lease(self._lease_store, lease_id)
            return
        except OSError as e:
            elapsed = (datetime.now(UTC) - start_time).total_seconds() * 1000
            trace_event("runtime.subprocess.spawn.ok", attributes={"spawned": False})
            trace_end(
                status=TraceStatus.error,
                attributes={"status": "failed", "error_kind": "spawn_error"},
            )
            yield _make_failure(
                event_base,
                lease_id,
                request_id,
                RuntimeInvocationStatus.FAILED,
                "spawn_error",
                f"Failed to spawn process: {e}",
                elapsed,
            )
            await _release_lease(self._lease_store, lease_id)
            return

        # ── Emit running status ─────────────────────────────────────
        trace_event(
            "runtime.subprocess.spawn.ok",
            attributes={"spawned": True, "pid": getattr(proc, "pid", None)},
        )
        yield RuntimeStatusEvent(
            event_id=f"{event_base}_running",
            lease_id=lease_id,
            request_id=request_id,
            event_kind=RuntimeStreamEventKind.STATUS,
            captured_at=_now_str(),
            status=RuntimeInvocationStatus.RUNNING,
        )

        # ── Drain stdout/stderr concurrently ────────────────────────
        stdout_result = StreamDrainResult()
        stderr_result = StreamDrainResult()
        chunk_events: list[RuntimeOutputChunkEvent] = []
        progress = _StreamProgress(
            start_time=start_time, last_output_at=datetime.now(UTC)
        )

        async def drain_stdout() -> None:
            assert proc.stdout is not None
            await _drain_stream_collect(
                proc.stdout,
                "stdout",
                self._max_stdout_bytes,
                self._chunk_size,
                event_base,
                lease_id,
                request_id,
                stdout_result,
                chunk_events,
                progress,
            )
            trace_event(
                "runtime.subprocess.stdout.chunk",
                attributes={"stdout_bytes": stdout_result.total_bytes},
            )

        async def drain_stderr() -> None:
            assert proc.stderr is not None
            await _drain_stream_collect(
                proc.stderr,
                "stderr",
                self._max_stderr_bytes,
                self._chunk_size,
                event_base,
                lease_id,
                request_id,
                stderr_result,
                chunk_events,
                progress,
            )
            trace_event(
                "runtime.subprocess.stderr.chunk",
                attributes={"stderr_bytes": stderr_result.total_bytes},
            )

        drain_tasks: list[asyncio.Task[None]] = [
            asyncio.create_task(drain_stdout()),
            asyncio.create_task(drain_stderr()),
        ]

        # ── Poll loop: heartbeat + stall detection + wait ───────────
        timeout_s = request.timeout_ms / 1000.0
        timed_out = False
        cancelled = False
        exit_code: int | None = None

        deadline_ts = start_time.timestamp() + timeout_s
        heartbeat_s = (
            self._heartbeat_interval_ms / 1000.0
            if self._heartbeat_interval_ms > 0
            else 0.0
        )
        stall_warning_s = (
            self._stall_warning_after_ms / 1000.0
            if self._stall_warning_after_ms is not None
            else None
        )
        stall_check_s = self._stall_check_interval_ms / 1000.0

        last_heartbeat_t: float = 0.0
        last_stall_warning_t: float = 0.0
        _heartbeat_counter: int = 0

        try:
            while True:
                now_ts = datetime.now(UTC).timestamp()
                now_mono = time.monotonic()

                # Check timeout
                remaining = deadline_ts - now_ts
                if remaining <= 0:
                    timed_out = True
                    trace_event(
                        "runtime.subprocess.timeout",
                        attributes={"timeout_seconds": timeout_s},
                    )
                    break

                # Check if process already exited
                if proc.returncode is not None:
                    exit_code = proc.returncode
                    break

                # Compute wait interval (min of remaining, heartbeat, stall check)
                check = max(0.01, remaining)
                if heartbeat_s > 0:
                    check = min(check, heartbeat_s)
                if stall_warning_s is not None:
                    check = min(check, stall_check_s)

                # Wait for process exit (or timeout)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=check)
                    exit_code = proc.returncode
                    break
                except TimeoutError:
                    pass

                # ── Emit heartbeat ───────────────────────────────────
                if heartbeat_s > 0 and (now_mono - last_heartbeat_t) >= heartbeat_s:
                    _heartbeat_counter += 1
                    elapsed_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
                    yield RuntimeHeartbeatEvent(
                        event_id=f"{event_base}_heartbeat_{_heartbeat_counter}",
                        lease_id=lease_id,
                        request_id=request_id,
                        event_kind=RuntimeStreamEventKind.HEARTBEAT,
                        captured_at=_now_str(),
                        elapsed_ms=elapsed_ms,
                    )
                    last_heartbeat_t = now_mono

                # ── Stall detection ──────────────────────────────────
                if stall_warning_s is not None:
                    stall_elapsed = (
                        datetime.now(UTC) - progress.last_output_at
                    ).total_seconds()
                    if stall_elapsed >= stall_warning_s:
                        # Emit warning at most once per stall window
                        if (now_mono - last_stall_warning_t) >= stall_warning_s:
                            yield RuntimeWarningEvent(
                                event_id=f"{event_base}_stall_warning",
                                lease_id=lease_id,
                                request_id=request_id,
                                event_kind=RuntimeStreamEventKind.WARNING,
                                captured_at=_now_str(),
                                warning_kind=RuntimeStreamWarningKind.STALL_DETECTED.value,
                                message=(
                                    f"No output for {stall_elapsed:.1f}s "
                                    f"(threshold: {stall_warning_s:.1f}s)"
                                ),
                            )
                            last_stall_warning_t = now_mono

                        # ── Terminate on hard stall ──────────────────
                        if (
                            self._terminate_on_stall
                            and self._stall_terminate_after_ms is not None
                        ):
                            terminate_s = self._stall_terminate_after_ms / 1000.0
                            if stall_elapsed >= terminate_s:
                                timed_out = True
                                trace_event(
                                    "runtime.subprocess.kill",
                                    attributes={"reason": "stall"},
                                )
                                try:
                                    proc.terminate()
                                    try:
                                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                                    except TimeoutError:
                                        proc.kill()
                                        await proc.wait()
                                except ProcessLookupError:
                                    pass
                                break

        except asyncio.CancelledError:
            cancelled = True
            trace_event("runtime.subprocess.kill", attributes={"reason": "cancelled"})
        finally:
            for t in drain_tasks:
                t.cancel()
            await asyncio.gather(*drain_tasks, return_exceptions=True)
            if proc is not None:
                await _finalize_subprocess(proc)

        elapsed_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

        # ── Yield chunk events (sort by stream, then index) ─────────
        chunk_events.sort(key=lambda e: (e.stream, e.chunk_index))
        for ce in chunk_events:
            yield ce

        # ── Emit terminal event ─────────────────────────────────────
        _terminal_handled = False

        terminal_event: RuntimeCompletionEvent | RuntimeFailureEvent
        if timed_out:
            terminal_event = _make_failure(
                event_base,
                lease_id,
                request_id,
                RuntimeInvocationStatus.TIMED_OUT,
                "timeout",
                f"Execution timed out after {timeout_s}s",
                elapsed_ms,
                exit_code,
                stdout_result.final_hash,
                stderr_result.final_hash,
                stdout_result.total_bytes,
                stderr_result.total_bytes,
                stdout_result.truncated,
                stderr_result.truncated,
            )
        elif cancelled:
            terminal_event = _make_failure(
                event_base,
                lease_id,
                request_id,
                RuntimeInvocationStatus.CANCELLED,
                "cancelled",
                "Execution was cancelled",
                elapsed_ms,
                exit_code,
                stdout_result.final_hash,
                stderr_result.final_hash,
                stdout_result.total_bytes,
                stderr_result.total_bytes,
                stdout_result.truncated,
                stderr_result.truncated,
            )
        elif exit_code == 0:
            assert exit_code is not None
            terminal_event = RuntimeCompletionEvent(
                event_id=f"{event_base}_completed",
                lease_id=lease_id,
                request_id=request_id,
                event_kind=RuntimeStreamEventKind.COMPLETION,
                captured_at=_now_str(),
                status=RuntimeInvocationStatus.SUCCEEDED,
                exit_code=exit_code,
                duration_ms=elapsed_ms,
                stdout_sha256=stdout_result.final_hash,
                stderr_sha256=stderr_result.final_hash,
                stdout_bytes=stdout_result.total_bytes,
                stderr_bytes=stderr_result.total_bytes,
                stdout_truncated=stdout_result.truncated,
                stderr_truncated=stderr_result.truncated,
            )
        else:
            assert exit_code is not None
            terminal_event = RuntimeCompletionEvent(
                event_id=f"{event_base}_completed",
                lease_id=lease_id,
                request_id=request_id,
                event_kind=RuntimeStreamEventKind.COMPLETION,
                captured_at=_now_str(),
                status=RuntimeInvocationStatus.FAILED,
                exit_code=exit_code,
                duration_ms=elapsed_ms,
                stdout_sha256=stdout_result.final_hash,
                stderr_sha256=stderr_result.final_hash,
                stdout_bytes=stdout_result.total_bytes,
                stderr_bytes=stderr_result.total_bytes,
                stdout_truncated=stdout_result.truncated,
                stderr_truncated=stderr_result.truncated,
            )

        yield terminal_event

        if _terminal_handled:
            return
        _terminal_handled = True

        trace_event(
            "runtime.subprocess.exit",
            attributes={
                "exit_code": exit_code,
                "timed_out": timed_out,
                "cancelled": cancelled,
            },
        )
        trace_event(
            "runtime.subprocess.result_classified",
            attributes={
                "status": terminal_event.status.value
                if hasattr(terminal_event, "status")
                and terminal_event.status is not None
                else None,
                "exit_code": exit_code,
                "stdout_bytes": stdout_result.total_bytes,
                "stderr_bytes": stderr_result.total_bytes,
                "timed_out": timed_out,
                "killed": False,
                "cancelled": cancelled,
            },
        )
        end_status = (
            TraceStatus.ok
            if isinstance(terminal_event, RuntimeCompletionEvent)
            and terminal_event.status == RuntimeInvocationStatus.SUCCEEDED
            else TraceStatus.error
        )
        if timed_out:
            end_status = TraceStatus.timed_out
        elif cancelled:
            end_status = TraceStatus.cancelled
        trace_end(
            status=end_status,
            attributes={
                "exit_code": exit_code,
                "status": terminal_event.status.value
                if hasattr(terminal_event, "status")
                and terminal_event.status is not None
                else None,
                "duration_ms": elapsed_ms,
                "stdout_bytes": stdout_result.total_bytes,
                "stderr_bytes": stderr_result.total_bytes,
                "timed_out": timed_out,
                "killed": False,
                "cancelled": cancelled,
            },
        )

        # ── Audit terminal event (optional, failure-safe) ───────────
        if self._audit_trail_store is not None:
            try:
                await _append_audit_event(
                    self._audit_trail_store, self._audit_actor, lease, terminal_event
                )
            except Exception:
                yield RuntimeWarningEvent(
                    event_id=f"{event_base}_audit_failed",
                    lease_id=lease_id,
                    request_id=request_id,
                    event_kind=RuntimeStreamEventKind.WARNING,
                    captured_at=_now_str(),
                    warning_kind="audit_append_failed",
                    message="Audit append failed; execution result preserved",
                )

        # ── Release lease ───────────────────────────────────────────
        await _release_lease(self._lease_store, lease_id)
        lease.status = ExecutionLeaseStatus.RELEASED


def _make_failure(
    event_base: str,
    lease_id: str,
    request_id: str,
    status: RuntimeInvocationStatus,
    error_kind: str,
    refusal_reason: str,
    duration_ms: float | None = None,
    exit_code: int | None = None,
    stdout_sha256: str | None = None,
    stderr_sha256: str | None = None,
    stdout_bytes: int | None = None,
    stderr_bytes: int | None = None,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
) -> RuntimeFailureEvent:
    return RuntimeFailureEvent(
        event_id=f"{event_base}_failed",
        lease_id=lease_id,
        request_id=request_id,
        event_kind=RuntimeStreamEventKind.FAILURE,
        captured_at=_now_str(),
        status=status,
        error_kind=error_kind,
        refusal_reason=refusal_reason,
        duration_ms=duration_ms,
        exit_code=exit_code,
        stdout_sha256=stdout_sha256,
        stderr_sha256=stderr_sha256,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


async def _release_lease(
    lease_store: ExecutionLeaseStore | None, lease_id: str
) -> None:
    """Release the lease if a store is available."""
    if lease_store is not None:
        lease_store.release(lease_id)


def _build_terminal_envelope(
    terminal_event: RuntimeCompletionEvent | RuntimeFailureEvent,
    lease: ExecutionLease,
    audit_actor: ReceiptActor | None,
) -> ReceiptEnvelope:
    """Build a content-light ReceiptEnvelope from a terminal execution event.

    The envelope captures:
    - actor: the audit actor or a runtime/system default
    - subject: runtime invocation with lease_id and workspace/path context
    - input: execution request reference (SHA256 of request)
    - output: terminal status, stdout/stderr hashes and byte counts
    - evidence: SHA256 of the terminal event itself
    - decision: completed/failed/blocked/timed_out as appropriate

    All content is content-light: no raw stdout, stderr, or file contents.
    """
    actor = audit_actor or ReceiptActor(
        actor_id="runtime",
        actor_kind=ReceiptActorKind.RUNTIME,
        display_name="RuntimeSupervisor",
        is_authoritative=False,
    )

    request = lease.request
    subject = ReceiptSubject(
        subject_id=lease.lease_id,
        subject_kind=ReceiptSubjectKind.RUNTIME_INVOCATION,
        workspace_id=request.workspace_id if request else None,
        path=request.worktree_path if request else None,
    )

    inp = ReceiptInput(
        input_id=request.request_id if request else None,
        input_kind="execution_request",
        input_sha256=request.request_sha256 if request else None,
    )

    status_str = terminal_event.status.value

    output = ReceiptOutput(
        output_kind="runtime_execution",
        output_sha256=terminal_event.stdout_sha256,
        output_bytes=terminal_event.stdout_bytes,
        status=status_str,
    )

    decision = ReceiptDecision(
        decision=status_str,
        rationale=f"Exit code: {getattr(terminal_event, 'exit_code', 'N/A')}",
    )

    # Compute terminal event hash as evidence
    event_dump = terminal_event.model_dump(mode="json")
    canonical = dump_canonical_json(event_dump)
    event_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    evidence = [
        ReceiptEvidence(
            evidence_kind=ReceiptEvidenceKind.RUNTIME_EVENT,
            evidence_sha256=f"sha256:{event_hash}",
            schema_version="rig.relay.runtime_stream_event.v1",
        )
    ]

    envelope = build_receipt_envelope(
        receipt_kind="runtime_event",
        actor=actor,
        subject=subject,
        decision=decision,
        evidence_override=evidence,
    )
    # Manually attach input/output since the builder doesn't accept them
    envelope = envelope.model_copy(update={"input": inp, "output": output})
    return envelope


def _map_decision_kind(
    terminal_event: RuntimeCompletionEvent | RuntimeFailureEvent,
) -> AuditDecisionKind:
    """Map a terminal event to an AuditDecisionKind."""
    if isinstance(terminal_event, RuntimeCompletionEvent):
        if terminal_event.status == RuntimeInvocationStatus.SUCCEEDED:
            return AuditDecisionKind.COMPLETED
        return AuditDecisionKind.FAILED
    # RuntimeFailureEvent
    if terminal_event.status == RuntimeInvocationStatus.BLOCKED:
        return AuditDecisionKind.REFUSED
    return AuditDecisionKind.FAILED


async def _append_audit_event(
    audit_store: AuditTrailStore,
    audit_actor: ReceiptActor | None,
    lease: ExecutionLease,
    terminal_event: RuntimeCompletionEvent | RuntimeFailureEvent,
) -> None:
    """Build and append an audit event from a terminal execution event.

    Failure-safe: any exception propagates to the caller (which wraps
    it in a warning event).
    """
    envelope = _build_terminal_envelope(terminal_event, lease, audit_actor)

    workspace_id = lease.request.workspace_id if lease.request else None

    audit_store.append_audit_event(
        event_id=terminal_event.event_id,
        action=AuditActionKind.EXECUTION_COMPLETED,
        decision=_map_decision_kind(terminal_event),
        actor=audit_actor,
        subject=envelope.subject,
        workspace_id=workspace_id,
        envelope=envelope,
    )


__all__ = ["RuntimeSupervisor"]
