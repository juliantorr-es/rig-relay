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
    ToolMutationClass,
    ToolOutputKind,
)
from rig_relay.core.tool_runtime_models import (
    RefusalCode,
    ToolRuntimeRefusal,
    ToolRuntimeResult,
    ToolRuntimeStatus,
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

    def handle_failed_tool_response(
        self,
        failed: Any,
        *,
        turn_id: str = "",
        correlation_id: str = "",
        causation_id: str = "",
    ) -> LLMMessage:
        """Append a role=tool message for a failed/unavailable tool call.

        A model-issued tool call that cannot be dispatched (tool unavailable,
        disabled, or argument validation failure) must still produce a bound
        tool observation before the conversation continues.

        Emits structured telemetry for observability AND a canonical
        <rig-tool-outcome> annotation so the model receives truthful
        pre-execution refusal semantics rather than a raw error string.

        Returns the appended LLMMessage for caller inspection.
        """
        loop = self._loop
        error_text = getattr(failed, "error", "Unknown error")

        # ── Classify failure kind for canonical outcome ──────────────
        failure_kind = _classify_failure_kind(error_text)
        refusal_code: RefusalCode
        match failure_kind:
            case "unknown_tool":
                refusal_code = RefusalCode.TOOL_NOT_FOUND
            case "disabled_tool":
                refusal_code = RefusalCode.TOOL_PERMISSION_DENIED
            case _:
                refusal_code = RefusalCode.TOOL_INVOCATION_FAILED

        # ── Construct a pre-execution refused runtime result ─────────
        tool_name = getattr(failed, "tool_name", "unknown")
        call_id = getattr(failed, "call_id", "")
        pre_result = ToolRuntimeResult(
            status=ToolRuntimeStatus.REFUSED,
            tool_name=tool_name,
            tool_call_id=call_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            turn_id=turn_id,
            error_kind=failure_kind,
            error_message=error_text,
            refusal=ToolRuntimeRefusal(
                refusal_code=refusal_code, message=error_text, recoverable=False
            ),
            mutation_performed=False,
            investigation_outcome=None,
        )

        # ── Derive agent outcome annotation ─────────────────────────
        from rig_relay.core.tools._agent_outcome import (
            derive_agent_outcome,
            format_agent_outcome,
            neutralize_reserved_delimiters,
        )

        outcome = derive_agent_outcome(
            pre_result,
            _resolve_mutation_class(
                tool_name, tool_manager=getattr(loop, "tool_manager", None)
            ),
        )
        annotation = format_agent_outcome(outcome)
        display_text = neutralize_reserved_delimiters(error_text)
        display_text = (
            f"<tool_error>{tool_name}: {display_text}</tool_error>\n\n{annotation}"
        )

        msg = LLMMessage.model_validate(
            loop.format_handler.create_failed_tool_response_message(
                failed, display_text
            )
        )
        loop.messages.append(msg)

        # ── Emit outcome projection + structured telemetry ───────────
        if self._evidence is not None:
            try:
                self._evidence.emit_agent_outcome_projection(
                    outcome, correlation_id=correlation_id, causation_id=causation_id
                )
            except Exception:
                pass

            try:
                error_sha256 = hashlib.sha256(display_text.encode("utf-8")).hexdigest()
            except Exception:
                error_sha256 = ""

            try:
                self._evidence.emit_tool_call_failed_resolved(
                    tool_name=tool_name,
                    call_id=call_id,
                    error=error_text,
                    failure_kind=failure_kind,
                    error_sha256=error_sha256,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    turn_id=turn_id,
                )
            except Exception:
                pass

        return msg


def _classify_failure_kind(error: str) -> str:
    """Classify the failure kind from the error message text.

    Returns one of: 'unknown_tool', 'disabled_tool', 'malformed_args', 'resolution_failure'
    """
    if (
        "Unknown tool" in error
        or "not found" in error.lower()
        or "unavailable" in error.lower()
    ):
        return "unknown_tool"
    if "disabled" in error.lower() or "not permitted" in error.lower():
        return "disabled_tool"
    if (
        "invalid" in error.lower()
        or "malformed" in error.lower()
        or "validation" in error.lower()
    ):
        return "malformed_args"
    return "resolution_failure"


_MUTATION_TOOL_NAMES: frozenset[str] = frozenset({
    "search_replace",
    "write_file",
    "patch_file",
    "checkpoint",
})


def _resolve_mutation_class(
    tool_name: str, tool_manager: Any = None
) -> ToolMutationClass:
    """Return the mutation class for a tool name.

    Prefers canonical tool registry lookup via tool_manager.available_tools.
    Falls back to a minimal hardcoded list for known built-in mutation tools
    when no registry is available.

    Unknown/untrusted tools default to READ_ONLY (safe — they cannot have
    mutated state).
    """
    if tool_manager is not None and hasattr(tool_manager, "available_tools"):
        available = tool_manager.available_tools
        tool_cls = available.get(tool_name)
        if tool_cls is not None:
            mc = getattr(tool_cls, "mutation_class", None)
            if mc is not None:
                if hasattr(mc, "value"):
                    return mc
                return ToolMutationClass(str(mc))
    if tool_name in _MUTATION_TOOL_NAMES:
        return ToolMutationClass.WRITES_WORKSPACE
    return ToolMutationClass.READ_ONLY
