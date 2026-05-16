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
import uuid

from pydantic import BaseModel, ConfigDict

from rig_relay.coordination.execution_lease import ExecutionLease, ExecutionLeaseStatus
from rig_relay.core.tool_subprocess import ToolSubprocessRequest, ToolSubprocessResult
from rig_relay.runtime.execution_request import ExecutionRequest
from rig_relay.runtime.stream_types import (
    RuntimeCompletionEvent,
    RuntimeFailureEvent,
    RuntimeInvocationStatus,
    RuntimeOutputChunkEvent,
)
from rig_relay.runtime.supervisor import RuntimeSupervisor


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


def _sha256_text(text: str) -> str:
    return (
        "sha256:" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    )


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
    ) -> None:
        self._max_stdout_bytes = max_stdout_bytes
        self._max_stderr_bytes = max_stderr_bytes
        self._heartbeat_interval_ms = heartbeat_interval_ms

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
            return SupervisorExecutionResult(
                status="refused",
                refusal_code="empty_argv",
                error_message="argv must be non-empty",
            )

        cwd_str = str(cwd)
        if not Path(cwd_str).is_dir():
            return SupervisorExecutionResult(
                status="refused",
                refusal_code="cwd_not_found",
                error_message=f"cwd does not exist: {cwd_str}",
                cwd=cwd_str,
            )

        supervisor = RuntimeSupervisor(
            lease_store=None,
            max_stdout_bytes=stdout_limit_bytes or self._max_stdout_bytes,
            max_stderr_bytes=stderr_limit_bytes or self._max_stderr_bytes,
            heartbeat_interval_ms=self._heartbeat_interval_ms,
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
            return SupervisorExecutionResult(
                status="failed",
                refusal_code="cancelled",
                error_message="Execution was cancelled",
                cwd=cwd_str,
            )

        if terminal_event is None:
            return SupervisorExecutionResult(
                status="failed",
                refusal_code="no_terminal_event",
                error_message="Supervisor did not emit a terminal event",
                cwd=cwd_str,
            )

        stdout_text = "".join(stdout_chunks)
        stderr_text = "".join(stderr_chunks)
        command_family = " ".join(argv[:2])
        return self._terminal_to_result(
            terminal_event, stdout_text, stderr_text, command_family, cwd_str
        )

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
        elif terminal_event.status == RuntimeInvocationStatus.BLOCKED:
            status = "refused"
        else:
            status = "failed"
        return SupervisorExecutionResult(
            status=status,
            exit_code=getattr(terminal_event, "exit_code", None),
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            stdout_bytes=getattr(terminal_event, "stdout_bytes", 0),
            stderr_bytes=getattr(terminal_event, "stderr_bytes", 0),
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
    ) -> None:
        self._invoker = SupervisorCommandInvoker(
            max_stdout_bytes=max_stdout_bytes,
            max_stderr_bytes=max_stderr_bytes,
            heartbeat_interval_ms=heartbeat_interval_ms,
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
        )


__all__ = [
    "RuntimeSupervisorToolSubprocessRunner",
    "SupervisorCommandInvoker",
    "SupervisorExecutionResult",
]
