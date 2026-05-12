from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tests.mock.utils import collect_result
from vibe.core.tools.base import BaseToolState, ToolError, ToolPermission
from vibe.core.tools.builtins.bash import Bash, BashArgs, BashToolConfig
from vibe.core.tools.builtins.git import (
    GitBranch,
    GitBranchArgs,
    GitDiff,
    GitDiffArgs,
    GitLog,
    GitLogArgs,
    GitLsFiles,
    GitLsFilesArgs,
    GitShow,
    GitShowArgs,
    GitStatus,
    GitStatusArgs,
    GitToolConfig,
)


@pytest.fixture
def git_config():
    return GitToolConfig()


@pytest.mark.asyncio
async def test_git_status_argv(git_config):
    tool = GitStatus(config_getter=lambda: git_config, state=BaseToolState())
    args = GitStatusArgs(short=True, branch=True)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_proc = mock_exec.return_value
        mock_proc.communicate.return_value = (b"mock status", b"")
        mock_proc.returncode = 0

        await collect_result(tool.run(args))

        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert call_args[0] == "git"
        assert "status" in call_args
        assert "--short" in call_args
        assert "--branch" in call_args


@pytest.mark.asyncio
async def test_git_diff_argv_with_paths(git_config):
    tool = GitDiff(config_getter=lambda: git_config, state=BaseToolState())
    args = GitDiffArgs(paths=["file1.py", "file2.py"], cached=True)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_proc = mock_exec.return_value
        mock_proc.communicate.return_value = (b"mock diff", b"")
        mock_proc.returncode = 0

        await collect_result(tool.run(args))

        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert "diff" in call_args
        assert "--cached" in call_args
        # Verify '--' is used before paths
        idx_sep = call_args.index("--")
        assert call_args[idx_sep + 1] == "file1.py"
        assert call_args[idx_sep + 2] == "file2.py"


@pytest.mark.asyncio
async def test_git_log_argv(git_config):
    tool = GitLog(config_getter=lambda: git_config, state=BaseToolState())
    args = GitLogArgs(max_count=10, oneline=True)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_proc = mock_exec.return_value
        mock_proc.communicate.return_value = (b"mock log", b"")
        mock_proc.returncode = 0

        await collect_result(tool.run(args))

        call_args = mock_exec.call_args[0]
        assert "log" in call_args
        assert "-n" in call_args
        assert "10" in call_args
        assert "--oneline" in call_args


@pytest.mark.asyncio
async def test_git_tool_raises_tool_error_on_nonzero_exit(git_config):
    tool = GitStatus(config_getter=lambda: git_config, state=BaseToolState())
    
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_proc = mock_exec.return_value
        mock_proc.communicate.return_value = (b"", b"fatal: not a git repository")
        mock_proc.returncode = 128

        with pytest.raises(ToolError) as excinfo:
            await collect_result(tool.run(GitStatusArgs()))
        
        assert "Git command failed with exit code 128" in str(excinfo.value)
        assert "fatal: not a git repository" in str(excinfo.value)


def test_bash_git_demotion():
    config = BashToolConfig()
    bash = Bash(config_getter=lambda: config, state=BaseToolState())

    # git status used to be allowlisted (ALWAYS), now it should be ASK (None or Context with ASK)
    status_perm = bash.resolve_permission(BashArgs(command="git status"))
    # resolve_permission returns None if it's not sensitive and not allowlisted and not denylisted
    # and not outside workdir. None means fall through to config.permission (which is ASK).
    assert status_perm is None or status_perm.permission == ToolPermission.ASK

    # destructive git should be NEVER
    reset_perm = bash.resolve_permission(BashArgs(command="git reset --hard HEAD"))
    assert reset_perm.permission == ToolPermission.NEVER
    
    clean_perm = bash.resolve_permission(BashArgs(command="git clean -fd"))
    assert clean_perm.permission == ToolPermission.NEVER


@pytest.mark.asyncio
async def test_git_ls_files_argv(git_config):
    tool = GitLsFiles(config_getter=lambda: git_config, state=BaseToolState())
    args = GitLsFilesArgs(others=True, modified=True)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_proc = mock_exec.return_value
        mock_proc.communicate.return_value = (b"file1\nfile2", b"")
        mock_proc.returncode = 0

        await collect_result(tool.run(args))

        call_args = mock_exec.call_args[0]
        assert "ls-files" in call_args
        assert "--others" in call_args
        assert "--exclude-standard" in call_args
        assert "--modified" in call_args
