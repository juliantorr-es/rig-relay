from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.cli.desktop_cockpit import CockpitAPI
from rig_relay.desktop.chat_state import ChatMessage, ChatRole, ChatState
from rig_relay.desktop.chat_store import ChatStore


@pytest.fixture
def chat_root(tmp_path: Path) -> Path:
    return tmp_path / "chat"


def test_chat_store_save_load(chat_root: Path):
    store = ChatStore(chat_root=chat_root)
    state = ChatState()
    state.messages.append(ChatMessage(role=ChatRole.USER, content="Hello"))

    store.save_state(state)
    assert (chat_root / "chat_state.json").is_file()

    loaded = store.load_state()
    assert len(loaded.messages) == 1
    assert loaded.messages[0].content == "Hello"


def test_chat_store_append_event(chat_root: Path):
    store = ChatStore(chat_root=chat_root)
    msg = ChatMessage(
        role=ChatRole.USER, content="Hello", metadata={"client_message_id": "c1"}
    )

    event_id = store.append_event("chat.message.created", message=msg)
    assert (chat_root / "chat_events.jsonl").is_file()

    with open(chat_root / "chat_events.jsonl") as f:
        line = f.readline()
        event = json.loads(line)
        assert event["event_id"] == event_id
        assert event["event_name"] == "chat.message.created"
        assert event["content_preview"] == "Hello"
        assert event["client_message_id"] == "c1"
        assert "content_sha256" in event


def test_cockpit_api_persistence(chat_root: Path):
    # Mock BUILD_ROOT in CockpitAPI is hard
    # We'll just test that it uses the store correctly
    api = CockpitAPI()
    api._store = ChatStore(chat_root=chat_root)  # Inject test store
    api._chat_state = ChatState()

    api.send_chat_message("Hello", "c1")

    # Verify files exist
    assert (chat_root / "chat_state.json").is_file()
    assert (chat_root / "chat_events.jsonl").is_file()

    # Reload in new API instance
    api2 = CockpitAPI()
    api2._store = ChatStore(chat_root=chat_root)
    api2._chat_state = api2._store.load_state()

    assert len(api2._chat_state.messages) == 1  # User only (Assistant is async)
    assert api2._chat_state.messages[0].content == "Hello"


def test_cockpit_api_idempotency_after_reload(chat_root: Path):
    store = ChatStore(chat_root=chat_root)
    api = CockpitAPI()
    api._store = store
    api._chat_state = ChatState()

    api.send_chat_message("Hello", "c1")
    initial_count = len(api._chat_state.messages)

    # Simulate reload
    api2 = CockpitAPI()
    api2._store = store
    api2._chat_state = store.load_state()

    # Send same client ID
    res = api2.send_chat_message("Hello", "c1")
    assert len(res["messages"]) == initial_count


def test_cockpit_api_clear_persists(chat_root: Path):
    store = ChatStore(chat_root=chat_root)
    api = CockpitAPI()
    api._store = store
    api._chat_state = ChatState()

    api.send_chat_message("Hello")
    api.clear_chat_view()

    # Reload
    api2 = CockpitAPI()
    api2._store = store
    api2._chat_state = store.load_state()
    assert len(api2._chat_state.messages) == 0
