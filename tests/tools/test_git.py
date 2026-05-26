from __future__ import annotations

import pytest

from rig_relay.core.tools.base import BaseToolState, ToolError
from rig_relay.core.tools.builtins.git import (
    GitBranch,
    GitBranchArgs,
    GitBranchResult,
    GitDiff,
    GitDiffArgs,
    GitDiffResult,
    GitLog,
    GitLogArgs,
    GitLogResult,
    GitLsFiles,
    GitLsFilesArgs,
    GitLsFilesResult,
    GitResult,
    GitShow,
    GitShowArgs,
    GitShowResult,
    GitStatus,
    GitStatusArgs,
    GitStatusResult,
    GitToolConfig,
)
from tests.mock.utils import collect_result


def _mock_head_branch(monkeypatch, tool, branch="main", head="abc1234"):
    async def mock_run_git(operation, args):
        if operation == "rev-parse" and "HEAD" in args:
            return GitResult(
                operation=operation,
                argv=["git", operation] + args,
                stdout=head,
                stderr="",
                returncode=0,
                truncated_stdout=False,
                truncated_stderr=False,
            )
        if operation == "branch" and "--show-current" in args:
            return GitResult(
                operation=operation,
                argv=["git", operation] + args,
                stdout=branch,
                stderr="",
                returncode=0,
                truncated_stdout=False,
                truncated_stderr=False,
            )
        raise RuntimeError(f"Unexpected git call: {operation} {args}")

    monkeypatch.setattr(tool, "_run_git", mock_run_git)


@pytest.fixture
def status_tool():
    return GitStatus(config_getter=GitToolConfig, state=BaseToolState())


@pytest.fixture
def diff_tool():
    return GitDiff(config_getter=GitToolConfig, state=BaseToolState())


@pytest.fixture
def log_tool():
    return GitLog(config_getter=GitToolConfig, state=BaseToolState())


@pytest.fixture
def branch_tool_():
    return GitBranch(config_getter=GitToolConfig, state=BaseToolState())


@pytest.fixture
def show_tool():
    return GitShow(config_getter=GitToolConfig, state=BaseToolState())


@pytest.fixture
def ls_files_tool():
    return GitLsFiles(config_getter=GitToolConfig, state=BaseToolState())


# ── Status ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_status_returns_typed_result(status_tool, monkeypatch, tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(repo)

    result = await collect_result(status_tool.run(GitStatusArgs()))
    assert isinstance(result, GitStatusResult)
    assert result.operation == "status"
    assert result.head_sha is not None and len(result.head_sha) == 40
    assert result.repository_state in ("clean", "unknown")


@pytest.mark.asyncio
async def test_git_status_branch_sha_populated(status_tool, monkeypatch, tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(repo)

    result = await collect_result(status_tool.run(GitStatusArgs()))
    assert isinstance(result, GitStatusResult)
    assert result.branch is not None
    assert result.head_sha is not None and len(result.head_sha) == 40


@pytest.mark.asyncio
async def test_git_status_detached_head(status_tool, monkeypatch, tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "--detach"], cwd=repo, check=True, capture_output=True
    )
    monkeypatch.chdir(repo)

    result = await collect_result(status_tool.run(GitStatusArgs()))
    assert result.is_detached is True
    assert result.branch is None


# ── Diff ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_diff_no_changes(diff_tool, monkeypatch, tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(repo)

    result = await collect_result(diff_tool.run(GitDiffArgs()))
    assert isinstance(result, GitDiffResult)
    assert result.files_changed_count == 0
    assert result.additions == 0
    assert result.deletions == 0


@pytest.mark.asyncio
async def test_git_diff_has_branch_sha(diff_tool, monkeypatch, tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(repo)

    result = await collect_result(diff_tool.run(GitDiffArgs()))
    assert result.head_sha is not None


# ── Log ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_log_returns_typed_result(log_tool, monkeypatch, tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(repo)

    result = await collect_result(log_tool.run(GitLogArgs(max_count=5)))
    assert isinstance(result, GitLogResult)
    assert result.commits_returned >= 1
    assert result.head_sha is not None


@pytest.mark.asyncio
async def test_git_log_caps_max_count(log_tool, monkeypatch, tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(repo)

    result = await collect_result(log_tool.run(GitLogArgs(max_count=200)))
    assert isinstance(result, GitLogResult)
    assert result.commits_returned == 0  # no commits in empty repo


# ── Branch ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_branch_returns_typed_result(branch_tool_, monkeypatch, tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(repo)

    result = await collect_result(branch_tool_.run(GitBranchArgs(show_current=True)))
    assert isinstance(result, GitBranchResult)
    assert result.current_branch is not None
    assert result.branch is not None


# ── Show ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_show_returns_typed_result(show_tool, monkeypatch, tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(repo)

    result = await collect_result(show_tool.run(GitShowArgs(ref="HEAD")))
    assert isinstance(result, GitShowResult)
    assert result.commit_sha is not None
    assert result.subject == "initial"


@pytest.mark.asyncio
async def test_git_show_rejects_dash_ref(show_tool):
    with pytest.raises(ToolError, match="Ref cannot start with '-'"):
        await collect_result(show_tool.run(GitShowArgs(ref="-n")))


# ── LsFiles ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_ls_files_returns_typed_result(ls_files_tool, monkeypatch, tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(repo)
    (repo / "new_file.py").write_text("content")

    result = await collect_result(ls_files_tool.run(GitLsFilesArgs(others=True)))
    assert isinstance(result, GitLsFilesResult)
    assert "new_file.py" in result.paths


# ── Path validation ───────────────────────────────────────────────────


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
