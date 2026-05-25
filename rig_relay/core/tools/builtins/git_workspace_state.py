from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
import subprocess
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
)
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolPermission,
)
from rig_relay.core.types import ToolStreamEvent

_GIT_TIMEOUT = 10
_PROTECTED_BRANCHES = frozenset({"main", "master"})
_MAX_CONFLICTED_IN_MESSAGE = 10
_UNMERGED_MIN_PARTS = 10
_UNMERGED_PATH_INDEX = 9
_RENAMED_MIN_PARTS = 10
_RENAMED_SRC_INDEX = 9
_RENAMED_DST_INDEX = 8
_ORDINARY_MIN_PARTS = 9
_ORDINARY_PATH_INDEX = 8


@dataclass
class _StatusV2Parsed:
    branch: str | None = None
    head_sha: str | None = None
    upstream: str | None = None
    ahead_count: int | None = None
    behind_count: int | None = None
    staged_paths: list[str] = field(default_factory=list)
    unstaged_paths: list[str] = field(default_factory=list)
    untracked_paths: list[str] = field(default_factory=list)
    deleted_paths: list[str] = field(default_factory=list)
    renamed_paths: list[dict[str, str]] = field(default_factory=list)
    conflicted_paths: list[str] = field(default_factory=list)
    is_detached: bool = False


class GitWorkspaceStateConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class GitWorkspaceStateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GitWorkspaceStateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_state: str
    branch: str | None = None
    head_sha: str | None = None
    upstream: str | None = None
    ahead_count: int | None = None
    behind_count: int | None = None
    checkpoint_readiness: str = "blocked"
    primary_blocker: str | None = None
    staged_paths: list[str] = Field(default_factory=list)
    unstaged_paths: list[str] = Field(default_factory=list)
    untracked_paths: list[str] = Field(default_factory=list)
    deleted_paths: list[str] = Field(default_factory=list)
    renamed_paths: list[dict[str, str]] = Field(default_factory=list)
    conflicted_paths: list[str] = Field(default_factory=list)
    checkpoint_candidate_paths: list[str] = Field(default_factory=list)
    checkpoint_blockers: list[str] = Field(default_factory=list)
    unique_changed_paths: int = 0
    staged_count: int = 0
    unstaged_count: int = 0
    untracked_count: int = 0
    deleted_count: int = 0
    renamed_count: int = 0
    conflicted_count: int = 0
    overlap_count: int = 0
    dirty_file_count: int = 0
    local_checkpoint_branch_policy_blocker: str | None = None
    remote_branch_protection_known: bool = False
    remote_branch_protection_status: str | None = None
    suggested_next_action: str | None = None


