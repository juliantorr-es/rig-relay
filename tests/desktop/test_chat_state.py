from __future__ import annotations

from datetime import datetime

import pytest

from rig_relay.desktop.chat_state import ChatMessage, ChatRole, ChatState

pytestmark = [pytest.mark.integration]

def test_chat_state_creation():
    state = ChatState()
    assert state.schema_version == 1
    assert not state.backend_wired
    assert len(state.messages) == 0
    assert isinstance(state.generated_at, datetime)


def test_chat_message_creation():
    msg = ChatMessage(role=ChatRole.USER, content="Hello")
    assert msg.role == ChatRole.USER
    assert msg.content == "Hello"
    assert msg.message_id is not None
    assert isinstance(msg.created_at, datetime)


def test_chat_state_serialization():
    state = ChatState(
        backend_wired=True,
        messages=[ChatMessage(role=ChatRole.ASSISTANT, content="Hi", status="ok")],
    )
    data = state.model_dump(mode="json")
    assert data["backend_wired"] is True
    assert data["messages"][0]["role"] == "assistant"
    assert data["messages"][0]["content"] == "Hi"
    assert data["messages"][0]["status"] == "ok"
    assert "message_id" in data["messages"][0]
    assert "created_at" in data["messages"][0]


def test_chat_role_enum():
    assert ChatRole.USER == "user"
    assert ChatRole.ASSISTANT == "assistant"
    assert ChatRole.SYSTEM == "system"
    assert ChatRole.TOOL == "tool"
    assert ChatRole.STATUS == "status"


def test_chat_message_metadata():
    msg = ChatMessage(role=ChatRole.USER, content="Test", metadata={"client_id": "123"})
    assert msg.metadata["client_id"] == "123"
    data = msg.model_dump(mode="json")
    assert data["metadata"]["client_id"] == "123"
