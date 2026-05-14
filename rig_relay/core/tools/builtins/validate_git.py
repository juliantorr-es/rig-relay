"""Validate tool — git state collection and dirty policy enforcement.

Read-only git introspection using argv subprocesses. Never mutates the
repo. Returns content-light ValidateGitState (counts and POSIX paths,
no raw status text, no diffs, no file contents).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil

from rig_relay.core.tools.builtins.validate_models import (
    DIRTY_POLICY_ALLOW_DIRTY,
    DIRTY_POLICY_ALLOW_LISTED_DIRTY,
    DIRTY_POLICY_CLEAN,
    ValidateGitState,
)


def _parse_git_status_branch(state: ValidateGitState, line: str) -> None:
    """Parse a git status branch header line (## ...)."""
    parts = line.removeprefix("## ").strip()
    if "..." in parts:
        branch_part, upstream_part = parts.split("...", 1)
        state.branch = branch_part.strip()
        if "[" in upstream_part:
            state.upstream, extra = upstream_part.split("[", 1)
            state.upstream = state.upstream.strip()
            if "ahead" in extra:
                state.ahead_count = _extract_count(extra, "ahead")
            if "behind" in extra:
                state.behind_count = _extract_count(extra, "behind")
        else:
            state.upstream = upstream_part.strip()
    else:
        state.branch = parts.strip()


def _parse_git_status_porcelain_line(
    state: ValidateGitState,
    line: str,
    dirty: list[str],
    untracked: list[str],
    changed: list[str],
) -> None:
    """Parse a single porcelain status line."""
    if len(line) < 4:  # noqa: PLR2004
        return
    code = line[:2]
    raw_path = line[3:].strip()
    path = raw_path.split()[-1] if " " in raw_path else raw_path
    rel_path = path.replace(os.sep, "/")

    changed.append(rel_path)

    if code == "??":
        untracked.append(rel_path)
        dirty.append(rel_path)
    elif "U" in code or "DD" in code or "AA" in code:
        state.conflicted_count += 1
        dirty.append(rel_path)
    else:
        dirty.append(rel_path)

    if code[0] != " ":
        state.staged_count += 1
    if code[0] == "M" or code[1] == "M":
        state.modified_count += 1
    if code[0] == "D" or code[1] == "D":
        state.deleted_count += 1


def _parse_git_status_porcelain(stdout: str, cwd: str | None) -> ValidateGitState:
    state = ValidateGitState(is_git_repo=True)
    lines_out = stdout.strip().splitlines()
    porcelain_lines: list[str] = []

    for l in lines_out:
        if not l.strip():
            continue
        if l.startswith("##"):
            _parse_git_status_branch(state, l)
        else:
            porcelain_lines.append(l)

    dirty_paths: list[str] = []
    untracked_paths: list[str] = []
    changed_paths: list[str] = []

    for l in porcelain_lines:
        _parse_git_status_porcelain_line(
            state, l, dirty_paths, untracked_paths, changed_paths
        )

    state.dirty_paths = sorted(set(dirty_paths))
    state.untracked_paths = sorted(set(untracked_paths))
    state.changed_paths = sorted(set(changed_paths))
    state.dirty_count = len(state.dirty_paths)
    state.untracked_count = len(state.untracked_paths)
    return state


def _extract_count(text: str, label: str) -> int:
    m = re.search(label + r"\s+(\d+)", text)
    return int(m.group(1)) if m else 0


async def _run_git(
    argv: list[str], cwd: str | None, timeout: int = 15
) -> tuple[str, str, int]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            cwd=cwd,
        )
    except FileNotFoundError:
        return "", "git not found", -1

    try:
        raw_stdout, raw_stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return "", "timed out", -1

    stdout_str = raw_stdout.decode("utf-8", errors="replace") if raw_stdout else ""
    stderr_str = raw_stderr.decode("utf-8", errors="replace") if raw_stderr else ""
    return stdout_str, stderr_str, proc.returncode or 0


