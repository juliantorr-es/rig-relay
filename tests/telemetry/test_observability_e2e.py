from __future__ import annotations

import importlib
import json
from pathlib import Path

from jsonschema import validate
import pytest

from vibe.core.config import VibeConfig
from vibe.core.paths._vibe_home import SESSIONS_ROOT
from vibe.core.telemetry.constants import EventName
from vibe.core.telemetry.duckdb_projection import HAS_DUCKDB, DuckDBProjection
from vibe.core.telemetry.local import log_local_event

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


@pytest.fixture(autouse=True)
def telemetry_events():
    """Override the autouse mock from conftest to allow real telemetry to flow."""
    return []


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
    import vibe.core.agent_loop
    import vibe.core.paths._vibe_home
    import vibe.core.telemetry.duckdb_projection
    import vibe.core.telemetry.local
    import vibe.core.telemetry.send

    importlib.reload(vibe.core.paths._vibe_home)
    importlib.reload(vibe.core.telemetry.local)
    importlib.reload(vibe.core.telemetry.send)
    importlib.reload(vibe.core.telemetry.duckdb_projection)
    importlib.reload(vibe.core.agent_loop)

    # Re-apply the real method to the class just in case the reload didn't fully clean it
    from vibe.core.telemetry.send import TelemetryClient as RealClient

    monkeypatch.setattr(
        "vibe.core.telemetry.send.TelemetryClient.send_telemetry_event",
        RealClient.send_telemetry_event,
    )

    return vibe.core.telemetry.send.TelemetryClient


@pytest.mark.asyncio
async def test_observability_e2e_request_accounting(
    tmp_path, monkeypatch, observability_schema
):
    """Test the full chain: log_local_event -> JSONL -> Schema -> DuckDB."""
    monkeypatch.chdir(tmp_path)

    session_id = "e2e-session-request"
    payload = {
        "context_accounting": {
            "model": "gpt-4",
            "call_type": "main_call",
            "message_id": "msg-123",
            "total_messages": 5,
            "total_chars": 1000,
            "estimated_tokens": 250,
            "by_role": {"user": 500, "assistant": 500},
            "largest_messages": [],
            "system_prompt_chars": 100,
            "tool_result_chars": 0,
            "user_message_chars": 400,
            "assistant_message_chars": 500,
            "stable_prefix_fingerprint": "abc",
            "dynamic_suffix_fingerprint": "def",
        }
    }

    # 1. Emit event
    log_local_event(
        session_id=session_id,
        event_name=EventName.REQUEST_ACCOUNTED,
        payload=payload,
        receipt_candidate=False,
    )

    # 2. Verify JSONL exists and matches schema
    log_file = SESSIONS_ROOT.path / session_id / "observability.jsonl"
    assert log_file.exists()

    line = log_file.read_text().splitlines()[0]
    event = json.loads(line)
    validate(instance=event, schema=observability_schema)
    assert event["event_name"] == EventName.REQUEST_ACCOUNTED

    # 3. Run DuckDB Projection
    if not HAS_DUCKDB:
        pytest.skip("DuckDB not installed, skipping projection phase")

    session_root = SESSIONS_ROOT.path
    analyzer = DuckDBProjection(session_root)
    summary = analyzer.get_summary()

    assert summary.sessions_seen == 1
    assert summary.events_seen == 1
    assert summary.request_count == 1
    assert summary.max_estimated_tokens == 250
    assert summary.avg_estimated_tokens == 250.0
    assert summary.events_by_name[EventName.REQUEST_ACCOUNTED] == 1
    assert not summary.errors


