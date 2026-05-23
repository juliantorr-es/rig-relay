"""Phase 3 tool batch behavior parity — proves _ConversationLoopAdapter integrates correctly.

Tests exercise the REAL production adapter (_ConversationLoopAdapter) wired to a
real AgentLoop, using FakeBackend at the LLM boundary. They prove:
- last_message_has_no_tool_calls() reflects _pending_tool_resolved state
- get_turn_batch_result() returns correct TurnBatchResult for pending/no-pending
- execute_tool_batch() actually dispatches to _execute_pending_tool_batch()
- The full pipeline (act → adapter → runtime → tool execution) works end-to-end
"""

from __future__ import annotations

from typing import Any as TypingAny, cast

import pytest

from rig_relay.core.agent_loop import AgentLoop
from rig_relay.core.agents.models import BuiltinAgentName
from rig_relay.core.config import VibeConfig
from rig_relay.core.conversation_loop_adapter import _ConversationLoopAdapter
from rig_relay.core.conversation_runtime.models import TurnBatchResult
from rig_relay.core.llm.format import FailedToolCall, ResolvedMessage, ResolvedToolCall
from rig_relay.core.tools.base import ToolPermission
from rig_relay.core.tools.builtins.todo import Todo, TodoArgs
from rig_relay.core.types import (
    AssistantEvent,
    BaseEvent,
    FunctionCall,
    ToolCall,
    ToolCallEvent,
    ToolResultEvent,
    UserMessageEvent,
)
from tests.conftest import build_test_agent_loop, build_test_vibe_config
from tests.mock.utils import mock_llm_chunk
from tests.stubs.fake_backend import FakeBackend


def _make_config(todo_permission: ToolPermission = ToolPermission.ALWAYS) -> VibeConfig:
    return build_test_vibe_config(
        enabled_tools=["todo"],
        tools={"todo": {"permission": todo_permission.value}},
        system_prompt_id="tests",
        include_project_context=False,
        include_prompt_detail=False,
    )


def _make_agent_loop(*, auto_approve: bool = True, backend: FakeBackend) -> AgentLoop:
    agent_name = (
        BuiltinAgentName.AUTO_APPROVE if auto_approve else BuiltinAgentName.DEFAULT
    )
    return build_test_agent_loop(
        config=_make_config(), agent_name=agent_name, backend=backend
    )


async def _collect_events(agent_loop: AgentLoop, prompt: str) -> list[BaseEvent]:
    return [ev async for ev in agent_loop.act(prompt)]


def _make_tool_call(
    call_id: str, index: int = 0, arguments: str | None = None
) -> ToolCall:
    args = arguments if arguments is not None else '{"action": "read"}'
    return ToolCall(
        id=call_id, index=index, function=FunctionCall(name="todo", arguments=args)
    )


def _build_resolved_message_with_calls() -> ResolvedMessage:
    return ResolvedMessage(
        tool_calls=[
            ResolvedToolCall(
                tool_name="todo",
                tool_class=Todo,
                validated_args=TodoArgs(action="read"),
                call_id="call_1",
            )
        ]
    )


def _build_resolved_message_with_only_failed() -> ResolvedMessage:
    return ResolvedMessage(
        tool_calls=[],
        failed_calls=[
            FailedToolCall(
                tool_name="unknown_tool",
                call_id="call_bad",
                error="Unknown tool 'unknown_tool'",
            )
        ],
    )


# ── last_message_has_no_tool_calls() ──────────────────────────────


@pytest.mark.asyncio
async def test_last_message_has_no_tool_calls_when_no_pending() -> None:
    agent_loop = build_test_agent_loop(config=_make_config())
    agent_loop._pending_tool_resolved = None
    adapter = _ConversationLoopAdapter(agent_loop, "hi")

    assert adapter.last_message_has_no_tool_calls() is True


@pytest.mark.asyncio
async def test_last_message_has_no_tool_calls_when_pending() -> None:
    agent_loop = build_test_agent_loop(config=_make_config())
    agent_loop._pending_tool_resolved = _build_resolved_message_with_calls()
    adapter = _ConversationLoopAdapter(agent_loop, "hi")

    assert adapter.last_message_has_no_tool_calls() is False


@pytest.mark.asyncio
async def test_last_message_has_no_tool_calls_with_only_failed() -> None:
    agent_loop = build_test_agent_loop(config=_make_config())
    agent_loop._pending_tool_resolved = _build_resolved_message_with_only_failed()
    adapter = _ConversationLoopAdapter(agent_loop, "hi")

    assert adapter.last_message_has_no_tool_calls() is False  # failed_calls exist


# ── get_turn_batch_result() ───────────────────────────────────────


@pytest.mark.asyncio
async def test_get_turn_batch_result_no_pending() -> None:
    agent_loop = build_test_agent_loop(config=_make_config())
    agent_loop._pending_tool_resolved = None
    adapter = _ConversationLoopAdapter(agent_loop, "hi")

    result = adapter.get_turn_batch_result()
    assert isinstance(result, TurnBatchResult)
    assert result.has_tool_work is False
    assert result.pending_batch is None
    assert result.assistant_is_final is True
    assert result.failed_calls == []


