"""Subagent tool adapter — routes model tool calls through ToolRuntime.

Provides the minimal bridge from SubagentRuntime to ToolRuntime without
importing AgentLoop, desktop, ralph, or analytics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rig_relay.core.tool_runtime import ToolRuntime
from rig_relay.core.tool_runtime_models import (
    ToolRuntimeExecutionMode,
    ToolRuntimeRequest,
)


@dataclass(frozen=True, slots=True)
class SubagentToolCall:
    tool_name: str
    call_id: str
    validated_args: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SubagentToolResult:
    success: bool
    status: str
    output_text: str
    refusal_code: str | None
    error_kind: str | None
    error_message: str | None
    degraded: bool
    supervisor_envelope_id: str | None
    supervisor_envelope_sha256: str | None
    supervisor_classification: str | None


def build_tool_runtime_request(
    call: SubagentToolCall,
    *,
    source_kind: str = "subagent_runtime",
    source_id: str = "",
    session_id: str = "",
    agent_id: str = "",
    lane_id: str = "",
    actor: str = "",
    audit_context: dict[str, object] | None = None,
) -> ToolRuntimeRequest:
    return ToolRuntimeRequest(
        tool_name=call.tool_name,
        tool_args=call.validated_args,
        tool_call_id=call.call_id,
        source_kind=source_kind,
        source_id=source_id,
        session_id=session_id,
        agent_id=agent_id,
        lane_id=lane_id,
        actor=actor,
        audit_context=dict(audit_context or {}),
        execution_mode=_infer_execution_mode(call.tool_name),
    )


def _infer_execution_mode(tool_name: str) -> ToolRuntimeExecutionMode:
    if tool_name in {"validate", "read_file", "grep", "git_status", "get_context"}:
        return ToolRuntimeExecutionMode.READ_ONLY
    if tool_name in {"bash", "search_replace", "write_file"}:
        return ToolRuntimeExecutionMode.MUTATION_EXECUTION
    return ToolRuntimeExecutionMode.UNKNOWN


async def execute_and_format(
    runtime: ToolRuntime,
    call: SubagentToolCall,
    *,
    source_kind: str = "subagent_runtime",
    source_id: str = "",
    session_id: str = "",
    agent_id: str = "",
) -> SubagentToolResult:
    request = build_tool_runtime_request(
        call,
        source_kind=source_kind,
        source_id=source_id,
        session_id=session_id,
        agent_id=agent_id,
    )
    result = await runtime.execute_one(request)

    output_text: str
    if result.provider_tool_response is not None:
        if hasattr(result.provider_tool_response, "model_dump"):
            d = result.provider_tool_response.model_dump()
            output_text = "\n".join(f"{k}: {v}" for k, v in d.items())
        else:
            output_text = str(result.provider_tool_response)
    else:
        output_text = result.status.value

    return SubagentToolResult(
        success=result.status.value in {"completed", "cached"},
        status=result.status.value,
        output_text=output_text,
        refusal_code=result.refusal.refusal_code.value if result.refusal else None,
        error_kind=result.error_kind,
        error_message=result.error_message,
        degraded=bool(result.degraded_capabilities),
        supervisor_envelope_id=result.supervisor_result_envelope_id,
        supervisor_envelope_sha256=result.supervisor_result_envelope_sha256,
        supervisor_classification=result.supervisor_result_classification,
    )


__all__ = [
    "SubagentToolCall",
    "SubagentToolResult",
    "build_tool_runtime_request",
    "execute_and_format",
]