# ruff: noqa: PLR0914
async def _collect_git_state(cwd: str | None) -> ValidateGitState:
    """Collect content-light git workspace state.

    Runs read-only git introspection commands. Never mutates the repo.
    Returns a structured ValidateGitState even when not in a git repo.
    """
    if not cwd:
        return ValidateGitState(is_git_repo=False)

    git_available = shutil.which("git")
    if not git_available:
        return ValidateGitState(
            is_git_repo=False,
            error_kind="missing_dependency",
            refusal_reason="git binary not found",
        )

    wt_result = await _run_git(["git", "rev-parse", "--is-inside-work-tree"], cwd)
    if not wt_result or wt_result[2] != 0:
        return ValidateGitState(is_git_repo=False)
    stdout_str, _stderr_str, _rc = wt_result
    if stdout_str.strip() != "true":
        return ValidateGitState(is_git_repo=False)

    branch: str | None = None
    br_result = await _run_git(["git", "branch", "--show-current"], cwd)
    if br_result and br_result[2] == 0:
        branch = br_result[0].strip() or None

    head: str | None = None
    head_result = await _run_git(["git", "rev-parse", "HEAD"], cwd)
    if head_result and head_result[2] == 0:
        head = head_result[0].strip()[:40] or None

    is_worktree = branch is None

    upstream: str | None = None
    ahead_count = 0
    behind_count = 0
    up_result = await _run_git(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd
    )
    if up_result and up_result[2] == 0:
        upstream = up_result[0].strip() or None
        ab_result = await _run_git(
            ["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"], cwd
        )
        if ab_result and ab_result[2] == 0:
            parts = ab_result[0].strip().split()
            if len(parts) == 2:  # noqa: PLR2004
                behind_count = int(parts[0])
                ahead_count = int(parts[1])

    status_result = await _run_git(
        ["git", "status", "--short", "--branch", "--untracked-files=all"], cwd
    )

    porcelain_sha256: str | None = None
    parsed: ValidateGitState = ValidateGitState()
    if status_result and status_result[2] == 0:
        raw_output = status_result[0]
        porcelain_sha256 = hashlib.sha256(raw_output.encode("utf-8")).hexdigest()
        parsed = _parse_git_status_porcelain(raw_output, cwd)

    return ValidateGitState(
        branch=branch or parsed.branch or None,
        head=head,
        is_git_repo=True,
        is_worktree=is_worktree,
        upstream=upstream or parsed.upstream or None,
        ahead_count=ahead_count or parsed.ahead_count or 0,
        behind_count=behind_count or parsed.behind_count or 0,
        dirty_count=parsed.dirty_count or 0,
        modified_count=parsed.modified_count or 0,
        deleted_count=parsed.deleted_count or 0,
        untracked_count=parsed.untracked_count or 0,
        staged_count=parsed.staged_count or 0,
        conflicted_count=parsed.conflicted_count or 0,
        dirty_paths=parsed.dirty_paths or [],
        untracked_paths=parsed.untracked_paths or [],
        changed_paths=parsed.changed_paths or [],
        status_porcelain_sha256=porcelain_sha256,
    )


# ── Dirty policy enforcement ─────────────────────────────────────────


# ruff: noqa: PLR0911
def _check_dirty_policy(
    git_state: ValidateGitState, policy: str | None, allowed_paths: list[str]
) -> str | None:
    """Check dirty state against expected_dirty_policy.

    Args:
        git_state: Current git workspace state.
        policy: Expected dirty policy.
        allowed_paths: Paths allowed to be dirty under allow_listed_dirty.

    Returns:
        A refusal/blocker reason string, or None if the policy passes.
    """
    if not policy:
        return None

    if policy == DIRTY_POLICY_ALLOW_DIRTY:
        return None

    if not git_state.is_git_repo:
        return None

    if policy == DIRTY_POLICY_CLEAN:
        if git_state.dirty_count > 0 or git_state.conflicted_count > 0:
            return (
                f"Workspace is dirty ({git_state.dirty_count} files) but "
                "expected_dirty_policy is 'clean'"
            )
        return None

    if policy == DIRTY_POLICY_ALLOW_LISTED_DIRTY:
        if git_state.dirty_count == 0 and git_state.conflicted_count == 0:
            return None
        allowed_set = set(allowed_paths)
        dirty_set = set(git_state.dirty_paths)
        unlisted = dirty_set - allowed_set
        if unlisted:
            sorted_unlisted = sorted(unlisted)
            return (
                "Unlisted dirty paths under expected_dirty_policy="
                f"'allow_listed_dirty': {sorted_unlisted}"
            )
        return None

    return None  # Unknown policy
