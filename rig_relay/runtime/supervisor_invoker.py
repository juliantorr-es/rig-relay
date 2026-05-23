"""SupervisorCommandInvoker — lightweight bridge from tools to RuntimeSupervisor.

Provides a simple invoke API for tool implementations (Bash, Validate, etc.)
that want to route through RuntimeSupervisor without owning lease machinery.

The invoker synthesizes a minimal ExecutionLease internally, runs the
supervisor, collects the terminal event, and returns a typed result.

Rules:
- Command argv as list[str], no shell strings.
- cwd, timeout, stdout/stderr limits enforced by supervisor.
- No shell=True path unless explicitly governed.
- Result is content-light (hashes, byte counts, truncated flags).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict

from rig_relay.coordination.execution_lease import ExecutionLease, ExecutionLeaseStatus
from rig_relay.core.tool_subprocess import ToolSubprocessRequest, ToolSubprocessResult
from rig_relay.governance.governance_engine import GovernanceEngine
from rig_relay.runtime.execution_budgets import (
    BASH_MAX_OUTPUT_BYTES,
    TOOL_MAX_RUNTIME_SECONDS,
)
from rig_relay.runtime.execution_request import ExecutionRequest
from rig_relay.runtime.stream_types import (
    RuntimeCompletionEvent,
    RuntimeFailureEvent,
    RuntimeInvocationStatus,
    RuntimeOutputChunkEvent,
    RuntimeStreamEventKind,
)
from rig_relay.runtime.supervisor import RuntimeSupervisor
from rig_relay.runtime.supervisor_result import (
    RuntimeSupervisorCleanup,
    RuntimeSupervisorCommandDigest,
    RuntimeSupervisorEnvelopeContext,
    RuntimeSupervisorFailure,
    RuntimeSupervisorOutputDigest,
    RuntimeSupervisorResourceUsage,
    RuntimeSupervisorResultClassification,
    RuntimeSupervisorResultEnvelope,
    RuntimeSupervisorTiming,
    build_runtime_supervisor_result_envelope,
)


class SupervisorExecutionStatus:
    """Status constants for supervised subprocess execution."""

    COMPLETED: str = "completed"
    FAILED: str = "failed"
    TIMED_OUT: str = "timed_out"
    STALLED: str = "stalled"
    REFUSED: str = "refused"


class SupervisorExecutionResult(BaseModel):
    """Content-light result from SupervisorCommandInvoker.

    Mirrors the fields available from RuntimeSupervisor's terminal events
    but in a simplified flat shape for tool consumption.
    """

    model_config = ConfigDict(extra="forbid")

    status: str = "completed"
    exit_code: int | None = None
    stdout_text: str = ""
    stderr_text: str = ""
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_sha256: str = ""
    stderr_sha256: str = ""
    duration_ms: float = 0.0
    command_family: str = ""
    cwd: str = ""
    refusal_code: str | None = None
    error_message: str | None = None
    result_envelope: RuntimeSupervisorResultEnvelope | None = None


def _sha256_text(text: str) -> str:
    return (
        "sha256:" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    )


def _classify_cwd_kind(cwd_path: str) -> str:
    """Classify a working directory path into a safe category."""
    import os

    p = str(cwd_path).lower()
    home = os.path.expanduser("~").lower()
    if p.startswith("/tmp") or "/var/folders" in p:
        return "temp"
    if "worktree" in p or "worktrees" in p:
        return "worktree"
    if p.startswith(home):
        return "repo"
    if "application support" in p:
        return "app_support"
    return "unknown"


class SupervisorCommandInvoker:
    """Invoke a subprocess command through RuntimeSupervisor.

    Synthesizes a minimal lease (ephemeral, released synchronously)
    so tools can benefit from RuntimeSupervisor's governance, timeout,
    stall detection, and bounded output without owning lease machinery.

    Usage:
        invoker = SupervisorCommandInvoker()
        result = await invoker.invoke(
            argv=["pytest", "-x"],
            cwd="/path/to/worktree",
            timeout_seconds=60,
            stdout_limit_bytes=65536,
        )
    """

    def __init__(
        self,
        *,
        max_stdout_bytes: int = 65536,
        max_stderr_bytes: int = 65536,
        heartbeat_interval_ms: int = 1000,
        trace_recorder: Any | None = None,
        cpu_budget_seconds: float = TOOL_MAX_RUNTIME_SECONDS,
        io_budget_bytes: int = BASH_MAX_OUTPUT_BYTES,
    ) -> None:
        self._max_stdout_bytes = max_stdout_bytes
        self._max_stderr_bytes = max_stderr_bytes
        self._heartbeat_interval_ms = heartbeat_interval_ms
        self._trace_recorder = trace_recorder
        self._cpu_budget_seconds = cpu_budget_seconds
        self._io_budget_bytes = io_budget_bytes

    def _start_trace_span(
        self,
        argv: list[str],
        cwd_str: str,
        timeout_seconds: float,
        tool_batch_id: str = "",
    ) -> tuple[Any | None, Any | None, Any | None]:
        if self._trace_recorder is None:
            return None, None, None
        from rig_relay.tracing.models import TraceStatus as _TS

        recorder = self._trace_recorder
        attrs = {
            "executable": argv[0],
            "argv_hash": hashlib.sha256(" ".join(argv).encode()).hexdigest()[:16],
            "argv_count": len(argv),
            "cwd_hash": hashlib.sha256(cwd_str.encode()).hexdigest()[:16],
            "cwd_kind": _classify_cwd_kind(cwd_str),
            "timeout_seconds": timeout_seconds,
        }
        if tool_batch_id:
            attrs["tool_batch_id"] = tool_batch_id
        trace_span = recorder.start_span("runtime.subprocess.execute", attributes=attrs)
        return recorder, trace_span, _TS

    @staticmethod
    def _sha256_hex_prefixed(text: str) -> str:
        return (
            "sha256:"
            + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        )

    @staticmethod
    def _command_digest(
        argv: list[str], cwd_str: str
    ) -> RuntimeSupervisorCommandDigest:
        return RuntimeSupervisorCommandDigest(
            executable=argv[0],
            argv_hash=SupervisorCommandInvoker._sha256_hex_prefixed(" ".join(argv)),
            argc=len(argv),
            cwd_hash=SupervisorCommandInvoker._sha256_hex_prefixed(cwd_str),
            cwd_kind=_classify_cwd_kind(cwd_str),
        )

    @staticmethod
    def _output_digest(
        stdout_sha256: str,
        stderr_sha256: str,
        stdout_bytes: int,
        stderr_bytes: int,
        stdout_truncated: bool,
        stderr_truncated: bool,
    ) -> RuntimeSupervisorOutputDigest:
        return RuntimeSupervisorOutputDigest(
            stdout_sha256=stdout_sha256,
            stderr_sha256=stderr_sha256,
            stdout_bytes=stdout_bytes,
            stderr_bytes=stderr_bytes,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )

    @staticmethod
    def _timing_digest(
        *,
        started_at: str | None = None,
        completed_at: str | None = None,
        duration_ms: float | None = None,
    ) -> RuntimeSupervisorTiming:
        return RuntimeSupervisorTiming(
            started_at=started_at, completed_at=completed_at, duration_ms=duration_ms
        )

    @staticmethod
    def _resource_usage(
        event: RuntimeCompletionEvent | RuntimeFailureEvent,
    ) -> RuntimeSupervisorResourceUsage:
        is_budget_exceeded = (
            not isinstance(event, RuntimeCompletionEvent)
            and event.status == RuntimeInvocationStatus.BUDGET_EXCEEDED
        )
        return RuntimeSupervisorResourceUsage(
            exit_code=getattr(event, "exit_code", None),
            signal=None,
            timed_out=getattr(event, "status", None)
            == RuntimeInvocationStatus.TIMED_OUT,
            killed=is_budget_exceeded,
            killed_reason=(
                getattr(event, "error_kind", None) if is_budget_exceeded else None
            ),
            cancelled=getattr(event, "status", None)
            == RuntimeInvocationStatus.CANCELLED,
            pid=None,
        )

    @staticmethod
    def _classify_terminal(
        event: RuntimeCompletionEvent | RuntimeFailureEvent,
    ) -> RuntimeSupervisorResultClassification:
        if isinstance(event, RuntimeCompletionEvent):
            return (
                RuntimeSupervisorResultClassification.COMPLETED
                if event.status == RuntimeInvocationStatus.SUCCEEDED
                else RuntimeSupervisorResultClassification.FAILED
            )
        match event.status:
            case RuntimeInvocationStatus.TIMED_OUT:
                return RuntimeSupervisorResultClassification.TIMED_OUT
            case RuntimeInvocationStatus.BUDGET_EXCEEDED:
                return RuntimeSupervisorResultClassification.BUDGET_KILLED
            case RuntimeInvocationStatus.CANCELLED:
                return RuntimeSupervisorResultClassification.CANCELLED
            case RuntimeInvocationStatus.BLOCKED:
                return RuntimeSupervisorResultClassification.REFUSED
            case RuntimeInvocationStatus.FAILED if getattr(event, "error_kind", "") in {
                "command_not_found",
                "spawn_error",
            }:
                return RuntimeSupervisorResultClassification.SPAWN_FAILED
            case _:
                return RuntimeSupervisorResultClassification.FAILED

    def _build_result_envelope(
        self,
        *,
        argv: list[str],
        cwd_str: str,
        terminal_event: RuntimeCompletionEvent | RuntimeFailureEvent,
        stdout_text: str,
        stderr_text: str,
        trace_span: Any | None,
        trace_status: Any | None,
        started_at: str | None = None,
    ) -> RuntimeSupervisorResultEnvelope:
        command = self._command_digest(argv, cwd_str)
        output = self._output_digest(
            stdout_sha256=getattr(terminal_event, "stdout_sha256", "")
            or _sha256_text(stdout_text),
            stderr_sha256=getattr(terminal_event, "stderr_sha256", "")
            or _sha256_text(stderr_text),
            stdout_bytes=getattr(terminal_event, "stdout_bytes", 0) or 0,
            stderr_bytes=getattr(terminal_event, "stderr_bytes", 0) or 0,
            stdout_truncated=getattr(terminal_event, "stdout_truncated", False),
            stderr_truncated=getattr(terminal_event, "stderr_truncated", False),
        )
        timing = self._timing_digest(
            started_at=started_at,
            completed_at=getattr(terminal_event, "captured_at", None),
            duration_ms=getattr(terminal_event, "duration_ms", None),
        )
        classification = self._classify_terminal(terminal_event)
        resource_usage = self._resource_usage(terminal_event)
        cleanup = RuntimeSupervisorCleanup(status="completed", reason=None)
        error = None
        if isinstance(terminal_event, RuntimeFailureEvent):
            error = RuntimeSupervisorFailure(
                error_kind=terminal_event.error_kind,
                reason=terminal_event.refusal_reason,
                cleanup_status=cleanup.status,
            )
        evidence = {
            "trace_id": getattr(trace_span, "trace_id", None),
            "parent_span_id": getattr(trace_span, "parent_span_id", None),
            "span_id": getattr(trace_span, "span_id", None),
        }
        return build_runtime_supervisor_result_envelope(
            command=command,
            cwd={"cwd_hash": command.cwd_hash, "cwd_kind": command.cwd_kind},
            state_projection={
                "current_state": classification.value,
                "previous_state": None,
                "last_event": terminal_event.event_kind.value,
                "transition_count": 0,
                "exit_code": getattr(terminal_event, "exit_code", None),
                "timed_out": classification
                == RuntimeSupervisorResultClassification.TIMED_OUT,
                "killed": classification
                == RuntimeSupervisorResultClassification.KILLED,
                "stdout_bytes": output.stdout_bytes,
                "stderr_bytes": output.stderr_bytes,
            },
            classification=classification,
            resource_usage=resource_usage,
            output=output,
            timing=timing,
            context=RuntimeSupervisorEnvelopeContext(
                trace_id=evidence["trace_id"],
                parent_span_id=evidence["parent_span_id"],
                span_id=evidence["span_id"],
                error=error,
                cleanup=cleanup,
            ),
        )

    @staticmethod
    def _end_trace_span(
        recorder: Any | None,
        trace_span: Any | None,
        trace_status: Any | None,
        *,
        result: SupervisorExecutionResult | None = None,
        status: Any | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        if recorder is None or trace_span is None or trace_status is None:
            return
        end_status = status
        end_attrs = attributes or {}
        if result is not None:
            envelope_classification = (
                result.result_envelope.classification.value
                if result.result_envelope is not None
                else result.status
            )
            end_status = (
                trace_status.ok
                if envelope_classification == "completed"
                else trace_status.error
            )
            if envelope_classification == "timed_out":
                end_status = trace_status.timed_out
            elif envelope_classification == "budget_killed":
                end_status = trace_status.error
            elif envelope_classification == "refused":
                end_status = trace_status.refused
            elif envelope_classification == "cancelled":
                end_status = trace_status.cancelled
            end_attrs = {
                "exit_code": result.exit_code,
                "status": envelope_classification,
                "duration_ms": result.duration_ms,
                "stdout_bytes": result.stdout_bytes,
                "stderr_bytes": result.stderr_bytes,
                "stdout_truncated": result.stdout_truncated,
                "stderr_truncated": result.stderr_truncated,
            }
        recorder.end_span(trace_span, status=end_status, attributes=end_attrs)

    async def invoke(
        self,
        argv: list[str],
        *,
        cwd: str | Path,
        timeout_seconds: float = 60,
        stdout_limit_bytes: int | None = None,
        stderr_limit_bytes: int | None = None,
        env_overlay: dict[str, str] | None = None,
        purpose: str = "",
        workspace_id: str | None = None,
        worktree_path: str | None = None,
    ) -> SupervisorExecutionResult:
        """Run a command through RuntimeSupervisor and return a flat result.

        Args:
            argv: Command and arguments as list of non-empty strings.
            cwd: Working directory (str or Path).
            timeout_seconds: Max execution time in seconds.
            stdout_limit_bytes: Max stdout bytes (defaults to self._max_stdout_bytes).
            stderr_limit_bytes: Max stderr bytes (defaults to self._max_stderr_bytes).
            env_overlay: Additional env vars (sensitive vars stripped by supervisor).
            purpose: Human-readable purpose for audit/telemetry.
            workspace_id: Optional workspace context.
            worktree_path: Optional worktree path.
        """
        if not argv or not argv[0]:
            envelope = build_runtime_supervisor_result_envelope(
                command=RuntimeSupervisorCommandDigest(
                    executable="",
                    argv_hash=SupervisorCommandInvoker._sha256_hex_prefixed(""),
                    argc=0,
                    cwd_hash=SupervisorCommandInvoker._sha256_hex_prefixed(""),
                    cwd_kind="unknown",
                ),
                cwd={
                    "cwd_hash": SupervisorCommandInvoker._sha256_hex_prefixed(""),
                    "cwd_kind": "unknown",
                },
                state_projection={
                    "current_state": "refused",
                    "previous_state": None,
                    "last_event": "precondition_failed",
                    "transition_count": 0,
                    "exit_code": None,
                    "timed_out": False,
                    "killed": False,
                    "stdout_bytes": 0,
                    "stderr_bytes": 0,
                },
                classification=RuntimeSupervisorResultClassification.REFUSED,
                resource_usage=RuntimeSupervisorResourceUsage(),
                output=RuntimeSupervisorOutputDigest(
                    stdout_sha256=_sha256_text(""),
                    stderr_sha256=_sha256_text(""),
                    stdout_bytes=0,
                    stderr_bytes=0,
                ),
                timing=RuntimeSupervisorTiming(),
                context=RuntimeSupervisorEnvelopeContext(
                    cleanup=RuntimeSupervisorCleanup(
                        status="not_started", reason="empty_argv"
                    ),
                    error=RuntimeSupervisorFailure(
                        error_kind="empty_argv",
                        reason="argv must be non-empty",
                        cleanup_status="not_started",
                    ),
                ),
            )
            return SupervisorExecutionResult(
                status="refused",
                refusal_code="empty_argv",
                error_message="argv must be non-empty",
                result_envelope=envelope,
            )

        cwd_str = str(cwd)
        if not Path(cwd_str).is_dir():
            envelope = build_runtime_supervisor_result_envelope(
                command=RuntimeSupervisorCommandDigest(
                    executable=argv[0],
                    argv_hash=SupervisorCommandInvoker._sha256_hex_prefixed(
                        " ".join(argv)
                    ),
                    argc=len(argv),
                    cwd_hash=SupervisorCommandInvoker._sha256_hex_prefixed(cwd_str),
                    cwd_kind=_classify_cwd_kind(cwd_str),
                ),
                cwd={
                    "cwd_hash": SupervisorCommandInvoker._sha256_hex_prefixed(cwd_str),
                    "cwd_kind": _classify_cwd_kind(cwd_str),
                },
                state_projection={
                    "current_state": "refused",
                    "previous_state": None,
                    "last_event": "precondition_failed",
                    "transition_count": 0,
                    "exit_code": None,
                    "timed_out": False,
                    "killed": False,
                    "stdout_bytes": 0,
                    "stderr_bytes": 0,
                },
                classification=RuntimeSupervisorResultClassification.REFUSED,
                resource_usage=RuntimeSupervisorResourceUsage(),
                output=RuntimeSupervisorOutputDigest(
                    stdout_sha256=_sha256_text(""),
                    stderr_sha256=_sha256_text(""),
                    stdout_bytes=0,
                    stderr_bytes=0,
                ),
                timing=RuntimeSupervisorTiming(),
                context=RuntimeSupervisorEnvelopeContext(
                    cleanup=RuntimeSupervisorCleanup(
                        status="not_started", reason="cwd_not_found"
                    ),
                    error=RuntimeSupervisorFailure(
                        error_kind="cwd_not_found",
                        reason=f"cwd does not exist: {cwd_str}",
                        cleanup_status="not_started",
                    ),
                ),
            )
            return SupervisorExecutionResult(
                status="refused",
                refusal_code="cwd_not_found",
                error_message=f"cwd does not exist: {cwd_str}",
                cwd=cwd_str,
                result_envelope=envelope,
            )

        supervisor = RuntimeSupervisor(
            lease_store=None,
            max_stdout_bytes=stdout_limit_bytes or self._max_stdout_bytes,
            max_stderr_bytes=stderr_limit_bytes or self._max_stderr_bytes,
            heartbeat_interval_ms=self._heartbeat_interval_ms,
            governance_engine=GovernanceEngine(),
            cpu_budget_seconds=self._cpu_budget_seconds,
            io_budget_bytes=self._io_budget_bytes,
        )

        recorder, trace_span, trace_status = self._start_trace_span(
            argv, cwd_str, timeout_seconds
        )

        lease = self._build_ephemeral_lease(
            argv=argv,
            cwd_str=cwd_str,
            timeout_seconds=timeout_seconds,
            purpose=purpose,
            env_overlay=env_overlay,
            workspace_id=workspace_id,
            worktree_path=worktree_path,
        )

        terminal_event: RuntimeCompletionEvent | RuntimeFailureEvent | None = None
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        try:
            async for event in supervisor.execute(lease):
                if isinstance(event, RuntimeCompletionEvent):
                    terminal_event = event
                elif isinstance(event, RuntimeFailureEvent):
                    terminal_event = event
                elif isinstance(event, RuntimeOutputChunkEvent):
                    chunk_text = event.chunk_text or ""
                    if event.stream == "stdout":
                        stdout_chunks.append(chunk_text)
                    elif event.stream == "stderr":
                        stderr_chunks.append(chunk_text)
        except asyncio.CancelledError:
            self._end_trace_span(
                recorder,
                trace_span,
                trace_status,
                status=trace_status.cancelled if trace_status is not None else None,
                attributes={"status": "cancelled"},
            )
            return SupervisorExecutionResult(
                status="failed",
                refusal_code="cancelled",
                error_message="Execution was cancelled",
                cwd=cwd_str,
                result_envelope=self._build_result_envelope(
                    argv=argv,
                    cwd_str=cwd_str,
                    terminal_event=RuntimeFailureEvent(
                        event_id="cancelled",
                        lease_id=lease.lease_id,
                        request_id=lease.request.request_id,
                        event_kind=RuntimeStreamEventKind.FAILURE,
                        captured_at=datetime.now(UTC).isoformat(),
                        status=RuntimeInvocationStatus.CANCELLED,
                        error_kind="cancelled",
                        refusal_reason="Execution was cancelled",
                    ),
                    stdout_text="",
                    stderr_text="",
                    trace_span=trace_span,
                    trace_status=trace_status,
                ),
            )

        if terminal_event is None:
            self._end_trace_span(
                recorder,
                trace_span,
                trace_status,
                status=trace_status.error if trace_status is not None else None,
                attributes={"status": "no_terminal_event"},
            )
            return SupervisorExecutionResult(
                status="failed",
                refusal_code="no_terminal_event",
                error_message="Supervisor did not emit a terminal event",
                cwd=cwd_str,
                result_envelope=self._build_result_envelope(
                    argv=argv,
                    cwd_str=cwd_str,
                    terminal_event=RuntimeFailureEvent(
                        event_id="no_terminal_event",
                        lease_id=lease.lease_id,
                        request_id=lease.request.request_id,
                        event_kind=RuntimeStreamEventKind.FAILURE,
                        captured_at=datetime.now(UTC).isoformat(),
                        status=RuntimeInvocationStatus.FAILED,
                        error_kind="no_terminal_event",
                        refusal_reason="Supervisor did not emit a terminal event",
                    ),
                    stdout_text="",
                    stderr_text="",
                    trace_span=trace_span,
                    trace_status=trace_status,
                ),
            )

        stdout_text = "".join(stdout_chunks)
        stderr_text = "".join(stderr_chunks)
        command_family = " ".join(argv[:2])
        result = self._terminal_to_result(
            terminal_event, stdout_text, stderr_text, command_family, cwd_str
        )
        result.result_envelope = self._build_result_envelope(
            argv=argv,
            cwd_str=cwd_str,
            terminal_event=terminal_event,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            trace_span=trace_span,
            trace_status=trace_status,
            started_at=lease.acquired_at,
        )

        self._end_trace_span(recorder, trace_span, trace_status, result=result)

        return result

    @staticmethod
    def _terminal_to_result(
        terminal_event: RuntimeCompletionEvent | RuntimeFailureEvent,
        stdout_text: str,
        stderr_text: str,
        command_family: str,
        cwd_str: str,
    ) -> SupervisorExecutionResult:
        if isinstance(terminal_event, RuntimeCompletionEvent):
            if terminal_event.status == RuntimeInvocationStatus.SUCCEEDED:
                status = "completed"
            else:
                status = "failed"
            return SupervisorExecutionResult(
                status=status,
                exit_code=terminal_event.exit_code,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
                stdout_bytes=terminal_event.stdout_bytes,
                stderr_bytes=terminal_event.stderr_bytes,
                stdout_truncated=terminal_event.stdout_truncated,
                stderr_truncated=terminal_event.stderr_truncated,
                stdout_sha256=terminal_event.stdout_sha256 or _sha256_text(stdout_text),
                stderr_sha256=terminal_event.stderr_sha256 or _sha256_text(stderr_text),
                duration_ms=terminal_event.duration_ms,
                command_family=command_family,
                cwd=cwd_str,
            )
        # RuntimeFailureEvent
        if terminal_event.status == RuntimeInvocationStatus.TIMED_OUT:
            status = "timed_out"
        elif terminal_event.status == RuntimeInvocationStatus.BUDGET_EXCEEDED:
            status = "budget_killed"
        elif terminal_event.status == RuntimeInvocationStatus.BLOCKED:
            status = "refused"
        else:
            status = "failed"
        return SupervisorExecutionResult(
            status=status,
            exit_code=getattr(terminal_event, "exit_code", None),
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            stdout_bytes=getattr(terminal_event, "stdout_bytes", 0) or 0,
            stderr_bytes=getattr(terminal_event, "stderr_bytes", 0) or 0,
            stdout_truncated=getattr(terminal_event, "stdout_truncated", False),
            stderr_truncated=getattr(terminal_event, "stderr_truncated", False),
            stdout_sha256=getattr(terminal_event, "stdout_sha256", "")
            or _sha256_text(stdout_text),
            stderr_sha256=getattr(terminal_event, "stderr_sha256", "")
            or _sha256_text(stderr_text),
            duration_ms=getattr(terminal_event, "duration_ms", 0.0),
            command_family=command_family,
            cwd=cwd_str,
            refusal_code=getattr(terminal_event, "error_kind", None),
            error_message=getattr(terminal_event, "refusal_reason", None),
        )

    @staticmethod
    def parse_shell_to_argv(command: str) -> list[str] | str:
        """Parse a shell command string into argv list.

        Returns the argv list on success, or a string error message.
        Uses shlex for safe splitting (handles quoting, escaping).
        """
        import shlex

        try:
            argv = shlex.split(command)
            if not argv:
                return "empty command after splitting"
            return argv
        except ValueError as e:
            return f"shell parsing error: {e}"

    def _build_ephemeral_lease(
        self,
        argv: list[str],
        cwd_str: str,
        timeout_seconds: float,
        purpose: str,
        env_overlay: dict[str, str] | None,
        workspace_id: str | None,
        worktree_path: str | None,
    ) -> ExecutionLease:
        request_id = f"svc_{uuid.uuid4().hex[:12]}"
        request = ExecutionRequest(
            request_id=request_id,
            argv=argv,
            cwd=cwd_str,
            timeout_ms=int(timeout_seconds * 1000),
            purpose=purpose or f"Supervised: {' '.join(argv)}",
            workspace_id=workspace_id,
            worktree_path=worktree_path,
            env_overlay=env_overlay or {},
        )
        return ExecutionLease(
            lease_id=f"lease_{request_id}",
            request=request,
            workspace_id=workspace_id,
            worktree_path=worktree_path,
            acquired_at=datetime.now(UTC).isoformat(),
            expires_at=(
                datetime.now(UTC) + timedelta(seconds=timeout_seconds + 10)
            ).isoformat(),
            status=ExecutionLeaseStatus.ACTIVE,
        )

    @staticmethod
    def has_shell_metacharacters(command: str) -> bool:
        """Check if a shell command string contains metacharacters.

        Metacharacters include pipes, redirects, command substitution,
        process substitution, and shell control operators.
        """
        import re

        # Check for common shell metacharacters
        patterns: list[tuple[str, str]] = [
            ("pipe", r"\|"),
            ("redirect_out", r"\d?>"),
            ("redirect_in", r"\d?<"),
            ("command_substitution", r"\$\([^)]*\)"),
            ("backtick_substitution", r"`[^`]*`"),
            ("process_substitution", r"[<>]\("),
            ("background", r"\s&\s*$"),
            ("and_or", r"\s&&\s|\s\|\|\s"),
            ("here_doc", r"<<"),
            ("here_str", r"<<<"),
        ]

        found: list[str] = []
        for name, pattern in patterns:
            if re.search(pattern, command):
                found.append(name)

        return bool(found)


class RuntimeSupervisorToolSubprocessRunner:
    """Implements ToolSubprocessRunner backed by RuntimeSupervisor.

    Bridges the core tool-level subprocess protocol to the runtime
    supervisor infrastructure. Creates ephemeral leases internally.

    Usage:
        runner = RuntimeSupervisorToolSubprocessRunner()
        result = await runner.run(ToolSubprocessRequest(
            argv=["echo", "hello"],
            cwd="/tmp",
        ))
    """

    def __init__(
        self,
        *,
        max_stdout_bytes: int = 65536,
        max_stderr_bytes: int = 65536,
        heartbeat_interval_ms: int = 1000,
        cpu_budget_seconds: float = TOOL_MAX_RUNTIME_SECONDS,
        io_budget_bytes: int = BASH_MAX_OUTPUT_BYTES,
    ) -> None:
        self._invoker = SupervisorCommandInvoker(
            max_stdout_bytes=max_stdout_bytes,
            max_stderr_bytes=max_stderr_bytes,
            heartbeat_interval_ms=heartbeat_interval_ms,
            cpu_budget_seconds=cpu_budget_seconds,
            io_budget_bytes=io_budget_bytes,
        )

    async def run(self, request: ToolSubprocessRequest) -> ToolSubprocessResult:

        result = await self._invoker.invoke(
            argv=request.argv,
            cwd=request.cwd,
            timeout_seconds=request.timeout_seconds,
            stdout_limit_bytes=request.stdout_limit_bytes,
            stderr_limit_bytes=request.stderr_limit_bytes,
            env_overlay=request.env,
            purpose=f"{request.tool_name}: {' '.join(request.argv)}",
        )

        supervisor_metadata: dict[str, object] = {
            "subprocess_supervised": True,
            "supervisor_backend": "RuntimeSupervisor",
            "command_family": result.command_family,
        }
        supervisor_envelope = result.result_envelope

        return ToolSubprocessResult(
            status=result.status,
            exit_code=result.exit_code,
            stdout_text=result.stdout_text,
            stderr_text=result.stderr_text,
            stdout_bytes=result.stdout_bytes,
            stderr_bytes=result.stderr_bytes,
            stdout_truncated=result.stdout_truncated,
            stderr_truncated=result.stderr_truncated,
            stdout_sha256=result.stdout_sha256,
            stderr_sha256=result.stderr_sha256,
            duration_ms=result.duration_ms,
            command_family=result.command_family,
            refusal_code=result.refusal_code,
            error_message=result.error_message,
            supervisor_metadata=supervisor_metadata,
            supervisor_result_envelope=(
                supervisor_envelope.model_dump(mode="json")
                if supervisor_envelope is not None
                else None
            ),
            supervisor_result_envelope_sha256=(
                _envelope_sha256(supervisor_envelope)
                if supervisor_envelope is not None
                else None
            ),
            supervisor_result_classification=(
                supervisor_envelope.classification.value
                if supervisor_envelope is not None
                else None
            ),
        )


def _envelope_sha256(envelope: Any) -> str:
    """SHA256 of the canonical JSON serialization of a result envelope."""
    import json as _json

    payload = _json.dumps(
        envelope.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "RuntimeSupervisorToolSubprocessRunner",
    "SupervisorCommandInvoker",
    "SupervisorExecutionResult",
]