class GitWorkspaceState(
    BaseTool[
        GitWorkspaceStateArgs,
        GitWorkspaceStateResult,
        GitWorkspaceStateConfig,
        BaseToolState,
    ]
):
    description: ClassVar[str] = (
        "Return a structured read-side projection of the current local Git "
        "workspace state: branch, staged/unstaged/untracked/deleted/renamed/conflicted "
        "files, upstream divergence, checkpoint candidates and blockers. "
        "Use this tool for a deterministic answer about workspace state. "
        "Use git_status, git_diff, git_log, git_show, and git_ls_files for detailed "
        "inspection of raw Git output, history, or specific object content."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.DETERMINISTIC_REPO_STATE
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.READ_ONLY

    async def run(
        self, args: GitWorkspaceStateArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | GitWorkspaceStateResult, None]:
        del args, ctx

        is_inside = _run_is_inside_work_tree()
        if not is_inside:
            yield GitWorkspaceStateResult(
                repository_state="not_a_repository",
                checkpoint_readiness="blocked",
                primary_blocker="not_a_repository",
                suggested_next_action="Initialize a git repository.",
            )
            return

        raw = _run_git_status_porcelain_v2()
        if raw is None:
            yield GitWorkspaceStateResult(
                repository_state="clean",
                checkpoint_readiness="blocked",
                primary_blocker="git_status_unavailable",
                suggested_next_action="Unable to read git status.",
            )
            return

        parsed = _parse_status_v2(raw)
        result = _build_result(parsed)
        yield result


def _run_is_inside_work_tree() -> bool | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return False

    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _run_git_status_porcelain_v2() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain=v2", "--branch"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, Exception):
        return None

    if proc.returncode != 0:
        return None
    return proc.stdout


def _parse_status_v2(raw: str) -> _StatusV2Parsed:
    parsed = _StatusV2Parsed()

    for line in raw.splitlines():
        if not line:
            continue
        _parse_status_line(line, parsed)

    return parsed


def _parse_status_line(line: str, parsed: _StatusV2Parsed) -> None:
    if line.startswith("# branch.oid "):
        parsed.head_sha = line[len("# branch.oid ") :]
    elif line.startswith("# branch.head "):
        head_value = line[len("# branch.head ") :]
        if head_value == "(detached)":
            parsed.is_detached = True
        else:
            parsed.branch = head_value
    elif line.startswith("# branch.upstream "):
        parsed.upstream = line[len("# branch.upstream ") :]
    elif line.startswith("# branch.ab "):
        _parse_branch_ab(line, parsed)
    elif line.startswith("?"):
        parsed.untracked_paths.append(line[2:])
    elif line.startswith("u"):
        _parse_unmerged(line, parsed)
    elif line.startswith("1"):
        _parse_ordinary(line, parsed)
    elif line.startswith("2"):
        _parse_renamed(line, parsed)


def _parse_branch_ab(line: str, parsed: _StatusV2Parsed) -> None:
    ab_value = line[len("# branch.ab ") :]
    for part in ab_value.split():
        if part.startswith("+"):
            try:
                parsed.ahead_count = int(part[1:])
            except ValueError:
                pass
        elif part.startswith("-"):
            try:
                parsed.behind_count = int(part[1:])
            except ValueError:
                pass


def _parse_unmerged(line: str, parsed: _StatusV2Parsed) -> None:
    parts = line[2:].split()
    if len(parts) >= _UNMERGED_MIN_PARTS:
        parsed.conflicted_paths.append(parts[_UNMERGED_PATH_INDEX])


def _parse_ordinary(line: str, parsed: _StatusV2Parsed) -> None:
    parts = line.split()
    if len(parts) < _ORDINARY_MIN_PARTS:
        return
    xy = parts[1]
    path = parts[_ORDINARY_PATH_INDEX]
    if "D" in xy:
        parsed.deleted_paths.append(path)
    if xy[0] in {"M", "A", "R"}:
        parsed.staged_paths.append(path)
    if xy[1] in {"M", "D"}:
        parsed.unstaged_paths.append(path)


def _parse_renamed(line: str, parsed: _StatusV2Parsed) -> None:
    parts = line.split()
    if len(parts) < _RENAMED_MIN_PARTS:
        return
    xy = parts[1]
    src = parts[_RENAMED_SRC_INDEX]
    dst = parts[_RENAMED_DST_INDEX] if len(parts) > _RENAMED_DST_INDEX else ""
    entry: dict[str, str] = {}
    if src:
        entry["old"] = src
    if dst:
        entry["new"] = dst
    parsed.renamed_paths.append(entry)
    if xy[0] in {"R", "M", "A"} and dst:
        parsed.staged_paths.append(dst)
    if xy[1] in {"R", "M", "D"} and dst:
        parsed.unstaged_paths.append(dst)


def _build_result(parsed: _StatusV2Parsed) -> GitWorkspaceStateResult:
    repository_state = _compute_repository_state(parsed)

    staged_set = set(parsed.staged_paths)
    unstaged_set = set(parsed.unstaged_paths)
    overlap_set = staged_set & unstaged_set
    all_set = (
        staged_set
        | unstaged_set
        | set(parsed.untracked_paths)
        | set(parsed.deleted_paths)
        | set(parsed.conflicted_paths)
    )
    for entry in parsed.renamed_paths:
        old = entry.get("old")
        new = entry.get("new")
        if old:
            all_set.add(old)
        if new:
            all_set.add(new)

    unique = len(all_set)

    checkpoint_blockers = _build_checkpoint_blockers(
        parsed.is_detached, parsed.branch, parsed.conflicted_paths
    )

    readiness = (
        "blocked"
        if checkpoint_blockers
        or repository_state in {"conflicted", "detached_head", "unborn_branch"}
        else "ready"
    )

    checkpoint_candidate_paths = list(parsed.staged_paths)

    suggested_next_action = _build_suggested_next_action(
        repository_state=repository_state,
        is_detached=parsed.is_detached,
        branch=parsed.branch,
        has_staged=bool(parsed.staged_paths),
        has_unstaged=bool(parsed.unstaged_paths),
        has_conflicts=bool(parsed.conflicted_paths),
    )

    return GitWorkspaceStateResult(
        repository_state=repository_state,
        branch=parsed.branch,
        head_sha=parsed.head_sha,
        upstream=parsed.upstream,
        ahead_count=parsed.ahead_count,
        behind_count=parsed.behind_count,
        checkpoint_readiness=readiness,
        primary_blocker=checkpoint_blockers[0] if checkpoint_blockers else None,
        staged_paths=parsed.staged_paths,
        unstaged_paths=parsed.unstaged_paths,
        untracked_paths=parsed.untracked_paths,
        deleted_paths=parsed.deleted_paths,
        renamed_paths=parsed.renamed_paths,
        conflicted_paths=parsed.conflicted_paths,
        checkpoint_candidate_paths=checkpoint_candidate_paths,
        checkpoint_blockers=checkpoint_blockers,
        unique_changed_paths=unique,
        staged_count=len(parsed.staged_paths),
        unstaged_count=len(parsed.unstaged_paths),
        untracked_count=len(parsed.untracked_paths),
        deleted_count=len(parsed.deleted_paths),
        renamed_count=len(parsed.renamed_paths),
        conflicted_count=len(parsed.conflicted_paths),
        overlap_count=len(overlap_set),
        dirty_file_count=unique,
        local_checkpoint_branch_policy_blocker=(
            f"Rig refuses governed checkpoint on protected branch '{parsed.branch}'. "
            "Create or switch to an admitted task branch/worktree."
            if parsed.branch in _PROTECTED_BRANCHES
            else None
        ),
        remote_branch_protection_known=False,
        remote_branch_protection_status=None,
        suggested_next_action=suggested_next_action,
    )


def _compute_repository_state(parsed: _StatusV2Parsed) -> str:
    if parsed.conflicted_paths:
        return "conflicted"
    if parsed.is_detached:
        return "detached_head"
    if (
        parsed.staged_paths
        or parsed.unstaged_paths
        or parsed.deleted_paths
        or parsed.untracked_paths
        or parsed.renamed_paths
    ):
        return "dirty"
    if parsed.branch is None and parsed.head_sha is None:
        return "unborn_branch"
    return "clean"


def _build_checkpoint_blockers(
    is_detached: bool, branch: str | None, conflicted_paths: list[str]
) -> list[str]:
    blockers: list[str] = []
    if is_detached:
        blockers.append("detached HEAD")
    if branch in _PROTECTED_BRANCHES:
        blockers.append(f"protected branch: {branch}")
    if conflicted_paths:
        blocker = "conflicted files: " + ", ".join(
            conflicted_paths[:_MAX_CONFLICTED_IN_MESSAGE]
        )
        if len(conflicted_paths) > _MAX_CONFLICTED_IN_MESSAGE:
            blocker += (
                f" (and {len(conflicted_paths) - _MAX_CONFLICTED_IN_MESSAGE} more)"
            )
        blockers.append(blocker)
    return blockers


def _build_suggested_next_action(
    repository_state: str,
    is_detached: bool,
    branch: str | None,
    has_staged: bool,
    has_unstaged: bool,
    has_conflicts: bool,
) -> str:
    """Deterministic blocker-precedence model.

    Blockers take priority over staging advice. Suggested actions refer
    only to lawful governed native operations — never to raw git add/commit.
    """
    rules: list[tuple[bool, str]] = [
        (
            repository_state == "not_a_repository",
            "Initialize a git repository before staging changes.",
        ),
        (has_conflicts, "Resolve merge conflicts before staging or checkpointing."),
        (
            is_detached,
            "Create or switch to an admitted task branch/worktree before "
            "staging files for checkpoint. Changes are visible above.",
        ),
        (
            branch in _PROTECTED_BRANCHES,
            "Create or switch to an admitted task branch/worktree before "
            "staging files for checkpoint. Checkpointing is refused on "
            f"protected branch '{branch}'.",
        ),
        (
            has_unstaged and not has_staged,
            "Changes are unstaged. Use governed native tools (write_file, "
            "search_replace) to stage admitted files, then checkpoint.",
        ),
        (
            has_staged,
            "Staged files are checkpoint candidates. "
            "Run validation, then checkpoint with include_paths containing "
            "the staged files.",
        ),
        (
            repository_state == "unborn_branch",
            "Make an initial commit before checkpointing.",
        ),
    ]
    for condition, message in rules:
        if condition:
            return message
    return "Nothing to checkpoint. Make changes and stage them using native tools."


__all__ = ["GitWorkspaceState", "GitWorkspaceStateArgs", "GitWorkspaceStateResult"]
