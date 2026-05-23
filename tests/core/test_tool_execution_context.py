from __future__ import annotations

from unittest.mock import MagicMock

from rig_relay.core.tool_executor.context import ToolSessionContext, ToolTurnContext


class FakeToolManager:
    def get(self, name: str) -> object:
        return MagicMock()

    @property
    def available_tools(self) -> dict[str, object]:
        return {}


class FakeTraceRuntime:
    def tool_span(self, *, tool_name: str, call_id: str, arguments: str) -> object:
        from contextlib import nullcontext

        return nullcontext()


class FakeResultSink:
    def record(self, result: object) -> None:
        pass


class FakeTelemetryClient:
    def emit_governance_gate_decision(
        self,
        *,
        gate: str,
        decision: str,
        reason: str = "",
        tool_name: str = "",
        mutation_intent: bool = False,
        policy_version: str = "v1",
        severity: str = "info",
        trace_id: str = "",
        span_id: str = "",
        receipt_id: str = "",
        session_id: str | None = None,
        turn_id: str = "",
        operator_action_required: bool = False,
        renewal: bool = False,
    ) -> None:
        pass


class TestToolSessionTurnContextProtocols:
    def test_tool_manager_port_satisfied_by_fake(self) -> None:
        tm = FakeToolManager()
        assert hasattr(tm, "get")
        assert hasattr(tm, "available_tools")

    def test_trace_runtime_port_satisfied(self) -> None:
        tr = FakeTraceRuntime()
        assert hasattr(tr, "tool_span")

    def test_result_sink_port_satisfied_by_fake(self) -> None:
        rs = FakeResultSink()
        assert hasattr(rs, "record")

    def test_governance_telemetry_port_satisfied_by_telemetryclient(self) -> None:
        tc = FakeTelemetryClient()
        assert hasattr(tc, "emit_governance_gate_decision")


class TestToolTurnContextImmutability:
    def test_turn_context_is_immutable(self) -> None:
        ctx = ToolTurnContext(
            turn_id="turn-aaa", user_message_id="msg-111", bypass_permissions=False
        )
        assert ctx.turn_id == "turn-aaa"
        assert ctx.user_message_id == "msg-111"
        assert ctx.bypass_permissions is False

    def test_turn_context_no_leak_across_consecutive_batches(self) -> None:
        ctx1 = ToolTurnContext(
            turn_id="turn-aaa", user_message_id="msg-111", bypass_permissions=False
        )
        ctx2 = ToolTurnContext(
            turn_id="turn-bbb", user_message_id="msg-222", bypass_permissions=True
        )
        assert ctx1.turn_id == "turn-aaa"
        assert ctx2.turn_id == "turn-bbb"
        assert ctx1.bypass_permissions is False
        assert ctx2.bypass_permissions is True

    def test_session_context_is_immutable(self) -> None:
        ctx = ToolSessionContext(
            session_id="session-1",
            tool_manager=FakeToolManager(),
            trace_runtime=FakeTraceRuntime(),
            result_sink=FakeResultSink(),
            telemetry_client=FakeTelemetryClient(),
        )
        assert ctx.session_id == "session-1"

    def test_telemetry_client_is_wired(self) -> None:
        tc = FakeTelemetryClient()
        ctx = ToolSessionContext(
            session_id="s1",
            tool_manager=FakeToolManager(),
            trace_runtime=FakeTraceRuntime(),
            result_sink=FakeResultSink(),
            telemetry_client=tc,
        )
        assert ctx.telemetry_client is tc

    def test_telemetry_client_can_be_none(self) -> None:
        ctx = ToolSessionContext(
            session_id="s1",
            tool_manager=FakeToolManager(),
            trace_runtime=FakeTraceRuntime(),
            result_sink=FakeResultSink(),
            telemetry_client=None,
        )
        assert ctx.telemetry_client is None
