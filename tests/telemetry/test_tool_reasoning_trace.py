from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import validate

from vibe.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
    ToolOutputKind,
    ToolReasoningTrace,
)

REPO_ROOT = Path(__file__).parent.parent.parent
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


def test_tool_reasoning_trace_schema_is_valid():
    schema_path = SCHEMA_DIR / "rig.relay.artifact.tool_reasoning_trace.v1.schema.json"
    assert schema_path.exists()
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["title"] == "Tool Reasoning Trace"
    assert "required" in schema
    assert schema["additionalProperties"] is False

    # Required fields should include core metadata
    required = schema["required"]
    for field in [
        "schema_version",
        "artifact_kind",
        "session_id",
        "tool_call_id",
        "tool_name",
        "normalized_input_sha256",
        "tool_output_kind",
        "tool_output_sha256",
        "latency_ms",
        "input_bytes",
        "output_bytes",
        "determinism_class",
        "mutation_class",
    ]:
        assert field in required, f"{field} should be required"


def test_tool_reasoning_trace_schema_validates_minimal():
    schema_path = SCHEMA_DIR / "rig.relay.artifact.tool_reasoning_trace.v1.schema.json"
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    # Minimal valid instance: all required fields, no rationale
    instance = {
        "schema_version": "rig.relay.artifact.tool_reasoning_trace.v1",
        "artifact_kind": "tool_reasoning_trace",
        "session_id": "session-123",
        "message_id": "msg-1",
        "tool_call_id": "call_001",
        "tool_name": "grep",
        "step_index": 0,
        "normalized_input_sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
        "tool_output_kind": "inline",
        "tool_output_sha256": "sha256:abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
        "latency_ms": 150.5,
        "input_bytes": 42,
        "output_bytes": 1024,
        "determinism_class": "deterministic_repo_state",
        "mutation_class": "read_only",
    }

    validate(instance=instance, schema=schema)


def test_tool_reasoning_trace_uses_relative_paths():
    """Tool output artifact path must be a relative path, not absolute."""
    trace = ToolReasoningTrace(
        session_id="s1",
        tool_call_id="c1",
        tool_name="grep",
        normalized_input_sha256="a" * 64,
        tool_output_sha256="sha256:" + "b" * 64,
        tool_output_artifact_path="sessions/s1/artifacts/tool-results/0001_grep.json",
    )
    path_val = trace.tool_output_artifact_path
    assert path_val is not None
    assert not path_val.startswith("/")
    assert not path_val.startswith("~")


def test_tool_reasoning_trace_records_core_fields():
    trace = ToolReasoningTrace(
        session_id="s1",
        tool_call_id="c1",
        tool_name="grep",
        normalized_input_sha256="a" * 64,
        tool_output_sha256="sha256:" + "b" * 64,
        determinism_class="deterministic_repo_state",
        mutation_class="read_only",
    )
    assert trace.tool_name == "grep"
    assert trace.tool_call_id == "c1"
    assert trace.determinism_class == "deterministic_repo_state"
    assert trace.mutation_class == "read_only"
    assert trace.normalized_input_sha256 == "a" * 64
    assert trace.tool_output_sha256 == "sha256:" + "b" * 64
    assert trace.schema_version == "rig.relay.artifact.tool_reasoning_trace.v1"
    assert trace.artifact_kind == "tool_reasoning_trace"


def test_tool_reasoning_trace_records_output_bytes_and_kind():
    trace = ToolReasoningTrace(
        session_id="s1",
        tool_call_id="c1",
        tool_name="write_file",
        normalized_input_sha256="a" * 64,
        tool_output_sha256="sha256:" + "b" * 64,
        tool_output_kind=ToolOutputKind.INLINE,
        latency_ms=200.0,
        input_bytes=100,
        output_bytes=5000,
        inline_output_bytes=5000,
        artifacted_output_bytes=0,
        truncated=False,
    )
    assert trace.tool_output_kind == ToolOutputKind.INLINE
    assert trace.latency_ms == 200.0
    assert trace.input_bytes == 100
    assert trace.output_bytes == 5000
    assert trace.inline_output_bytes == 5000
    assert trace.artifacted_output_bytes == 0
    assert trace.truncated is False


def test_missing_rationale_is_empty_not_fabricated():
    """When rationale is not available, fields must be empty strings, not None or placeholder."""
    trace = ToolReasoningTrace(
        session_id="s1",
        tool_call_id="c1",
        tool_name="grep",
        normalized_input_sha256="a" * 64,
        tool_output_sha256="sha256:" + "b" * 64,
    )
    assert trace.user_goal_summary == ""
    assert trace.active_plan_summary == ""
    assert trace.tool_selection_rationale_summary == ""
    assert trace.observation_summary == ""
    assert trace.decision_after_observation == ""
    # Not fabricated placeholders
    assert "(not" not in trace.tool_selection_rationale_summary
    assert "unavailable" not in trace.tool_selection_rationale_summary


