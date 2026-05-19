from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from rig_relay.acp.acp_agent_loop import VibeAcpAgentLoop
from rig_relay.core.agent_loop import AgentLoop
from rig_relay.core.types import LLMChunk, LLMMessage, LLMUsage, Role
from tests.stubs.fake_backend import FakeBackend
from tests.stubs.fake_client import FakeClient


@pytest.fixture
def backend() -> FakeBackend:
    backend = FakeBackend(
        LLMChunk(
            message=LLMMessage(role=Role.assistant, content="Hi"),
            usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
        )
    )
    return backend


def _create_acp_agent() -> VibeAcpAgentLoop:
    vibe_acp_agent = VibeAcpAgentLoop()
    client = FakeClient()
    vibe_acp_agent.on_connect(client)
    client.on_connect(vibe_acp_agent)
    return vibe_acp_agent


@pytest.fixture
def acp_agent_loop(backend: FakeBackend) -> VibeAcpAgentLoop:
    class PatchedAgent(AgentLoop):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs, backend=backend)

    patch("rig_relay.core.agent_loop.AgentLoop", side_effect=PatchedAgent).start()
    return _create_acp_agent()


@pytest.fixture
def temp_session_dir(tmp_path: Path) -> Path:
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    return session_dir
