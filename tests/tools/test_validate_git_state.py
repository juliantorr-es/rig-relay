"""Tests for validate tool — Stage 5: Worktree/Lane Awareness and Dirty-State Policy.

Tests cover:
- ValidateGitState model
- _parse_porcelain_line
- _parse_porcelain_branch
- _parse_git_status_porcelain
- _collect_git_state via temporary git repos
- _check_dirty_policy
- expected_dirty_policy enforcement in run()
- worktree-readiness profile
- before_git_state / after_git_state in ValidateResult
- content-light receipt with git summary
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.validate import (
    DIRTY_POLICY_ALLOW_DIRTY,
    DIRTY_POLICY_ALLOW_LISTED_DIRTY,
    DIRTY_POLICY_CLEAN,
    Validate,
    ValidateArgs,
    ValidateGitState,
    ValidateResult,
    ValidateToolConfig,
    _check_dirty_policy,
    _parse_git_status_porcelain,
    get_profile,
    list_profiles,
)

# ── ValidateGitState model ────────────────────────────────────────────


def test_git_state_extra_forbidden() -> None:
    """ValidateGitState rejects extra fields."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ValidateGitState.model_validate({"is_git_repo": True, "unknown_field": "bad"})


def test_git_state_defaults() -> None:
    """ValidateGitState has sensible defaults for non-git-repo."""
    state = ValidateGitState()
    assert state.is_git_repo is False
    assert state.branch is None
    assert state.head is None
    assert state.dirty_count == 0
    assert state.dirty_paths == []


def test_git_state_fields() -> None:
    """ValidateGitState accepts and returns all fields."""
    state = ValidateGitState(
        is_git_repo=True,
        branch="main",
        head="abc123",
        is_worktree=False,
        upstream="origin/main",
        ahead_count=1,
        behind_count=2,
        dirty_count=3,
        modified_count=1,
        deleted_count=1,
        untracked_count=1,
        staged_count=1,
        conflicted_count=1,
        dirty_paths=["a.py", "b.py"],
        untracked_paths=["c.py"],
        changed_paths=["a.py", "b.py", "c.py"],
        status_porcelain_sha256="dummyhash",
    )
    assert state.branch == "main"
    assert state.head == "abc123"
    assert state.is_git_repo is True
    assert state.dirty_paths == ["a.py", "b.py"]


# ── Porcelain parser tests ────────────────────────────────────────────


def test_parse_git_status_clean() -> None:
    """Clean workspace parses with zero counts."""
    output = "## main"
    result = _parse_git_status_porcelain(output, None)
    assert result.is_git_repo is True
    assert result.branch == "main"
    assert result.dirty_count == 0
    assert result.dirty_paths == []


def test_parse_git_status_mixed() -> None:
    """Mixed workspace parses counts and paths correctly."""
    output = "## main...origin/main [ahead 1]\n M mod.py\n D del.py\n?? untracked.py\nM  staged.py\nUU conflict.py"
    result = _parse_git_status_porcelain(output, None)
    assert result.branch == "main"
    assert result.upstream == "origin/main"
    assert result.ahead_count == 1
    assert result.dirty_count >= 1
    assert result.conflicted_count >= 1


def test_parse_git_status_paths_are_relative() -> None:
    """Parsed paths use workspace-relative POSIX form."""
    output = "## main\n M sub/file.py"
    result = _parse_git_status_porcelain(output, None)
    assert "sub/file.py" in result.dirty_paths
    assert not result.dirty_paths[0].startswith("/")


def test_parse_git_status_empty_output() -> None:
    """Empty output produces clean state."""
    result = _parse_git_status_porcelain("", None)
    assert result.dirty_count == 0


# ── Dirty policy tests ───────────────────────────────────────────────


def test_dirty_policy_none_passes() -> None:
    """None policy does not block."""
    state = ValidateGitState(is_git_repo=True, dirty_count=5)
    result = _check_dirty_policy(state, None, [])
    assert result is None


def test_dirty_policy_allow_dirty_passes() -> None:
    """allow_dirty policy does not block."""
    state = ValidateGitState(is_git_repo=True, dirty_count=5)
    result = _check_dirty_policy(state, DIRTY_POLICY_ALLOW_DIRTY, [])
    assert result is None


def test_dirty_policy_clean_fails_with_dirty() -> None:
    """clean policy blocks when workspace is dirty."""
    state = ValidateGitState(is_git_repo=True, dirty_count=3)
    result = _check_dirty_policy(state, DIRTY_POLICY_CLEAN, [])
    assert result is not None
    assert "dirty" in result.lower()


def test_dirty_policy_clean_passes_with_clean() -> None:
    """clean policy passes when workspace is clean."""
    state = ValidateGitState(is_git_repo=True, dirty_count=0)
    result = _check_dirty_policy(state, DIRTY_POLICY_CLEAN, [])
    assert result is None


