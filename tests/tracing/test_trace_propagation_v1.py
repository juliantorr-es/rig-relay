from __future__ import annotations

from uuid import UUID

import pytest

from rig_relay.context.models import ContextMode, ContextRequest
from rig_relay.core.runtime_state import AgentRuntimeState
from rig_relay.core.tool_runtime_models import (
    ToolRuntimeExecutionMode,
    ToolRuntimeRequest,
)
from rig_relay.runtime.supervisor_result import (
    RuntimeSupervisorEnvelopeContext,
    RuntimeSupervisorResultEnvelope,
)
from rig_relay.runtime.tool_invocation_adapter import (
    RuntimeToolInvocationEnvelope,
    RuntimeToolInvocationStatus,
    RuntimeToolName,
)
from rig_relay.tracing.context import TraceContext
from rig_relay.tracing.models import new_trace_id


class TestAgentLoopStartEventHasTraceContext:
    def test_trace_context_has_trace_id_and_session_id(self) -> None:
        ctx = TraceContext(trace_id=new_trace_id(), session_id="session-abc-123")
        assert ctx.trace_id
        assert ctx.session_id
        assert ctx.trace_id != ctx.session_id

    def test_agent_runtime_state_has_session_id(self) -> None:
        state = AgentRuntimeState(session_id="session-runtime-42")
        assert state.session_id == "session-runtime-42"
        assert "session_id" in AgentRuntimeState.model_fields


class TestToolInvocationInheritsTraceContext:
    def test_tool_runtime_request_has_session_id(self) -> None:
        request = ToolRuntimeRequest(
            tool_name="test_tool",
            tool_args={"x": 1},
            tool_call_id="call-1",
            session_id="sess-xyz",
            agent_id="agent-42",
            lane_id="lane-a",
            lease_id="lease-99",
            turn_id="turn-7",
            invocation_id="inv-1",
            execution_mode=ToolRuntimeExecutionMode.READ_ONLY,
        )
        assert request.session_id == "sess-xyz"
        assert request.agent_id == "agent-42"
        assert request.lane_id == "lane-a"
        assert request.lease_id == "lease-99"

    def test_invocation_envelope_carries_session_and_agent(self) -> None:
        envelope = RuntimeToolInvocationEnvelope(
            invocation_id="inv-1",
            intent_id="intent-a",
            tool_name=RuntimeToolName.WRITE_FILE,
            status=RuntimeToolInvocationStatus.PREPARED,
            session_id="sess-env",
            task_id="task-1",
            lane_id="lane-b",
            workspace_id="ws-1",
            mission_id="mission-m",
            agent_id="agent-g",
            lease_id="lease-l",
        )
        assert envelope.session_id == "sess-env"
        assert envelope.mission_id == "mission-m"
        assert envelope.agent_id == "agent-g"
        assert envelope.lane_id == "lane-b"


class TestSupervisorResultCarriesTraceContext:
    def test_envelope_has_trace_fields(self) -> None:
        from rig_relay.runtime.supervisor_result import (
            RuntimeSupervisorCommandDigest,
            RuntimeSupervisorOutputDigest,
            RuntimeSupervisorResourceUsage,
            RuntimeSupervisorResultClassification,
            RuntimeSupervisorTiming,
            build_runtime_supervisor_result_envelope,
        )

        envelope = build_runtime_supervisor_result_envelope(
            command=RuntimeSupervisorCommandDigest(
                executable="echo",
                argv_hash="sha256:abc",
                argc=1,
                cwd_hash="sha256:def",
                cwd_kind="worktree",
            ),
            cwd={"path": "/tmp"},
            state_projection={"current_state": "running"},
            classification=RuntimeSupervisorResultClassification.COMPLETED,
            resource_usage=RuntimeSupervisorResourceUsage(exit_code=0),
            output=RuntimeSupervisorOutputDigest(
                stdout_sha256="sha256:out",
                stderr_sha256="sha256:err",
                stdout_bytes=10,
                stderr_bytes=0,
            ),
            timing=RuntimeSupervisorTiming(duration_ms=42.0),
            context=RuntimeSupervisorEnvelopeContext(
                trace_id="trace-123", parent_span_id="parent-456", span_id="span-789"
            ),
        )
        assert envelope.trace_id == "trace-123"
        assert envelope.parent_span_id == "parent-456"
        assert envelope.span_id == "span-789"

    def test_envelope_context_has_trace_fields(self) -> None:
        ctx = RuntimeSupervisorEnvelopeContext(
            trace_id="trace-abc", parent_span_id="parent-def", span_id="span-ghi"
        )
        assert ctx.trace_id == "trace-abc"
        assert ctx.parent_span_id == "parent-def"
        assert ctx.span_id == "span-ghi"


