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
from rig_relay.core.tool_runtime_models import ToolRuntimeResult
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
        runtime_result: ToolRuntimeResult | None = None,
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

        corr_id = (
            getattr(runtime_result, "correlation_id", "") or ""
            if runtime_result
            else ""
        )
        cause_id = (
            getattr(runtime_result, "causation_id", "") or "" if runtime_result else ""
        )
        turn_id_val = (
            getattr(runtime_result, "turn_id", "") or "" if runtime_result else ""
        )

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

        # ── Agent outcome projection ──────────────────────────────────
        if runtime_result is not None:
            from rig_relay.core.tools._agent_outcome import (
                derive_agent_outcome,
                format_agent_outcome,
                neutralize_reserved_delimiters,
            )

            outcome = derive_agent_outcome(runtime_result, tool_call.tool_class)
            annotation = format_agent_outcome(outcome)
            display_text = neutralize_reserved_delimiters(display_text)
            display_text = f"{display_text}\n\n{annotation}"

            if self._evidence is not None:
                self._evidence.emit_agent_outcome_projection(
                    outcome, correlation_id=corr_id, causation_id=cause_id
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
                correlation_id=corr_id,
                causation_id=cause_id,
                turn_id=turn_id_val,
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
                correlation_id=corr_id,
                causation_id=cause_id,
                turn_id=turn_id_val,
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

    def handle_failed_tool_response(self, failed: Any) -> LLMMessage:
        """Append a role=tool message for a failed/unavailable tool call.

        A model-issued tool call that cannot be dispatched (tool unavailable,
        disabled, or argument validation failure) must still produce a bound
        tool observation before the conversation continues.
        Returns the appended LLMMessage for caller inspection.
        """
        loop = self._loop
        error_msg = (
            f"<tool_error>{failed.tool_name}: {failed.error}"
            f"</tool_error>"
        )
        msg = LLMMessage.model_validate(
            loop.format_handler.create_failed_tool_response_message(
                failed, error_msg
            )
        )
        loop.messages.append(msg)
        return msg