def test_dirty_policy_clean_non_repo_passes() -> None:
    """clean policy does not block when not in a git repo."""
    state = ValidateGitState(is_git_repo=False, dirty_count=0)
    result = _check_dirty_policy(state, DIRTY_POLICY_CLEAN, [])
    assert result is None


def test_dirty_policy_allow_listed_dirty_passes_with_allowed() -> None:
    """allow_listed_dirty passes when all dirty paths are in allowed list."""
    state = ValidateGitState(
        is_git_repo=True, dirty_count=2, dirty_paths=["a.py", "b.py"]
    )
    result = _check_dirty_policy(
        state, DIRTY_POLICY_ALLOW_LISTED_DIRTY, ["a.py", "b.py"]
    )
    assert result is None


def test_dirty_policy_allow_listed_dirty_fails_with_unlisted() -> None:
    """allow_listed_dirty blocks when unlisted dirty paths exist."""
    state = ValidateGitState(
        is_git_repo=True, dirty_count=2, dirty_paths=["a.py", "c.py"]
    )
    result = _check_dirty_policy(state, DIRTY_POLICY_ALLOW_LISTED_DIRTY, ["a.py"])
    assert result is not None
    assert "c.py" in result


def test_dirty_policy_allow_listed_dirty_passes_with_clean() -> None:
    """allow_listed_dirty passes when workspace is clean."""
    state = ValidateGitState(is_git_repo=True, dirty_count=0)
    result = _check_dirty_policy(state, DIRTY_POLICY_ALLOW_LISTED_DIRTY, ["a.py"])
    assert result is None


# ── worktree-readiness profile tests ──────────────────────────────────


def test_worktree_readiness_profile_exists() -> None:
    """worktree-readiness profile is registered."""
    assert "worktree-readiness" in list_profiles()


def test_worktree_readiness_profile_has_no_checks() -> None:
    """worktree-readiness profile has no lint/test/schema checks."""
    profile = get_profile("worktree-readiness")
    assert profile is not None
    assert profile.checks == []
    assert profile.allow_mutation is False
    assert profile.allow_network is False


def test_worktree_readiness_profile_description() -> None:
    """worktree-readiness profile describes its purpose."""
    profile = get_profile("worktree-readiness")
    assert profile is not None
    assert "readiness" in profile.description.lower()


# ── ValidateGitState in ValidateResult ────────────────────────────────


def test_validate_result_accepts_git_state() -> None:
    """ValidateResult accepts ValidateGitState via before/after fields."""
    gs = ValidateGitState(is_git_repo=True, branch="main", head="abc123", dirty_count=0)
    result = ValidateResult(
        profile="worktree-readiness",
        status="passed",
        before_git_state=gs,
        after_git_state=gs,
    )
    assert result.before_git_state is not None
    assert result.before_git_state.branch == "main"
    assert result.after_git_state is not None


def test_validate_receipt_git_summary_content_light() -> None:
    """ValidateReceipt before_git_summary contains counts only."""
    from rig_relay.core.tools.builtins.validate import Validate

    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())

    gs = ValidateGitState(
        is_git_repo=True,
        dirty_count=3,
        modified_count=1,
        deleted_count=1,
        untracked_count=1,
        staged_count=0,
        conflicted_count=0,
        dirty_paths=["a.py", "b.py", "c.py"],
        untracked_paths=["c.py"],
        changed_paths=["a.py", "b.py", "c.py"],
        status_porcelain_sha256="abc",
    )
    result = ValidateResult(
        profile="worktree-readiness",
        status="passed",
        before_git_state=gs,
        after_git_state=gs,
    )
    receipt = tool.build_receipt(result)
    assert receipt.before_git_summary is not None
    assert receipt.before_git_summary.get("dirty_count") == 3
    assert receipt.before_git_summary.get("modified_count") == 1
    # Ensure no raw paths leak into receipt
    assert "dirty_paths" not in receipt.before_git_summary
    assert "status_porcelain_sha256" not in receipt.before_git_summary


def test_validate_receipt_git_summary_none_when_no_git() -> None:
    """ValidateReceipt git summary is None when no git state captured."""
    from rig_relay.core.tools.builtins.validate import Validate

    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())

    result = ValidateResult(
        profile="quick", status="passed", before_git_state=None, after_git_state=None
    )
    receipt = tool.build_receipt(result)
    assert receipt.before_git_summary is None
    assert receipt.after_git_summary is None


# ── Temporary git repo integration tests ─────────────────────────────


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo with one committed file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, capture_output=True
    )
    test_file = repo / "test.py"
    test_file.write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, capture_output=True)
    return repo


