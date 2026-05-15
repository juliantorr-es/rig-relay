import tempfile
import subprocess
from pathlib import Path

from rig_relay.ralph.background_policy import demo_policy, default_policy
from rig_relay.ralph.lane_contracts import RalphLane
from rig_relay.ralph.lane_executor import (
    LaneExecutionPlan,
    execute_in_lane,
    commit_in_lane,
)


def test_execute_refused_when_disabled():
    lane = RalphLane(lane_id="lane-1", status="active")
    plan = LaneExecutionPlan(lane_id="lane-1", execution_enabled=True)
    result = execute_in_lane(lane, plan, default_policy())
    assert result.status == "refused"
    assert "disabled" in result.error


def test_execute_refused_when_not_enabled():
    lane = RalphLane(lane_id="lane-1", status="active")
    plan = LaneExecutionPlan(lane_id="lane-1", execution_enabled=False)
    result = execute_in_lane(lane, plan, demo_policy())
    assert result.status == "refused"


def test_execute_refused_when_lane_not_ready():
    lane = RalphLane(lane_id="lane-1", status="proposed")
    plan = LaneExecutionPlan(lane_id="lane-1", execution_enabled=True)
    result = execute_in_lane(lane, plan, demo_policy())
    assert result.status == "refused"
    assert "not ready" in result.error


def test_execute_read_only_in_temp_worktree():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        subprocess.run(["git", "-C", str(root), "init"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@test"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "--allow-empty", "-m", "init"], capture_output=True)

        wt = root / "worktree"
        subprocess.run(["git", "-C", str(root), "worktree", "add", str(wt), "HEAD"], capture_output=True)

        lane = RalphLane(
            lane_id="lane-exec-1",
            status="active",
            worktree_path=str(wt),
            branch_name="ralph/test-abc12345",
        )
        plan = LaneExecutionPlan(
            lane_id="lane-exec-1",
            worktree_path=str(wt),
            branch_name="ralph/test-abc12345",
            objective="test execution",
            allowed_paths=["test_output.txt"],
            execution_mode="patch_in_lane",
            execution_enabled=True,
        )
        result = execute_in_lane(lane, plan, demo_policy())

        assert result.status in ("completed", "completed_no_changes")
        if result.changed_files:
            assert "test_output.txt" in result.changed_files


def test_commit_refused_when_disabled():
    lane = RalphLane(lane_id="lane-1", branch_name="ralph/test")
    result = commit_in_lane(lane, Path("/tmp"), ["test.txt"], default_policy())
    assert result.status == "refused"


def test_commit_refused_for_non_ralph_branch():
    lane = RalphLane(lane_id="lane-1", branch_name="feature/not-ralph")
    result = commit_in_lane(lane, Path("/tmp"), ["test.txt"], demo_policy())
    assert result.status == "refused"
    assert "not a Ralph branch" in result.error


def test_commit_refused_no_changes():
    lane = RalphLane(lane_id="lane-1", branch_name="ralph/test")
    result = commit_in_lane(lane, Path("/tmp"), [], demo_policy())
    assert result.status == "refused"
    assert "no changes" in result.error


def test_commit_in_temp_worktree():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        subprocess.run(["git", "-C", str(root), "init"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@test"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "--allow-empty", "-m", "init"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "checkout", "-b", "ralph/test-commit"], capture_output=True)

        (root / "test.txt").write_text("hello")
        lane = RalphLane(lane_id="lane-c1", branch_name="ralph/test-commit")
        result = commit_in_lane(lane, root, ["test.txt"], demo_policy())

        assert result.status == "committed"
        assert result.commit_sha != ""
        assert "test.txt" in result.changed_files