@pytest.mark.asyncio
async def test_get_turn_batch_result_with_pending_tools() -> None:
    agent_loop = build_test_agent_loop(config=_make_config())
    agent_loop._pending_tool_resolved = _build_resolved_message_with_calls()
    adapter = _ConversationLoopAdapter(agent_loop, "hi")

    result = adapter.get_turn_batch_result()
    assert result.has_tool_work is True
    assert result.pending_batch is not None
    assert len(result.pending_batch) == 1
    assert result.assistant_is_final is False
    assert result.failed_calls == []


@pytest.mark.asyncio
async def test_get_turn_batch_result_with_failed_calls() -> None:
    agent_loop = build_test_agent_loop(config=_make_config())
    agent_loop._pending_tool_resolved = _build_resolved_message_with_only_failed()
    adapter = _ConversationLoopAdapter(agent_loop, "hi")

    result = adapter.get_turn_batch_result()
    assert result.has_tool_work is False  # no executable tools, only failures
    assert result.pending_batch is None
    assert result.assistant_is_final is False  # failed calls exist → not final
    assert len(result.failed_calls) == 1


# ── execute_tool_batch() ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_tool_batch_executes_pending_and_clears_state() -> None:
    agent_loop = build_test_agent_loop(
        config=_make_config(), agent_name=BuiltinAgentName.AUTO_APPROVE
    )
    agent_loop._pending_tool_resolved = _build_resolved_message_with_calls()

    adapter = _ConversationLoopAdapter(agent_loop, "check todos")

    events = [ev async for ev in cast(TypingAny, adapter.execute_tool_batch())]

    assert agent_loop._pending_tool_resolved is None
    assert len(events) >= 1, "execute_tool_batch must yield at least one event"
    event_types = [type(e) for e in events]
    assert ToolCallEvent in event_types, "execute_tool_batch must yield ToolCallEvent"
    assert ToolResultEvent in event_types, (
        "execute_tool_batch must yield ToolResultEvent"
    )


@pytest.mark.asyncio
async def test_execute_tool_batch_noop_when_no_pending() -> None:
    agent_loop = build_test_agent_loop(config=_make_config())
    agent_loop._pending_tool_resolved = None
    adapter = _ConversationLoopAdapter(agent_loop, "hi")

    events = [ev async for ev in cast(TypingAny, adapter.execute_tool_batch())]
    assert events == [], "execute_tool_batch must be a no-op with no pending state"


# ── Full pipeline integration tests ───────────────────────────────


@pytest.mark.asyncio
async def test_tool_batch_execution_through_full_pipeline() -> None:
    tool_call = _make_tool_call("call_full1")
    backend = FakeBackend([
        [mock_llm_chunk(content="Let me check your todos.", tool_calls=[tool_call])],
        [mock_llm_chunk(content="I retrieved 0 todos.")],
    ])
    agent_loop = _make_agent_loop(backend=backend)

    events = await _collect_events(agent_loop, "What's my todo list?")

    assert [type(e) for e in events] == [
        UserMessageEvent,
        AssistantEvent,
        ToolCallEvent,
        ToolResultEvent,
        AssistantEvent,
    ]
    assert agent_loop._pending_tool_resolved is None


@pytest.mark.asyncio
async def test_no_tool_calls_completes_without_execution() -> None:
    backend = FakeBackend([[mock_llm_chunk(content="Hello! No tools needed.")]])
    agent_loop = _make_agent_loop(backend=backend)

    events = await _collect_events(agent_loop, "Say hello")

    assert [type(e) for e in events] == [UserMessageEvent, AssistantEvent]
    assert agent_loop._pending_tool_resolved is None


@pytest.mark.asyncio
async def test_two_tool_turns_clear_pending_each_time() -> None:
    tc1 = _make_tool_call("call_a1")
    tc2 = _make_tool_call("call_b2")
    backend = FakeBackend([
        [mock_llm_chunk(content="First tools.", tool_calls=[tc1])],
        [mock_llm_chunk(content="First done.")],
        [mock_llm_chunk(content="Second tools.", tool_calls=[tc2])],
        [mock_llm_chunk(content="Second done.")],
    ])
    agent_loop = _make_agent_loop(backend=backend)

    events1 = await _collect_events(agent_loop, "First request")
    assert ToolResultEvent in [type(e) for e in events1]
    assert agent_loop._pending_tool_resolved is None

    events2 = await _collect_events(agent_loop, "Second request")
    assert ToolResultEvent in [type(e) for e in events2]
    assert agent_loop._pending_tool_resolved is None

    assert [type(e) for e in events1] == [
        UserMessageEvent,
        AssistantEvent,
        ToolCallEvent,
        ToolResultEvent,
        AssistantEvent,
    ]
    assert [type(e) for e in events2] == [
        UserMessageEvent,
        AssistantEvent,
        ToolCallEvent,
        ToolResultEvent,
        AssistantEvent,
    ]
