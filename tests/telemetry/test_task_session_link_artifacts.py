from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate

from vibe.core.telemetry.artifacts import (
    TaskSessionLinkArtifact,
    ToolOutputArtifactWriter,
)


def test_write_task_session_link_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    writer = ToolOutputArtifactWriter("parent-session")
    artifact = TaskSessionLinkArtifact(
        parent_session_id="parent-session",
        parent_turn_id="turn-1",
        parent_tool_call_id="call-1",
        task_id="task-1",
        child_session_id="child-session",
        provider="deepseek",
        model="deepseek-v4-pro",
        thinking_requested=True,
        thinking_enabled=True,
        thinking_type="enabled",
        reasoning_effort="high",
        tool_access_policy="reasoning_only",
        result_compression_policy="final_only",
        timeout_seconds=12.5,
        input_prompt_sha256="sha256:" + "a" * 64,
        output_result_sha256="sha256:" + "b" * 64,
        child_artifact_manifest_sha256="sha256:" + "c" * 64,
        linkage_sha256="sha256:" + "d" * 64,
        status="completed",
        started_at="2024-01-01T00:00:00Z",
        completed_at="2024-01-01T00:00:01Z",
        warnings=[],
    )

    result = writer.write_task_session_link_artifact(
        artifact=artifact, tool_call_id="call-1"
    )

    assert result.tool_name == "task"
    assert Path(result.path).exists()
    content = json.loads(Path(result.path).read_text(encoding="utf-8"))
    schema_path = (
        Path(__file__).parent.parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.artifact.envelope.v1.schema.json"
    )
    validate(instance=content, schema=json.loads(schema_path.read_text()))
    assert content["artifact_kind"] == "task_session_link"
    assert content["payload"]["status"] == "completed"
    assert content["payload"]["linkage_sha256"] == artifact.linkage_sha256