def test_telemetry_send_reasoning_trace_signature():
    """Verify the send_tool_reasoning_trace method exists and accepts expected params."""
    from unittest.mock import MagicMock

    from vibe.core.telemetry.constants import EventName
    from vibe.core.telemetry.send import TelemetryClient

    mock_config = MagicMock()
    mock_config.enable_local_observability = False
    mock_config.enable_telemetry = False

    client = TelemetryClient(config_getter=lambda: mock_config)
    # Should not raise
    client.send_tool_reasoning_trace(
        session_id="s1",
        tool_name="grep",
        tool_call_id="c1",
        normalized_input_sha256="a" * 64,
        tool_output_sha256="sha256:" + "b" * 64,
        latency_ms=150.0,
        input_bytes=50,
        output_bytes=1024,
    )


def test_doctor_identifies_largest_inline_output():
    """Doctor summarize_tool_reasoning must identify largest inline outputs."""
    from vibe.core.telemetry.doctor import summarize_tool_reasoning
    from vibe.core.telemetry.local import dump_canonical_json
    from vibe.core.telemetry.constants import EventName

    tmp_dir = Path("/tmp/test_doctor_trace_inline")
    session_id = "test-inline"
    obs_dir = tmp_dir / "sessions" / session_id
    obs_dir.mkdir(parents=True, exist_ok=True)
    obs_path = obs_dir / "observability.jsonl"

    events = [
        {
            "event_name": EventName.TOOL_REASONING_TRACE,
            "payload": {
                "tool_name": "read_file",
                "tool_call_id": "c1",
                "inline_output_bytes": 50000,
                "artifacted_output_bytes": 0,
                "output_bytes": 50000,
                "latency_ms": 10,
            },
        },
        {
            "event_name": EventName.TOOL_REASONING_TRACE,
            "payload": {
                "tool_name": "bash",
                "tool_call_id": "c2",
                "inline_output_bytes": 200000,
                "artifacted_output_bytes": 0,
                "output_bytes": 200000,
                "latency_ms": 500,
            },
        },
    ]
    with obs_path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(dump_canonical_json(ev) + "\n")

    result = summarize_tool_reasoning(tmp_dir, session_id)
    assert result["total_traces"] == 2
    assert len(result["largest_inline_outputs"]) >= 1
    assert result["largest_inline_outputs"][0]["tool_name"] == "bash"
    assert result["largest_inline_outputs"][0]["inline_output_bytes"] == 200000


def test_doctor_identifies_slow_tool_call():
    """Doctor summarize_tool_reasoning must identify slowest tool calls."""
    from vibe.core.telemetry.doctor import summarize_tool_reasoning
    from vibe.core.telemetry.local import dump_canonical_json
    from vibe.core.telemetry.constants import EventName

    tmp_dir = Path("/tmp/test_doctor_trace_slow")
    session_id = "test-slow"
    obs_dir = tmp_dir / "sessions" / session_id
    obs_dir.mkdir(parents=True, exist_ok=True)
    obs_path = obs_dir / "observability.jsonl"

    events = [
        {
            "event_name": EventName.TOOL_REASONING_TRACE,
            "payload": {
                "tool_name": "grep",
                "tool_call_id": "c1",
                "latency_ms": 50,
                "output_bytes": 1000,
            },
        },
        {
            "event_name": EventName.TOOL_REASONING_TRACE,
            "payload": {
                "tool_name": "bash",
                "tool_call_id": "c2",
                "latency_ms": 5000,
                "output_bytes": 50000,
            },
        },
    ]
    with obs_path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(dump_canonical_json(ev) + "\n")

    result = summarize_tool_reasoning(tmp_dir, session_id)
    assert result["total_traces"] == 2
    assert len(result["slowest_tool_calls"]) >= 1
    assert result["slowest_tool_calls"][0]["tool_name"] == "bash"
    assert result["slowest_tool_calls"][0]["latency_ms"] == 5000


def test_doctor_tool_reasoning_missing_log():
    """Doctor should handle missing observability log gracefully."""
    from vibe.core.telemetry.doctor import summarize_tool_reasoning

    result = summarize_tool_reasoning(Path("/nonexistent"), "no-session")
    assert result["traces"] == []
    assert any("missing" in w.lower() for w in result["warnings"])


def test_tool_reasoning_trace_determinism_contract():
    """ToolReasoningTrace should serialize cleanly to dict matching ToolDogfoodContract pattern."""
    trace = ToolReasoningTrace(
        session_id="s1",
        tool_call_id="c1",
        tool_name="grep",
        normalized_input_sha256="a" * 64,
        tool_output_sha256="sha256:" + "b" * 64,
        determinism_class="deterministic_repo_state",
        mutation_class="read_only",
        latency_ms=100.0,
    )
    dump = trace.model_dump()
    assert dump["determinism_class"] == "deterministic_repo_state"
    assert dump["mutation_class"] == "read_only"
    assert dump["latency_ms"] == 100.0

    # Should be serializable to JSON
    import json
    json_str = trace.model_dump_json()
    parsed = json.loads(json_str)
    assert parsed["tool_name"] == "grep"
    assert parsed["normalized_input_sha256"] == "a" * 64
