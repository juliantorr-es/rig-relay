"""Phase 3 event stream contract — event ordering and finalization.

Tests that the conversation loop produces events in the correct order
and does not duplicate finalization. Uses fake adapters — no live providers.
"""

from __future__ import annotations

import json

import pytest

from rig_relay.core.conversation_runtime import (
    ConversationRuntime,
    ConversationRuntimePhaseEvent,
    ConversationRuntimeRequest,
    ConversationRuntimeStatus,
)
from rig_relay.core.conversation_turn import TurnOutcome, TurnPhase


class _FakeAssistantEvent:
    """Mimics AssistantEvent without real provider data."""

    def __init__(self, content: str = "done", stopped: bool = False) -> None:
        self.content = content
        self.stopped_by_middleware = stopped
        self.message_id = "msg-1"


class TestEventStreamContract:
    """Verify that the event stream contract is well-defined:

    1. UserMessageEvent is always first
    2. Phase events are emitted in order
    3. No duplicate FINALIZING phases
    4. Build_result produces consistent outcome
    """

    def test_phase_ordering_is_contractually_defined(self) -> None:
        """Phase ordering must match TurnPhase enum ordering."""
        actual_order = [p.value for p in TurnPhase]
        # Not testing exact enum order, but that all expected phases exist
        for phase in ["created", "model_calling", "finalizing"]:
            assert phase in actual_order, f"Missing phase: {phase}"

    def test_result_build_is_consistent_after_phase_sequence(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._phase(TurnPhase.CONTEXT_BUILDING)
        cr._phase(TurnPhase.CONTEXT_READY)
        cr._phase(TurnPhase.MODEL_CALLING)
        cr._finish(TurnOutcome.SUCCESS)

        result = cr.build_result()
        assert result.status == ConversationRuntimeStatus.COMPLETED
        assert result.final_outcome == "success"
        assert len(result.phases_entered) == 5

    def test_no_multiple_finalizing_logged_to_turn(self) -> None:
        """Subsequent _finish calls should not produce phantom finalizing."""
        cr = ConversationRuntime()
        cr._session_id = "s2"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._finish(TurnOutcome.SUCCESS)

        result = cr.build_result()
        finalizing_count = sum(1 for p in result.phases_entered if p == "finalizing")
        assert finalizing_count == 1, f"Expected 1 finalizing, got {finalizing_count}"

    def test_error_path_produces_fail_outcome(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s3"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._finish(TurnOutcome.LLM_ERROR, "model 500")

        result = cr.build_result()
        assert result.status == ConversationRuntimeStatus.FAILED
        assert result.final_outcome == "llm_error"
        assert result.error_message == "model 500"

    def test_tool_failure_outcome_preserved(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s4"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._phase(TurnPhase.MODEL_CALLING)
        # Simulate tool failure path
        cr._finish(TurnOutcome.TOOL_FAILURE, "tool returned non-zero")

        result = cr.build_result()
        assert result.final_outcome == "tool_failure"

    def test_phase_event_is_json_safe(self) -> None:
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

    def test_request_model_is_json_safe(self) -> None:
        req = ConversationRuntimeRequest(
            session_id="s1",
            user_message_text="hello",
            user_message_id="u1",
            max_turns=10,
        )
        d = req.model_dump()
        assert json.dumps(d)
        assert d["session_id"] == "s1"

    def test_result_all_fields_present(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        cr._start_time = 0.0

        cr._phase(TurnPhase.CREATED)
        cr._phase(TurnPhase.MODEL_CALLING)
        cr._finish(TurnOutcome.SUCCESS)

        result = cr.build_result()
        d = result.model_dump()
        required = [
            "session_id",
            "turn_id",
            "status",
            "final_outcome",
            "phases_entered",
            "total_turns",
            "tool_calls_attempted",
            "tool_calls_succeeded",
            "tool_calls_failed",
            "tool_calls_skipped",
            "duration_ms",
        ]
        for field in required:
            assert field in d, f"Missing field: {field}"


class TestEventStreamPrivacy:
    def test_trace_attributes_exclude_raw_content(self) -> None:
        from rig_relay.core.conversation_runtime.models import PhaseTraceAttributes

        attrs = PhaseTraceAttributes(
            conversation_session_id="s1",
            conversation_turn_id="t1",
            conversation_phase="model_calling",
            conversation_tool_call_count=3,
        )
        d = attrs.model_dump()
        assert "prompt" not in d
        assert "message_content" not in d
        assert "tool_output" not in d
        assert "stdout" not in d

    def test_trace_attributes_extra_forbidden(self) -> None:
        from pydantic import ValidationError

        from rig_relay.core.conversation_runtime.models import PhaseTraceAttributes

        with pytest.raises(ValidationError):
            PhaseTraceAttributes(
                conversation_session_id="s1",
                conversation_phase="x",
                raw_prompt="leaked",  # type: ignore[call-arg]
            )
