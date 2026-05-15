"""Work map builder — reads active worktrees, agent lanes, and collision state.

Designed for the rig.get_context tool. Scans `.rig/relay/worktrees/`,
`.rig/work/`, and `.rig/relay/sessions/` to discover active agent work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rig_relay.context.models import ActiveLane, CollisionWarning


def scan_worktrees(workspace_root: Path | None = None) -> list[ActiveLane]:
    """Scan .rig/relay/worktrees/ for active agent work."""
    root = (workspace_root or Path.cwd()).resolve()
    worktrees_dir = root / ".rig" / "relay" / "worktrees"

    if not worktrees_dir.is_dir():
        return []

    lanes: list[ActiveLane] = []
    for entry in sorted(worktrees_dir.iterdir()):
        if not entry.is_dir():
            continue
        # Read worktree metadata if available
        meta = entry / "worktree.json"
        lane = ActiveLane(worktree_path=str(entry))

        if meta.is_file():
            try:
                import json

                data = json.loads(meta.read_text(encoding="utf-8"))
                lane.agent_id = data.get("agent_id", "")
                lane.mission_id = data.get("mission_id", "")
                lane.claimed_paths = data.get("claimed_paths", [])
                lane.status = data.get("status", "active")
            except Exception:
                pass

        # Check for dirty files in the worktree
        dirty_paths = list(entry.rglob("*"))
        lane.dirty_paths = [str(p.relative_to(root)) for p in dirty_paths if p.is_file()][:20]

        lanes.append(lane)

    return lanes


def scan_work_ledger(workspace_root: Path | None = None) -> list[ActiveLane]:
    """Scan .rig/work/ for active lane data."""
    root = (workspace_root or Path.cwd()).resolve()
    work_dir = root / ".rig" / "work"

    if not work_dir.is_dir():
        return []

    lanes: list[ActiveLane] = []
    for entry in sorted(work_dir.iterdir()):
        if not entry.is_dir():
            continue
        meta = entry / "lane.json"
        lane = ActiveLane(worktree_path=str(entry))

        if meta.is_file():
            try:
                import json

                data = json.loads(meta.read_text(encoding="utf-8"))
                lane.agent_id = data.get("agent_id", "")
                lane.mission_id = data.get("mission_id", "")
                lane.claimed_paths = data.get("claimed_paths", [])
                lane.status = data.get("status", "active")
            except Exception:
                pass

        lanes.append(lane)

    return lanes


def compute_collision_warnings(
    requested_paths: list[str],
    active_lanes: list[ActiveLane],
) -> list[CollisionWarning]:
    """Check if any requested paths overlap with active lanes' claimed paths.

    Returns a collision warning for each overlapping path.
    """
    if not requested_paths or not active_lanes:
        return []

    warnings: list[CollisionWarning] = []
    for rp in requested_paths:
        for lane in active_lanes:
            for cp in lane.claimed_paths:
                if cp in rp or rp in cp:
                    warnings.append(CollisionWarning(
                        path=rp,
                        claimed_by=lane.agent_id or lane.mission_id or "unknown",
                        reason=f"Path '{rp}' overlaps with claimed path '{cp}' "
                        f"in {lane.status} lane. Read-only inspection recommended.",
                    ))
                    break

    return warnings


def build_active_work(
    workspace_root: Path | None = None,
    requested_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Build the active work section of a context packet.

    Combines worktree scans, work ledger scans, and collision detection.
    """
    worktrees = scan_worktrees(workspace_root)
    ledger = scan_work_ledger(workspace_root)

    # Deduplicate: worktrees take priority
    seen_worktree = {l.worktree_path for l in worktrees}
    for lane in ledger:
        if lane.worktree_path not in seen_worktree:
            worktrees.append(lane)

    collisions = compute_collision_warnings(requested_paths or [], worktrees)

    return {
        "lanes": [l.model_dump(mode="json") for l in worktrees],
        "collision_warnings": [c.model_dump(mode="json") for c in collisions],
    }
