from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rig_relay.desktop.chat_state import ChatRole
from scripts.rig_relay_desktop_cockpit import CockpitAPI


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.load_state.return_value = MagicMock(messages=[], pending_response=False)
    return store


@pytest.fixture
def api(mock_store):
    with patch("scripts.rig_relay_desktop_cockpit.ChatStore", return_value=mock_store):
        with patch("scripts.rig_relay_desktop_cockpit.VibeConfig.load"):
            with patch("scripts.rig_relay_desktop_cockpit.AgentLoop"):
                with patch(
                    "scripts.rig_relay_desktop_cockpit.ChatAgentAdapter"
                ) as mock_adapter_cls:
                    api = CockpitAPI()
                    api._adapter = mock_adapter_cls.return_value
                    api._adapter.is_running = False
                    return api


def test_cockpit_api_refuses_concurrent_send(api):
    api._adapter.is_running = True
    result = api.send_chat_message("Hi")
    assert result == {"error": "another_response_active"}


def test_cockpit_api_cancel_no_active_returns_error(api):
    api._adapter.is_running = False
    result = api.cancel_chat_response()
    assert result == {"error": "no_active_response"}


def test_cockpit_api_idempotency_duplicate_client_id(api):
    # Setup some existing messages
    msg = MagicMock(role=ChatRole.USER)
    msg.metadata = {"client_message_id": "c1"}
    api._chat_state.messages = [msg]

    # Send same client_id
    result = api.send_chat_message("Hi again", client_message_id="c1")
    # Should return state without starting a new loop
    assert api._adapter.process_message.call_count == 0


def test_cockpit_api_cross_thread_scheduling(api):
    loop = MagicMock()
    api._loop_holder = [loop]

    with patch("asyncio.run_coroutine_threadsafe") as mock_run:
        api.send_chat_message("Thread safe?")
        assert mock_run.called
        assert mock_run.call_args[0][1] == loop
