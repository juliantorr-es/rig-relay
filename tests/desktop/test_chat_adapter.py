from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from rig_relay.core.tools.base import BaseTool
from rig_relay.core.types import (
    AssistantEvent,
    ToolCallEvent,
    ToolResultEvent,
    UserMessageEvent,
)
from rig_relay.desktop.chat_agent_adapter import ChatAgentAdapter
from rig_relay.desktop.chat_store import ChatStore


class DummyTool(BaseTool):
    async def run(self, args, ctx=None):
        if False:
            yield
        pass


@pytest.fixture
def chat_root(tmp_path):
    return tmp_path / "chat"


@pytest.fixture
def store(chat_root):
    return ChatStore(chat_root=chat_root)


@pytest.fixture
def mock_agent_loop():
    loop = MagicMock()
    loop.act = MagicMock()
    return loop


@pytest.mark.asyncio
async def test_adapter_process_message(store, mock_agent_loop):
    on_update = MagicMock()
    adapter = ChatAgentAdapter(mock_agent_loop, store, on_update)

    # Mock act to yield events
    async def mock_act(text, client_message_id):
        yield UserMessageEvent(content=text, message_id=client_message_id)
        yield AssistantEvent(content="Hello", message_id="msg1")
        yield AssistantEvent(content=" world", message_id="msg1")

    mock_agent_loop.act.side_effect = mock_act

    await adapter.process_message("Hi", "c1")
    # Wait for the task to finish
    while adapter.is_running:
        await asyncio.sleep(0.01)

    state = store.load_state()
    assert len(state.messages) == 2
    assert state.messages[0].content == "Hi"
    assert state.messages[1].content == "Hello world"
    assert on_update.called


@pytest.mark.asyncio
async def test_adapter_tool_events(store, mock_agent_loop):
    on_update = MagicMock()
    adapter = ChatAgentAdapter(mock_agent_loop, store, on_update)

    async def mock_act(text, client_message_id):
        from pydantic import BaseModel

        class DummyResult(BaseModel):
            output: str

        yield UserMessageEvent(content=text, message_id=client_message_id)
        yield ToolCallEvent(tool_call_id="t1", tool_name="ls", tool_class=DummyTool)
        yield ToolResultEvent(
            tool_name="ls",
            tool_class=DummyTool,
            tool_call_id="t1",
            result=DummyResult(output="files..."),
        )

    mock_agent_loop.act.side_effect = mock_act

    await adapter.process_message("List files", "c2")
    while adapter.is_running:
        await asyncio.sleep(0.01)

    state = store.load_state()
    assert len(state.messages) == 2  # User + Tool status
    assert "Tool ls finished: output='files...'" in state.messages[1].content
    assert state.messages[1].status == "success"


@pytest.mark.asyncio
async def test_adapter_cancellation(store, mock_agent_loop):
    on_update = MagicMock()
    adapter = ChatAgentAdapter(mock_agent_loop, store, on_update)

    # Use an event to synchronize the test
    started = asyncio.Event()

    async def mock_act(text, client_message_id):
        started.set()
        yield AssistantEvent(content="Thinking...", message_id="m1")
        try:
            await asyncio.sleep(10)  # Long sleep
        except asyncio.CancelledError:
            # Finalize status happens in adapter, but we catch it here to end mock
            raise
        yield AssistantEvent(content="Done", message_id="m1")

    mock_agent_loop.act.side_effect = mock_act

    # Start processing (don't await yet as it waits for task to start)
    await adapter.process_message("Wait", "c3")
    await started.wait()
    await asyncio.sleep(0.1)  # Let events process

    adapter.cancel()

    # Wait for completion
    while adapter.is_running:
        await asyncio.sleep(0.01)

    state = store.load_state()
    assert state.pending_response is False
    # Verify final status was set to cancelled
    for msg in state.messages:
        if msg.role == "status":  # Thinking message
            assert msg.status == "cancelled"


@pytest.mark.asyncio
async def test_adapter_concurrent_send_refused(store, mock_agent_loop):
    on_update = MagicMock()
    adapter = ChatAgentAdapter(mock_agent_loop, store, on_update)

    started = asyncio.Event()

    async def mock_act(text, client_message_id):
        started.set()
        await asyncio.sleep(1)
        yield AssistantEvent(content="Done", message_id="m1")

    mock_agent_loop.act.side_effect = mock_act

    await adapter.process_message("First", "c1")
    await started.wait()
    assert adapter.is_running is True

    # Try second message
    await adapter.process_message("Second", "c2")
    # Should be ignored (only one task created)
    assert mock_agent_loop.act.call_count == 1


@pytest.mark.asyncio
async def test_adapter_tool_output_sanitization(store, mock_agent_loop):
    on_update = MagicMock()
    adapter = ChatAgentAdapter(mock_agent_loop, store, on_update)

    async def mock_act(text, client_message_id):
        from pydantic import BaseModel

        class DummyResult(BaseModel):
            output: str

        yield ToolCallEvent(tool_call_id="t1", tool_name="ls", tool_class=DummyTool)
        # Test diff sanitization
        yield ToolResultEvent(
            tool_name="diff",
            tool_class=DummyTool,
            tool_call_id="t1",
            result=DummyResult(output="--- a/file\n+++ b/file\n-old\n+new"),
        )

    mock_agent_loop.act.side_effect = mock_act

    await adapter.process_message("Show diff", "c3")
    while adapter.is_running:
        await asyncio.sleep(0.01)

    state = store.load_state()
    assert "[diff content omitted]" in state.messages[0].content


@pytest.mark.asyncio
async def test_adapter_error_handling(store, mock_agent_loop):
    on_update = MagicMock()
    adapter = ChatAgentAdapter(mock_agent_loop, store, on_update)

    async def mock_act(text, client_message_id):
        raise ValueError("Simulated provider failure")

    mock_agent_loop.act.side_effect = mock_act

    await adapter.process_message("Fail", "c4")
    while adapter.is_running:
        await asyncio.sleep(0.01)

    state = store.load_state()
    assert state.pending_response is False
    # Check if we have an error message
    assert any(msg.status == "error" for msg in state.messages)
    assert any(
        "failed" in msg.content.lower()
        for msg in state.messages
        if msg.status == "error"
    )

    import json

    events = []
    if store._events_path.exists():
        with open(store._events_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))

    assert any(e["event_name"] == "chat.response.error" for e in events)
