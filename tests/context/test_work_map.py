"""Tests for work_map — verifies active work scanning and collision detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.context.models import ActiveLane
from rig_relay.context.work_map import (
    build_active_work,
    compute_collision_warnings,
    scan_work_ledger,
    scan_worktrees,
)

pytestmark = [pytest.mark.integration]

class TestScanWorktrees:
    def test_no_worktrees_returns_empty(self, tmp_path: Path) -> None:
        lanes = scan_worktrees(tmp_path)
        assert lanes == []

    def test_worktree_detected(self, tmp_path: Path) -> None:
        worktrees_dir = tmp_path / ".rig" / "relay" / "worktrees" / "wt-001"
        worktrees_dir.mkdir(parents=True)
        (worktrees_dir / "worktree.json").write_text(
            '{"agent_id": "agent-1", "mission_id": "M1", "claimed_paths": ["src/main.py"], "status": "active"}'
        )
        lanes = scan_worktrees(tmp_path)
        assert len(lanes) == 1
        assert lanes[0].agent_id == "agent-1"
        assert lanes[0].mission_id == "M1"

    def test_worktree_without_meta(self, tmp_path: Path) -> None:
        worktrees_dir = tmp_path / ".rig" / "relay" / "worktrees" / "wt-002"
        worktrees_dir.mkdir(parents=True)
        lanes = scan_worktrees(tmp_path)
        assert len(lanes) == 1
        assert lanes[0].agent_id == ""


class TestScanWorkLedger:
    def test_no_ledger_returns_empty(self, tmp_path: Path) -> None:
        lanes = scan_work_ledger(tmp_path)
        assert lanes == []

    def test_ledger_lane_detected(self, tmp_path: Path) -> None:
        lane_dir = tmp_path / ".rig" / "work" / "lane-001"
        lane_dir.mkdir(parents=True)
        (lane_dir / "lane.json").write_text(
            '{"agent_id": "agent-2", "mission_id": "M2", "claimed_paths": ["docs/"], "status": "active"}'
        )
        lanes = scan_work_ledger(tmp_path)
        assert len(lanes) == 1
        assert lanes[0].agent_id == "agent-2"


class TestComputeCollisionWarnings:
    def test_no_paths_no_warnings(self) -> None:
        warnings = compute_collision_warnings([], [])
        assert warnings == []

    def test_no_overlap_no_warnings(self) -> None:
        lanes = [ActiveLane(agent_id="a1", claimed_paths=["src/"])]
        warnings = compute_collision_warnings(["docs/"], lanes)
        assert warnings == []

    def test_overlap_detected(self) -> None:
        lanes = [ActiveLane(agent_id="a1", claimed_paths=["src/main.py"])]
        warnings = compute_collision_warnings(["src/main.py"], lanes)
        assert len(warnings) == 1
        assert warnings[0].claimed_by == "a1"

    def test_overlap_with_prefix(self) -> None:
        lanes = [ActiveLane(agent_id="a1", claimed_paths=["src/"])]
        warnings = compute_collision_warnings(["src/main.py"], lanes)
        assert len(warnings) == 1
        assert warnings[0].path == "src/main.py"

    def test_multiple_overlaps(self) -> None:
        lanes = [
            ActiveLane(agent_id="a1", claimed_paths=["src/file1.py"]),
            ActiveLane(agent_id="a2", claimed_paths=["src/file2.py"]),
        ]
        warnings = compute_collision_warnings(["src/file1.py", "src/file2.py"], lanes)
        assert len(warnings) == 2


class TestBuildActiveWork:
    def test_no_data_returns_empty(self, tmp_path: Path) -> None:
        result = build_active_work(tmp_path, [])
        assert result["lanes"] == []
        assert result["collision_warnings"] == []

    def test_worktree_with_collision(self, tmp_path: Path) -> None:
        worktrees_dir = tmp_path / ".rig" / "relay" / "worktrees" / "wt-001"
        worktrees_dir.mkdir(parents=True)
        (worktrees_dir / "worktree.json").write_text(
            '{"agent_id": "a1", "claimed_paths": ["src/main.py"], "status": "active"}'
        )
        result = build_active_work(tmp_path, ["src/main.py"])
        assert len(result["lanes"]) == 1
        assert len(result["collision_warnings"]) == 1
        assert result["collision_warnings"][0]["claimed_by"] == "a1"

    def test_does_not_write_files(self, tmp_path: Path) -> None:
        """Prove build_active_work is read-only."""
        before = sorted(p.name for p in tmp_path.rglob("*"))
        build_active_work(tmp_path, [])
        after = sorted(p.name for p in tmp_path.rglob("*"))
        assert before == after
