from __future__ import annotations

from rig_relay.core.conversation_turn import (
    ConversationTurnRuntime,
    TurnOutcome,
    TurnPhase,
)


class TestConversationTurnRuntimeDefaults:
    def test_default_phase_is_created(self):
        turn = ConversationTurnRuntime()
        assert turn.phase == TurnPhase.CREATED

    def test_default_outcome_is_unknown(self):
        turn = ConversationTurnRuntime()
        assert turn.outcome == TurnOutcome.UNKNOWN

    def test_turn_id_is_generated(self):
        turn = ConversationTurnRuntime()
        assert turn.turn_id
        assert len(turn.turn_id) == 12

    def test_turn_ids_are_unique(self):
        t1 = ConversationTurnRuntime()
        t2 = ConversationTurnRuntime()
        assert t1.turn_id != t2.turn_id

    def test_created_at_is_set(self):
        turn = ConversationTurnRuntime()
        assert turn.created_at


class TestPhaseTransitions:
    def test_advance_adds_to_history(self):
        turn = ConversationTurnRuntime()
        assert len(turn.phase_history) == 0
        turn.advance(TurnPhase.CONTEXT_BUILDING)
        assert len(turn.phase_history) == 1
        assert turn.phase == TurnPhase.CONTEXT_BUILDING

    def test_advance_multiple_phases(self):
        turn = ConversationTurnRuntime()
        turn.advance(TurnPhase.MODEL_CALLING)
        turn.advance(TurnPhase.ASSISTANT_PARSED)
        turn.advance(TurnPhase.COMPLETED)
        assert len(turn.phase_history) == 3
        assert turn.phase == TurnPhase.COMPLETED

    def test_phase_history_is_fifo(self):
        turn = ConversationTurnRuntime()
        turn.advance(TurnPhase.MODEL_CALLING)
        turn.advance(TurnPhase.COMPLETED)
        first_phase = turn.phase_history[0][0]
        assert first_phase == TurnPhase.CREATED.value


class TestOutcomeMarking:
    def test_mark_outcome_sets_outcome(self):
        turn = ConversationTurnRuntime()
        turn.mark_outcome(TurnOutcome.SUCCESS)
        assert turn.outcome == TurnOutcome.SUCCESS
        assert turn.outcome_at is not None

    def test_mark_outcome_with_reason(self):
        turn = ConversationTurnRuntime()
        turn.mark_outcome(TurnOutcome.TOOL_FAILURE, "bash command failed")
        assert turn.outcome == TurnOutcome.TOOL_FAILURE
        assert "bash command failed" in turn.outcome_reason

    def test_can_represent_failure_phase(self):
        turn = ConversationTurnRuntime()
        turn.advance(TurnPhase.MODEL_CALLING)
        turn.advance(TurnPhase.FAILED)
        turn.mark_outcome(TurnOutcome.LLM_ERROR, "rate limit exceeded")
        assert turn.phase == TurnPhase.FAILED
        assert turn.outcome == TurnOutcome.LLM_ERROR


class TestDebugSnapshot:
    def test_to_debug_dict_is_json_safe(self):
        import json

        turn = ConversationTurnRuntime(session_id="s1")
        turn.advance(TurnPhase.COMPLETED)
        turn.mark_outcome(TurnOutcome.SUCCESS)
        json.dumps(turn.to_debug_dict())

    def test_to_debug_dict_contains_phases(self):
        turn = ConversationTurnRuntime(session_id="s1")
        turn.advance(TurnPhase.CONTEXT_BUILDING)
        d = turn.to_debug_dict()
        assert d["phase"] == TurnPhase.CONTEXT_BUILDING.value
        assert d["phase_count"] == 1

    def test_deterministic_snapshot_same_input(self):
        t1 = ConversationTurnRuntime(session_id="x", user_message_text="hi")
        t2 = ConversationTurnRuntime(session_id="x", user_message_text="hi")
        # Different turn_ids, but structure is identical
        assert t1.session_id == t2.session_id
        assert t1.user_message_text == t2.user_message_text

    def test_summary_line(self):
        turn = ConversationTurnRuntime(session_id="x")
        turn.advance(TurnPhase.COMPLETED)
        turn.mark_outcome(TurnOutcome.SUCCESS)
        line = turn.summary_line()
        assert "turn=" in line
        assert "phase=completed" in line
        assert "outcome=success" in line


class TestConstructionWithoutToolExecution:
    def test_can_construct_without_full_tool_context(self):
        turn = ConversationTurnRuntime(
            session_id="abc", user_message_text="test message"
        )
        assert turn.session_id == "abc"
        assert turn.tool_call_count == 0
        assert turn.tool_success_count == 0

    def test_tool_metadata_starts_zero(self):
        turn = ConversationTurnRuntime()
        assert turn.tool_call_count == 0
        assert turn.tool_success_count == 0
        assert turn.tool_failure_count == 0
        assert turn.tool_skip_count == 0
        assert turn.tool_total_duration_ms == 0.0


class TestPhaseOrder:
    def test_valid_phase_order(self):
        turn = ConversationTurnRuntime()
        valid_order = [
            TurnPhase.CONTEXT_BUILDING,
            TurnPhase.CONTEXT_READY,
            TurnPhase.MODEL_CALLING,
            TurnPhase.ASSISTANT_PARSED,
            TurnPhase.TOOL_CALLS_RUNNING,
            TurnPhase.TOOL_CALLS_COMPLETED,
            TurnPhase.FINALIZING,
            TurnPhase.COMPLETED,
        ]
        for phase in valid_order:
            turn.advance(phase)
        assert len(turn.phase_history) == len(valid_order)
