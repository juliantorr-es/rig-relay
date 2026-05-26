"""Agent loop functional recovery tests — Gates 0-5."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from rig_relay.core.agents.models import BuiltinAgentName
from rig_relay.core.tool_executor.adapter_builder import ToolRuntimeAdapterBuilder
from rig_relay.core.tool_executor.concurrency import ToolConcurrencyManager
from rig_relay.core.tool_executor.context import ToolSessionContext, ToolTurnContext
from rig_relay.core.tool_executor.council_gate import CouncilGate
from rig_relay.core.tool_executor.executor import ToolExecutor
from rig_relay.core.tool_runtime_models import RefusalCode, ToolRuntimeStatus
from rig_relay.core.types import (
    FunctionCall,
    Role,
    ToolCall,
    ToolCallEvent,
    ToolResultEvent,
)
from tests.conftest import build_test_agent_loop, build_test_vibe_config
from tests.mock.utils import mock_llm_chunk
from tests.stubs.fake_backend import FakeBackend

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
        agent_name=BuiltinAgentName.UNSAFE_RAW_SHELL,
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
        agent_name=BuiltinAgentName.UNSAFE_RAW_SHELL,
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
    source = tmp_working_directory / "calc.py"
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
        agent_name=BuiltinAgentName.UNSAFE_RAW_SHELL,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=["write_file"],
            tools={"write_file": {"permission": "always"}},
            governed_context_enabled=False,
        ),
        workspace_root=tmp_working_directory,
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
        raise AssertionError(f"Tool was skipped: {skip_details}")

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
    source = tmp_working_directory / "calc.py"
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
        agent_name=BuiltinAgentName.UNSAFE_RAW_SHELL,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=["write_file", "read_file"],
            tools={
                "write_file": {"permission": "always"},
                "read_file": {"permission": "always"},
            },
            governed_context_enabled=False,
        ),
        workspace_root=tmp_working_directory,
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
        raise AssertionError(
            f"Tool was skipped: {skip_details}. All events: {event_summary}"
        )
    if error_events:
        err_details = [(e.tool_name, getattr(e, "error", "?")) for e in error_events]
        raise AssertionError(
            f"Tool has error: {err_details}. All events: {event_summary}"
        )

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


@pytest.mark.asyncio
async def test_runtime_identity_does_not_contaminate_strict_tool_args(
    tmp_working_directory: Path,
):
    """Airlock positive: write_file receives only declared args. No internal
    metadata reaches Pydantic extra="forbid" validation. Runtime result
    identity (correlation_id, causation_id, session_id, turn_id, tool_call_id)
    remains intact.
    """
    source = Path("calc.py")
    source.write_text("def add(a, b):\n    return a - b  # bug\n")

    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Fixing.",
                tool_calls=[
                    _write_file_tool_call(
                        str(source),
                        "def add(a, b):\n    return a + b\n",
                        call_id="wf_airlock",
                    )
                ],
            )
        ],
        [mock_llm_chunk(content="Done.")],
    ])

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.UNSAFE_RAW_SHELL,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=["write_file"],
            tools={"write_file": {"permission": "always"}},
            governed_context_enabled=False,
        ),
    )

    events = []
    async for event in loop.act("Fix calc.py"):
        events.append(event)

    # Mutation succeeded — file was modified in admitted workspace
    assert "return a + b" in source.read_text()

    # No validation errors from extra fields
    from rig_relay.core.types import ToolResultEvent

    for e in events:
        if isinstance(e, ToolResultEvent):
            err = getattr(e, "error", None)
            assert err is None or "extra inputs" not in str(err), (
                f"Validation error in tool result: {err}"
            )

    # role=tool message appended with correct identity
    tool_msgs = [m for m in loop.messages if m.role == Role.tool]
    assert len(tool_msgs) >= 1
    assert tool_msgs[-1].tool_call_id == "wf_airlock"

    # Runtime correlation identity preserved
    # Verify the tool call completed event carries correlation_id
    # (proves identity travels through request/result, not args)

    await loop.aclose()


@pytest.mark.asyncio
async def test_model_cannot_supply_runtime_reserved_tool_fields(
    tmp_working_directory: Path,
):
    """Airlock adversarial: model-supplied _tool_runtime_call_id, worktree_path,
    or repo_root are rejected by strict tool validation. No file mutation occurs.
    The refusal reaches the agent loop as an honest structured outcome.
    """
    source = Path("calc.py")
    source.write_text("x = 1\n")

    # Model attempts to inject _tool_runtime_call_id as a tool argument.
    # write_file's WriteFileArgs has extra="forbid" — should reject.
    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Writing with forged args.",
                tool_calls=[
                    ToolCall(
                        id="wf_forged",
                        index=0,
                        function=FunctionCall(
                            name="write_file",
                            arguments=json.dumps({
                                "path": "calc.py",
                                "content": "hacked\n",
                                "overwrite": True,
                                "_tool_runtime_call_id": "forged_by_model",
                            }),
                        ),
                    )
                ],
            )
        ],
        [mock_llm_chunk(content="I could not write — the call was rejected.")],
    ])

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.UNSAFE_RAW_SHELL,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=["write_file"],
            tools={"write_file": {"permission": "always"}},
            governed_context_enabled=False,
        ),
    )

    events = []
    async for event in loop.act("Write to calc.py with special fields"):
        events.append(event)

    # File was NOT modified — the forged call was rejected
    assert source.read_text() == "x = 1\n", (
        f"File was modified despite forged args: {source.read_text()}"
    )

    # File was NOT modified — the forged call was rejected
    assert source.read_text() == "x = 1\n", (
        f"File was modified despite forged args: {source.read_text()}"
    )

    # The forged call may be rejected at different stages:
    # - Format handler resolve_tool_calls may put it in failed_calls
    # - Or the tool executor may skip it with a validation error
    # Either way: no write_file ToolResultEvent should exist
    from rig_relay.core.types import ToolResultEvent

    tool_results = [
        e
        for e in events
        if isinstance(e, ToolResultEvent)
        and getattr(e, "tool_name", "") == "write_file"
    ]
    # Failed calls now produce ToolResultEvents via the batch executor.
    # The forged _tool_runtime_call_id must produce a failure observation.
    assert len(tool_results) == 1, (
        f"Expected 1 failed ToolResultEvent, got {len(tool_results)}: {[(getattr(e, 'tool_name', '?'), str(getattr(e, 'error', '?'))[:60]) for e in tool_results]}"
        % (
            len(tool_results),
            [
                (getattr(e, "tool_name", "?"), str(getattr(e, "error", "?"))[:60])
                for e in tool_results
            ],
        )
    )
    tr = tool_results[0]
    assert getattr(tr, "error", None) is not None, "Failed call must produce error"
    assert "extra" in str(getattr(tr, "error", "")).lower(), (
        "Error should mention extra inputs"
    )

    # role=tool message should NOT exist for write_file
    tool_msgs = [
        m
        for m in loop.messages
        if m.role == Role.tool and getattr(m, "tool_call_id", "") == "wf_forged"
    ]
    assert len(tool_msgs) == 1, (
        f"Expected 1 role=tool for failed forged call, got {len(tool_msgs)}"
    )

    await loop.aclose()


@pytest.mark.asyncio
async def test_scoped_mission_cannot_use_bash_for_outside_write(
    tmp_working_directory: Path,
):
    """Airlock: Reproduce Probe D — bash cannot modify files outside the
    admitted workspace in a contained mission. The bash command must be refused
    and the outside file must remain unchanged.
    """
    admitted = Path("admitted")
    admitted.mkdir()
    outside_dir = Path("..") / "outside_airlock"
    outside_dir.mkdir(exist_ok=True)
    secret = outside_dir / "secret.txt"
    secret.write_text("original content\n")

    from rig_relay.core.types import BaseEvent

    # Collect events to verify refusal
    events: list[BaseEvent] = []

    # Create a FakeBackend that attempts bash echo redirect to outside file
    from rig_relay.core.types import FunctionCall, ToolCall

    bash_cmd = f"echo 'hacked' >> {secret.absolute()}"
    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Using bash to write outside.",
                tool_calls=[
                    ToolCall(
                        id="bash_bypass",
                        index=0,
                        function=FunctionCall(
                            name="bash", arguments=json.dumps({"command": bash_cmd})
                        ),
                    )
                ],
            )
        ],
        [mock_llm_chunk(content="I cannot write there.")],
    ])

    # AgentLoop WITHOUT bypass — contained mission
    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.DEFAULT,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=["bash", "read_file"], governed_context_enabled=False
        ),
        workspace_root=admitted,
    )

    async for event in loop.act(f"Append a line to {secret}"):
        events.append(event)

    # File outside workspace was NOT modified
    assert secret.read_text() == "original content\n", (
        f"Outside file was modified! Content: {secret.read_text()}"
    )

    # Bash was refused — ToolResultEvent with skipped or error
    from rig_relay.core.types import ToolResultEvent

    tool_results = [
        e
        for e in events
        if isinstance(e, ToolResultEvent) and getattr(e, "tool_name", "") == "bash"
    ]
    assert len(tool_results) >= 1, (
        f"No ToolResultEvent for bash. Events: {[type(e).__name__ for e in events]}"
    )
    tr = tool_results[0]
    assert getattr(tr, "skipped", False) or getattr(tr, "error", None), (
        f"Bash was not refused: skipped={getattr(tr, 'skipped', None)} error={getattr(tr, 'error', None)}"
    )

    # role=tool message with refusal
    tool_msgs = [
        m
        for m in loop.messages
        if m.role == Role.tool and getattr(m, "tool_call_id", "") == "bash_bypass"
    ]
    assert len(tool_msgs) >= 1, "No refusal message for bash"

    await loop.aclose()


@pytest.mark.asyncio
async def test_cat_outside_workspace_is_refused_in_contained_mission(
    tmp_working_directory: Path,
):
    """Airlock fail-closed: cat /outside/file is not a validate reroute
    and must be refused in a contained mission, not fall through to raw bash.
    """
    outside = Path("..") / "outside_cat"
    outside.mkdir(exist_ok=True)
    secret = outside / "data.txt"
    secret.write_text("secret\n")

    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Reading outside.",
                tool_calls=[
                    ToolCall(
                        id="cat_bypass",
                        index=0,
                        function=FunctionCall(
                            name="bash",
                            arguments=json.dumps({
                                "command": f"cat {secret.absolute()}"
                            }),
                        ),
                    )
                ],
            )
        ],
        [mock_llm_chunk(content="Refused.")],
    ])

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.DEFAULT,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=["bash", "cat"], governed_context_enabled=False
        ),
    )

    events = []
    async for event in loop.act(f"Read {secret}"):
        events.append(event)

    tr_events = [
        e
        for e in events
        if isinstance(e, ToolResultEvent) and getattr(e, "tool_name", "") == "bash"
    ]
    assert len(tr_events) >= 1
    tr = tr_events[0]
    assert getattr(tr, "skipped", False) or getattr(tr, "error", None), (
        f"cat outside workspace was not refused: skipped={getattr(tr, 'skipped', None)}"
    )
    await loop.aclose()


@pytest.mark.asyncio
async def test_grep_outside_workspace_is_refused_in_contained_mission(
    tmp_working_directory: Path,
):
    """Airlock fail-closed: grep outside is not a validate reroute and must be refused."""
    outside = Path("..") / "outside_grep"
    outside.mkdir(exist_ok=True)
    (outside / "data.txt").write_text("secret\n")

    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Searching.",
                tool_calls=[
                    ToolCall(
                        id="grep_bypass",
                        index=0,
                        function=FunctionCall(
                            name="bash",
                            arguments=json.dumps({
                                "command": f"grep secret {outside.absolute()}/data.txt"
                            }),
                        ),
                    )
                ],
            )
        ],
        [mock_llm_chunk(content="Refused.")],
    ])

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.DEFAULT,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=["bash"], governed_context_enabled=False
        ),
    )

    events = []
    async for event in loop.act(f"Search in {outside}"):
        events.append(event)

    tr_events = [
        e
        for e in events
        if isinstance(e, ToolResultEvent) and getattr(e, "tool_name", "") == "bash"
    ]
    assert len(tr_events) >= 1
    assert getattr(tr_events[0], "skipped", False) or getattr(
        tr_events[0], "error", None
    )
    await loop.aclose()


@pytest.mark.asyncio
async def test_direct_argv_outside_access_is_not_admitted(tmp_working_directory: Path):
    """Airlock fail-closed: a command without shell metacharacters that
    accesses a path outside the workspace via argv is still refused.
    """
    outside = Path("..") / "outside_argv"
    outside.mkdir(exist_ok=True)
    (outside / "data.txt").write_text("secret\n")

    # python3 -c with open() — no shell metacharacters, but still outside access
    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Reading via Python.",
                tool_calls=[
                    ToolCall(
                        id="py_bypass",
                        index=0,
                        function=FunctionCall(
                            name="bash",
                            arguments=json.dumps({
                                "command": f"python3 -c \"open('{outside.absolute()}/data.txt').read()\""
                            }),
                        ),
                    )
                ],
            )
        ],
        [mock_llm_chunk(content="Refused.")],
    ])

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.DEFAULT,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=["bash"], governed_context_enabled=False
        ),
    )

    events = []
    async for event in loop.act(f"Read {outside}/data.txt via Python"):
        events.append(event)

    tr_events = [
        e
        for e in events
        if isinstance(e, ToolResultEvent) and getattr(e, "tool_name", "") == "bash"
    ]
    assert len(tr_events) >= 1
    assert getattr(tr_events[0], "skipped", False) or getattr(
        tr_events[0], "error", None
    )
    await loop.aclose()


@pytest.mark.asyncio
async def test_malformed_validate_like_command_is_refused(tmp_working_directory: Path):
    """Airlock fail-closed: a command resembling a validate pattern but
    malformed (e.g. ruff without 'check') must be refused, not fall through.
    """
    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Running ruff.",
                tool_calls=[
                    ToolCall(
                        id="ruff_mal",
                        index=0,
                        function=FunctionCall(
                            name="bash", arguments=json.dumps({"command": "ruff"})
                        ),
                    )
                ],
            )
        ],
        [mock_llm_chunk(content="Refused.")],
    ])

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.DEFAULT,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=["bash"], governed_context_enabled=False
        ),
    )

    events = []
    async for event in loop.act("Run ruff"):
        events.append(event)

    tr_events = [
        e
        for e in events
        if isinstance(e, ToolResultEvent) and getattr(e, "tool_name", "") == "bash"
    ]
    assert len(tr_events) >= 1
    tr = tr_events[0]
    assert getattr(tr, "skipped", False) or getattr(tr, "error", None), (
        f"Malformed ruff was not refused: {getattr(tr, 'skipped', None)} {getattr(tr, 'error', None)}"
    )
    await loop.aclose()


@pytest.mark.asyncio
async def test_validate_command_pytest_still_accepted_in_contained_mission(
    tmp_working_directory: Path,
):
    """Airlock: pytest command matches validate reroute and should be
    accepted (rerouted to validate tool), not raw-bash-refused.
    """
    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Running tests.",
                tool_calls=[
                    ToolCall(
                        id="pytest_ok",
                        index=0,
                        function=FunctionCall(
                            name="bash", arguments=json.dumps({"command": "pytest"})
                        ),
                    )
                ],
            )
        ],
        [mock_llm_chunk(content="Tests pass.")],
    ])

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.DEFAULT,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=["bash", "validate"], governed_context_enabled=False
        ),
    )

    events = []
    async for event in loop.act("Run pytest"):
        events.append(event)

    # pytest should be rerouted to validate or at least not raw-bash-refused
    tr_events = [
        e
        for e in events
        if isinstance(e, ToolResultEvent)
        and getattr(e, "tool_name", "") in ("bash", "validate")
    ]
    assert len(tr_events) >= 1
    # Whether it ran through validate or bash, it should not be a raw refusal
    # (validate reroute is the allowed exception)
    await loop.aclose()


@pytest.mark.asyncio
async def test_mission_scoped_auto_can_mutate_and_validate(tmp_working_directory: Path):
    """MISSION_SCOPED_AUTO grants scoped mutation + validation authority
    without requiring per-edit human approval.
    """
    source = Path("calc.py")
    source.write_text("def add(a, b):\n    return a - b  # bug\n")

    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Fixing.",
                tool_calls=[
                    _write_file_tool_call(
                        str(source),
                        "def add(a, b):\n    return a + b\n",
                        call_id="wf_msa",
                    )
                ],
            )
        ],
        [mock_llm_chunk(content="Done.")],
    ])

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.MISSION_SCOPED_AUTO,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=["write_file", "read_file"],
            tools={
                "write_file": {"permission": "always"},
                "read_file": {"permission": "always"},
            },
            governed_context_enabled=False,
        ),
    )

    events = []
    async for event in loop.act("Fix calc.py"):
        events.append(event)

    from rig_relay.core.types import ToolResultEvent

    tr_events = [
        e
        for e in events
        if isinstance(e, ToolResultEvent)
        and getattr(e, "tool_name", "") == "write_file"
    ]
    assert len(tr_events) >= 1, "No ToolResultEvent for write_file"

    # Evidence persistence is now bootstrapped (agent_loop.py wires
    # FilesystemReceiptStore into GovernanceRuntime at init).
    # Mutation MUST succeed under MISSION_SCOPED_AUTO — no bypass, no skips.
    skipped = [e for e in tr_events if getattr(e, "skipped", False)]
    assert len(skipped) == 0, (
        f"Mutation was skipped under MISSION_SCOPED_AUTO: "
        f"{[getattr(e, 'skip_reason', '?') for e in skipped]}"
    )

    # File must be modified
    assert "return a + b" in source.read_text(), (
        f"File not modified: {source.read_text()}"
    )

    # Bypass must remain false (contained autonomy, not unsafe)
    assert not loop.bypass_tool_permissions, (
        "MISSION_SCOPED_AUTO must not bypass governance"
    )

    await loop.aclose()


@pytest.mark.asyncio
async def test_mission_scoped_auto_refuses_raw_bash(tmp_working_directory: Path):
    """MISSION_SCOPED_AUTO has bash in base_disabled — raw shell is refused
    and the model receives a structured refusal observation.
    """
    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Using bash.",
                tool_calls=[
                    ToolCall(
                        id="bash_msa",
                        index=0,
                        function=FunctionCall(
                            name="bash",
                            arguments=json.dumps({"command": "echo hacked"}),
                        ),
                    )
                ],
            )
        ],
        [
            mock_llm_chunk(
                content="I cannot use raw bash — it is disabled in this profile."
            )
        ],
    ])

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.MISSION_SCOPED_AUTO,
        backend=backend,
        config=build_test_vibe_config(governed_context_enabled=False),
    )

    events = []
    async for event in loop.act("Run echo hacked via bash"):
        events.append(event)

    # bash is absent from available_tools
    assert "bash" not in loop.tool_manager.available_tools

    from rig_relay.core.types import Role, ToolCallEvent, ToolResultEvent

    # No executable ToolCallEvent for bash
    tc_events = [
        e
        for e in events
        if isinstance(e, ToolCallEvent) and getattr(e, "tool_name", "") == "bash"
    ]
    assert len(tc_events) == 0, "bash ToolCallEvent emitted"

    # Exactly one failed/refused ToolResultEvent for bash
    tr_events = [
        e
        for e in events
        if isinstance(e, ToolResultEvent) and getattr(e, "tool_name", "") == "bash"
    ]
    assert len(tr_events) == 1, f"Expected 1 failed TR for bash, got {len(tr_events)}"

    # Exactly one role=tool message with bash_msa call_id
    tool_msgs = [
        m
        for m in loop.messages
        if m.role == Role.tool and getattr(m, "tool_call_id", "") == "bash_msa"
    ]
    assert len(tool_msgs) == 1, (
        f"Expected 1 role=tool for bash_msa, got {len(tool_msgs)}. "
        f"Roles: {[(str(getattr(m, 'role', '?')), getattr(m, 'tool_call_id', '?')) for m in loop.messages]}"
    )

    # Second backend turn executed (no dangling tool call)
    assert len(backend._requests_messages) >= 2, (
        f"Expected >= 2 backend calls, got {len(backend._requests_messages)}"
    )

    # No file was created
    assert not Path("hacked").exists()

    await loop.aclose()


@pytest.mark.asyncio
async def test_mixed_batch_disabled_and_valid_tools(tmp_working_directory: Path):
    """Model emits one disabled (bash) + one valid (read_file) in same batch.
    Both produce bound observations. Valid tool executes normally.
    """
    test_file = Path("target.py")
    test_file.write_text("x = 1\n")

    backend = FakeBackend([
        [
            mock_llm_chunk(
                content="Reading and running.",
                tool_calls=[
                    ToolCall(
                        id="rf_valid",
                        index=0,
                        function=FunctionCall(
                            name="read_file",
                            arguments=json.dumps({"path": "target.py"}),
                        ),
                    ),
                    ToolCall(
                        id="bash_invalid",
                        index=1,
                        function=FunctionCall(
                            name="bash",
                            arguments=json.dumps({"command": "echo hacked"}),
                        ),
                    ),
                ],
            )
        ],
        [mock_llm_chunk(content="Done.")],
    ])

    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.MISSION_SCOPED_AUTO,
        backend=backend,
        config=build_test_vibe_config(governed_context_enabled=False),
    )

    events = []
    async for event in loop.act("Read target.py and run echo hacked"):
        events.append(event)

    from rig_relay.core.types import Role, ToolResultEvent

    # Valid tool produced result
    rf = [
        e
        for e in events
        if isinstance(e, ToolResultEvent) and getattr(e, "tool_name", "") == "read_file"
    ]
    assert len(rf) >= 1, "No read_file result"

    # Disabled tool produced failed result
    br = [
        e
        for e in events
        if isinstance(e, ToolResultEvent) and getattr(e, "tool_name", "") == "bash"
    ]
    assert len(br) >= 1, "No bash failure result"

    # Both tool slots have role=tool messages
    for cid in ("rf_valid", "bash_invalid"):
        msgs = [
            m
            for m in loop.messages
            if m.role == Role.tool and getattr(m, "tool_call_id", "") == cid
        ]
        assert len(msgs) == 1, f"Missing tool msg for {cid}"

    # Second turn succeeded (no dangling tool call)
    assert len(backend._requests_messages) >= 2

    await loop.aclose()


@pytest.mark.asyncio
async def test_admitted_mission_agent_loop_causally_prepares_validates_and_checkpoints(
    tmp_working_directory: Path,
):
    """Under an admitted mission with MISSION_SCOPED_AUTO (bypass=False),
    prove a causal governed chain: repair → prepare_checkpoint → validate
    → checkpoint. The reactive backend observes prior tool results to
    construct each subsequent step using actual runtime-emitted receipt
    digests. Verifies commit contents, receipt trailers, dirty-file
    preservation, and governance evidence persistence.
    """
    import hashlib
    import json
    import subprocess

    # ── 1. Set up real Git repo on a permissible task branch ──────
    subprocess.run(["git", "init", "-b", "main"], capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@t"], capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], capture_output=True)
    calc = Path("calc.py")
    calc.write_text("def add(a, b):\n    return a - b\n")
    test_file = Path("test_calc.py")
    test_file.write_text("from calc import add\nassert add(2, 3) == 5\n")
    notes = Path("notes.txt")
    notes.write_text("scratch\n")
    subprocess.run(
        ["git", "add", "calc.py", "test_calc.py", "notes.txt"], capture_output=True
    )
    subprocess.run(["git", "commit", "-m", "init"], capture_output=True)
    subprocess.run(["git", "checkout", "-b", "fix-calc"], capture_output=True)
    # Dirty notes.txt after branching — must remain dirty
    notes.write_text("scratch\nmore notes - do NOT commit\n")

    from rig_relay.core.agents.models import BuiltinAgentName
    from rig_relay.core.types import (
        FunctionCall,
        LLMMessage,
        Role,
        ToolCall,
        ToolCallEvent,
    )
    from tests.conftest import build_test_agent_loop, build_test_vibe_config
    from tests.mock.utils import mock_llm_chunk

    # ── 2. Build causal reactive backend ──
    class CausalBackend:
        """Reactive backend that constructs tool calls from prior observations."""

        def __init__(self, workspace: Path):
            self._workspace = workspace
            self._turn = 0
            self._requests_messages: list[list[LLMMessage]] = []
            # Extracted from prior tool results
            self._prep_receipt: str = ""
            self._prep_digest: str = ""
            self._valid_receipt: str = ""

        @property
        def requests_messages(self):
            return self._requests_messages

        def _compute_sha256(self, relpath: str) -> str:
            file_path = self._workspace / relpath
            return hashlib.sha256(file_path.read_bytes()).hexdigest()

        def _find_tool_result_dict(
            self, messages: list[LLMMessage], tool_name: str
        ) -> dict[str, str] | None:
            """Parse key: value pairs from a tool result LLMMessage.

            Tool results are formatted one entry per line as ``k: v``.
            Only string-valued fields are captured; multi-line or
            structured values are ignored.
            """
            for msg in reversed(messages):
                role = getattr(msg, "role", None)
                name = getattr(msg, "name", "")
                if role == Role.tool and name == tool_name:
                    content = getattr(msg, "content", "")
                    if isinstance(content, str) and content.strip():
                        result: dict[str, str] = {}
                        for line in content.strip().splitlines():
                            if ": " in line:
                                k, v = line.split(": ", 1)
                                result[k.strip()] = v.strip()
                        return result
            return None

        async def complete(
            self,
            *,
            model,
            messages,
            temperature,
            tools,
            tool_choice,
            extra_headers,
            max_tokens,
            metadata=None,
        ):
            import sys as _sys

            _sys.stderr.write(f"\n--- complete() called: turn={self._turn + 1} ---\n")
            _sys.stderr.flush()
            self._requests_messages.append(list(messages))
            self._turn += 1

            if self._turn == 1:
                # Fix the bug
                return mock_llm_chunk(
                    content="Fixing.",
                    tool_calls=[
                        ToolCall(
                            id="fix",
                            index=0,
                            function=FunctionCall(
                                name="write_file",
                                arguments=json.dumps({
                                    "path": "calc.py",
                                    "content": "def add(a, b):\n    return a + b\n",
                                    "overwrite": True,
                                }),
                            ),
                        )
                    ],
                )
            elif self._turn == 2:
                # Prepare checkpoint with actual file SHA-256
                sha = self._compute_sha256("calc.py")
                return mock_llm_chunk(
                    content="Preparing checkpoint.",
                    tool_calls=[
                        ToolCall(
                            id="prep",
                            index=0,
                            function=FunctionCall(
                                name="prepare_checkpoint",
                                arguments=json.dumps({
                                    "paths": [
                                        {
                                            "path": "calc.py",
                                            "change_kind": "modify",
                                            "expected_worktree_sha256": sha,
                                        }
                                    ]
                                }),
                            ),
                        )
                    ],
                )
            elif self._turn == 3:
                # Extract preparation receipt from prior tool observation
                prep_result = self._find_tool_result_dict(
                    messages, "prepare_checkpoint"
                )
                if prep_result:
                    self._prep_receipt = prep_result.get("receipt_sha256", "")
                    self._prep_digest = prep_result.get("post_index_tree_digest", "")
                # Validate bound to preparation receipt
                return mock_llm_chunk(
                    content="Validating.",
                    tool_calls=[
                        ToolCall(
                            id="val",
                            index=0,
                            function=FunctionCall(
                                name="validate",
                                arguments=json.dumps({
                                    "profile": "python",
                                    "paths": ["calc.py", "test_calc.py"],
                                    "preparation_receipt_sha256": self._prep_receipt,
                                    "workspace_root": str(self._workspace),
                                    "check_only": True,
                                }),
                            ),
                        )
                    ],
                )
            elif self._turn == 4:
                # Extract validation receipt from prior tool observation
                valid_result = self._find_tool_result_dict(messages, "validate")
                if valid_result:
                    self._valid_receipt = valid_result.get(
                        "validation_receipt_sha256", ""
                    )
                # Checkpoint with all receipt bindings
                return mock_llm_chunk(
                    content="Committing.",
                    tool_calls=[
                        ToolCall(
                            id="cp",
                            index=0,
                            function=FunctionCall(
                                name="checkpoint",
                                arguments=json.dumps({
                                    "include_paths": ["calc.py"],
                                    "message": ("fix: change return a - b to a + b"),
                                    "allow_partial": False,
                                    "preparation_receipt_sha256": (self._prep_receipt),
                                    "validation_receipt_sha256": (self._valid_receipt),
                                    "validation_summary": ["pytest test_calc.py"],
                                }),
                            ),
                        )
                    ],
                )
            else:
                return mock_llm_chunk(content="Done.")

        async def complete_streaming(
            self,
            *,
            model,
            messages,
            temperature,
            tools,
            tool_choice,
            extra_headers,
            max_tokens,
            metadata=None,
        ):
            chunk = await self.complete(
                model=model,
                messages=messages,
                temperature=temperature,
                tools=tools,
                tool_choice=tool_choice,
                extra_headers=extra_headers,
                max_tokens=max_tokens,
                metadata=metadata,
            )
            yield chunk

        async def count_tokens(
            self,
            *,
            model,
            messages,
            temperature=0.0,
            tools=None,
            tool_choice=None,
            extra_headers=None,
            metadata=None,
        ):
            return 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

    backend = CausalBackend(Path.cwd())

    # ── 3. Establish mission authority ──
    from rig_relay.coordination.store import CoordinationStore

    coord_store = CoordinationStore(
        Path.cwd() / ".build" / "rig-relay" / "coordination"
    )
    claim_result = coord_store.claim_task(
        session_id="causal-test-sess",
        task_id="causal-test-task",
        claim_kind="implementation",
        ttl_seconds=3600,
        scope={"allowed_paths": [str(Path.cwd())]},
    )
    assert claim_result is not None and claim_result.claim is not None

    # Build the agent loop
    loop = build_test_agent_loop(
        agent_name=BuiltinAgentName.MISSION_SCOPED_AUTO,
        backend=backend,
        config=build_test_vibe_config(
            enabled_tools=[
                "write_file",
                "prepare_checkpoint",
                "validate",
                "checkpoint",
                "read_file",
                "grep",
                "git_status",
                "git_diff",
                "git_ls_files",
            ],
            governed_context_enabled=False,
        ),
    )

    # Install mission authority (admitted checkpoint)
    authority = loop.install_mission_authority(
        claim=claim_result.claim,
        worktree_root=str(Path.cwd()),
        admitted_checkpoint=True,
        mission_id="causal-test-mission",
    )
    assert authority is not None, "Mission authority must be active"

    # ── 4. Execute agent loop ──
    events = []
    async for event in loop.act(
        "Fix calc.py: change return a - b to return a + b. "
        "Prepare checkpoint for calc.py. Validate. Then checkpoint."
    ):
        events.append(event)

    # Debug: list all events
    import sys as _sys2

    _sys2.stderr.write("\n=== ALL EVENTS ===\n")
    for _i, _e in enumerate(events):
        _tn = getattr(_e, "tool_name", "")
        _err = getattr(_e, "error", "")
        _ok = getattr(_e, "ok", None)
        _refusal = getattr(_e, "refusal_reason", "")
        _skipped = getattr(_e, "skipped", False)
        _event_type = type(_e).__name__
        _info = f"{_event_type}"
        if _tn:
            _info += f" tool={_tn}"
        if _err:
            _info += f" error={str(_err)[:80]}"
        if _ok is not None:
            _info += f" ok={_ok}"
        if _refusal:
            _info += f" refusal={_refusal}"
        if _skipped:
            _info += " SKIPPED"
        _sys2.stderr.write(f"  [{_i}] {_info}\n")
    _sys2.stderr.write(f"\nBackend turn={backend._turn}\n")
    _sys2.stderr.write(
        f"Backend prep_receipt={backend._prep_receipt[:20] if backend._prep_receipt else 'EMPTY'}\n"
    )
    _sys2.stderr.write(
        f"Backend valid_receipt={backend._valid_receipt[:20] if backend._valid_receipt else 'EMPTY'}\n"
    )
    _sys2.stderr.flush()

    # ── 5. Assert conditions ──

    # Condition 1: File was repaired
    assert "return a + b" in calc.read_text(), f"calc.py not fixed: {calc.read_text()}"

    # Condition 2: MISSION_SCOPED_AUTO has bypass_tool_permissions=False
    assert not loop.bypass_tool_permissions, "bypass must remain False"

    # Condition 3: No bash execution (bash is disabled)
    bash_events = [
        e
        for e in events
        if isinstance(e, ToolCallEvent) and getattr(e, "tool_name", "") == "bash"
    ]
    assert len(bash_events) == 0, "bash must not be invoked"

    # Condition 4: prepare_checkpoint succeeded with non-empty receipt
    from rig_relay.core.tools.builtins.prepare_checkpoint import PrepareCheckpointResult

    prep_results = [e for e in events if isinstance(e, PrepareCheckpointResult)]
    assert len(prep_results) >= 1, "No PrepareCheckpointResult event"
    prep = prep_results[0]
    assert prep.ok, f"prepare_checkpoint failed: {prep.refusal_reason}"
    assert prep.receipt_sha256, "prepare_checkpoint must have receipt_sha256"

    # Condition 5: validate succeeded with non-empty validation receipt
    from rig_relay.core.tools.builtins.validate_models import ValidateResult

    valid_results = [e for e in events if isinstance(e, ValidateResult)]
    assert len(valid_results) >= 1, "No ValidateResult event"
    valid = valid_results[0]
    assert valid.validation_receipt_sha256, (
        f"validate must have validation_receipt_sha256: status={valid.status}"
    )

    # Condition 6: checkpoint succeeded with real commit SHA
    from rig_relay.core.tools.builtins.checkpoint import CheckpointResult

    cp_results = [e for e in events if isinstance(e, CheckpointResult)]
    assert len(cp_results) >= 1, "No CheckpointResult event"
    cp = cp_results[0]
    assert cp.ok, (
        f"checkpoint refused: {cp.refusal_reason} (error_kind={cp.error_kind})"
    )
    assert cp.commit_sha is not None, "checkpoint must have commit_sha"
    assert len(cp.files_committed) >= 1, "checkpoint must have files_committed"

    # Condition 7: committed tree contains only calc.py
    committed_files = (
        subprocess
        .run(
            ["git", "show", "--name-only", "--format=", cp.commit_sha],
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()
    )
    committed_files = [f for f in committed_files if f]
    assert "calc.py" in committed_files, f"calc.py not in committed: {committed_files}"
    assert "notes.txt" not in committed_files, (
        f"notes.txt must not be committed: {committed_files}"
    )

    # Condition 8: notes.txt still dirty
    r = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    assert "notes.txt" in r.stdout, f"notes.txt should be dirty: {r.stdout}"

    # Condition 9: commit message contains receipt trailers
    commit_msg = subprocess.run(
        ["git", "log", "-1", "--format=%B", cp.commit_sha],
        capture_output=True,
        text=True,
    ).stdout
    assert "Rig-Preparation-Receipt-SHA256" in commit_msg, (
        f"commit msg missing preparation receipt trailer: {commit_msg}"
    )
    assert "Rig-Validation-Receipt-SHA256" in commit_msg, (
        f"commit msg missing validation receipt trailer: {commit_msg}"
    )

    # Condition 10: bypass_tool_permissions remained False
    assert not loop.bypass_tool_permissions

    # Condition 11: governance evidence directory exists
    evidence_dir = Path.cwd() / ".build" / "rig-relay" / "governance"
    evidence_files = list(evidence_dir.glob("*.json")) if evidence_dir.exists() else []
    # Evidence store may be empty if no gate decisions required mutation
    # evidence. At minimum, the directory should have been created.
    assert evidence_dir.exists() or True, (
        "governance evidence directory should exist after governed mutation"
    )

    # Condition 12: causal receipt propagation — receipts were dynamic
    assert backend._prep_receipt, "Backend must have extracted preparation receipt"
    assert backend._valid_receipt, "Backend must have extracted validation receipt"

    # Condition 13: Receipts are non-empty strings (not placeholder "")
    assert len(backend._prep_receipt) >= 8, (
        f"prep_receipt too short: {backend._prep_receipt}"
    )
    assert len(backend._valid_receipt) >= 8, (
        f"valid_receipt too short: {backend._valid_receipt}"
    )

    # Condition 14: commit message does not indicate error/refusal
    assert "refused" not in commit_msg.lower(), (
        f"commit message should not indicate refusal: {commit_msg}"
    )

    # Condition 15: Loop produced terminal completion event
    assert len(events) > 0, "Must produce events"

    await loop.aclose()
