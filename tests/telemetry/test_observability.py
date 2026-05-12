from __future__ import annotations

import json
import os
import importlib
from pathlib import Path
from unittest.mock import patch
import pytest
from vibe.core.config import VibeConfig
import vibe.core.telemetry.send
from vibe.core.telemetry.constants import EventName
from vibe.core.types import LLMMessage, Role

@pytest.fixture
def mock_config():
    config = VibeConfig()
    config.enable_local_observability = True
    config.enable_remote_telemetry = False
    return config

@pytest.fixture
def real_telemetry_client():
    # Force reload to get the real send_telemetry_event (not the conftest mock)
    importlib.reload(vibe.core.telemetry.send)
    return vibe.core.telemetry.send.TelemetryClient

@pytest.mark.asyncio
async def test_local_observability_writes_formal_envelope(tmp_path, mock_config, monkeypatch, real_telemetry_client):
    monkeypatch.chdir(tmp_path)
    
    sid = "test-session"
    client = real_telemetry_client(
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
    
    # Check formal envelope
    assert event["schema_version"] == "rig.relay.observability.v1"
    assert "event_id" in event
    assert event["session_id"] == sid
    assert event["sequence"] == 0
    assert "created_at" in event
    assert event["event_name"] == EventName.REQUEST_ACCOUNTED
    assert event["producer"]["name"] == "rig-relay"
    assert "version" in event["producer"]
    assert event["receipt_candidate"] is False
    assert "event_hash" in event
    
    # Check payload
    assert "context_accounting" in event["payload"]
    accounting = event["payload"]["context_accounting"]
    assert accounting["total_messages"] == 2
    assert "stable_prefix_fingerprint" in accounting

@pytest.mark.asyncio
async def test_local_observability_sequencing(tmp_path, mock_config, monkeypatch, real_telemetry_client):
    monkeypatch.chdir(tmp_path)
    sid = "seq-session"
    
    client = real_telemetry_client(
        config_getter=lambda: mock_config,
        session_id_getter=lambda: sid
    )
    
    # Send three events
    client.send_telemetry_event("event.one", {"idx": 1})
    client.send_telemetry_event("event.two", {"idx": 2})
    client.send_telemetry_event("event.three", {"idx": 3})
        
    log_file = tmp_path / ".rig" / "relay" / "sessions" / sid / "observability.jsonl"
    lines = log_file.read_text().splitlines()
    assert len(lines) == 3
    
    for i, line in enumerate(lines):
        event = json.loads(line)
        assert event["sequence"] == i
        assert event["event_name"] == f"rig.relay.event.{['one', 'two', 'three'][i]}"

@pytest.mark.asyncio
async def test_local_observability_receipt_candidate(tmp_path, mock_config, monkeypatch, real_telemetry_client):
    monkeypatch.chdir(tmp_path)
    sid = "receipt-session"
    
    client = real_telemetry_client(
        config_getter=lambda: mock_config,
        session_id_getter=lambda: sid
    )
    
    # Directly test with the receipt_candidate flag
    client.send_telemetry_event(
        EventName.TOOL_CALL_COMPLETED, 
        {"tool": "test"}, 
        receipt_candidate=True
    )
        
    log_file = tmp_path / ".rig" / "relay" / "sessions" / sid / "observability.jsonl"
    line = log_file.read_text().splitlines()[0]
    event = json.loads(line)
    assert event["event_name"] == EventName.TOOL_CALL_COMPLETED
    assert event["receipt_candidate"] is True

@pytest.mark.asyncio
async def test_remote_telemetry_disabled_by_default():
    config = VibeConfig()
    assert config.enable_local_observability is True
    assert config.enable_remote_telemetry is False
