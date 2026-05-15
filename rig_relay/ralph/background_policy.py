"""Ralph background policy — governs whether and how Ralph may create lanes.

Lane-start approval and adoption approval are separate.
Toggle ON authorizes only lane proposal/isolated work under policy.
Toggle ON does not authorize merge, push, or live workspace mutation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

POLICY_VERSION = "rig.ralph_background_policy.v1"

ALLOWED_CAPABILITIES = frozenset({
    "read_all_lane_projections",
    "read_report_projections",
    "read_bash_analytics_projections",
    "read_desktop_event_projections",
    "read_findings_projections",
    "create_isolated_worktree",
    "edit_inside_ralph_worktree",
    "run_allowed_validators",
    "commit_to_ralph_branch",
    "write_lane_report",
    "seal_review_bundle",
    "propose_adoption",
})

FORBIDDEN_CAPABILITIES = frozenset({
    "merge",
    "push_remote",
    "mutate_live_workspace",
    "mutate_orchestrator_lane_without_adoption",
    "promote_canonical_findings",
    "delete_canonical_findings",
    "access_credentials",
    "external_network_call",
    "destructive_git",
    "delete_untracked_files",
    "scheduler_launch_without_policy",
    "daemon_launch_without_policy",
    "recursive_background_agent",
})


class RalphBackgroundPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = POLICY_VERSION
    enabled: bool = False
    max_active_lanes: int = 2
    max_pending_review_lanes: int = 10
    allowed_projection_sources: list[str] = Field(default_factory=list)
    allowed_capabilities: list[str] = Field(default_factory=list)
    forbidden_capabilities: list[str] = Field(
        default_factory=lambda: sorted(FORBIDDEN_CAPABILITIES)
    )
    lane_root: str = ".rig/worktrees/ralph"
    branch_prefix: str = "ralph"
    require_lane_start_approval: bool = True
    require_adoption_approval: bool = True
    execution_enabled: bool = False
    merge_enabled: bool = False
    push_enabled: bool = False

    def validate_capabilities(self) -> list[str]:
        violations: list[str] = []
        for cap in self.allowed_capabilities:
            if cap in FORBIDDEN_CAPABILITIES:
                violations.append(cap)
            elif cap not in ALLOWED_CAPABILITIES:
                violations.append(f"unknown:{cap}")
        return violations

    def active_lanes_allowed(self, current_count: int) -> bool:
        if not self.enabled:
            return False
        return current_count < self.max_active_lanes

    def pending_review_allowed(self, current_count: int) -> bool:
        if not self.enabled:
            return False
        return current_count < self.max_pending_review_lanes


def default_policy() -> RalphBackgroundPolicy:
    return RalphBackgroundPolicy()


__all__ = [
    "ALLOWED_CAPABILITIES",
    "FORBIDDEN_CAPABILITIES",
    "POLICY_VERSION",
    "RalphBackgroundPolicy",
    "default_policy",
]
