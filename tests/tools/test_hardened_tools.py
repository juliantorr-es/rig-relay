from __future__ import annotations

import pytest
from pathlib import Path

from tests.mock.utils import collect_result
from vibe.core.tools.base import BaseToolState, ToolError, ToolPermission
from vibe.core.tools.builtins.bash import Bash, BashArgs, BashToolConfig
from vibe.core.tools.builtins.write_file import WriteFile, WriteFileArgs, WriteFileConfig
from vibe.core.tools.builtins.search_replace import SearchReplace, SearchReplaceArgs, SearchReplaceConfig
from vibe.core.tools.permissions import PermissionContext


@pytest.fixture
def bash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = BashToolConfig()
    return Bash(config_getter=lambda: config, state=BaseToolState())


def test_bash_allowlist_no_longer_silently_allows_git_status_diff_log(bash):
    # git status used to be in _get_default_allowlist()
    # Now it should require ASK permission (resolve_permission returns None)
    
    status_perm = bash.resolve_permission(BashArgs(command="git status"))
    # None means fall through to config.permission (ASK)
    assert status_perm is None or status_perm.permission == ToolPermission.ASK

    diff_perm = bash.resolve_permission(BashArgs(command="git diff"))
    assert diff_perm is None or diff_perm.permission == ToolPermission.ASK

    log_perm = bash.resolve_permission(BashArgs(command="git log"))
    assert log_perm is None or log_perm.permission == ToolPermission.ASK


def test_bash_blocks_dangerous_commands(bash):
    dangerous = [
        "git reset",
        "git reset --hard HEAD",
        "git clean",
        "git clean -fd",
        "git restore",
        "git checkout",
        "git checkout main",
        "git stash",
        "git rebase",
        "git merge",
        "git push --force",
        "git push --force-with-lease",
        "rm -rf /",
        "rm -fr .",
        "rm -rf subdir",
    ]
    for cmd in dangerous:
        perm = bash.resolve_permission(BashArgs(command=cmd))
        assert isinstance(perm, PermissionContext)
        assert perm.permission == ToolPermission.NEVER, f"Failed to block {cmd}"


def test_bash_malformed_command_does_not_crash(bash):
    # Test with characters that might confuse parsers
    malformed = [
        "git status; ) ( ; rm -rf",
        "echo \"unclosed quote",
        "$(cat /etc/passwd)",
        "`rm -rf /`",
        "| | |",
    ]
    for cmd in malformed:
        # Should not raise exception
        bash.resolve_permission(BashArgs(command=cmd))


@pytest.mark.asyncio
async def test_write_file_rejects_outside_workdir_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())
    
    outside_path = str(tmp_path.parent / "escape.txt")
    with pytest.raises(ToolError, match="outside the project directory"):
        await collect_result(tool.run(WriteFileArgs(path=outside_path, content="test")))


@pytest.mark.asyncio
async def test_write_file_rejects_directory_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())
    
    dir_path = tmp_path / "subdir"
    dir_path.mkdir()
    
    with pytest.raises(ToolError, match="Path is a directory"):
        await collect_result(tool.run(WriteFileArgs(path="subdir", content="test")))


@pytest.mark.asyncio
async def test_search_replace_rejects_outside_workdir_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())
    
    outside_path = str(tmp_path.parent / "escape.txt")
    with pytest.raises(ToolError, match="outside the project directory"):
        await collect_result(tool.run(SearchReplaceArgs(file_path=outside_path, content="test")))


@pytest.mark.asyncio
async def test_search_replace_does_not_write_when_block_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "file.txt"
    target.write_text("Hello World", encoding="utf-8")
    
    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())
    
    content = "<<<<<<< SEARCH\nNon-existent\n=======\nNew\n>>>>>>> REPLACE"
    
    with pytest.raises(ToolError, match="SEARCH/REPLACE blocks failed"):
        await collect_result(tool.run(SearchReplaceArgs(file_path="file.txt", content=content)))
    
    # Verify file content is unchanged
    assert target.read_text(encoding="utf-8") == "Hello World"
