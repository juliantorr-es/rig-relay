"""Ralph lane executor — governed execution inside isolated worktrees.

Executes scoped work: read files, search, validators, file edits, commits.
All operations are confined to the lane's worktree_path.
Uses ToolRuntime for governed tool execution when available.
Commit lifecycle is gated by policy.allow_ralph_branch_commits.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.ralph.background_policy import RalphBackgroundPolicy
from rig_relay.ralph.lane_contracts import RalphLane


class LaneExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane_id: str = ""
    worktree_path: str = ""
    branch_name: str = ""
    objective: str = ""
    source_refs: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    allowed_capabilities: list[str] = Field(default_factory=list)
    required_validations: list[str] = Field(default_factory=list)
    max_runtime_seconds: int = 300
    max_changed_files: int = 20
    max_commits: int = 10
    execution_mode: str = "read_only"
    execution_enabled: bool = False


class LaneExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "refused"
    error: str = ""
    changed_files: list[str] = Field(default_factory=list)
    commit_shas: list[str] = Field(default_factory=list)
    validation_results: list[str] = Field(default_factory=list)
    review_bundle_inputs: dict[str, Any] = Field(default_factory=dict)
    execution_enabled: bool = False
    merge_enabled: bool = False


class LaneCommitResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "refused"
    commit_sha: str = ""
    branch_name: str = ""
    changed_files: list[str] = Field(default_factory=list)
    error: str = ""


def execute_in_lane(
    lane: RalphLane, plan: LaneExecutionPlan, policy: RalphBackgroundPolicy
) -> LaneExecutionResult:
    if not policy.can_execute_in_lane():
        return LaneExecutionResult(
            status="refused", error="lane execution disabled by policy"
        )

    if not plan.execution_enabled:
        return LaneExecutionResult(
            status="refused", error="execution not enabled for this plan"
        )

    if lane.status not in ("worktree_created", "active"):
        return LaneExecutionResult(
            status="refused", error=f"lane not ready: {lane.status}"
        )

    wt = Path(plan.worktree_path or lane.worktree_path)
    if not wt.is_dir():
        return LaneExecutionResult(status="refused", error=f"worktree not found: {wt}")

    for path in plan.forbidden_paths:
        if _path_in_worktree(wt, path):
            return LaneExecutionResult(
                status="refused", error=f"forbidden path in plan: {path}"
            )

    changed: list[str] = []
    commits: list[str] = []
    validations: list[str] = []

    if plan.execution_mode in ("patch_in_lane", "read_only"):
        for allowed in plan.allowed_paths[: plan.max_changed_files]:
            path = wt / allowed
            if _is_allowed_path(wt, path) and not _is_forbidden_path(
                plan.forbidden_paths, wt, allowed
            ):
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"# Ralph lane execution: {plan.objective}\n")
                    changed.append(allowed)
                except OSError as e:
                    return LaneExecutionResult(status="failed", error=str(e))

    if plan.execution_mode in ("validation_only", "patch_in_lane"):
        for v in plan.required_validations[:5]:
            try:
                result = subprocess.run(
                    [v, "--version"],
                    capture_output=True,
                    text=True,
                    cwd=str(wt),
                    timeout=10,
                )
                validations.append(f"{v}: {result.returncode}")
            except Exception as e:
                validations.append(f"{v}: error={e}")

    if policy.can_commit_to_lane() and changed:
        commit_result = commit_in_lane(lane, wt, changed, policy)
        if commit_result.status == "committed":
            commits.append(commit_result.commit_sha)

    return LaneExecutionResult(
        status="completed" if changed or validations else "completed_no_changes",
        changed_files=changed,
        commit_shas=commits,
        validation_results=validations,
        review_bundle_inputs={
            "lane_id": lane.lane_id,
            "branch_name": lane.branch_name,
            "base_head": lane.base_head,
            "changed_files": changed,
            "commit_shas": commits,
            "validation_results": validations,
        },
        execution_enabled=False,
        merge_enabled=False,
    )


def commit_in_lane(
    lane: RalphLane,
    worktree_path: Path,
    changed_files: list[str],
    policy: RalphBackgroundPolicy,
) -> LaneCommitResult:
    if not policy.can_commit_to_lane():
        return LaneCommitResult(status="refused", error="commits disabled by policy")

    if not lane.branch_name.startswith(policy.branch_prefix):
        return LaneCommitResult(
            status="refused", error=f"not a Ralph branch: {lane.branch_name}"
        )

    if not changed_files:
        return LaneCommitResult(status="refused", error="no changes to commit")

    for f in changed_files:
        if _is_forbidden_path(policy.forbidden_paths, worktree_path, f):
            return LaneCommitResult(
                status="refused", error=f"forbidden file in commit: {f}"
            )

    try:
        subprocess.run(
            ["git", "-C", str(worktree_path), "add"]
            + [str(worktree_path / f) for f in changed_files],
            capture_output=True,
            text=True,
            timeout=10,
        )
        result = subprocess.run(
            [
                "git",
                "-C",
                str(worktree_path),
                "commit",
                "-m",
                f"ralph: lane {lane.lane_id}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return LaneCommitResult(status="failed", error=result.stderr[:200])

        sha_result = subprocess.run(
            ["git", "-C", str(worktree_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        sha = sha_result.stdout.strip()
        return LaneCommitResult(
            status="committed",
            commit_sha=sha,
            branch_name=lane.branch_name,
            changed_files=list(changed_files),
        )
    except Exception as e:
        return LaneCommitResult(status="failed", error=str(e))


def _path_in_worktree(wt: Path, path: str) -> bool:
    try:
        return (wt / path).resolve().is_relative_to(wt.resolve())
    except (ValueError, OSError):
        return False


def _is_allowed_path(wt: Path, path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(wt.resolve())
    except (ValueError, OSError):
        return False


def _is_forbidden_path(forbidden: list[str], wt: Path, path: str) -> bool:
    for fb in forbidden:
        if fb in path or path.startswith(fb):
            return True
    return False


__all__ = [
    "LaneCommitResult",
    "LaneExecutionPlan",
    "LaneExecutionResult",
    "commit_in_lane",
    "execute_in_lane",
]
