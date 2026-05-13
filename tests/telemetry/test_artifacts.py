from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import validate

from vibe.core.telemetry.artifacts import (
    ToolOutputArtifactWriter,
    make_prompt_excerpt,
    should_artifact_tool_result,
)
from vibe.core.telemetry.local import dump_canonical_json


def test_should_artifact_tool_result():
    # Small output
    assert not should_artifact_tool_result("small", threshold_bytes=100)
    # Large output
    assert should_artifact_tool_result("a" * 101, threshold_bytes=100)


def test_make_prompt_excerpt():
    content = "0123456789"
    # No truncation
    assert make_prompt_excerpt(content, max_bytes=10) == content
    # Truncation
    excerpt = make_prompt_excerpt(content, max_bytes=4)
    assert "[TRUNCATED]" in excerpt
    # Verify it keeps prefix and suffix
    assert excerpt.startswith("01")
    assert excerpt.endswith("89")


def test_write_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session_id = "test-session"
    writer = ToolOutputArtifactWriter(session_id)

    tool_name = "test_tool"
    raw_output = "Hello, artifact!"

    artifact = writer.write_artifact(tool_name, raw_output, sequence=5)

    # Verify artifact object
    assert artifact.session_id == session_id
    assert artifact.tool_name == tool_name
    assert Path(artifact.path).exists()
    assert artifact.byte_size > 0
    assert artifact.sha256.startswith("sha256:")
    assert artifact.payload_sha256.startswith("sha256:")

    # Verify file content
    content = json.loads(Path(artifact.path).read_text())
    schema_path = (
        Path(__file__).parent.parent.parent
        / "docs"
        / "architecture"
        / "schemas"
        / "rig.relay.tool_output_artifact.v1.schema.json"
    )
    validate(instance=content, schema=json.loads(schema_path.read_text()))
    assert content["schema_version"] == "rig.relay.tool_output_artifact.v1"
    assert content["tool_name"] == tool_name
    assert content["payload"]["raw_output"] == raw_output
    assert content["payload"]["raw_payload_kind"] == "text"
    assert content["payload_sha256"] == artifact.payload_sha256
    assert content["artifact_record_sha256"] == artifact.artifact_record_sha256

    payload_bytes = json.dumps(
        content["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert (
        artifact.payload_sha256 == f"sha256:{hashlib.sha256(payload_bytes).hexdigest()}"
    )


def test_write_artifact_is_canonical_for_equivalent_inputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    writer = ToolOutputArtifactWriter("session-1")

    first = writer.write_artifact("read_file", "Hello, artifact!", sequence=1)
    second = writer.write_artifact("read_file", "Hello, artifact!", sequence=1)

    first_content = Path(first.path).read_text(encoding="utf-8")
    second_content = Path(second.path).read_text(encoding="utf-8")

    assert first_content == dump_canonical_json(json.loads(first_content))
    assert second_content == dump_canonical_json(json.loads(second_content))
    assert json.loads(first_content)["payload"] == json.loads(second_content)["payload"]
    assert (
        json.loads(first_content)["payload_sha256"]
        == json.loads(second_content)["payload_sha256"]
    )


def test_artifact_filename_determinism(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    writer = ToolOutputArtifactWriter("session-1")

    # Filename should contain sequence and tool name
    artifact = writer.write_artifact("ls", "output", sequence=42)
    path = Path(artifact.path)
    assert path.name.startswith("0042_ls_")


def test_unicode_truncation_safety():
    # Multi-byte character at the boundary
    content = "a" * 2047 + "🔥" + "b" * 2047
    excerpt = make_prompt_excerpt(content, max_bytes=4096)
    # Should not crash and should contain the character if it fits or be handled safely
    assert "[TRUNCATED]" in excerpt
    # The 'errors="ignore"' in decode handles the boundary safely
