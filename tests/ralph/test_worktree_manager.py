from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from rig_relay.ralph.background_policy import default_policy, demo_policy
from rig_relay.ralph.lane_contracts import RalphLane
from rig_relay.ralph.worktree_manager import (
    build_safe_branch_name,
    build_safe_worktree_path,
    create_lane_worktree,
)


def test_build_safe_branch_name():
    name = build_safe_branch_name("Fix DirtyFileGuard singleton!!!", "abc12345")
    assert name.startswith("ralph/")
    assert "!!!" not in name
    assert "abc12345" in name
    assert len(name) < 80


def test_build_safe_worktree_path():
    path = build_safe_worktree_path(".rig/worktrees/ralph", "lane-123")
    assert path.startswith(str(Path(".rig/worktrees/ralph").resolve()))


def test_path_escape_detected():
    path = build_safe_worktree_path(".rig/worktrees/ralph", "../../etc")
    assert path == ""


def test_default_policy_refuses_worktree_creation():
    lane = RalphLane(lane_id="lane-1")
    result = create_lane_worktree(lane, default_policy())
    assert result.status == "refused"
    assert "disabled" in result.error


@pytest.mark.slow
@pytest.mark.integration
def test_demo_policy_creates_worktree_in_temp_repo():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        import subprocess

        subprocess.run(["git", "-C", str(root), "init"], capture_output=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "test@test"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Test"], capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "--allow-empty", "-m", "init"],
            capture_output=True,
        )

        policy = demo_policy()
        policy.lane_root = str(root / ".rig" / "worktrees" / "ralph")
        lane = RalphLane(lane_id="lane-test-1")

        result = create_lane_worktree(lane, policy, repo_root=root)

        assert result.status == "created"
        assert result.branch_name.startswith("ralph/")
        assert result.worktree_path != ""
        assert result.base_head != ""


def test_max_active_lanes_refused():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        import subprocess

        subprocess.run(["git", "-C", str(root), "init"], capture_output=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "test@test"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Test"], capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "--allow-empty", "-m", "init"],
            capture_output=True,
        )

        policy = demo_policy()
        policy.max_active_lanes = 1
        policy.lane_root = str(root / ".rig" / "worktrees" / "ralph")
        lane = RalphLane(lane_id="lane-max-1")

        result = create_lane_worktree(
            lane, policy, repo_root=root, existing_lane_count=1
        )
        assert result.status == "refused"
        assert "max active" in result.error.lower()
