from __future__ import annotations

import json
from pathlib import Path
import pytest
from vibe.core.telemetry.artifacts import (
    ToolOutputArtifactWriter,
    should_artifact_tool_result,
    make_prompt_excerpt,
)

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
    
    # Verify file content
    content = json.loads(Path(artifact.path).read_text())
    assert content["tool_name"] == tool_name
    assert content["raw_output"] == raw_output
    assert content["raw_payload_kind"] == "text"

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
