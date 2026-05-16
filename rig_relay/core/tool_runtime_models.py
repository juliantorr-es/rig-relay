"""ToolRuntime models — typed boundaries for governed tool execution.

These models define the contract between AgentLoop (turn conductor)
and ToolRuntime (governed tool executor). Every tool execution
produces a structured ToolRuntimeResult with explicit status,
cache outcome, approval outcome, and degradation information.

Graceful degradation is a first-class concern: failures, refusals,
cache unavailability, receipt unavailability, and timeouts all become
typed results rather than ad-hoc branches or crashes.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolRuntimeStatus(StrEnum):
    """Outcome of a single tool execution."""

    COMPLETED = "completed"
    CACHED = "cached"
    REFUSED = "refused"
    APPROVAL_REQUIRED = "approval_required"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"
    DEGRADED = "degraded"


class ToolRuntimeCacheStatus(StrEnum):
    """Cache outcome for a tool execution."""

    NOT_APPLICABLE = "not_applicable"
    HIT = "hit"
    MISS = "miss"
    UNAVAILABLE = "unavailable"
    WRITE_FAILED = "write_failed"


class ToolRuntimeApprovalStatus(StrEnum):
    """Approval decision state."""

    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    APPROVED = "approved"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


class ToolRuntimeExecutionMode(StrEnum):
    """Classification of tool mutation risk."""

    READ_ONLY = "read_only"
    MUTATION_PROPOSAL = "mutation_proposal"
    MUTATION_EXECUTION = "mutation_execution"
    UNKNOWN = "unknown"


class RefusalCode(StrEnum):
    """Structured refusal codes for degraded tool execution."""

    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_PERMISSION_DENIED = "tool_permission_denied"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_UNAVAILABLE = "approval_unavailable"
    CACHE_UNAVAILABLE = "cache_unavailable"
    CACHE_WRITE_FAILED = "cache_write_failed"
    PATCH_PROPOSAL_REQUIRED = "patch_proposal_required"
    TOOL_INVOCATION_FAILED = "tool_invocation_failed"
    TOOL_TIMEOUT = "tool_timeout"
    RECEIPT_UNAVAILABLE = "receipt_unavailable"
    CONTEXT_OBSERVATION_FAILED = "context_observation_failed"
    MALFORMED_TOOL_ARGS = "malformed_tool_args"
    UNSUPPORTED_EXECUTION_MODE = "unsupported_execution_mode"


class ToolRuntimeRequest(BaseModel):
    """Input to ToolRuntime.execute_one()."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str = ""
    source_kind: str | None = None
    source_id: str | None = None
    invocation_id: str | None = None
    turn_id: str | None = None
    session_id: str | None = None
    agent_id: str | None = None
    lane_id: str | None = None
    lease_id: str | None = None
    workspace_root: str | None = None
    worktree_path: str | None = None
    actor: str | None = None
    execution_mode: ToolRuntimeExecutionMode = ToolRuntimeExecutionMode.UNKNOWN
    context_envelope_id: str | None = None
    bypass_permissions: bool = False
    audit_context: dict[str, Any] = Field(default_factory=dict)
    runtime_envelope_sha256: str | None = None
    receipt_context: dict[str, Any] = Field(default_factory=dict)
    policy_hints: dict[str, Any] = Field(default_factory=dict)


class ToolRuntimeRefusal(BaseModel):
    """Structured refusal produced when tool execution is blocked."""

    model_config = ConfigDict(extra="forbid")

    refusal_code: RefusalCode
    message: str
    recoverable: bool = False
    suggested_next_action: str | None = None


class ToolRuntimeDecision(BaseModel):
    """Pre-execution decision: should the tool run, and under what conditions."""

    model_config = ConfigDict(extra="forbid")

    should_execute: bool = True
    approval_status: ToolRuntimeApprovalStatus = ToolRuntimeApprovalStatus.NOT_REQUIRED
    reason: str = ""
    refusal: ToolRuntimeRefusal | None = None
    requires_patch_proposal: bool = False
    cache_status: ToolRuntimeCacheStatus = ToolRuntimeCacheStatus.NOT_APPLICABLE


