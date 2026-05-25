"""Agent loop functional recovery tests — Gates 0-5."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from rig_relay.core.agents.models import BuiltinAgentName
from rig_relay.core.config._settings import VibeConfig
from rig_relay.core.types import (
    FunctionCall,
    Role,
    ToolCall,
    ToolCallEvent,
    ToolResultEvent,
    AssistantEvent,
)
from rig_relay.core.tool_executor.adapter_builder import ToolRuntimeAdapterBuilder
from rig_relay.core.tool_executor.concurrency import ToolConcurrencyManager
from rig_relay.core.tool_executor.context import ToolSessionContext, ToolTurnContext
from rig_relay.core.tool_executor.council_gate import CouncilGate
from rig_relay.core.tool_executor.executor import ToolExecutor
from rig_relay.core.tool_runtime_models import (
    RefusalCode,
    ToolRuntimeRefusal,
    ToolRuntimeResult,
    ToolRuntimeStatus,
)
from tests.conftest import build_test_agent_loop, build_test_vibe_config
from tests.stubs.fake_backend import FakeBackend
from tests.mock.utils import mock_llm_chunk


# ── Gate 0: Council refusal preserves full correlation identity ──────


@pytest.mark.asyncio
async def test_council_refusal_produces_tool_response_with_full_identity():
    """Gate 0: council BLOCK produces role=tool with typed ToolRuntimeResult."""
    corr_id = "corr_gate0_test"
    cause_id = "cause_gate0_test"
    turn_id = "turn-gate0"
    session_id = "sess-gate0"

    turn_ctx = ToolTurnContext(
        turn_id=turn_id,
        user_message_id="msg-1",
        correlation_id=corr_id,
        causation_id=cause_id,
    )

    captured_calls = []

    class MutationToolClass:
        from rig_relay.core.telemetry.tool_contract import ToolMutationClass

        mutation_class = ToolMutationClass.MUTATES_GIT_STATE

    result_sink_records = []

    class FakeResultSink:
        def record(self, result):
            result_sink_records.append(result)

    session_ctx = ToolSessionContext(
        session_id=session_id,
        workspace_root=Path("/tmp/test"),
        handle_tool_response=lambda **kw: captured_calls.append(kw),
        result_sink=FakeResultSink(),
        tool_manager=MagicMock(),
        trace_runtime=MagicMock(),
        rewind_manager=MagicMock(),
    )

    council_gate = MagicMock(spec=CouncilGate)
    future = asyncio.Future()
    future.set_result("BLOCK")
    council_gate.consult = MagicMock(return_value=future)

    adapter_builder = MagicMock(spec=ToolRuntimeAdapterBuilder)
    concurrency = ToolConcurrencyManager()

    executor = ToolExecutor(
        session_ctx=session_ctx,
        adapter_builder=adapter_builder,
        council_gate=council_gate,
        concurrency=concurrency,
    )
    executor._turn_ctx = turn_ctx
    session_ctx.tool_manager.get.return_value = MutationToolClass()
    session_ctx.trace_runtime.tool_span = MagicMock()

    ctx_spy = MagicMock()
    session_ctx.trace_runtime.tool_span.return_value = ctx_spy
    ctx_spy.__aenter__ = AsyncMock(return_value=MagicMock())
    ctx_spy.__aexit__ = AsyncMock(return_value=None)
    session_ctx.rewind_manager.add_snapshot = MagicMock()

    from rig_relay.core.llm.format import ResolvedToolCall

    tool_call = MagicMock(spec=ResolvedToolCall)
    tool_call.tool_name = "write_file"
    tool_call.call_id = "tc-gate0"
    tool_call.tool_class = MutationToolClass
    tool_call.args_dict = {"file_path": "/tmp/test/out.txt", "content": "test"}
    tool_call.validated_args = MagicMock()
    tool_call.validated_args.model_dump_json.return_value = "{}"

    events = []
    async for event in executor.execute_one_tool(tool_call):
        events.append(event)

    skip_events = [e for e in events if getattr(e, "skipped", False)]
    assert len(skip_events) == 1
    assert skip_events[0].tool_call_id == "tc-gate0"

    assert len(captured_calls) == 1
    runtime_result = captured_calls[0]["runtime_result"]
    assert runtime_result is not None
    assert runtime_result.status == ToolRuntimeStatus.REFUSED
    assert runtime_result.correlation_id == corr_id
    assert runtime_result.causation_id == cause_id
    assert runtime_result.turn_id == turn_id
    assert runtime_result.session_id == session_id
    assert runtime_result.refusal is not None
    assert runtime_result.refusal.refusal_code == RefusalCode.CAPABILITY_GATED

    from rig_relay.core.tools._agent_outcome import derive_agent_outcome

    outcome = derive_agent_outcome(runtime_result, MutationToolClass)
    assert outcome.mutation_disposition == "not_performed"
    assert outcome.status == "refused"
    assert outcome.correlation_id == corr_id
    assert outcome.causation_id == cause_id


# ── Gate 1: Read-only tool loop completes ──


@pytest.mark.asyncio
async def test_read_only_tool_loop(tmp_path):
    """Gate 1: Agent loop executes read_file, reinjects result, continues."""
    workspace = tmp_path
    test_file = workspace / "target.py"
    test_file.write_text("def hello():\n    return 'world'\n")
    import os

    print(f"DIAG cwd: {os.getcwd()}", flush=True)
    print(f"DIAG tmp_path: {tmp_path}", flush=True)
    print(f"DIAG workspace: {workspace}", flush=True)

    tc_id = "tc-read-gate1"
    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Let me read that file.",
                tool_calls=[
                    ToolCall(
                        id=tc_id,
                        index=0,
                        function=FunctionCall(
                            name="read_file",
                            arguments=json.dumps({"path": str(test_file)}),
                        ),
                    )
                ],
            )
        ],
        [mock_llm_chunk(content="The file contains a hello() function.")],
    ])

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.AUTO_APPROVE,
        backend=backend,
        config=build_test_vibe_config(governed_context_enabled=False),
        workspace_root=workspace,
    )

    events = []
    async for event in loop.act("Read target.py and tell me what it does."):
        events.append(event)

    assert len(backend._requests_messages) >= 2

    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(tool_calls) >= 1, "No ToolCallEvent"

    tool_msgs = [m for m in loop.messages if m.role == Role.tool]
    assert len(tool_msgs) >= 1
    assert tool_msgs[-1].tool_call_id == tc_id

    assistant_msgs = [m for m in loop.messages if m.role == Role.assistant]
    assert len(assistant_msgs) >= 2

    await loop.aclose()


# ── Gate 1.5: Projection failure surfaces ──


@pytest.mark.asyncio
async def test_result_projection_failure_surfaces_not_swallowed(tmp_path):
    """Gate 1.5: handle_tool_response exception aborts batch, no continuation."""
    workspace = tmp_path
    test_file = workspace / "target.py"
    test_file.write_text("def hello(): return 'world'\n")

    tc_id = "tc-gate15"
    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Let me read that file.",
                tool_calls=[
                    ToolCall(
                        id=tc_id,
                        index=0,
                        function=FunctionCall(
                            name="read_file",
                            arguments=json.dumps({"path": str(test_file)}),
                        ),
                    )
                ],
            )
        ]
    ])

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.AUTO_APPROVE,
        backend=backend,
        config=build_test_vibe_config(governed_context_enabled=False),
        workspace_root=workspace,
    )

    sabotaged_called = [False]

    def sabotaged_htr(*args, **kwargs):
        sabotaged_called[0] = True
        raise RuntimeError("Injected projection failure")

    original_ctx = loop._session_exec_ctx
    sabotaged_ctx = ToolSessionContext(
        session_id=original_ctx.session_id,
        workspace_root=original_ctx.workspace_root,
        config=original_ctx.config,
        tool_manager=original_ctx.tool_manager,
        trace_runtime=original_ctx.trace_runtime,
        rewind_manager=original_ctx.rewind_manager,
        approval_callback=original_ctx.approval_callback,
        result_sink=original_ctx.result_sink,
        stats=original_ctx.stats,
        handle_tool_response=sabotaged_htr,
        telemetry_client=original_ctx.telemetry_client,
    )
    loop._tool_executor._session_ctx = sabotaged_ctx

    from rig_relay.core.tool_executor.executor import ToolObservationDeliveryError

    events = []
    try:
        async for event in loop.act("Read target.py and tell me what it does."):
            events.append(event)
    except ToolObservationDeliveryError:
        pass

    assert sabotaged_called[0], "Sabotage was never triggered"
    assert len(backend._requests_messages) <= 1, "Backend called more than once"

    tool_msgs = [m for m in loop.messages if m.role == Role.tool]
    assert len(tool_msgs) == 0, "No tool msg expected when projection fails"

    await loop.aclose()


# ── Helpers for Gates 3-5 ────────────────────────────────────────────


def _write_file_tool_call(path, content, call_id="call_1"):
    return ToolCall(
        id=call_id,
        index=0,
        function=FunctionCall(
            name="write_file",
            arguments=json.dumps({"path": path, "content": content, "overwrite": True}),
        ),
    )


# ── Gate 3: Scoped Mutation ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_scoped_mutation_cycle(tmp_working_directory):
    """Gate 3: Agent executes write_file, result reinjected, final assistant."""
    source = tmp_path / "calc.py"
    source.write_text("def add(a, b):\n    return a - b  # bug\n")

    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Fixing.",
                tool_calls=[
                    _write_file_tool_call(
                        str(source),
                        "def add(a, b):\n    return a + b\n",
                        call_id="wf_fix",
                    )
                ],
            )
        ],
        [mock_llm_chunk(content="The fix is applied.")],
    ])

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.AUTO_APPROVE,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=["write_file"],
            tools={"write_file": {"permission": "always"}},
            governed_context_enabled=False,
        ),
        workspace_root=tmp_path,
    )

    events = []
    async for event in loop.act("Fix the bug in calc.py"):
        events.append(event)

    # Diagnostic: check events first
    tc = [e for e in events if isinstance(e, ToolCallEvent)]
    tr = [e for e in events if isinstance(e, ToolResultEvent)]
    skip_events = [e for e in tr if getattr(e, "skipped", False)]
    error_events = [e for e in tr if getattr(e, "error", None)]
    assert len(tc) >= 1, (
        f"Expected >= 1 ToolCallEvent, got {len(tc)}. Events: {[(type(e).__name__, getattr(e, 'tool_name', '?')) for e in events]}"
    )
    assert len(tr) >= 1, (
        f"Expected >= 1 ToolResultEvent, got {len(tr)}. Skip: {len(skip_events)}, Error: {len(error_events)}"
    )
    if skip_events:
        skip_details = [
            (e.tool_name, getattr(e, "skip_reason", "?")) for e in skip_events
        ]
        assert False, f"Tool was skipped: {skip_details}"

    # Source was mutated
    assert "return a + b" in source.read_text(), (
        f"File not modified: {source.read_text()}"
    )

    # role=tool message
    tool_msgs = [m for m in loop.messages if m.role == Role.tool]
    assert len(tool_msgs) >= 1

    # Loop continued
    ast = [m for m in loop.messages if m.role == Role.assistant]
    assert len(ast) >= 2

    await loop.aclose()


# ── Gate 4: Self-Repair ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_self_repair_cycle(tmp_working_directory):
    """Gate 4: Agent reads broken file, fixes it, verifies via readback."""
    source = tmp_path / "calc.py"
    source.write_text("def add(a, b):\n    return a - b  # bug\n")

    backend = FakeBackend([
        # Turn 1: read the broken file
        [
            mock_llm_chunk(
                content="Let me check the code.",
                tool_calls=[
                    ToolCall(
                        id="rf_check",
                        index=0,
                        function=FunctionCall(
                            name="read_file",
                            arguments=json.dumps({"path": str(source)}),
                        ),
                    )
                ],
            )
        ],
        # Turn 2: fix it
        [
            mock_llm_chunk(
                content="Fixing the bug.",
                tool_calls=[
                    _write_file_tool_call(
                        str(source),
                        "def add(a, b):\n    return a + b\n",
                        call_id="wf_repair",
                    )
                ],
            )
        ],
        # Turn 3: verify
        [
            mock_llm_chunk(
                content="Verifying.",
                tool_calls=[
                    ToolCall(
                        id="rf_verify",
                        index=0,
                        function=FunctionCall(
                            name="read_file",
                            arguments=json.dumps({"path": str(source)}),
                        ),
                    )
                ],
            )
        ],
        [mock_llm_chunk(content="Fixed. The bug has been corrected.")],
    ])

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.AUTO_APPROVE,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=["write_file", "read_file"],
            tools={
                "write_file": {"permission": "always"},
                "read_file": {"permission": "always"},
            },
            governed_context_enabled=False,
        ),
        workspace_root=tmp_path,
    )

    events = []
    async for event in loop.act("Fix the bug in calc.py"):
        events.append(event)

    # Diagnostic: check events first with detailed assertion
    tc = [e for e in events if isinstance(e, ToolCallEvent)]
    tr = [e for e in events if isinstance(e, ToolResultEvent)]
    skip_events = [e for e in tr if getattr(e, "skipped", False)]
    error_events = [e for e in tr if getattr(e, "error", None)]
    event_summary = [
        (
            type(e).__name__,
            getattr(e, "tool_name", "?"),
            getattr(e, "skipped", "?"),
            getattr(e, "error", "?"),
        )
        for e in events
    ]

    assert len(tc) >= 1, f"ToolCallEvents: {len(tc)}, All events: {event_summary}"
    assert len(tr) >= 1, (
        f"ToolResultEvents: {len(tr)}, Skip: {len(skip_events)}, Error: {len(error_events)}, All events: {event_summary}"
    )
    if skip_events:
        skip_details = [
            (e.tool_name, getattr(e, "skip_reason", "?")) for e in skip_events
        ]
        assert False, f"Tool was skipped: {skip_details}. All events: {event_summary}"
    if error_events:
        err_details = [(e.tool_name, getattr(e, "error", "?")) for e in error_events]
        assert False, f"Tool has error: {err_details}. All events: {event_summary}"

    # Source was mutated
    assert "return a + b" in source.read_text(), (
        f"File not modified: {source.read_text()}"
    )

    # Tool call and result events
    tc = [e for e in events if isinstance(e, ToolCallEvent)]
    tr = [e for e in events if isinstance(e, ToolResultEvent)]
    assert len(tc) >= 1
    assert len(tr) >= 1

    # role=tool message
    tool_msgs = [m for m in loop.messages if m.role == Role.tool]
    assert len(tool_msgs) >= 1

    # Loop continued
    ast = [m for m in loop.messages if m.role == Role.assistant]
    assert len(ast) >= 2

    await loop.aclose()


# ── Gate 5: Honest Refusal ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_honest_refusal_produces_structured_outcome(tmp_path):
    """Gate 5: Out-of-scope write refused, model honestly reports inability."""
    admitted = tmp_path / "workspace"
    admitted.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("original\n")

    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Let me write to that file.",
                tool_calls=[
                    _write_file_tool_call(str(secret), "hacked", call_id="wf_refused")
                ],
            )
        ],
        [
            mock_llm_chunk(
                content="I cannot write to that path — it is outside the admitted workspace."
            )
        ],
    ])

    from rig_relay.core.types import ApprovalResponse

    async def deny_cb(*args, **kwargs):
        return (ApprovalResponse.NO, "Path outside admitted workspace")

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.DEFAULT,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=["write_file"],
            tools={"write_file": {"permission": "always"}},
            governed_context_enabled=False,
        ),
        workspace_root=admitted,
    )
    loop.set_approval_callback(deny_cb)

    events = []
    async for event in loop.act("Write to the secret file outside the workspace"):
        events.append(event)

    # Refused event
    skip_events = [
        e
        for e in events
        if isinstance(e, ToolResultEvent) and getattr(e, "skipped", False)
    ]
    assert len(skip_events) >= 1

    # role=tool with refusal
    tool_msgs = [m for m in loop.messages if m.role == Role.tool]
    assert len(tool_msgs) >= 1
    content = (tool_msgs[-1].content or "").lower()
    assert "outside" in content or "refused" in content or "cannot" in content

    # Model honesty
    ast = [m for m in loop.messages if m.role == Role.assistant]
    final = (ast[-1].content or "").lower()
    assert "cannot" in final or "outside" in final or "unable" in final

    # File NOT modified
    assert secret.read_text() == "original\n"

    await loop.aclose()
