from __future__ import annotations

from rig_relay.core.runtime_state import AgentRuntimeState, ReadinessState


class TestAgentRuntimeStateDefaults:
    def test_default_state_has_empty_session_id(self):
        state = AgentRuntimeState()
        assert state.session_id == ""

    def test_default_readiness_is_unknown(self):
        state = AgentRuntimeState()
        assert state.readiness == ReadinessState.UNKNOWN

    def test_default_stats_are_zero(self):
        state = AgentRuntimeState()
        assert state.steps == 0
        assert state.tool_calls_succeeded == 0
        assert state.tool_calls_failed == 0


class TestAgentRuntimeStateHelpers:
    def test_to_debug_dict_excludes_callbacks(self):
        state = AgentRuntimeState(session_id="s1")
        d = state.to_debug_dict()
        assert "session_id" in d
        assert "callback" not in str(d).lower()

    def test_to_debug_dict_is_json_safe(self):
        import json

        state = AgentRuntimeState(session_id="s1", context_tokens=1234)
        json.dumps(state.to_debug_dict())

    def test_readiness_summary_for_ready(self):
        state = AgentRuntimeState(readiness=ReadinessState.READY, init_duration_ms=42)
        assert "ready" in state.readiness_summary()
        assert "42ms" in state.readiness_summary()

    def test_readiness_summary_for_failed(self):
        state = AgentRuntimeState(
            readiness=ReadinessState.FAILED, init_error="something broke"
        )
        assert "failed" in state.readiness_summary()
        assert "something broke" in state.readiness_summary()

    def test_readiness_summary_for_initializing(self):
        state = AgentRuntimeState(readiness=ReadinessState.INITIALIZING)
        assert "initializing" in state.readiness_summary()

    def test_readiness_summary_for_partial_ready(self):
        state = AgentRuntimeState(readiness=ReadinessState.PARTIAL_READY)
        assert "partial_ready" in state.readiness_summary()

    def test_current_session_summary(self):
        state = AgentRuntimeState(
            session_id="abc", agent_profile_name="test-agent", steps=5
        )
        s = state.current_session_summary()
        assert s["session_id"] == "abc"
        assert s["agent"] == "test-agent"
        assert s["steps"] == 5


class TestAgentRuntimeStateRoundtrip:
    def test_fields_preserved_after_create(self):
        state = AgentRuntimeState(
            session_id="s1",
            agent_profile_name="default",
            max_turns=10,
            max_price=5.0,
            session_rules_count=2,
            bypass_tool_permissions=True,
            enable_local_observability=False,
            enable_streaming=True,
            steps=42,
            context_tokens=8000,
            tool_calls_succeeded=3,
            tool_calls_failed=1,
            tool_calls_agreed=4,
            tool_calls_rejected=0,
        )
        assert state.session_id == "s1"
        assert state.max_turns == 10
        assert state.max_price == 5.0
        assert state.session_rules_count == 2
        assert state.bypass_tool_permissions is True
        assert state.enable_local_observability is False
        assert state.enable_streaming is True
        assert state.steps == 42
        assert state.tool_calls_succeeded == 3
        assert state.tool_calls_failed == 1

    def test_snapshot_at_is_set(self):
        state = AgentRuntimeState()
        assert state.snapshot_at


class TestReadinessTransitions:
    def test_all_readiness_values_are_distinct(self):
        values = list(ReadinessState)
        assert len(values) == len(set(values))

    def test_unknown_is_default(self):
        state = AgentRuntimeState()
        assert state.readiness == ReadinessState.UNKNOWN
