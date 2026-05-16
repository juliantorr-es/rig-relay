"""ToolSubprocessRunner — protocol and models for tool-level subprocess execution.

Defines the contract between tools (Bash, Validate, etc.) and the
subprocess execution substrate (RuntimeSupervisor). Tools depend on
this protocol; the runtime provides the implementation.

This lives in core/ so tools can depend on it without importing runtime
internals directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class ToolSubprocessRequest(BaseModel):
    """Request to execute a subprocess command from a tool.

    All fields are content-light: no raw file contents, no secrets.
    The runtime layer enriches this with governance/supervisor metadata.
    """

    model_config = ConfigDict(extra="forbid")

    argv: list[str]
    cwd: str
    timeout_seconds: float = 60.0
    stdout_limit_bytes: int = 65536
    stderr_limit_bytes: int = 65536
    stdin_text: str | None = None
    env: dict[str, str] | None = None
    tool_name: str = ""
    invocation_id: str | None = None
    lane_id: str | None = None
    lease_id: str | None = None
    actor: str | None = None
    audit_context: dict[str, object] = {}
    receipt_context: dict[str, object] = {}


class ToolSubprocessResult(BaseModel):
    """Result from a supervised subprocess execution.

    Content-light: no raw stdout/stderr in audit-facing fields.
    stdout_text/stderr_text are truncated/bounded.
    """

    model_config = ConfigDict(extra="forbid")

    status: str  # completed | failed | timed_out | stalled | refused | killed
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
    receipt_sha256: str | None = None
    refusal_code: str | None = None
    error_message: str | None = None
    supervisor_metadata: dict[str, object] = {}
    supervisor_result_envelope: dict[str, object] | None = None
    supervisor_result_envelope_sha256: str | None = None
    supervisor_result_classification: str | None = None


class ToolSubprocessRunner(Protocol):
    """Protocol for tools to execute supervised subprocess commands.

    Implementations route to RuntimeSupervisor or a test double.
    """

    async def run(self, request: ToolSubprocessRequest) -> ToolSubprocessResult: ...


@dataclass(frozen=True)
class ShellFeatureResult:
    """Result of shell-feature detection on a bash command string.

    If safe_for_argv is True, the command can be represented as argv
    and routed through the supervised subprocess runner.

    If safe_for_argv is False, the command contains shell features
    (pipes, redirects, command substitution, etc.) and must be
    refused or explicitly governed.
    """

    safe_for_argv: bool
    argv: list[str]
    detected_features: list[str]


__all__ = [
    "ShellFeatureResult",
    "ToolSubprocessRequest",
    "ToolSubprocessResult",
    "ToolSubprocessRunner",
]
