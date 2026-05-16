"""Ralph lane worktree manager — governed branch/worktree creation.

Uses existing WorktreeManager from coordination/ for actual git operations.
Never touches live runtime workspace. Adds Ralph-specific safety gates:
branch name sanitization, path escape detection, policy enforcement.
"""

from __future__ import annotations

from pathlib import Path
import re

from rig_relay.ralph.background_policy import RalphBackgroundPolicy
from rig_relay.ralph.lane_contracts import RalphLane

_UNSAFE_BRANCH_CHARS = re.compile(r"[ ~^:?*\[\\]")


def build_safe_branch_name(slug: str, short_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug.lower())[:40]
    return f"ralph/{safe}-{short_id[:8]}"


def build_safe_worktree_path(lane_root: str, lane_id: str) -> str:
    root = Path(lane_root).resolve()
    path = (root / lane_id).resolve()
    if str(path) != str((root / lane_id).resolve()):
        return ""
    if not str(path).startswith(str(root)):
        return ""
    return str(path)


class LaneWorktreeResult:
    def __init__(
        self,
        status: str,
        lane: RalphLane | None = None,
        branch_name: str = "",
        worktree_path: str = "",
        base_head: str = "",
        error: str = "",
    ) -> None:
        self.status = status
        self.lane = lane
        self.branch_name = branch_name
        self.worktree_path = worktree_path
        self.base_head = base_head
        self.error = error


def create_lane_worktree(
    lane: RalphLane,
    policy: RalphBackgroundPolicy,
    repo_root: Path | None = None,
    existing_lane_count: int = 0,
) -> LaneWorktreeResult:
    if not policy.can_create_worktree():
        return LaneWorktreeResult(
            "refused", error="worktree creation disabled by policy"
        )

    if not policy.active_lanes_allowed(existing_lane_count):
        return LaneWorktreeResult(
            "refused", error=f"max active lanes ({policy.max_active_lanes}) reached"
        )

    branch_name = build_safe_branch_name(
        "mission", lane.lane_id[-12:] if lane.lane_id else "unknown"
    )
    if _UNSAFE_BRANCH_CHARS.search(branch_name):
        return LaneWorktreeResult("refused", error=f"unsafe branch name: {branch_name}")

    worktree_path = build_safe_worktree_path(policy.lane_root, lane.lane_id)
    if not worktree_path:
        return LaneWorktreeResult(
            "refused",
            error=f"worktree path escape detected: {policy.lane_root}/{lane.lane_id}",
        )

    root = (repo_root or Path.cwd()).resolve()
    try:
        from rig_relay.coordination.worktree_manager import WorktreeManager

        mgr = WorktreeManager(repo_root=root, worktree_root=Path(worktree_path).parent)
        result = mgr.create(workspace_id=lane.lane_id, branch_name=branch_name)
        if result.status == "created" and result.record:
            lane.branch_name = branch_name
            lane.worktree_path = str(result.record.path)
            lane.base_head = result.record.head_sha or ""
            lane.base_branch = ""
            lane.status = "worktree_created"
            return LaneWorktreeResult(
                "created",
                lane=lane,
                branch_name=branch_name,
                worktree_path=str(result.record.path),
                base_head=lane.base_head,
            )
        return LaneWorktreeResult(
            "failed", error=f"worktree creation failed: {result.status}"
        )
    except ImportError:
        return LaneWorktreeResult("refused", error="WorktreeManager not available")
    except Exception as e:
        return LaneWorktreeResult("failed", error=str(e))


__all__ = [
    "LaneWorktreeResult",
    "build_safe_branch_name",
    "build_safe_worktree_path",
    "create_lane_worktree",
]
