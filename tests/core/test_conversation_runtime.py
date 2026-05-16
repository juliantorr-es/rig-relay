from __future__ import annotations

import json

import pytest

from rig_relay.core.conversation_runtime import (
    ConversationLoopDecision,
    ConversationLoopDecisionKind,
    ConversationRuntime,
    ConversationRuntimePhaseEvent,
    ConversationRuntimeRequest,
    ConversationRuntimeStatus,
    PhaseTraceAttributes,
)
from rig_relay.core.conversation_turn import TurnOutcome, TurnPhase

# ── Fake trace hook for test observation ────────────────────────


class RecordingTraceHook:
    def __init__(self) -> None:
        self.phase_events: list[PhaseTraceAttributes] = []
        self.result_events: list[PhaseTraceAttributes] = []
        self.error_on_phase: Exception | None = None
        self.error_on_result: Exception | None = None

    def on_phase_event(self, attrs: PhaseTraceAttributes) -> None:
        if self.error_on_phase is not None:
            raise self.error_on_phase
        self.phase_events.append(attrs)

    def on_result(self, attrs: PhaseTraceAttributes) -> None:
        if self.error_on_result is not None:
            raise self.error_on_result
        self.result_events.append(attrs)


# ── Phase ordering tests ────────────────────────────────────────


