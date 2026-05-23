"""ToolResultRuntime — tool result normalization and message appending.

Phase 4 extraction target. Uses TelemetryEvidenceService for telemetry
emission (Step 2 refactor). Message appending stays here.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Literal

from rig_relay.core.telemetry.artifacts import should_artifact_tool_result
from rig_relay.core.telemetry.local import dump_canonical_json
from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass as ToolDeterminismClass,
    ToolMutationClass as ToolMutationClass,
    ToolOutputKind,
)
from rig_relay.core.types import LLMMessage, ToolResultEvent

if TYPE_CHECKING:
    from opentelemetry import trace

    from rig_relay.core._agent_models import ToolDecision
    from rig_relay.core.agent_loop import AgentLoop
    from rig_relay.core.llm.format import ResolvedToolCall
    from rig_relay.core.telemetry_evidence_service import (
        TelemetryEvidenceService as TelemetryEvidenceService,
    )


class ToolResultRuntime:
    __slots__ = ("_loop", "_evidence")

    def __init__(self, loop: AgentLoop, *, evidence: Any = None) -> None:
        self._loop = loop
        self._evidence = evidence

    def handle_tool_response(
        self,
        tool_call: ResolvedToolCall,
        text: str,
        status: Literal["success", "failure", "skipped"],
        decision: ToolDecision | None = None,
        result: dict[str, Any] | None = None,
        span: trace.Span | None = None,
        duration_ms: float | None = None,
    ) -> None:
        loop = self._loop

        if decision is None:
            from rig_relay.core._agent_models import ToolDecision, ToolExecutionResponse
            from rig_relay.core.tools.base import ToolPermission

            tool_permission = (
                loop._governance_runtime._resolve_tool_permission(tool_call.tool_name)
                if (
                    hasattr(loop, "_governance_runtime")
                    and loop._governance_runtime is not None
                )
                else ToolPermission.ALWAYS
            )
            decision = ToolDecision(
                verdict=ToolExecutionResponse.EXECUTE, approval_type=tool_permission
            )

        input_json = dump_canonical_json(tool_call.args_dict)
        input_sha256 = hashlib.sha256(input_json.encode("utf-8")).hexdigest()
        output_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

        output_kind = ToolOutputKind.INLINE
        if status == "failure":
            output_kind = ToolOutputKind.ERROR
        elif not text:
            output_kind = ToolOutputKind.EMPTY
        elif should_artifact_tool_result(text):
            output_kind = ToolOutputKind.ARTIFACTED

        display_text = text
        if should_artifact_tool_result(text) and self._evidence is not None:
            display_text = self._evidence.emit_artifact_written(
                artifact=None,
                display_text=text,
                tool_name=tool_call.tool_name,
                sequence=len(loop.messages),
            )

        loop.messages.append(
            LLMMessage.model_validate(
                loop.format_handler.create_tool_response_message(
                    tool_call, display_text
                )
            )
        )

        if span is not None:
            from rig_relay.core.tracing import set_tool_result

            set_tool_result(span, text)

        if self._evidence is not None:
            self._evidence.emit_tool_call_finished(
                tool_call=tool_call,
                status=status,
                decision=decision,
                result=result,
                input_sha256=input_sha256,
                output_sha256=output_sha256,
                output_kind=output_kind,
            )

        if self._evidence is not None:
            self._evidence.capture_model_observation(tool_call, status, duration_ms)
            self._evidence.emit_tool_reasoning_trace(
                tool_call=tool_call,
                input_sha256=input_sha256,
                output_sha256=output_sha256,
                output_kind=output_kind,
                input_json=input_json,
                text=text,
                duration_ms=duration_ms,
            )

    def tool_failure_event(
        self,
        tool_call: ResolvedToolCall,
        error_msg: str,
        decision: ToolDecision | None = None,
        cancelled: bool = False,
        span: trace.Span | None = None,
    ) -> ToolResultEvent:
        self.handle_tool_response(tool_call, error_msg, "failure", decision, span=span)
        return ToolResultEvent(
            tool_name=tool_call.tool_name,
            tool_class=tool_call.tool_class,
            error=error_msg,
            cancelled=cancelled,
            tool_call_id=tool_call.call_id,
        )
