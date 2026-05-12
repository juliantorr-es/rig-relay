from __future__ import annotations

from pathlib import Path
import pytest

from vibe.core.tools.base import ToolError
from vibe.core.tools.determinism import (
    normalize_tool_path,
    require_path_within_workdir,
    truncate_text,
    parse_shell_commands,
)


def test_normalize_rejects_empty_path():
    with pytest.raises(ToolError, match="Path cannot be empty"):
        normalize_tool_path("")
    with pytest.raises(ToolError, match="Path cannot be empty"):
        normalize_tool_path("   ")


def test_normalize_resolves_relative_path_under_cwd(tmp_path):
    cwd = tmp_path / "workdir"
    cwd.mkdir()
    
    path = normalize_tool_path("file.txt", cwd=cwd)
    assert path == (cwd / "file.txt").resolve()
    
    path = normalize_tool_path("./subdir/../file.txt", cwd=cwd)
    assert path == (cwd / "file.txt").resolve()


def test_normalize_expands_user():
    # expanduser() behavior depends on the environment, but we can verify it doesn't crash
    path = normalize_tool_path("~/file.txt")
    assert path.is_absolute()


def test_require_path_within_workdir_allows_inside_path(tmp_path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    inside = workdir / "file.txt"
    
    assert require_path_within_workdir(inside, workdir=workdir) == inside


def test_require_path_within_workdir_rejects_outside_path(tmp_path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    outside = tmp_path / "outside.txt"
    
    with pytest.raises(ToolError, match="Security error: Path .* is outside the project directory"):
        require_path_within_workdir(outside, workdir=workdir)


def test_require_path_within_workdir_allows_scratchpad(monkeypatch):
    import vibe.core.scratchpad as scratchpad
    
    scratch_path = Path("/tmp/vibe/scratch/temp.txt")
    # Mock _active_scratchpads
    monkeypatch.setattr(scratchpad, "_active_scratchpads", {"test": Path("/tmp/vibe/scratch")})
    
    assert require_path_within_workdir(scratch_path, workdir=Path("/home/user/project")) == scratch_path


def test_truncate_text_respects_max_bytes_and_utf8():
    text = "Hello World"
    truncated, was_truncated = truncate_text(text, 5)
    assert truncated == "Hello"
    assert was_truncated is True
    
    text = "Hello World"
    truncated, was_truncated = truncate_text(text, 20)
    assert truncated == "Hello World"
    assert was_truncated is False
    
    # UTF-8 multi-byte character: 🌟 (4 bytes)
    text = "🌟🌟"
    truncated, was_truncated = truncate_text(text, 6)
    assert truncated == "🌟" # 4 bytes
    assert was_truncated is True


def test_parse_shell_commands():
    command = "ls -la && echo 'hello world' | grep hello ; rm -rf /tmp"
    commands = parse_shell_commands(command)
    
    assert "ls -la" in commands
    assert "echo 'hello world'" in commands
    assert "grep hello" in commands
    assert "rm -rf /tmp" in commands