@pytest.mark.asyncio
async def test_collect_git_state_in_repo(temp_git_repo: Path) -> None:
    """_collect_git_state captures state in a real git repo."""
    from rig_relay.core.tools.builtins.validate import _collect_git_state

    state = await _collect_git_state(str(temp_git_repo))
    assert state.is_git_repo is True
    assert state.head is not None
    assert len(state.head) == 40
    assert state.dirty_count == 0


@pytest.mark.asyncio
async def test_collect_git_state_dirty_in_repo(temp_git_repo: Path) -> None:
    """_collect_git_state detects dirty files."""
    from rig_relay.core.tools.builtins.validate import _collect_git_state

    dirty_file = temp_git_repo / "dirty.py"
    dirty_file.write_text("x = 2\n")
    state = await _collect_git_state(str(temp_git_repo))
    assert state.is_git_repo is True
    assert state.dirty_count >= 1
    assert any("dirty.py" in p for p in state.dirty_paths)


@pytest.mark.asyncio
async def test_collect_git_state_non_repo(tmp_path: Path) -> None:
    """_collect_git_state returns non-repo state for non-git dir."""
    from rig_relay.core.tools.builtins.validate import _collect_git_state

    state = await _collect_git_state(str(tmp_path))
    assert state.is_git_repo is False


@pytest.mark.asyncio
async def test_collect_git_state_none_cwd() -> None:
    """_collect_git_state returns non-repo state when cwd is None."""
    from rig_relay.core.tools.builtins.validate import _collect_git_state

    state = await _collect_git_state(None)
    assert state.is_git_repo is False


@pytest.mark.asyncio
async def test_worktree_readiness_via_tool(temp_git_repo: Path) -> None:
    """worktree-readiness profile can be invoked in a git repo."""
    from rig_relay.core.tools.builtins.validate import Validate, ValidateArgs

    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    args = ValidateArgs(profile="worktree-readiness", workspace_root=str(temp_git_repo))
    results = []
    async for event in tool.run(args):
        if isinstance(event, ValidateResult):
            results.append(event)
    assert len(results) == 1
    r = results[0]
    assert r.profile == "worktree-readiness"
    # Should pass since repo is clean (no checks to fail)
    assert r.status in ("passed", "skipped")
    assert r.before_git_state is not None
    assert r.before_git_state.is_git_repo is True
    assert r.after_git_state is not None


@pytest.mark.asyncio
async def test_worktree_readiness_with_dirty_policy_clean(temp_git_repo: Path) -> None:
    """worktree-readiness with clean policy blocks dirty workspace."""
    from rig_relay.core.tools.builtins.validate import Validate, ValidateArgs

    dirty_file = temp_git_repo / "dirty.py"
    dirty_file.write_text("x = 2\n")

    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    args = ValidateArgs(
        profile="worktree-readiness",
        workspace_root=str(temp_git_repo),
        expected_dirty_policy=DIRTY_POLICY_CLEAN,
    )
    results = []
    async for event in tool.run(args):
        if isinstance(event, ValidateResult):
            results.append(event)
    assert len(results) == 1
    r = results[0]
    # Should fail due to dirty workspace
    assert r.status == "failed" or r.error_kind == "dirty_workspace"


@pytest.mark.asyncio
async def test_allow_listed_dirty_relative_path_passes(temp_git_repo):
    """allow_listed_dirty passes when dirty path is a workspace-relative path."""
    (temp_git_repo / "dirty.py").write_text("x=2\n")
    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    args = ValidateArgs(
        profile="worktree-readiness",
        workspace_root=str(temp_git_repo),
        expected_dirty_policy=DIRTY_POLICY_ALLOW_LISTED_DIRTY,
        paths=["dirty.py"],
    )
    results = [r async for r in tool.run(args) if isinstance(r, ValidateResult)]
    assert len(results) == 1
    assert results[0].status in ("passed", "skipped")


@pytest.mark.asyncio
async def test_allow_listed_dirty_absolute_path_passes(temp_git_repo):
    """allow_listed_dirty passes when dirty path is an absolute path inside workspace."""
    dirty_file = temp_git_repo / "dirty.py"
    dirty_file.write_text("x=2\n")
    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    args = ValidateArgs(
        profile="worktree-readiness",
        workspace_root=str(temp_git_repo),
        expected_dirty_policy=DIRTY_POLICY_ALLOW_LISTED_DIRTY,
        paths=[str(dirty_file.resolve())],
    )
    results = [r async for r in tool.run(args) if isinstance(r, ValidateResult)]
    assert len(results) == 1
    assert results[0].status in ("passed", "skipped")