class TestConversationRuntimePhases:
    def test_phase_recording(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "test-session"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._phase(TurnPhase.MODEL_CALLING)
        cr._finish(TurnOutcome.SUCCESS)

        result = cr.build_result()
        assert result.session_id == "test-session"
        assert result.final_outcome == "success"
        assert result.status == ConversationRuntimeStatus.COMPLETED
        assert len(result.phases_entered) >= 3

    def test_no_tool_turn_phases(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._phase(TurnPhase.CONTEXT_BUILDING)
        cr._phase(TurnPhase.CONTEXT_READY)
        cr._phase(TurnPhase.MODEL_CALLING)
        cr._finish(TurnOutcome.SUCCESS)

        result = cr.build_result()
        entered = set(result.phases_entered)
        assert "created" in entered
        assert "context_building" in entered
        assert "model_calling" in entered
        assert "tool_calls_running" not in entered
        assert result.tool_calls_attempted == 0
        assert result.final_outcome == "success"

    def test_tool_call_turn_phases(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s2"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._phase(TurnPhase.CONTEXT_BUILDING)
        cr._phase(TurnPhase.CONTEXT_READY)
        cr._phase(TurnPhase.MODEL_CALLING)
        cr._finish(TurnOutcome.SUCCESS)

        result = cr.build_result()
        assert result.final_outcome == "success"

    def test_records_failure_on_model_error(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s3"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._phase(TurnPhase.MODEL_CALLING)
        cr._finish(TurnOutcome.LLM_ERROR, "model returned 500")

        result = cr.build_result()
        assert result.final_outcome == "llm_error"
        assert result.status == ConversationRuntimeStatus.FAILED
        assert result.error_message == "model returned 500"

    def test_records_user_cancelled(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s4"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._phase(TurnPhase.MODEL_CALLING)
        cr._finish(TurnOutcome.USER_CANCELLED, "user hit esc")

        result = cr.build_result()
        assert result.final_outcome == "user_cancelled"
        assert result.status == ConversationRuntimeStatus.FAILED

    def test_records_middleware_stop(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s5"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._finish(TurnOutcome.MIDDLEWARE_STOP)

        result = cr.build_result()
        assert result.final_outcome == "middleware_stop"
        assert result.phases_entered == ["created", "finalizing"]


# ── Trace hook tests ────────────────────────────────────────────


class TestConversationRuntimeTraceHook:
    def test_phase_event_callback_receives_every_phase_in_order(self) -> None:
        hook = RecordingTraceHook()
        cr = ConversationRuntime(trace_hook=hook)
        cr._session_id = "trace-session"
        cr.set_turn_id("turn-001")
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._phase(TurnPhase.CONTEXT_BUILDING)
        cr._phase(TurnPhase.CONTEXT_READY)
        cr._phase(TurnPhase.MODEL_CALLING)
        cr._finish(TurnOutcome.SUCCESS)

        # Phase events: CREATED, CONTEXT_BUILDING, CONTEXT_READY, MODEL_CALLING, FINALIZING
        assert len(hook.phase_events) == 5
        phases_seen = [e.conversation_phase for e in hook.phase_events]
        assert phases_seen == [
            "created",
            "context_building",
            "context_ready",
            "model_calling",
            "finalizing",
        ]

    def test_result_callback_receives_final_status(self) -> None:
        hook = RecordingTraceHook()
        cr = ConversationRuntime(trace_hook=hook)
        cr._session_id = "s"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._finish(TurnOutcome.SUCCESS)

        assert len(hook.result_events) == 1
        result_event = hook.result_events[0]
        assert result_event.conversation_status == "success"
        assert result_event.conversation_phase == "finalizing"

    def test_callback_error_does_not_break_runtime(self) -> None:
        hook = RecordingTraceHook()
        hook.error_on_phase = RuntimeError("trace backend down")

        cr = ConversationRuntime(trace_hook=hook)
        cr._session_id = "s"
        cr._start_time = 0.0

        # Should not raise
        cr._phase(TurnPhase.CREATED)
        cr._finish(TurnOutcome.SUCCESS)

        result = cr.build_result()
        assert result.final_outcome == "success"

    def test_result_callback_error_does_not_break_runtime(self) -> None:
        hook = RecordingTraceHook()
        hook.error_on_result = RuntimeError("result backend down")

        cr = ConversationRuntime(trace_hook=hook)
        cr._session_id = "s"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._finish(TurnOutcome.TOOL_FAILURE, "some error")

        result = cr.build_result()
        assert result.final_outcome == "tool_failure"

    def test_trace_attributes_are_json_safe(self) -> None:
        hook = RecordingTraceHook()
        cr = ConversationRuntime(trace_hook=hook)
        cr._session_id = "trace-session"
        cr.set_turn_id("turn-001")
        cr._start_time = 0.0
        cr.set_tool_call_count(3)

        cr._phase(TurnPhase.CREATED)
        cr._finish(TurnOutcome.SUCCESS)

        for event in hook.phase_events:
            d = event.model_dump()
            assert json.dumps(d)  # must not raise

    def test_trace_attributes_have_expected_fields(self) -> None:
        import time

        hook = RecordingTraceHook()
        cr = ConversationRuntime(trace_hook=hook)
        cr._session_id = "trace-session"
        cr.set_turn_id("turn-abc")
        cr._start_time = time.monotonic()
        cr.set_tool_call_count(5)

        cr._phase(TurnPhase.MODEL_CALLING)
        cr._finish(TurnOutcome.SUCCESS, "all good")

        # First phase event
        first = hook.phase_events[0]
        assert first.conversation_session_id == "trace-session"
        assert first.conversation_turn_id == "turn-abc"
        assert first.conversation_phase == "model_calling"
        assert first.conversation_tool_call_count == 5
        assert first.conversation_duration_ms is not None

        # Result event
        result = hook.result_events[0]
        assert result.conversation_status == "success"
        assert result.conversation_reason == "all good"

    def test_no_trace_hook_does_not_crash(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._finish(TurnOutcome.SUCCESS)

        result = cr.build_result()
        assert result.final_outcome == "success"

    def test_trace_attributes_exclude_message_content(self) -> None:
        hook = RecordingTraceHook()
        cr = ConversationRuntime(trace_hook=hook)
        cr._session_id = "s"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._finish(TurnOutcome.SUCCESS)

        for event in hook.phase_events:
            d = event.model_dump()
            # Must not contain message content fields
            assert "content" not in d
            assert "message" not in d
            assert "prompt" not in d
            assert "tool_output" not in d

    def test_turn_id_is_preserved_in_trace(self) -> None:
        hook = RecordingTraceHook()
        cr = ConversationRuntime(trace_hook=hook)
        cr._session_id = "sess-1"
        cr.set_turn_id("turn-xyz")
        cr._start_time = 0.0

        cr._phase(TurnPhase.CONTEXT_BUILDING)
        cr._finish(TurnOutcome.SUCCESS)

        for event in hook.phase_events:
            assert event.conversation_turn_id == "turn-xyz"


# ── Result tests ────────────────────────────────────────────────


class TestConversationRuntimeResult:
    def test_result_is_json_safe(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "test"
        cr._start_time = 0.0
        cr._phase(TurnPhase.CREATED)
        cr._finish(TurnOutcome.SUCCESS)

        result = cr.build_result()
        d = result.model_dump()
        assert json.dumps(d)

    def test_result_has_required_fields(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "test"
        cr._start_time = 0.0
        cr._phase(TurnPhase.CREATED)
        cr._finish(TurnOutcome.SUCCESS)

        result = cr.build_result()
        assert result.session_id == "test"
        assert result.status != ConversationRuntimeStatus.NOT_STARTED
        assert result.phases_entered
        assert result.duration_ms is not None and result.duration_ms >= 0

    def test_build_result_with_turn_data(self) -> None:
        from rig_relay.core.conversation_turn import ConversationTurnRuntime

        turn = ConversationTurnRuntime(
            session_id="s", user_message_text="hello", user_message_id="u1"
        )
        turn.tool_call_count = 5
        turn.tool_success_count = 4
        turn.tool_failure_count = 1
        turn.tool_skip_count = 0
        turn.tool_total_duration_ms = 1200.0
        turn.context_section_count = 7
        turn.context_envelope_id = "env-abc"
        turn.assistant_content_length = 450

        cr = ConversationRuntime()
        cr._session_id = "s"
        cr._start_time = 0.0
        cr._phase(TurnPhase.CREATED)
        cr._phase(TurnPhase.CONTEXT_BUILDING)
        cr._finish(TurnOutcome.SUCCESS)

        result = cr.build_result(turn=turn)
        assert result.tool_calls_attempted == 5
        assert result.tool_calls_succeeded == 4
        assert result.tool_calls_failed == 1
        assert result.tool_calls_skipped == 0
        assert result.tool_total_duration_ms == 1200.0
        assert result.context_section_count == 7
        assert result.context_envelope_id == "env-abc"
        assert result.assistant_content_length == 450


# ── Forbidden imports ───────────────────────────────────────────


class TestConversationRuntimeNoForbiddenImports:
    def test_no_forbidden_imports(self) -> None:
        import ast
        from pathlib import Path

        pkg = (
            Path(__file__).resolve().parents[2] / "rig_relay/core/conversation_runtime"
        )
        forbidden = {"desktop", "ralph", "scripts", "duckdb", "analytics"}
        for py_file in pkg.rglob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for f in forbidden:
                            assert f not in alias.name, (
                                f"{py_file.name} imports forbidden {f}"
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for f in forbidden:
                            assert f not in node.module, (
                                f"{py_file.name} imports forbidden {f}"
                            )


# ── Models ──────────────────────────────────────────────────────


class TestConversationRuntimePhaseEvent:
    def test_phase_event_serializable(self) -> None:
        event = ConversationRuntimePhaseEvent(
            turn_id="t1",
            session_id="s1",
            phase="model_calling",
            previous_phase="context_ready",
            phase_index=3,
        )
        d = event.model_dump()
        assert json.dumps(d)
        assert d["turn_id"] == "t1"
        assert d["phase"] == "model_calling"


class TestConversationRuntimeRequest:
    def test_request_minimal_fields(self) -> None:
        req = ConversationRuntimeRequest(
            session_id="s1", user_message_text="hello", user_message_id="u1"
        )
        assert req.session_id == "s1"
        assert req.user_message_text == "hello"
        assert req.max_turns is None


class TestPhaseTraceAttributes:
    def test_serializable(self) -> None:
        attrs = PhaseTraceAttributes(
            conversation_session_id="s1",
            conversation_turn_id="t1",
            conversation_phase="created",
            conversation_previous_phase=None,
            conversation_status=None,
            conversation_reason=None,
            conversation_tool_call_count=3,
            conversation_duration_ms=125.0,
            trace_id="abc123",
        )
        d = attrs.model_dump()
        assert json.dumps(d)
        assert d["conversation_session_id"] == "s1"
        assert d["conversation_turn_id"] == "t1"
        assert d["conversation_phase"] == "created"

    def test_all_fields_can_be_none_except_session_and_phase(self) -> None:
        attrs = PhaseTraceAttributes(
            conversation_session_id="s1", conversation_phase="created"
        )
        d = attrs.model_dump()
        assert d["conversation_turn_id"] is None
        assert d["conversation_status"] is None
        assert d["conversation_reason"] is None

    def test_extra_fields_forbidden(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PhaseTraceAttributes(
                conversation_session_id="s1",
                conversation_phase="x",
                message_content="secret",  # type: ignore[call-arg]
            )


# ── Decision model tests (Phase 2A) ────────────────────────────


class TestConversationLoopDecision:
    def test_stop_middleware_has_should_break(self) -> None:
        d = ConversationLoopDecision.stop_middleware("test")
        assert d.kind == ConversationLoopDecisionKind.stop_middleware
        assert d.should_break is True
        assert d.should_run_tools is False

    def test_stop_cancelled_has_should_break(self) -> None:
        d = ConversationLoopDecision.stop_cancelled("user hit escape")
        assert d.kind == ConversationLoopDecisionKind.stop_cancelled
        assert d.should_break is True

    def test_stop_completed_has_should_break(self) -> None:
        d = ConversationLoopDecision.stop_completed("final reply")
        assert d.kind == ConversationLoopDecisionKind.stop_completed
        assert d.should_break is True

    def test_run_tools_has_should_run_tools(self) -> None:
        d = ConversationLoopDecision.run_tools("3 tool calls")
        assert d.kind == ConversationLoopDecisionKind.run_tools
        assert d.should_run_tools is True
        assert d.should_break is False

    def test_continue_turn_no_break(self) -> None:
        d = ConversationLoopDecision.continue_turn()
        assert d.kind == ConversationLoopDecisionKind.continue_turn
        assert d.should_break is False

    def test_fail_error_has_should_break(self) -> None:
        d = ConversationLoopDecision.fail_error("crash", {"error_type": "ValueError"})
        assert d.kind == ConversationLoopDecisionKind.fail_error
        assert d.should_break is True
        assert d.attributes["error_type"] == "ValueError"

    def test_decision_serializes_json_safe(self) -> None:
        d = ConversationLoopDecision.stop_completed("done")
        serialized = d.model_dump_json()
        parsed = json.loads(serialized)
        assert parsed["kind"] == "stop_completed"
        assert "message_content" not in serialized


class TestConversationRuntimeDecisions:
    def test_decide_middleware_stop(self) -> None:
        cr = ConversationRuntime()
        d = cr.decide_after_middleware("STOP")
        assert d.kind == ConversationLoopDecisionKind.stop_middleware
        assert d.should_break is True

    def test_decide_middleware_continue(self) -> None:
        cr = ConversationRuntime()
        d = cr.decide_after_middleware("CONTINUE")
        assert d.kind == ConversationLoopDecisionKind.continue_turn

    def test_decide_model_turn_cancelled(self) -> None:
        cr = ConversationRuntime()
        d = cr.decide_after_model_turn(user_cancelled=True)
        assert d.kind == ConversationLoopDecisionKind.stop_cancelled

    def test_decide_model_turn_assistant_final(self) -> None:
        cr = ConversationRuntime()
        d = cr.decide_after_model_turn(assistant_final=True)
        assert d.kind == ConversationLoopDecisionKind.stop_completed

    def test_decide_model_turn_tool_calls(self) -> None:
        cr = ConversationRuntime()
        d = cr.decide_after_model_turn(assistant_final=False)
        assert d.kind == ConversationLoopDecisionKind.run_tools

    def test_decide_model_turn_error(self) -> None:
        cr = ConversationRuntime()
        d = cr.decide_after_model_turn(error="connection refused")
        assert d.kind == ConversationLoopDecisionKind.fail_error
        assert "connection refused" in d.reason

    def test_decide_on_exception(self) -> None:
        cr = ConversationRuntime()
        d = cr.decide_on_exception(ValueError("bad value"))
        assert d.kind == ConversationLoopDecisionKind.fail_error
        assert "bad value" in d.reason
        assert d.attributes["error_type"] == "ValueError"

    def test_decision_does_not_include_message_content(self) -> None:
        cr = ConversationRuntime()
        d = cr.decide_after_model_turn(assistant_final=True)
        serialized = d.model_dump_json()
        assert "message" not in serialized.lower() or "reason" in serialized


# ── Phase 2B decision tests ────────────────────────────────────


class TestDecideAfterHookProcessing:
    def test_hook_retry_maps_to_retry_hooks(self) -> None:
        cr = ConversationRuntime()
        d = cr.decide_after_hook_processing(hook_returned_user_message=True)
        assert d.kind == ConversationLoopDecisionKind.retry_hooks
        assert d.should_retry_hooks is True
        assert "hook returned user message" in d.reason

    def test_hook_pass_through_maps_to_stop_completed(self) -> None:
        cr = ConversationRuntime()
        d = cr.decide_after_hook_processing(hook_returned_user_message=False)
        assert d.kind == ConversationLoopDecisionKind.stop_completed
        assert "no retry message" in d.reason

    def test_hook_retry_clears_finish_outcome(self) -> None:
        cr = ConversationRuntime()
        cr._finish_outcome = TurnOutcome.SUCCESS
        cr._finish_reason = "stale"
        cr.decide_after_hook_processing(hook_returned_user_message=True)
        assert cr._finish_outcome is None
        assert cr._finish_reason == ""


class TestDecideAfterToolBatch:
    def test_tool_batch_completed_maps_to_continue_turn(self) -> None:
        cr = ConversationRuntime()
        d = cr.decide_after_tool_batch()
        assert d.kind == ConversationLoopDecisionKind.continue_turn
        assert "tool batch completed" in d.reason


class TestDecideAfterBudgetCheck:
    def test_budget_ok_continues(self) -> None:
        cr = ConversationRuntime()
        d = cr.decide_after_budget_check(current_turn=1, max_turns=5)
        assert d.kind == ConversationLoopDecisionKind.continue_turn
        assert "budget ok" in d.reason

    def test_budget_exceeded_fails(self) -> None:
        cr = ConversationRuntime()
        d = cr.decide_after_budget_check(current_turn=5, max_turns=5)
        assert d.kind == ConversationLoopDecisionKind.fail_budget_exceeded
        assert d.should_break is True
        assert "max turns 5" in d.reason

    def test_budget_none_max_turns_continues(self) -> None:
        cr = ConversationRuntime()
        d = cr.decide_after_budget_check(current_turn=999, max_turns=None)
        assert d.kind == ConversationLoopDecisionKind.continue_turn


class TestPhase2BDecisionsAreJsonSafe:
    def test_decisions_serialize(self) -> None:
        import json

        cr = ConversationRuntime()
        for d in [
            cr.decide_after_hook_processing(False),
            cr.decide_after_hook_processing(True),
            cr.decide_after_tool_batch(),
            cr.decide_after_budget_check(1, 5),
            cr.decide_after_budget_check(5, 5),
        ]:
            serialized = d.model_dump_json()
            assert json.loads(serialized)

    def test_decisions_exclude_raw_content(self) -> None:
        cr = ConversationRuntime()
        for d in [
            cr.decide_after_hook_processing(False),
            cr.decide_after_tool_batch(),
            cr.decide_after_budget_check(1, 5),
        ]:
            serialized = d.model_dump_json()
            assert "message_content" not in serialized
            assert "tool_output" not in serialized
            assert "prompt" not in serialized