class TestContextRequestCarriesTraceContext:
    def test_context_request_preserves_mission_id_and_agent_id(self) -> None:
        request = ContextRequest(
            mission_id="mission-007", agent_id="agent-bond", mode=ContextMode.MAP
        )
        assert request.mission_id == "mission-007"
        assert request.agent_id == "agent-bond"

    def test_context_request_defaults_to_none(self) -> None:
        request = ContextRequest(mode=ContextMode.MAP)
        assert request.mission_id is None
        assert request.agent_id is None


def _build_result_envelope() -> RuntimeSupervisorResultEnvelope:
    from rig_relay.runtime.supervisor_result import (
        RuntimeSupervisorCommandDigest,
        RuntimeSupervisorOutputDigest,
        RuntimeSupervisorResourceUsage,
        RuntimeSupervisorResultClassification,
        RuntimeSupervisorTiming,
    )

    return RuntimeSupervisorResultEnvelope(
        result_id="r1",
        command=RuntimeSupervisorCommandDigest(
            executable="echo",
            argv_hash="sha256:a",
            argc=1,
            cwd_hash="sha256:b",
            cwd_kind="worktree",
        ),
        cwd={"path": "/tmp"},
        state="running",
        classification=RuntimeSupervisorResultClassification.COMPLETED,
        resource_usage=RuntimeSupervisorResourceUsage(exit_code=0),
        output=RuntimeSupervisorOutputDigest(
            stdout_sha256="sha256:out",
            stderr_sha256="sha256:err",
            stdout_bytes=0,
            stderr_bytes=0,
        ),
        timing=RuntimeSupervisorTiming(),
    )


_PYDANTIC_MODELS: list[tuple[str, object]] = [
    ("RuntimeSupervisorResultEnvelope", _build_result_envelope()),
    ("ContextRequest", ContextRequest(mode=ContextMode.MAP)),
    (
        "ToolRuntimeRequest",
        ToolRuntimeRequest(
            tool_name="t", tool_args={}, execution_mode=ToolRuntimeExecutionMode.UNKNOWN
        ),
    ),
    ("AgentRuntimeState", AgentRuntimeState(session_id="s")),
]

_FORBIDDEN_FIELDS = frozenset({
    "raw_path",
    "raw_file_contents",
    "access_token",
    "raw_prompt",
})


class TestTraceContextIsContentLight:
    @pytest.mark.parametrize("model_name,instance", _PYDANTIC_MODELS)
    def test_model_has_no_forbidden_fields(self, model_name: str, instance) -> None:
        field_names = set(type(instance).model_fields.keys())
        overlap = field_names & _FORBIDDEN_FIELDS
        assert not overlap, f"{model_name} contains forbidden content fields: {overlap}"

    def test_trace_context_slots_are_clean(self) -> None:
        ctx = TraceContext(trace_id=new_trace_id(), session_id="s")
        for forbidden in _FORBIDDEN_FIELDS:
            assert not hasattr(ctx, forbidden), (
                f"TraceContext has forbidden attribute: {forbidden}"
            )


class TestTraceIdFormatIsValidUuidOrHex:
    def test_new_trace_id_is_valid_hex(self) -> None:
        tid = new_trace_id()
        assert len(tid) == 32, f"Expected 32 chars, got {len(tid)}: {tid}"
        assert tid == tid.lower(), f"Expected lowercase hex: {tid}"
        hex_chars = set("0123456789abcdef")
        assert all(c in hex_chars for c in tid), f"Non-hex chars in: {tid}"

    def test_trace_context_generated_trace_id_is_valid_hex(self) -> None:
        ctx = TraceContext(session_id="s")
        assert len(ctx.trace_id) == 32
        hex_chars = set("0123456789abcdef")
        assert all(c in hex_chars for c in ctx.trace_id)

    def test_explicit_trace_id_is_preserved(self) -> None:
        ctx = TraceContext(trace_id="abcdef0123456789abcdef0123456789", session_id="s")
        assert ctx.trace_id == "abcdef0123456789abcdef0123456789"

    def test_trace_id_is_valid_uuid(self) -> None:
        for _ in range(10):
            tid = new_trace_id()
            parsed = UUID(tid)
            assert parsed.version == 4
