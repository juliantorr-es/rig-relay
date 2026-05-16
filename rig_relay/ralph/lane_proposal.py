"""Ralph lane proposal — builds lane from mission candidate under policy.

Pure function: no git commands, no worktree creation, no merge.
Derives lane_id, branch_name, worktree_path from candidate + policy.
"""

from __future__ import annotations

import hashlib
from typing import Any

from rig_relay.ralph.background_policy import RalphBackgroundPolicy
from rig_relay.ralph.lane_contracts import RalphLane


def build_lane_proposal(
    candidate: dict[str, Any] | None = None,
    run_state: dict[str, Any] | None = None,
    background_policy: RalphBackgroundPolicy | None = None,
    *,
    source_orchestrator_lane_ids: list[str] | None = None,
    source_report_ids: list[str] | None = None,
    source_finding_ids: list[str] | None = None,
) -> tuple[RalphLane | None, list[str]]:
    """Build a Ralph lane proposal from a mission candidate.

    Returns (lane, violations). If lane is None, violations explain why.

    No git commands, no worktree creation, no merge.
    """
    violations: list[str] = []
    policy = background_policy or RalphBackgroundPolicy()

    if not policy.enabled:
        return None, ["background policy is disabled"]

    if candidate is None:
        return None, ["candidate is required"]

    candidate_id = candidate.get("candidate_id", "")
    title = candidate.get("title", "unnamed")
    source_kind = candidate.get("source_kind", "unknown")

    if not candidate_id:
        return None, ["candidate_id is required"]

    slug = title.lower().replace(" ", "-")[:40]
    short_id = hashlib.sha256(candidate_id.encode()).hexdigest()[:8]
    lane_id = f"ralph_lane_{short_id}"
    branch_name = f"ralph/{slug[:30]}-{short_id}"

    run_id = run_state.get("run_id", "") if run_state else ""
    scan_id = run_state.get("scan_id", "") if run_state else ""

    lane = RalphLane(
        lane_id=lane_id,
        mission_id=f"ralph_mission_{short_id}",
        source_run_id=run_id,
        source_scan_id=scan_id,
        source_candidate_id=candidate_id,
        source_orchestrator_lane_ids=source_orchestrator_lane_ids or [],
        source_report_ids=source_report_ids or [],
        source_finding_ids=source_finding_ids or [],
        branch_name=branch_name,
        worktree_path=f"{policy.lane_root}/{lane_id}",
        base_branch="main",
        base_head="",
        status="proposed",
        approval_state="not_requested",
        allowed_capabilities=list(policy.allowed_capabilities),
        forbidden_capabilities=list(policy.forbidden_capabilities),
        execution_enabled=False,
        merge_enabled=False,
        push_enabled=False,
    )

    return lane, violations


__all__ = ["build_lane_proposal"]
