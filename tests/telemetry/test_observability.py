from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest
from vibe.core.config import VibeConfig
from vibe.core.telemetry.send import TelemetryClient
from vibe.core.types import LLMMessage, Role

@pytest.fixture
def mock_config():
    config = VibeConfig()
    config.enable_local_observability = True
    config.enable_remote_telemetry = False
    return config

@pytest.mark.asyncio
async def test_local_observability_writes_jsonl(tmp_path, mock_config, monkeypatch):
    monkeypatch.chdir(tmp_path)
    
    sid = "test-session"
    # conftest.py mocks send_telemetry_event via monkeypatch.
    # We use patch.object to ensure we are using the real method here.
    with patch.object(TelemetryClient, "send_telemetry_event", TelemetryClient.send_telemetry_event):
        client = TelemetryClient(
            config_getter=lambda: mock_config,
            session_id_getter=lambda: sid
        )
        
        messages = [
            LLMMessage(role=Role.system, content="System prompt"),
            LLMMessage(role=Role.user, content="Hello"),
        ]
        
        client.send_request_sent(
            model="test-model",
            nb_context_chars=100,
            nb_context_messages=2,
            nb_prompt_chars=5,
            call_type="main_call",
            messages=messages
        )
        
    log_file = tmp_path / ".rig" / "relay" / "sessions" / sid / "observability.jsonl"
    assert log_file.exists()
    
    lines = log_file.read_text().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event_name"] == "rig.relay.context.request_accounted"
    assert "context_accounting" in event["payload"]
    accounting = event["payload"]["context_accounting"]
    assert accounting["total_messages"] == 2
    assert accounting["system_prompt_chars"] == len("System prompt")
    assert "stable_prefix_fingerprint" in accounting

@pytest.mark.asyncio
async def test_local_observability_works_without_api_key(tmp_path, mock_config, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    
    sid = "test-session-no-key"
    with patch.object(TelemetryClient, "send_telemetry_event", TelemetryClient.send_telemetry_event):
        client = TelemetryClient(
            config_getter=lambda: mock_config,
            session_id_getter=lambda: sid
        )
        
        assert client.is_active() is False
        
        client.send_telemetry_event("test.event", {"foo": "bar"})
        
    log_file = tmp_path / ".rig" / "relay" / "sessions" / sid / "observability.jsonl"
    assert log_file.exists()

@pytest.mark.asyncio
async def test_remote_telemetry_disabled_by_default():
    config = VibeConfig()
    # Default: local=True, remote=False
    assert config.enable_local_observability is True
    assert config.enable_remote_telemetry is False
    assert config.enable_telemetry is False