@pytest.mark.asyncio
async def test_allow_listed_dirty_dot_slash_path_passes(temp_git_repo):
    """allow_listed_dirty passes when dirty path uses ./ prefix."""
    (temp_git_repo / "dirty.py").write_text("x=2\n")
    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    args = ValidateArgs(
        profile="worktree-readiness",
        workspace_root=str(temp_git_repo),
        expected_dirty_policy=DIRTY_POLICY_ALLOW_LISTED_DIRTY,
        paths=["./dirty.py"],
    )
    results = [r async for r in tool.run(args) if isinstance(r, ValidateResult)]
    assert len(results) == 1
    assert results[0].status in ("passed", "skipped")


@pytest.mark.asyncio
async def test_allow_listed_dirty_fails_with_unlisted_path(temp_git_repo):
    """allow_listed_dirty fails when a dirty path is not in the allowed list."""
    (temp_git_repo / "dirty.py").write_text("x=2\n")
    (temp_git_repo / "other.py").write_text("y=3\n")
    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    args = ValidateArgs(
        profile="worktree-readiness",
        workspace_root=str(temp_git_repo),
        expected_dirty_policy=DIRTY_POLICY_ALLOW_LISTED_DIRTY,
        paths=["dirty.py"],
    )
    results = [r async for r in tool.run(args) if isinstance(r, ValidateResult)]
    assert len(results) == 1
    r = results[0]
    assert r.status == "failed"
    assert r.error_kind == "dirty_workspace"
    assert r.before_git_state is not None
    assert r.blocker_summary == {"dirty_workspace": 1}


@pytest.mark.asyncio
async def test_allow_listed_dirty_empty_paths_fails_when_dirty(temp_git_repo):
    """allow_listed_dirty with empty paths fails when workspace is dirty."""
    (temp_git_repo / "dirty.py").write_text("x=2\n")
    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    args = ValidateArgs(
        profile="worktree-readiness",
        workspace_root=str(temp_git_repo),
        expected_dirty_policy=DIRTY_POLICY_ALLOW_LISTED_DIRTY,
        paths=[],
    )
    results = [r async for r in tool.run(args) if isinstance(r, ValidateResult)]
    assert len(results) == 1
    r = results[0]
    assert r.status == "failed"
    assert r.error_kind == "dirty_workspace"


@pytest.mark.asyncio
async def test_outside_workspace_path_refused_before_dirty_policy(
    temp_git_repo, tmp_path
):
    """Outside-workspace path is refused before dirty-policy comparison."""
    outside = tmp_path / "outside.py"
    outside.write_text("x=2\n")
    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    args = ValidateArgs(
        profile="worktree-readiness",
        workspace_root=str(temp_git_repo),
        expected_dirty_policy=DIRTY_POLICY_CLEAN,
        paths=[str(outside)],
    )
    results = [r async for r in tool.run(args) if isinstance(r, ValidateResult)]
    assert len(results) == 1
    r = results[0]
    assert r.status == "refused"
    assert r.error_kind == "unsafe_paths"
    # Dirty-policy failure would be "failed", not "refused"
    assert r.error_kind != "dirty_workspace"


@pytest.mark.asyncio
async def test_allow_listed_dirty_duplicate_paths_passes(temp_git_repo):
    """Duplicate listed paths still pass."""
    (temp_git_repo / "dirty.py").write_text("x=2\n")
    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    args = ValidateArgs(
        profile="worktree-readiness",
        workspace_root=str(temp_git_repo),
        expected_dirty_policy=DIRTY_POLICY_ALLOW_LISTED_DIRTY,
        paths=["dirty.py", "dirty.py"],
    )
    results = [r async for r in tool.run(args) if isinstance(r, ValidateResult)]
    assert len(results) == 1
    assert results[0].status in ("passed", "skipped")


@pytest.mark.asyncio
async def test_clean_policy_fails_on_any_dirty_file(temp_git_repo):
    """clean policy still fails on any dirty file."""
    (temp_git_repo / "dirty.py").write_text("x=2\n")
    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    args = ValidateArgs(
        profile="worktree-readiness",
        workspace_root=str(temp_git_repo),
        expected_dirty_policy=DIRTY_POLICY_CLEAN,
    )
    results = [r async for r in tool.run(args) if isinstance(r, ValidateResult)]
    assert len(results) == 1
    r = results[0]
    assert r.status == "failed"
    assert r.error_kind == "dirty_workspace"
    assert r.before_git_state is not None
    assert r.blocker_summary == {"dirty_workspace": 1}


@pytest.mark.asyncio
async def test_allow_dirty_passes_with_dirty_files(temp_git_repo):
    """allow_dirty still passes with dirty files."""
    (temp_git_repo / "dirty.py").write_text("x=2\n")
    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    args = ValidateArgs(
        profile="worktree-readiness",
        workspace_root=str(temp_git_repo),
        expected_dirty_policy=DIRTY_POLICY_ALLOW_DIRTY,
    )
    results = [r async for r in tool.run(args) if isinstance(r, ValidateResult)]
    assert len(results) == 1
    assert results[0].status in ("passed", "skipped")
