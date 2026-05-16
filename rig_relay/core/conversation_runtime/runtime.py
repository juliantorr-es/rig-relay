"""ConversationRuntime — phase event recorder, result builder, and trace emitter.

ConversationRuntime observes the turn through _phase() and _finish()
calls from AgentLoop._conversation_loop. It owns the phase event log
and builds a JSON-safe result summary.

Phase trace hooks allow consumers (desktop, analytics, observability) to
observe phase transitions without coupling to AgentLoop internals.

In future slices, ConversationRuntime will own the loop orchestration
itself. Today it observes while AgentLoop retains loop policy.

Architecture boundary: must NOT import desktop, ralph, scripts,
duckdb, or analytics.
"""

from __future__ import annotations

import time
from typing import Any

from rig_relay.core.conversation_runtime.models import (
    ConversationLoopDecision,
    ConversationRuntimePhaseEvent,
    ConversationRuntimeResult,
    ConversationRuntimeStatus,
    PhaseTraceAttributes,
    PhaseTraceHook,
)
from rig_relay.core.conversation_turn import TurnOutcome, TurnPhase
from rig_relay.core.logger import logger


class ConversationRuntime:
    """Phase observer, result builder, and trace emitter.

    Called from AgentLoop._conversation_loop at each phase transition.
    Owns the phase event log and builds the turn result.

    Accepts optional PhaseTraceHook callbacks for structured trace
    evidence. Callback errors are caught and logged — they never
    propagate to the caller.

    Future: will own the loop itself (see extraction plan).
    """

    def __init__(self, *, trace_hook: PhaseTraceHook | None = None) -> None:
        self._phase_events: list[ConversationRuntimePhaseEvent] = []
        self._session_id: str = ""
        self._turn_id: str = ""
        self._start_time: float = 0.0
        self._finish_outcome: TurnOutcome | None = None
        self._finish_reason: str = ""
        self._trace_hook = trace_hook
        self._trace_id: str | None = None
        self._tool_call_count: int | None = None

    def set_turn_id(self, turn_id: str) -> None:
        self._turn_id = turn_id

    def set_tool_call_count(self, count: int) -> None:
        self._tool_call_count = count

    def _phase(self, phase: TurnPhase) -> None:
        previous = self._phase_events[-1].phase if self._phase_events else None
        event = ConversationRuntimePhaseEvent(
            turn_id=self._turn_id,
            session_id=self._session_id,
            phase=str(phase.value),
            previous_phase=str(previous) if previous else None,
            phase_index=len(self._phase_events) + 1,
        )
        self._phase_events.append(event)
        self._emit_trace(phase, previous)
        self._capture_trace_id()

    def _finish(self, outcome: TurnOutcome, reason: str = "") -> None:
        self._phase(TurnPhase.FINALIZING)
        self._finish_outcome = outcome
        self._finish_reason = reason
        self._emit_result_trace()

    def build_result(self, turn: Any = None) -> ConversationRuntimeResult:
        """Build a JSON-safe result from observed phase events."""
        duration_ms = (time.monotonic() - self._start_time) * 1000
        entered = [p.phase for p in self._phase_events]

        outcome = (
            str(self._finish_outcome.value)
            if self._finish_outcome
            else str(TurnOutcome.UNKNOWN.value)
        )

        return ConversationRuntimeResult(
            session_id=self._session_id,
            turn_id=self._turn_id,
            status=(
                ConversationRuntimeStatus.COMPLETED
                if self._finish_outcome == TurnOutcome.SUCCESS
                else ConversationRuntimeStatus.FAILED
            ),
            final_outcome=outcome,
            outcome_reason=self._finish_reason,
            phases_entered=entered,
            total_turns=0,
            tool_calls_attempted=getattr(turn, "tool_call_count", 0) if turn else 0,
            tool_calls_succeeded=getattr(turn, "tool_success_count", 0) if turn else 0,
            tool_calls_failed=getattr(turn, "tool_failure_count", 0) if turn else 0,
            tool_calls_skipped=getattr(turn, "tool_skip_count", 0) if turn else 0,
            tool_total_duration_ms=(
                getattr(turn, "tool_total_duration_ms", 0.0) if turn else 0.0
            ),
            context_section_count=getattr(turn, "context_section_count", 0)
            if turn
            else 0,
            context_envelope_id=getattr(turn, "context_envelope_id", None)
            if turn
            else None,
            llm_calls=0,
            assistant_content_length=(
                getattr(turn, "assistant_content_length", 0) if turn else 0
            ),
            duration_ms=duration_ms,
            error_message=self._finish_reason
            if self._finish_outcome != TurnOutcome.SUCCESS
            else None,
            last_phase=str(self._finish_outcome.value) if self._finish_outcome else "",
        )

    # ── Trace emission ──────────────────────────────────────────

    def _build_trace_attrs(
        self,
        phase: str,
        *,
        previous: str | None = None,
        status: str | None = None,
        reason: str | None = None,
    ) -> PhaseTraceAttributes:
        return PhaseTraceAttributes(
            conversation_session_id=self._session_id,
            conversation_turn_id=self._turn_id or None,
            conversation_phase=phase,
            conversation_previous_phase=previous,
            conversation_status=status,
            conversation_reason=reason,
            conversation_tool_call_count=self._tool_call_count,
            conversation_duration_ms=(
                (time.monotonic() - self._start_time) * 1000
                if self._start_time >= 0
                else None
            ),
            trace_id=self._trace_id,
        )

    def _emit_trace(self, phase: TurnPhase, previous: str | None) -> None:
        if self._trace_hook is None:
            return
        try:
            attrs = self._build_trace_attrs(str(phase.value), previous=previous)
            self._trace_hook.on_phase_event(attrs)
        except Exception:
            logger.debug("Phase trace hook error", exc_info=True)

    def _emit_result_trace(self) -> None:
        if self._trace_hook is None:
            return
        try:
            status = str(self._finish_outcome.value) if self._finish_outcome else None
            attrs = self._build_trace_attrs(
                "finalizing", status=status, reason=self._finish_reason or None
            )
            self._trace_hook.on_result(attrs)
        except Exception:
            logger.debug("Result trace hook error", exc_info=True)

    def _capture_trace_id(self) -> None:
        if self._trace_id is not None:
            return
        try:
            from opentelemetry import trace

            span = trace.get_current_span()
            ctx = span.get_span_context() if span else None
            if ctx is not None and ctx.is_valid:
                self._trace_id = format(ctx.trace_id, "032x")
        except Exception:
            pass

    # ── Decision methods (Phase 2B) ────────────────────────────

    # Phase 2A decisions

    def decide_after_middleware(self, action: str) -> ConversationLoopDecision:
        """Middleware STOP → stop_middleware. Otherwise continue."""
        if action == "STOP":
            self._finish_decision(TurnOutcome.MIDDLEWARE_STOP)
            return ConversationLoopDecision.stop_middleware("middleware action STOP")
        return ConversationLoopDecision.continue_turn("middleware action CONTINUE")

    def decide_after_model_turn(
        self,
        user_cancelled: bool = False,
        assistant_final: bool = True,
        error: str | None = None,
    ) -> ConversationLoopDecision:
        """After LLM turn: decide to stop, continue, or fail."""
        if error:
            self._finish_decision(TurnOutcome.LLM_ERROR)
            return ConversationLoopDecision.fail_error(error)
        if user_cancelled:
            self._finish_decision(TurnOutcome.USER_CANCELLED)
            return ConversationLoopDecision.stop_cancelled("user cancelled")
        if assistant_final:
            self._finish_decision(TurnOutcome.SUCCESS)
            return ConversationLoopDecision.stop_completed("assistant final reply")
        return ConversationLoopDecision.run_tools("tool calls present")

    def decide_on_exception(self, exc: Exception) -> ConversationLoopDecision:
        """Exception → fail_error."""
        self._finish_decision(TurnOutcome.LLM_ERROR)
        return ConversationLoopDecision.fail_error(
            str(exc)[:500], attributes={"error_type": type(exc).__name__}
        )

    # Phase 2B decisions

    def decide_after_hook_processing(
        self, hook_returned_user_message: bool = False
    ) -> ConversationLoopDecision:
        """After processing hooks: retry or accept completion."""
        if hook_returned_user_message:
            self._finish_outcome = None
            self._finish_reason = ""
            return ConversationLoopDecision.retry_hooks(
                "hook returned user message → retry turn"
            )
        return ConversationLoopDecision.stop_completed(
            "hooks processed, no retry message"
        )

    def decide_after_tool_batch(self) -> ConversationLoopDecision:
        """After tool execution batch: continue the turn loop."""
        return ConversationLoopDecision.continue_turn("tool batch completed")

    def decide_after_budget_check(
        self, current_turn: int, max_turns: int | None
    ) -> ConversationLoopDecision:
        """Check max-turn budget. Fail if exceeded."""
        if max_turns is not None and current_turn >= max_turns:
            self._finish_decision(TurnOutcome.LLM_ERROR)
            return ConversationLoopDecision.fail_budget_exceeded(
                f"max turns {max_turns} reached at turn {current_turn}"
            )
        return ConversationLoopDecision.continue_turn("budget ok")

    def _finish_decision(self, outcome: TurnOutcome) -> None:
        """Record terminal decision outcome without emitting extra phase."""
        self._finish_outcome = outcome
        self._finish_reason = str(outcome.value)
