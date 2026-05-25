"""Repository identity derivation — ephemeral preview candidates.

Slice 1A: Desktop Repository Preview Intake v1.
Preview identities are ephemeral and not persisted. Durable registration
is deferred to Slice 1B.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import NewType
import uuid

from rig_relay.digestion.models import (
    DirtyState,
    IdentityStatus,
    RepositoryIdentityCandidate,
)


class _GitError(Exception):
    """Raised when a read-only git observation fails."""


def _git_readonly(cwd: Path, *args: str) -> str:
    """Run a read-only git observation command with --no-optional-locks.

    Suppresses optional Git operations that may take locks or refresh the
    index. Used for all digestion-time repository observation to prevent
    unintended writes (e.g., git status silently rewriting .git/index).

    Args:
        cwd: Working directory (the git repo root).
        *args: Git subcommand and arguments.

    Returns:
        Stripped stdout of the git command.

    Raises:
        _GitError: If the git command fails or git is not available.
    """
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "--no-optional-locks", *args],
            text=True,
            stderr=subprocess.DEVNULL,
            cwd=cwd,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise _GitError(f"git {' '.join(args)} failed: {exc}") from exc


# ── Placeholder identity types (modeled but not created in 1A) ──

CheckoutIdentity = NewType("CheckoutIdentity", str)
"""A registered local clone identity. Not created in 1A, but modeled."""

WorktreeIdentity = NewType("WorktreeIdentity", str)
"""A specific opened worktree identity. Not created in 1A, but modeled."""


def derive_repository_identity_candidate(
    repo_root: Path, remotes: list[dict[str, str]], is_github_backed: bool
) -> RepositoryIdentityCandidate:
    """Derive an ephemeral repository identity candidate for preview intake.

    Does NOT assign a durable identity. Returns a candidate suitable for
    in-memory preview correlation only.

    For GitHub-backed repos with recognized remote: includes a
    remote-derived candidate digest as a matching signal.
    For local-only repos: status is unregistered_local_repository.
    """
    worktree_digest = _digest_path(repo_root)

    if is_github_backed and remotes:
        origin = _find_origin_remote(remotes)
        if origin:
            remote_digest = _digest_text(origin["url_digest"])
            return RepositoryIdentityCandidate(
                status=IdentityStatus.GITHUB_BACKED_CANDIDATE,
                remote_identity_digest=remote_digest,
                worktree_root_digest=worktree_digest,
                preview_correlation_id=str(uuid.uuid4()),
            )

    return RepositoryIdentityCandidate(
        status=IdentityStatus.UNREGISTERED_LOCAL,
        worktree_root_digest=worktree_digest,
        preview_correlation_id=str(uuid.uuid4()),
    )


def derive_checkout_identity_candidate(repo_root: Path) -> str:
    """Derive a matching signal for a potential local checkout identity.

    Uses the resolved git worktree root path as a matching signal.
    This is NOT a durable identity — it is a signal for detecting
    that a newly opened folder might be the same checkout as a
    previously registered one.
    """
    return _digest_path(repo_root)


def derive_worktree_identity_candidate(
    worktree_root: Path, checkout_identity_candidate: str
) -> str:
    """Derive a matching signal for a potential worktree identity.

    Combines the checkout candidate with the resolved worktree root
    to produce a worktree-scoped matching signal.
    """
    combined = f"{checkout_identity_candidate}:{_digest_path(worktree_root)}"
    return _digest_text(combined)


def _find_origin_remote(remotes: list[dict[str, str]]) -> dict[str, str] | None:
    """Find the 'origin' remote from the list, or the first remote."""
    for r in remotes:
        if r.get("name") == "origin":
            return r
    return remotes[0] if remotes else None


def _digest_path(path: Path) -> str:
    """SHA256 digest of a resolved path string."""
    return _digest_text(str(path.resolve()))


def _digest_text(text: str) -> str:
    """SHA256 hex digest of a text string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_git_worktree_root(path: Path) -> Path | None:
    """Resolve the Git worktree root for a given path.

    Uses `git --no-optional-locks rev-parse --show-toplevel`.
    Returns None if not in a git repo.
    """
    try:
        result = _git_readonly(path, "rev-parse", "--show-toplevel")
        return Path(result).resolve() if result else None
    except _GitError:
        return None