@pytest.mark.asyncio
async def test_observability_e2e_tool_completion(
    tmp_path, mock_config, monkeypatch, real_telemetry_client, observability_schema
):
    """Test the full chain: TelemetryClient -> local.py -> JSONL -> DuckDB for tool completions."""
    monkeypatch.chdir(tmp_path)

    session_id = "e2e-session-tool"
    client = real_telemetry_client(
        config_getter=lambda: mock_config, session_id_getter=lambda: session_id
    )

    from pydantic import BaseModel

    from vibe.core.llm.format import ResolvedToolCall
    from vibe.core.tools.base import BaseTool

    class MockArgs(BaseModel):
        pass

    tool_call = ResolvedToolCall(
        call_id="call-1", tool_name="ls", tool_class=BaseTool, validated_args=MockArgs()
    )

    # 1. Emit tool completion via TelemetryClient
    client.send_tool_call_finished(
        tool_call=tool_call,
        status="success",
        decision=None,
        result={"files": ["test.txt"], "file_existed": False},
        model="gpt-4",
        agent_profile_name="default",
    )

    # 2. Verify JSONL envelope has receipt_candidate: True
    log_file = SESSIONS_ROOT.path / session_id / "observability.jsonl"
    line = log_file.read_text().splitlines()[0]
    event = json.loads(line)
    validate(instance=event, schema=observability_schema)
    assert event["event_name"] == EventName.TOOL_CALL_COMPLETED
    assert event["receipt_candidate"] is True

    # 3. Run DuckDB Projection
    if not HAS_DUCKDB:
        pytest.skip("DuckDB not installed, skipping projection phase")

    session_root = SESSIONS_ROOT.path
    analyzer = DuckDBProjection(session_root)
    summary = analyzer.get_summary()

    assert summary.receipt_candidate_count == 1
    assert summary.tool_calls_by_name["ls"] == 1
    assert summary.tool_calls_by_status["success"] == 1
    assert not summary.errors


@pytest.mark.asyncio
async def test_observability_e2e_artifacting(
    tmp_path, mock_config, monkeypatch, real_telemetry_client, observability_schema
):
    """Test the full chain: AgentLoop -> ArtifactWriter -> JSONL -> DuckDB for large outputs."""
    monkeypatch.chdir(tmp_path)

    # We need a mock AgentLoop or a real one with minimal dependencies
    from vibe.core.agent_loop import AgentLoop

    session_id = "e2e-session-artifact"
    # We'll manually trigger _handle_tool_response on an AgentLoop instance
    loop = AgentLoop(config=mock_config)
    loop.session_id = session_id

    from pydantic import BaseModel

    from vibe.core.llm.format import ResolvedToolCall
    from vibe.core.tools.base import BaseTool

    class MockArgs(BaseModel):
        command: str

    tool_call = ResolvedToolCall(
        call_id="call-big",
        tool_name="bash",
        tool_class=BaseTool,
        validated_args=MockArgs(command="cat big_file"),
    )

    # Very large output to trigger artifacting
    big_text = "A" * 20000

    loop._handle_tool_response(tool_call=tool_call, text=big_text, status="success")

    # 1. Verify message was excerpted
    assert len(loop.messages[-1].content) < len(big_text)
    assert "[TRUNCATED]" in loop.messages[-1].content

    # 2. Verify artifact exists
    artifact_dir = SESSIONS_ROOT.path / session_id / "artifacts" / "tool-results"
    artifacts = list(artifact_dir.glob("*.json"))
    assert len(artifacts) == 1

    # 3. Verify observability event
    log_file = SESSIONS_ROOT.path / session_id / "observability.jsonl"
    events = [json.loads(line) for line in log_file.read_text().splitlines()]
    artifact_event = next(
        e for e in events if e["event_name"] == EventName.ARTIFACT_WRITTEN
    )
    assert artifact_event["payload"]["raw_byte_size"] > 20000
    assert artifact_event["receipt_candidate"] is True
    # Verify metadata only, not raw output
    assert "raw_output" not in artifact_event["payload"]
    assert "prompt_excerpt" not in artifact_event["payload"]
    assert (
        artifact_event["payload"]["schema_version"]
        == "rig.relay.tool_output_artifact.v1"
    )
    assert artifact_event["payload"]["payload_sha256"].startswith("sha256:")

    # 4. Verify DuckDB Projection
    if not HAS_DUCKDB:
        pytest.skip("DuckDB not installed")

    session_root = SESSIONS_ROOT.path
    analyzer = DuckDBProjection(session_root)
    summary = analyzer.get_summary()

    assert summary.artifact_count == 1
    assert summary.artifact_raw_bytes_total > 20000
    assert summary.artifact_bytes_saved_estimate > 10000
    assert summary.artifacts_by_tool["bash"] == 1


