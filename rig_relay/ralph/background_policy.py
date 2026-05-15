"""Ralph background policy v2 — explicit gates for each lifecycle transition.

Every dangerous capability is independently gated.
Default: everything disabled. Demo/dev policy enables lane work only.
Adoption, merge, and push-to-preproduction require separate approvals.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

POLICY_VERSION = "rig.ralph_background_policy.v2"

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

    allow_isolated_worktree_creation: bool = False
    allow_isolated_lane_execution: bool = False
    allow_ralph_branch_commits: bool = False
    allow_seal_review_bundle: bool = False
    allow_adoption_proposal: bool = False
    allow_adoption_merge: bool = False
    allow_push_to_preproduction: bool = False

    max_active_lanes: int = 2
    max_commits_per_lane: int = 10
    max_changed_files_per_lane: int = 20
    max_runtime_seconds_per_lane: int = 300

    lane_root: str = ".rig/worktrees/ralph"
    branch_prefix: str = "ralph"
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    allowed_capabilities: list[str] = Field(default_factory=list)
    forbidden_capabilities: list[str] = Field(
        default_factory=lambda: sorted(FORBIDDEN_CAPABILITIES)
    )
    required_validations: list[str] = Field(default_factory=list)
    require_lane_start_approval: bool = True
    require_adoption_approval: bool = True
    require_preproduction_push_approval: bool = True

    def validate_capabilities(self) -> list[str]:
        violations: list[str] = []
        for cap in self.allowed_capabilities:
            if cap in FORBIDDEN_CAPABILITIES:
                violations.append(f"forbidden:{cap}")
            elif cap not in ALLOWED_CAPABILITIES:
                violations.append(f"unknown:{cap}")
        return violations

    def active_lanes_allowed(self, current_count: int) -> bool:
        return self.enabled and self.allow_isolated_worktree_creation and current_count < self.max_active_lanes

    def can_create_worktree(self) -> bool:
        return self.enabled and self.allow_isolated_worktree_creation

    def can_execute_in_lane(self) -> bool:
        return self.enabled and self.allow_isolated_lane_execution

    def can_commit_to_lane(self) -> bool:
        return self.enabled and self.allow_ralph_branch_commits

    def can_seal_bundle(self) -> bool:
        return self.enabled and self.allow_seal_review_bundle

    def can_propose_adoption(self) -> bool:
        return self.enabled and self.allow_adoption_proposal

    def can_merge_adoption(self) -> bool:
        return self.enabled and self.allow_adoption_merge

    def can_push_preproduction(self) -> bool:
        return self.enabled and self.allow_push_to_preproduction


def default_policy() -> RalphBackgroundPolicy:
    return RalphBackgroundPolicy()


def demo_policy() -> RalphBackgroundPolicy:
    """Demo/developer policy: lane work enabled, merge/push still disabled."""
    return RalphBackgroundPolicy(
        enabled=True,
        allow_isolated_worktree_creation=True,
        allow_isolated_lane_execution=True,
        allow_ralph_branch_commits=True,
        allow_seal_review_bundle=True,
        allow_adoption_proposal=True,
        allow_adoption_merge=False,
        allow_push_to_preproduction=False,
        max_active_lanes=2,
        max_commits_per_lane=10,
        max_changed_files_per_lane=20,
        max_runtime_seconds_per_lane=300,
    )


__all__ = [
    "ALLOWED_CAPABILITIES",
    "FORBIDDEN_CAPABILITIES",
    "RalphBackgroundPolicy",
    "default_policy",
    "demo_policy",
]
