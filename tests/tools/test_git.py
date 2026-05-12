from __future__ import annotations

import pytest

from tests.mock.utils import collect_result
from vibe.core.tools.base import BaseToolState, ToolError, ToolPermission
from vibe.core.tools.builtins.git import (
    GitBranch,
    GitDiff,
    GitDiffArgs,
    GitLog,
    GitLogArgs,
    GitLsFiles,
    GitLsFilesArgs,
    GitResult,
    GitShow,
    GitShowArgs,
    GitStatus,
    GitStatusArgs,
)


@pytest.fixture
def status_tool():
    return GitStatus(
        config_getter=lambda: GitStatus.create_config_with_permission(
            ToolPermission.ALWAYS
        ),
        state=BaseToolState(),
    )


@pytest.fixture
def diff_tool():
    return GitDiff(
        config_getter=lambda: GitDiff.create_config_with_permission(
            ToolPermission.ALWAYS
        ),
        state=BaseToolState(),
    )


@pytest.fixture
def log_tool():
    return GitLog(
        config_getter=lambda: GitLog.create_config_with_permission(
            ToolPermission.ALWAYS
        ),
        state=BaseToolState(),
    )


@pytest.fixture
def branch_tool():
    return GitBranch(
        config_getter=lambda: GitBranch.create_config_with_permission(
            ToolPermission.ALWAYS
        ),
        state=BaseToolState(),
    )


@pytest.fixture
def show_tool():
    return GitShow(
        config_getter=lambda: GitShow.create_config_with_permission(
            ToolPermission.ALWAYS
        ),
        state=BaseToolState(),
    )


@pytest.fixture
def ls_files_tool():
    return GitLsFiles(
        config_getter=lambda: GitLsFiles.create_config_with_permission(
            ToolPermission.ALWAYS
        ),
        state=BaseToolState(),
    )


@pytest.mark.asyncio
async def test_git_status_argv(status_tool, monkeypatch):
    recorded_argv = []

    async def mock_run_git(operation, args):
        recorded_argv.append(["git", operation] + args)
        return GitResult(
            operation=operation,
            argv=recorded_argv[-1],
            stdout="",
            stderr="",
            returncode=0,
            truncated_stdout=False,
            truncated_stderr=False,
        )

    monkeypatch.setattr(status_tool, "_run_git", mock_run_git)

    await collect_result(status_tool.run(GitStatusArgs(short=True, branch=True)))
    assert recorded_argv[0] == ["git", "status", "--short", "--branch"]

    recorded_argv.clear()
    await collect_result(status_tool.run(GitStatusArgs(porcelain=True, branch=True)))
    assert recorded_argv[0] == ["git", "status", "--porcelain=v1", "--branch"]


@pytest.mark.asyncio
async def test_git_diff_argv(diff_tool, monkeypatch):
    recorded_argv = []

    async def mock_run_git(operation, args):
        recorded_argv.append(["git", operation] + args)
        return GitResult(
            operation=operation,
            argv=recorded_argv[-1],
            stdout="",
            stderr="",
            returncode=0,
            truncated_stdout=False,
            truncated_stderr=False,
        )

    monkeypatch.setattr(diff_tool, "_run_git", mock_run_git)

    await collect_result(
        diff_tool.run(GitDiffArgs(paths=["file.txt"], cached=True, stat=True))
    )
    assert recorded_argv[0] == ["git", "diff", "--cached", "--stat", "--", "file.txt"]


@pytest.mark.asyncio
async def test_git_log_argv(log_tool, monkeypatch):
    recorded_argv = []

    async def mock_run_git(operation, args):
        recorded_argv.append(["git", operation] + args)
        return GitResult(
            operation=operation,
            argv=recorded_argv[-1],
            stdout="",
            stderr="",
            returncode=0,
            truncated_stdout=False,
            truncated_stderr=False,
        )

    monkeypatch.setattr(log_tool, "_run_git", mock_run_git)

    await collect_result(
        log_tool.run(GitLogArgs(max_count=50, oneline=True, paths=["dir"]))
    )
    assert recorded_argv[0] == ["git", "log", "-n50", "--oneline", "--", "dir"]

    # Test capping
    recorded_argv.clear()
    await collect_result(log_tool.run(GitLogArgs(max_count=200)))
    assert recorded_argv[0] == ["git", "log", "-n100", "--oneline"]


@pytest.mark.asyncio
async def test_git_show_argv(show_tool, monkeypatch):
    recorded_argv = []

    async def mock_run_git(operation, args):
        recorded_argv.append(["git", operation] + args)
        return GitResult(
            operation=operation,
            argv=recorded_argv[-1],
            stdout="",
            stderr="",
            returncode=0,
            truncated_stdout=False,
            truncated_stderr=False,
        )

    monkeypatch.setattr(show_tool, "_run_git", mock_run_git)

    await collect_result(show_tool.run(GitShowArgs(ref="HEAD", paths=["file.py"])))
    assert recorded_argv[0] == ["git", "show", "HEAD", "--", "file.py"]


@pytest.mark.asyncio
async def test_git_show_rejects_ref_with_dash(show_tool):
    with pytest.raises(ToolError, match="Ref cannot start with '-'"):
        await collect_result(show_tool.run(GitShowArgs(ref="-n")))


@pytest.mark.asyncio
async def test_git_rejects_paths_with_dash(diff_tool):
    with pytest.raises(ToolError, match="Path spec cannot start with '-'"):
        await collect_result(diff_tool.run(GitDiffArgs(paths=["-o"])))


@pytest.mark.asyncio
async def test_git_rejects_absolute_paths_outside_workdir(
    diff_tool, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    outside = str(tmp_path.parent / "escape.txt")
    with pytest.raises(ToolError, match="Path is outside the project directory"):
        await collect_result(diff_tool.run(GitDiffArgs(paths=[outside])))


@pytest.mark.asyncio
async def test_git_ls_files_argv(ls_files_tool, monkeypatch):
    recorded_argv = []

    async def mock_run_git(operation, args):
        recorded_argv.append(["git", operation] + args)
        return GitResult(
            operation=operation,
            argv=recorded_argv[-1],
            stdout="",
            stderr="",
            returncode=0,
            truncated_stdout=False,
            truncated_stderr=False,
        )

    monkeypatch.setattr(ls_files_tool, "_run_git", mock_run_git)

    await collect_result(
        ls_files_tool.run(
            GitLsFilesArgs(others=True, modified=True, deleted=True, paths=["src"])
        )
    )
    assert recorded_argv[0] == [
        "git",
        "ls-files",
        "--others",
        "--modified",
        "--deleted",
        "--",
        "src",
    ]
