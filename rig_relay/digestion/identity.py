"""Repository identity derivation — ephemeral preview candidates.

Slice 1A: Desktop Repository Preview Intake v1.
Preview identities are ephemeral and not persisted. Durable registration
is deferred to Slice 1B.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from typing import NewType
import uuid

from rig_relay.digestion.models import (
    DirtyState,
    IdentityStatus,
    RepositoryIdentityCandidate,
)

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

    Uses `git rev-parse --show-toplevel`. Returns None if not in a git repo.
    """
    try:
        result = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
            cwd=path,
        ).strip()
        return Path(result).resolve() if result else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def resolve_git_branch(path: Path) -> str | None:
    """Resolve the current Git branch name."""
    try:
        result = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            cwd=path,
        ).strip()
        return result if result and result != "HEAD" else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def resolve_git_head_sha(path: Path) -> str | None:
    """Resolve the full SHA of HEAD."""
    try:
        result = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL, cwd=path
        ).strip()
        return result if result else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def resolve_git_remotes(path: Path) -> list[dict[str, str]]:
    """Resolve git remote information.

    Returns list of {name, url_digest, host} dicts.
    url_digest is a SHA256 of the remote URL (not the URL itself,
    to avoid leaking remote details into casual state).
    """
    try:
        result = subprocess.check_output(
            ["git", "remote", "-v"], text=True, stderr=subprocess.DEVNULL, cwd=path
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
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
        return subprocess.check_output(
            ["git", "status", "--porcelain=v2", "--branch"],
            text=True,
            stderr=subprocess.DEVNULL,
            cwd=path,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def parse_dirty_state_from_porcelain(porcelain_output: str) -> DirtyState:
    """Parse dirty file counts from git porcelain v2 output."""
    _PORCELAIN_V2_XY_WIDTH = 2

    state = DirtyState()
    for line in porcelain_output.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        xy = (
            line[:_PORCELAIN_V2_XY_WIDTH] if len(line) >= _PORCELAIN_V2_XY_WIDTH else ""
        )
        if "u" in xy.lower():
            state.conflicted += 1
        elif xy == "??":
            state.untracked += 1
        elif xy[0] != "." and xy[1] != ".":
            state.staged += 1
        elif xy[1] != ".":
            state.modified += 1
        elif xy[0] != ".":
            state.modified += 1
    return state


def is_github_backed(remotes: list[dict[str, str]]) -> bool:
    """Check whether any remote is github.com."""
    return any(r.get("host") == "github.com" for r in remotes)
