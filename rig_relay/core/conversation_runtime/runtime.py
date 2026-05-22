"""ConversationRuntime — phase event recorder, result builder, trace emitter, and loop owner.

ConversationRuntime owns turn sequencing, decision policy, phase tracking,
and loop continuation decisions. AgentLoop delegates turn execution to it
via ConversationRuntimeCallbacks.

Phase trace hooks allow consumers (desktop, analytics, observability) to
observe phase transitions without coupling to AgentLoop internals.

Architecture boundary: must NOT import desktop, ralph, scripts,
duckdb, or analytics.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
import time
from typing import Any

from rig_relay.core.conversation_runtime import _decisions, _trace_hooks
from rig_relay.core.conversation_runtime.models import (
    ConversationLoopDecision,
    ConversationRuntimeCallbacks,
    ConversationRuntimePhaseEvent,
    ConversationRuntimeResult,
    ConversationRuntimeStatus,
    PhaseTraceAttributes,
    PhaseTraceHook,
)
from rig_relay.core.conversation_turn import TurnOutcome, TurnPhase
from rig_relay.core.logger import logger
from rig_relay.core.types import BaseEvent


class ConversationRuntime:
    """Phase observer, result builder, trace emitter, and loop owner.

    Called from AgentLoop._conversation_loop at each phase transition.
    Owns the phase event log, builds the turn result, and drives the
    while-loop continuation decisions.

    Accepts optional PhaseTraceHook callbacks for structured trace
    evidence. Callback errors are caught and logged — they never
    propagate to the caller.
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
        return _trace_hooks.build_trace_attrs(
            session_id=self._session_id,
            turn_id=self._turn_id,
            phase=phase,
            previous=previous,
            status=status,
            reason=reason,
            tool_call_count=self._tool_call_count,
            start_time=self._start_time,
            trace_id=self._trace_id,
        )

    def _emit_trace(self, phase: TurnPhase, previous: str | None) -> None:
        if self._trace_hook is None:
            return
        try:
            attrs = self._build_trace_attrs(str(phase.value), previous=previous)
            _trace_hooks.emit_phase_event(self._trace_hook, attrs)
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
            _trace_hooks.emit_result_event(self._trace_hook, attrs)
        except Exception:
            logger.debug("Result trace hook error", exc_info=True)

    def _capture_trace_id(self) -> None:
        if self._trace_id is not None:
            return
        trace_id = _trace_hooks.capture_trace_id()
        if trace_id is not None:
            self._trace_id = trace_id

    # ── Decision methods (delegate to _decisions) ──────────────

    def decide_after_middleware(self, action: str) -> ConversationLoopDecision:
        decision = _decisions.decide_after_middleware(action)
        if decision.kind == "stop_middleware":
            self._finish_decision(TurnOutcome.MIDDLEWARE_STOP)
        return decision

    def decide_after_model_turn(
        self,
        user_cancelled: bool = False,
        assistant_final: bool = True,
        error: str | None = None,
    ) -> ConversationLoopDecision:
        decision = _decisions.decide_after_model_turn(
            user_cancelled=user_cancelled, assistant_final=assistant_final, error=error
        )
        if decision.kind == "fail_error":
            self._finish_decision(TurnOutcome.LLM_ERROR)
        elif decision.kind == "stop_cancelled":
            self._finish_decision(TurnOutcome.USER_CANCELLED)
        elif decision.kind == "stop_completed":
            self._finish_decision(TurnOutcome.SUCCESS)
        return decision

    def decide_on_exception(self, exc: Exception) -> ConversationLoopDecision:
        decision = _decisions.decide_on_exception(exc)
        self._finish_decision(TurnOutcome.LLM_ERROR)
        return decision

    def decide_after_hook_processing(
        self, hook_returned_user_message: bool = False
    ) -> ConversationLoopDecision:
        decision = _decisions.decide_after_hook_processing(
            hook_returned_user_message=hook_returned_user_message
        )
        if decision.kind == "retry_hooks":
            self._finish_outcome = None
            self._finish_reason = ""
        return decision

    def decide_after_tool_batch(self) -> ConversationLoopDecision:
        return _decisions.decide_after_tool_batch()

    def decide_after_budget_check(
        self, current_turn: int, max_turns: int | None
    ) -> ConversationLoopDecision:
        decision = _decisions.decide_after_budget_check(
            current_turn=current_turn, max_turns=max_turns
        )
        if decision.kind == "fail_budget_exceeded":
            self._finish_decision(TurnOutcome.LLM_ERROR)
        return decision

    def _finish_decision(self, outcome: TurnOutcome) -> None:
        """Record terminal decision outcome without emitting extra phase."""
        self._finish_outcome = outcome
        self._finish_reason = str(outcome.value)

    # ── Core loop ownership (Phase 3) ──────────────────────────

    async def execute_turn_loop(  # noqa: PLR0912, PLR0915
        self, adapter: ConversationRuntimeCallbacks
    ) -> AsyncGenerator[BaseEvent, None]:
        """Execute the conversation turn loop.

        Owns the while-loop, phase sequencing, decision policy, and
        outcome classification. Delegates execution mechanics to
        the adapter.
        """
        try:
            first_llm_turn = True
            turn_count = 0
            while True:
                turn_count += 1

                # ── Budget check (before each iteration) ───
                max_turns = adapter.check_max_turns()
                if max_turns is not None:
                    budget_decision = self.decide_after_budget_check(
                        turn_count - 1, max_turns
                    )
                    if budget_decision.kind == "fail_budget_exceeded":
                        self._finish(TurnOutcome.LLM_ERROR)
                        adapter.mark_turn_outcome(
                            TurnOutcome.LLM_ERROR, budget_decision.reason
                        )
                        return

                # ── Middleware ──────────────────────────────
                result, mw_events = await adapter.middleware_before_turn({})
                for event in mw_events:
                    yield event

                mw_action = getattr(result, "action", None)
                mw_action_str = str(mw_action) if mw_action else ""
                decision = self.decide_after_middleware(mw_action_str)
                if decision.kind == "stop_middleware":
                    adapter.mark_turn_outcome(
                        TurnOutcome.MIDDLEWARE_STOP, "middleware action STOP"
                    )
                    return

                # ── Context building (first turn only) ───────
                if first_llm_turn:
                    first_llm_turn = False
                    self._phase(TurnPhase.CONTEXT_BUILDING)
                    adapter.get_turn().advance(TurnPhase.CONTEXT_BUILDING)
                    envelope = await adapter.build_context_envelope(None)  # type: ignore[reportArgumentType]
                    if envelope is not None:
                        adapter.set_context_envelope(envelope)
                    self._phase(TurnPhase.CONTEXT_READY)
                    adapter.get_turn().advance(TurnPhase.CONTEXT_READY)

                # ── LLM turn ────────────────────────────────
                self._phase(TurnPhase.MODEL_CALLING)
                adapter.get_turn().advance(TurnPhase.MODEL_CALLING)

                user_cancelled = False
                async for event in adapter.stream_llm_turn():
                    if adapter.is_user_cancellation_event(event):
                        user_cancelled = True
                    yield event

                # ── Decision after model turn ───────────────
                batch_result = adapter.get_turn_batch_result()
                should_break = not batch_result.has_tool_work
                decision = self.decide_after_model_turn(
                    user_cancelled=user_cancelled, assistant_final=should_break
                )

                if decision.kind == "stop_cancelled":
                    self._finish(TurnOutcome.USER_CANCELLED, "user cancelled")
                    adapter.mark_turn_outcome(
                        TurnOutcome.USER_CANCELLED, "user cancelled"
                    )
                    return

                if decision.kind == "fail_error":
                    self._finish(TurnOutcome.LLM_ERROR, decision.reason)
                    adapter.mark_turn_outcome(TurnOutcome.LLM_ERROR, decision.reason)
                    return

                if decision.kind == "run_tools":
                    async for event in adapter.execute_tool_batch():
                        yield event
                    self.decide_after_tool_batch()
                    continue

                if decision.kind == "stop_completed":
                    # ── Hook processing ──────────────────
                    hook_retry = None
                    async for hook_event in adapter.stream_hooks_post_turn():
                        if adapter.is_hook_user_message(hook_event):
                            hook_retry = hook_event
                        else:
                            yield hook_event
                    hook_decision = self.decide_after_hook_processing(
                        hook_returned_user_message=hook_retry is not None
                    )
                    if hook_decision.kind == "retry_hooks":
                        adapter.inject_hook_message(hook_retry)
                        continue
                    break

                if decision.kind == "fail_budget_exceeded":
                    adapter.mark_turn_outcome(TurnOutcome.LLM_ERROR, decision.reason)
                    return

                break

            self._finish(TurnOutcome.SUCCESS)
            adapter.mark_turn_outcome(TurnOutcome.SUCCESS, "completed")

        except Exception as exc:
            self._finish(TurnOutcome.LLM_ERROR, str(exc)[:500])
            adapter.mark_turn_outcome(TurnOutcome.LLM_ERROR, str(exc)[:500])
            raise

        finally:
            adapter.persist_turn_state()