@pytest.mark.asyncio
async def test_observability_e2e_context_assembly(
    tmp_path, mock_config, monkeypatch, real_telemetry_client, observability_schema
):
    """Test the full chain: AgentLoop -> ContextAssembler -> JSONL -> DuckDB."""
    monkeypatch.chdir(tmp_path)

    from vibe.core.agent_loop import AgentLoop
    from vibe.core.types import LLMMessage, Role

    session_id = "e2e-session-context"
    loop = AgentLoop(config=mock_config)
    loop.session_id = session_id
    loop.messages.append(LLMMessage(role=Role.system, content="System"))
    loop.messages.append(LLMMessage(role=Role.user, content="Hello"))

    from vibe.core.config import ModelConfig

    model = ModelConfig(name="test-model", provider="test", alias="test", backend="api")

    # 1. Trigger context assembly report
    await loop._report_context_assembly(model)

    # 2. Verify JSONL exists and matches schema
    log_file = SESSIONS_ROOT.path / session_id / "observability.jsonl"
    line = log_file.read_text().splitlines()[0]
    event = json.loads(line)
    validate(instance=event, schema=observability_schema)
    assert event["event_name"] == EventName.CONTEXT_ASSEMBLY_REPORTED

    # Verify metadata only
    assert "blocks" not in event["payload"]
    assert "stable_prefix_bytes" in event["payload"]

    # 3. Verify report artifact exists (assembly and layout)
    report_dir = SESSIONS_ROOT.path / session_id / "context"
    reports = list(report_dir.glob("*.json"))
    assert len(reports) >= 1

    # 4. Verify DuckDB Projection
    if not HAS_DUCKDB:
        pytest.skip("DuckDB not installed")

    session_root = SESSIONS_ROOT.path
    analyzer = DuckDBProjection(session_root)
    summary = analyzer.get_summary()

    assert summary.context_assembly_count == 1
    assert summary.max_stable_prefix_bytes > 0
    assert summary.avg_context_estimated_tokens > 0


@pytest.mark.asyncio
async def test_observability_e2e_context_layout(
    tmp_path, mock_config, monkeypatch, real_telemetry_client, observability_schema
):
    """Test the full chain: AgentLoop -> ContextLayoutPlan -> JSONL -> DuckDB."""
    monkeypatch.chdir(tmp_path)

    from vibe.core.agent_loop import AgentLoop
    from vibe.core.types import LLMMessage, Role

    session_id = "e2e-session-layout"
    loop = AgentLoop(config=mock_config)
    loop.session_id = session_id
    loop.messages.append(LLMMessage(role=Role.system, content="System"))
    loop.messages.append(LLMMessage(role=Role.user, content="Hello"))

    from vibe.core.config import ModelConfig

    model = ModelConfig(name="test-model", provider="test", alias="test", backend="api")

    # 1. Trigger context reporting (includes assembly and layout)
    await loop._report_context_assembly(model)

    # 2. Verify JSONL exists and matches schema
    log_file = SESSIONS_ROOT.path / session_id / "observability.jsonl"
    lines = log_file.read_text().splitlines()

    # Assembly report
    event1 = json.loads(lines[0])
    assert event1["event_name"] == EventName.CONTEXT_ASSEMBLY_REPORTED

    # Layout plan
    event2 = json.loads(lines[1])
    validate(instance=event2, schema=observability_schema)
    assert event2["event_name"] == EventName.CONTEXT_LAYOUT_PLANNED
    assert event2["payload"]["prefix_stability_status"] == "unknown"

    # 3. Verify layout artifact exists
    report_dir = SESSIONS_ROOT.path / session_id / "context"
    layouts = list(report_dir.glob("layout_*.json"))
    assert len(layouts) == 1

    # 4. Verify DuckDB Projection
    if not HAS_DUCKDB:
        pytest.skip("DuckDB not installed")

    session_root = SESSIONS_ROOT.path
    analyzer = DuckDBProjection(session_root)
    summary = analyzer.get_summary()

    assert summary.context_layout_count == 1
    assert summary.avg_cacheability_ratio > 0
    assert summary.max_cache_candidate_bytes > 0