def resolve_git_branch(path: Path) -> str | None:
    """Resolve the current Git branch name."""
    try:
        result = _git_readonly(path, "rev-parse", "--abbrev-ref", "HEAD")
        return result if result and result != "HEAD" else None
    except _GitError:
        return None


def resolve_git_head_sha(path: Path) -> str | None:
    """Resolve the full SHA of HEAD."""
    try:
        result = _git_readonly(path, "rev-parse", "HEAD")
        return result if result else None
    except _GitError:
        return None


def resolve_git_remotes(path: Path) -> list[dict[str, str]]:
    """Resolve git remote information.

    Returns list of {name, url_digest, host} dicts.
    url_digest is a SHA256 of the remote URL (not the URL itself,
    to avoid leaking remote details into casual state).
    """
    try:
        result = _git_readonly(path, "remote", "-v")
    except _GitError:
        return []

    _REMOTE_LINE_MIN_PARTS = 2

    remotes: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in result.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < _REMOTE_LINE_MIN_PARTS:
            continue
        name = parts[0]
        url = parts[1]
        if name in seen:
            continue
        seen.add(name)
        host = _classify_host(url)
        remotes.append({"name": name, "url_digest": _digest_text(url), "host": host})
    return remotes


def _classify_host(url: str) -> str:
    """Classify a remote URL's hosting service."""
    url_lower = url.lower()
    if "github.com" in url_lower:
        return "github.com"
    if "gitlab.com" in url_lower:
        return "gitlab.com"
    if "bitbucket.org" in url_lower:
        return "bitbucket.org"
    return "other"


def resolve_git_porcelain_v2(path: Path) -> str:
    """Get machine-readable git status in porcelain v2 format.

    Git porcelain v2 exposes detailed worktree, branch-header,
    and file-status information suitable for script consumption.
    """
    try:
        return _git_readonly(path, "status", "--porcelain=v2", "--branch")
    except _GitError:
        return ""


def resolve_git_common_dir(path: Path) -> str | None:
    """Resolve the Git common directory for worktree correlation.

    Returns a SHA256 digest of the resolved common-dir path.
    Used to distinguish primary checkouts from linked worktrees
    and to correlate worktrees sharing the same repository.

    Returns None if not in a git repo.
    """
    try:
        raw = _git_readonly(path, "rev-parse", "--git-common-dir")
        if not raw:
            return None
        resolved = (path / raw).resolve()
        return _digest_path(resolved)
    except _GitError:
        return None


def parse_dirty_state_from_porcelain(porcelain_output: str) -> DirtyState:
    """Parse dirty file counts from git porcelain v2 output.

    Porcelain v2 format (regular entries):
        1 XY sub mH mI mW hH hI path
    where XY is at positions 2-3 of the line (0-indexed).

    Untracked files have a single '?' prefix at position 0.
    """
    _PORCELAIN_V2_MIN_LINE = 4

    state = DirtyState()
    for line in porcelain_output.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        # Untracked files: '?' prefix at position 0
        if line.startswith("?"):
            state.untracked += 1
            continue
        # Regular entries: XY status at positions 2-3
        if len(line) < _PORCELAIN_V2_MIN_LINE:
            continue
        x = line[2]
        y = line[3]
        xy = x + y
        if "u" in xy.lower():
            state.conflicted += 1
        elif x != "." and y != ".":
            state.staged += 1
        elif y != ".":
            state.modified += 1
        elif x != ".":
            state.modified += 1
    return state


def is_github_backed(remotes: list[dict[str, str]]) -> bool:
    """Check whether any remote is github.com."""
    return any(r.get("host") == "github.com" for r in remotes)