class ToolRuntimeResult(BaseModel):
    """Output from ToolRuntime.execute_one()."""

    model_config = ConfigDict(extra="forbid")

    status: ToolRuntimeStatus
    tool_name: str = ""
    tool_call_id: str = ""
    source_kind: str | None = None
    source_id: str | None = None
    runtime_envelope_sha256: str | None = None

    # ── Provider-facing ───────────────────────────────────────────
    provider_tool_response: Any = None
    tool_events: list[Any] = Field(default_factory=list)

    # ── Evidence ──────────────────────────────────────────────────
    receipt_refs: list[str] = Field(default_factory=list)

    # ── Diagnostics ───────────────────────────────────────────────
    cache_status: ToolRuntimeCacheStatus = ToolRuntimeCacheStatus.NOT_APPLICABLE
    approval_status: ToolRuntimeApprovalStatus = ToolRuntimeApprovalStatus.NOT_REQUIRED
    refusal: ToolRuntimeRefusal | None = None
    error_kind: str | None = None
    error_message: str | None = None
    context_observation_status: str = "not_attempted"
    execution_enabled: bool = True
    mutation_performed: bool = False
    degraded_capabilities: list[str] = Field(default_factory=list)

    # ── Metrics ───────────────────────────────────────────────────
    duration_ms: float | None = None
    cache_hit: bool = False

    def to_debug_dict(self) -> dict[str, Any]:
        """JSON-safe debug snapshot. Excludes large tool output bodies."""
        result: dict[str, Any] = {
            "status": self.status.value,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "cache": self.cache_status.value,
            "approval": self.approval_status.value,
            "execution_enabled": self.execution_enabled,
            "mutation_performed": self.mutation_performed,
            "context_observation": self.context_observation_status,
            "duration_ms": self.duration_ms,
            "cache_hit": self.cache_hit,
            "degraded": self.degraded_capabilities,
        }
        if self.refusal:
            result["refusal"] = {
                "code": self.refusal.refusal_code.value,
                "recoverable": self.refusal.recoverable,
            }
        if self.error_kind:
            result["error"] = self.error_kind
        if self.receipt_refs:
            result["receipts"] = len(self.receipt_refs)
        return result

    @classmethod
    def completed(
        cls,
        tool_name: str = "",
        tool_call_id: str = "",
        provider_tool_response: Any = None,
        tool_events: list[Any] | None = None,
        cache_status: ToolRuntimeCacheStatus = ToolRuntimeCacheStatus.MISS,
        approval_status: ToolRuntimeApprovalStatus = ToolRuntimeApprovalStatus.NOT_REQUIRED,
        duration_ms: float | None = None,
    ) -> ToolRuntimeResult:
        return cls(
            status=ToolRuntimeStatus.COMPLETED,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            provider_tool_response=provider_tool_response,
            tool_events=tool_events or [],
            cache_status=cache_status,
            approval_status=approval_status,
            duration_ms=duration_ms,
        )

    @classmethod
    def cached_result(
        cls,
        tool_name: str = "",
        tool_call_id: str = "",
        provider_tool_response: Any = None,
    ) -> ToolRuntimeResult:
        return cls(
            status=ToolRuntimeStatus.CACHED,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            provider_tool_response=provider_tool_response,
            cache_status=ToolRuntimeCacheStatus.HIT,
            cache_hit=True,
        )

    @classmethod
    def refused(
        cls,
        tool_name: str = "",
        tool_call_id: str = "",
        refusal: ToolRuntimeRefusal | None = None,
        approval_status: ToolRuntimeApprovalStatus = ToolRuntimeApprovalStatus.DENIED,
    ) -> ToolRuntimeResult:
        return cls(
            status=ToolRuntimeStatus.REFUSED,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            refusal=refusal,
            approval_status=approval_status,
            execution_enabled=False,
        )

    @classmethod
    def failed(
        cls,
        tool_name: str = "",
        tool_call_id: str = "",
        error_kind: str | None = None,
        error_message: str | None = None,
        refusal: ToolRuntimeRefusal | None = None,
        degraded_capabilities: list[str] | None = None,
    ) -> ToolRuntimeResult:
        return cls(
            status=ToolRuntimeStatus.FAILED,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            error_kind=error_kind,
            error_message=error_message,
            refusal=refusal,
            execution_enabled=False,
            degraded_capabilities=degraded_capabilities or [],
        )

    @classmethod
    def skipped(
        cls, tool_name: str = "", tool_call_id: str = "", reason: str = ""
    ) -> ToolRuntimeResult:
        return cls(
            status=ToolRuntimeStatus.SKIPPED,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            error_message=reason,
        )
