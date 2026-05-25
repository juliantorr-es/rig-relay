from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.git_workspace_state import (
    GitWorkspaceState,
    GitWorkspaceStateArgs,
    GitWorkspaceStateConfig,
    GitWorkspaceStateResult,
)


def _init_repo(base_path: Path, branch: str = "task/feature") -> Path:
    repo = base_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-b", branch], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)
    return repo


async def _run_state(cwd: Path) -> GitWorkspaceStateResult:
    tool = GitWorkspaceState(
        config_getter=lambda: GitWorkspaceStateConfig(), state=BaseToolState()
    )
    args = GitWorkspaceStateArgs()
    original = os.getcwd()
    os.chdir(cwd)
    try:
        results = [r async for r in tool.run(args, ctx=None)]
    finally:
        os.chdir(original)
    assert isinstance(results[0], GitWorkspaceStateResult)
    return results[0]


@pytest.mark.asyncio
@pytest.mark.real_artifact
@pytest.mark.substrate
async def test_clean_task_branch_no_checkpoint_needed(tmp_path):
    repo = _init_repo(tmp_path)
    r = await _run_state(repo)
    assert r.repository_state == "clean"
    assert r.local_git_checkpoint_precheck == "no_changes"
    assert r.branch == "task/feature"
    assert r.dirty_file_count == 0


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_dirty_task_branch_unstaged_file(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# new")
    r = await _run_state(repo)
    assert r.repository_state == "dirty"
    assert r.local_git_checkpoint_precheck == "preparation_required"
    assert r.preparation_required is True
    assert r.untracked_count >= 1
    assert "file.py" in r.untracked_paths
    assert "git add" not in (r.suggested_next_action or "")
    assert "prepare_checkpoint" in (r.suggested_next_action or "").lower()


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_staged_file_on_task_branch_ready_for_checkpoint(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# modified")
    subprocess.run(["git", "add", "file.py"], cwd=repo, check=True)
    r = await _run_state(repo)
    assert r.local_git_checkpoint_precheck == "git_preconditions_satisfied"
    assert r.staged_count >= 1
    assert "file.py" in r.checkpoint_candidate_paths
    assert "checkpoint" in (r.suggested_next_action or "").lower()


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_protected_main_branch_with_unstaged_blocks_checkpoint(tmp_path):
    repo = _init_repo(tmp_path, branch="main")
    (repo / "file.py").write_text("# modified")
    r = await _run_state(repo)
    assert r.local_git_checkpoint_precheck == "git_preconditions_blocked"
    assert r.primary_blocker is not None
    assert "protected branch" in r.primary_blocker.lower()
    assert (
        "branch" in (r.suggested_next_action or "").lower()
        or "worktree" in (r.suggested_next_action or "").lower()
    )
    assert "git add" not in (r.suggested_next_action or "")
    assert r.local_checkpoint_branch_policy_blocker is not None
    assert "main" in r.local_checkpoint_branch_policy_blocker
    assert r.unique_changed_paths >= 1


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_protected_main_branch_with_staged_reports_risk(tmp_path):
    repo = _init_repo(tmp_path, branch="main")
    (repo / "file.py").write_text("# staged on main")
    subprocess.run(["git", "add", "file.py"], cwd=repo, check=True)
    r = await _run_state(repo)
    assert r.local_git_checkpoint_precheck == "git_preconditions_blocked"
    assert r.primary_blocker is not None
    assert "protected branch" in r.primary_blocker.lower()
    assert r.staged_count >= 1
    assert "file.py" in r.staged_paths


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_detached_head_returns_full_state(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# change on detached HEAD")
    subprocess.run(["git", "add", "file.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "detach test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "checkout", "--detach"], cwd=repo, check=True, capture_output=True
    )
    (repo / "file.py").write_text("# modified after detach")
    subprocess.run(["git", "add", "file.py"], cwd=repo, check=True)
    r = await _run_state(repo)
    assert r.repository_state in ("detached_head", "dirty")
    assert r.local_git_checkpoint_precheck == "git_preconditions_blocked"
    assert r.primary_blocker is not None
    assert "detached" in r.primary_blocker.lower()
    assert r.staged_count >= 1
    assert r.dirty_file_count >= 1
    assert (
        "branch" in (r.suggested_next_action or "").lower()
        or "worktree" in (r.suggested_next_action or "").lower()
    )


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_conflicted_state_outranks_checkpoint(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# conflict")
    subprocess.run(["git", "add", "file.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(
        ["git", "checkout", "-b", "other"], cwd=repo, check=True, capture_output=True
    )
    (repo / "file.py").write_text("# other change")
    subprocess.run(["git", "add", "file.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "other"], cwd=repo, check=True)
    subprocess.run(
        ["git", "checkout", "task/feature"], cwd=repo, check=True, capture_output=True
    )
    (repo / "file.py").write_text("# our change")
    subprocess.run(["git", "add", "file.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "ours"], cwd=repo, check=True)
    proc = subprocess.run(
        ["git", "merge", "other"], cwd=repo, check=False, capture_output=True
    )
    r = await _run_state(repo)
    if proc.returncode != 0:
        assert r.local_git_checkpoint_precheck == "git_preconditions_blocked"
        assert r.primary_blocker is not None
        assert "conflict" in (r.suggested_next_action or "").lower()


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_category_accounting_reconciles(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "new.py").write_text("# untracked")
    (repo / "mod.py").write_text("# unstaged")
    subprocess.run(["git", "add", "mod.py"], cwd=repo, check=True)
    (repo / "mod.py").write_text("# modified again after staging")
    r = await _run_state(repo)
    assert r.untracked_count >= 1
    assert r.unique_changed_paths <= (
        r.staged_count
        + r.unstaged_count
        + r.untracked_count
        + r.deleted_count
        + r.conflicted_count
    )
    assert r.dirty_file_count == r.unique_changed_paths


@pytest.mark.asyncio
async def test_not_a_repository(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = await _run_state(empty)
    assert r.repository_state == "not_a_repository"
    assert r.local_git_checkpoint_precheck == "git_preconditions_blocked"
    assert r.primary_blocker == "not_a_repository"


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_no_git_add_in_suggested_actions(tmp_path):
    repo = _init_repo(tmp_path / "task")
    (repo / "file.py").write_text("# new")
    r = await _run_state(repo)
    assert "git add" not in (r.suggested_next_action or "")
    assert "git commit" not in (r.suggested_next_action or "")

    main_repo = _init_repo(tmp_path / "main", branch="main")
    (main_repo / "file.py").write_text("# change")
    r2 = await _run_state(main_repo)
    assert "git add" not in (r2.suggested_next_action or "")
    assert "git commit" not in (r2.suggested_next_action or "")
