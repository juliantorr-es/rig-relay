from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import patch

from jsonschema import validate
import pytest

from vibe.core.paths._vibe_home import SESSIONS_ROOT
from vibe.core.config import VibeConfig
from vibe.core.telemetry.constants import EventName
import vibe.core.telemetry.send
from vibe.core.types import LLMMessage, Role

SCHEMA_PATH = (
    Path(__file__).parent.parent.parent
    / "docs"
    / "architecture"
    / "schemas"
    / "rig.relay.observability.v1.schema.json"
)


@pytest.fixture(autouse=True)
def rig_home(tmp_path, monkeypatch):
    monkeypatch.setenv("RIG_RELAY_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def observability_schema():
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture
def mock_config():
    config = VibeConfig()
    config.enable_local_observability = True
    config.enable_remote_telemetry = False
    return config


@pytest.fixture
def real_telemetry_client(monkeypatch):
    """Force reload of telemetry modules to ensure we use the real implementation."""
    import vibe.core.paths._vibe_home
    import vibe.core.telemetry.local
    import vibe.core.telemetry.send

    importlib.reload(vibe.core.paths._vibe_home)
    importlib.reload(vibe.core.telemetry.local)
    importlib.reload(vibe.core.telemetry.send)

    # Re-apply the real method to the class just in case the reload didn't fully clean it
    from vibe.core.telemetry.send import TelemetryClient as RealClient
    monkeypatch.setattr(
        "vibe.core.telemetry.send.TelemetryClient.send_telemetry_event",
        RealClient.send_telemetry_event
    )

    return vibe.core.telemetry.send.TelemetryClient


@pytest.mark.asyncio
async def test_local_observability_writes_formal_envelope(
    tmp_path, mock_config, monkeypatch, real_telemetry_client, observability_schema
):
    monkeypatch.chdir(tmp_path)

    sid = "test-session"
    client = real_telemetry_client(
        config_getter=lambda: mock_config, session_id_getter=lambda: sid
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
        messages=messages,
    )

    log_file = SESSIONS_ROOT.path / sid / "observability.jsonl"
    assert log_file.exists()

    lines = log_file.read_text().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])

    # Validate against schema
    validate(instance=event, schema=observability_schema)

    # Check formal envelope
    assert event["schema_version"] == "rig.relay.observability.v1"
    assert event["event_name"] == EventName.REQUEST_ACCOUNTED
    assert event["receipt_candidate"] is False
    assert event["event_hash"].startswith("sha256:")


@pytest.mark.asyncio
async def test_local_observability_sequencing(
    tmp_path, mock_config, monkeypatch, real_telemetry_client
):
    monkeypatch.chdir(tmp_path)
    sid = "seq-session"

    client = real_telemetry_client(
        config_getter=lambda: mock_config, session_id_getter=lambda: sid
    )

    # Send three events
    client.send_telemetry_event("event.one", {"idx": 1})
    client.send_telemetry_event("event.two", {"idx": 2})
    client.send_telemetry_event("event.three", {"idx": 3})

    log_file = SESSIONS_ROOT.path / sid / "observability.jsonl"
    lines = log_file.read_text().splitlines()
    assert len(lines) == 3

    for i, line in enumerate(lines):
        event = json.loads(line)
        assert event["sequence"] == i
        assert event["event_name"] == f"rig.relay.event.{['one', 'two', 'three'][i]}"


@pytest.mark.asyncio
async def test_local_observability_hash_stability(
    tmp_path, mock_config, monkeypatch, real_telemetry_client
):
    monkeypatch.chdir(tmp_path)
    sid = "hash-session"

    client = real_telemetry_client(
        config_getter=lambda: mock_config, session_id_getter=lambda: sid
    )

    # Send identical event twice (wiping file in between to keep sequence=0)
    log_file = SESSIONS_ROOT.path / sid / "observability.jsonl"

    with patch("vibe.core.telemetry.local.datetime") as mock_datetime:
        fixed_now = "2024-01-01T00:00:00+00:00"
        mock_datetime.now.return_value.isoformat.return_value = fixed_now

        with patch("vibe.core.telemetry.local.uuid.uuid4") as mock_uuid:
            mock_uuid.return_value = "00000000-0000-0000-0000-000000000000"

            client.send_telemetry_event("stable.event", {"data": 1})
            event1 = json.loads(log_file.read_text().splitlines()[0])

            # Wipe and repeat
            log_file.unlink()
            client.send_telemetry_event("stable.event", {"data": 1})
            event2 = json.loads(log_file.read_text().splitlines()[0])

    assert event1["event_hash"] == event2["event_hash"]
    assert event1["event_hash"].startswith("sha256:")


@pytest.mark.asyncio
async def test_local_observability_receipt_candidate(
    tmp_path, mock_config, monkeypatch, real_telemetry_client
):
    monkeypatch.chdir(tmp_path)
    sid = "receipt-session"

    client = real_telemetry_client(
        config_getter=lambda: mock_config, session_id_getter=lambda: sid
    )

    # Directly test with the receipt_candidate flag
    client.send_telemetry_event(
        EventName.TOOL_CALL_COMPLETED, {"tool": "test"}, receipt_candidate=True
    )

    log_file = SESSIONS_ROOT.path / sid / "observability.jsonl"
    line = log_file.read_text().splitlines()[0]
    event = json.loads(line)
    assert event["event_name"] == EventName.TOOL_CALL_COMPLETED
    assert event["receipt_candidate"] is True


@pytest.mark.asyncio
async def test_remote_telemetry_disabled_by_default():
    config = VibeConfig()
    assert config.enable_local_observability is True
    assert config.enable_remote_telemetry is False
