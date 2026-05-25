from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import subprocess
from typing import Any

_MIN_COMMIT_SHA_LENGTH = 7
_PORCELAIN_V1_MIN_PARTS = 9
_PORCELAIN_V2_MIN_PARTS = 10
_PORCELAIN_V2_PATH_INDEX = 8


def compute_file_worktree_sha256(path: str, worktree_root: str | Path) -> str:
    """SHA256 of file bytes on disk. Returns 'sha256:<hex>' or raises FileNotFoundError."""
    full = Path(worktree_root) / path
    digest = hashlib.sha256(full.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def compute_index_tree_digest(worktree_root: str | Path) -> str | None:
    """git write-tree → tree object SHA. Returns None if index is empty or unmerged."""
    try:
        proc = subprocess.run(
            ["git", "write-tree"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(worktree_root),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def compute_head_tree_digest(worktree_root: str | Path) -> str | None:
    """git rev-parse HEAD^{tree} → current commit tree digest."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(worktree_root),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def get_current_branch(worktree_root: str | Path) -> str | None:
    """Return current branch name, None if detached or error."""
    try:
        proc = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(worktree_root),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def is_detached_head(worktree_root: str | Path) -> bool:
    """True if HEAD is detached."""
    try:
        proc = subprocess.run(
            ["git", "symbolic-ref", "-q", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(worktree_root),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return True
    return proc.returncode != 0


def has_conflicts(worktree_root: str | Path) -> bool:
    """True if index has unmerged entries."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--unmerged"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(worktree_root),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return True
    return bool(proc.stdout.strip())


def get_staged_paths(worktree_root: str | Path) -> list[str]:
    """Return list of staged (cached) file paths."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "-z"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(worktree_root),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []
    if proc.returncode != 0:
        return []
    return [p for p in proc.stdout.split("\0") if p]


def stage_paths_literal(paths: list[str], worktree_root: str | Path) -> bool:
    """Stage exact repository-relative paths using literal-safe git add.

    Uses --literal-pathspecs and --pathspec-from-file=- with NUL-delimited
    input to prevent wildcard expansion or pathspec interpretation.
    Returns True on success.
    """
    if not paths:
        return True
    try:
        proc = subprocess.run(
            [
                "git",
                "--literal-pathspecs",
                "add",
                "--pathspec-from-file=-",
                "--pathspec-file-nul",
                "--",
            ],
            input="\0".join(paths) + "\0",
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(worktree_root),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return proc.returncode == 0


def commit_prepared_index(
    message: str,
    worktree_root: str | Path,
    session_id: str = "",
    task_id: str = "",
    receipt_trailer: str = "",
) -> str | None:
    """Commit the current index with the given message and receipt trailer.

    Does NOT run git add. Commits exactly the current index.
    Returns commit SHA on success, None on failure.
    """
    full_message = message
    if session_id:
        full_message += f"\nSession: {session_id}"
    if task_id:
        full_message += f"\nTask: {task_id}"
    if receipt_trailer:
        full_message += f"\n{receipt_trailer}"

    try:
        proc = subprocess.run(
            ["git", "commit", "-m", full_message],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(worktree_root),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines() + proc.stderr.splitlines():
        if line.startswith("[") and "]" in line:
            sha_part = line.split("]")[0].split("[")[-1]
            if len(sha_part) >= _MIN_COMMIT_SHA_LENGTH:
                return sha_part
    return None


@dataclass
class IndexStateInspection:
    staged_paths: list[str] = field(default_factory=list)
    unstaged_paths: list[str] = field(default_factory=list)
    untracked_paths: list[str] = field(default_factory=list)
    deleted_paths: list[str] = field(default_factory=list)
    conflicted: bool = False


def inspect_index_state(worktree_root: str | Path) -> IndexStateInspection:
    """Return a structured view of the index and worktree state."""
    result = IndexStateInspection()
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain=v2"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(worktree_root),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return result
    if proc.returncode != 0:
        return result

    for line in proc.stdout.splitlines():
        if not line or line.startswith("#"):
            continue
        if line.startswith("?"):
            result.untracked_paths.append(line[2:])
        elif line.startswith("u"):
            result.conflicted = True
        elif line.startswith("1"):
            parts = line.split()
            if len(parts) >= _PORCELAIN_V1_MIN_PARTS:
                path = parts[_PORCELAIN_V2_PATH_INDEX]
                xy = parts[1]
                if xy[0] not in {" ", "?"}:
                    result.staged_paths.append(path)
                if xy[1] not in {" ", "?"}:
                    result.unstaged_paths.append(path)
        elif line.startswith("2"):
            parts = line.split()
            if len(parts) >= _PORCELAIN_V2_MIN_PARTS:
                xy = parts[1]
                new_path = (
                    parts[_PORCELAIN_V2_PATH_INDEX]
                    if len(parts) > _PORCELAIN_V2_PATH_INDEX
                    else ""
                )
                if xy[0] not in {" ", "?"} and new_path:
                    result.staged_paths.append(new_path)

    return result


@dataclass
class PreparationResult:
    ok: bool
    pre_index_tree_digest: str | None = None
    post_index_tree_digest: str | None = None
    prepared_paths: list[str] = field(default_factory=list)
    excluded_paths: list[str] = field(default_factory=list)
    refusal_code: str | None = None
    refusal_detail: str | None = None


def prepare_index_for_checkpoint(
    *,
    worktree_root: str | Path,
    branch: str | None,
    is_detached: bool,
    has_conflicts_flag: bool,
    is_protected_branch_func: Callable[[str | None], bool],
    is_path_in_scope_func: Callable[[str], bool],
    is_protected_dirty_func: Callable[[str], bool],
    has_active_write_reservation_func: Callable[[str], bool],
    preparation_paths: list[dict[str, Any]],
) -> PreparationResult:
    """Validate and prepare paths for checkpoint staging.

    Steps:
    1. Branch/HEAD/conflict checks
    2. For each path: scope, dirty guard, coordination, file-state verification
    3. Literal-safe git add for admitted paths
    4. Compute pre/post index tree digests

    Returns PreparationResult with ok=True and prepared_paths on success.
    """
    if has_conflicts_flag:
        return PreparationResult(
            ok=False,
            refusal_code="conflicted_worktree",
            refusal_detail="Index has unmerged entries. Resolve conflicts before preparation.",
        )
    if is_detached:
        return PreparationResult(
            ok=False,
            refusal_code="detached_head",
            refusal_detail="Detached HEAD. Create or switch to a task branch before preparation.",
        )
    if is_protected_branch_func(branch):
        return PreparationResult(
            ok=False,
            refusal_code="protected_branch",
            refusal_detail=f"Protected branch '{branch}'. Create or switch to a task branch.",
        )

    pre_digest = compute_index_tree_digest(worktree_root)

    prepared: list[str] = []
    excluded: list[str] = []

    for entry in preparation_paths:
        path = entry.get("path", "")
        change_kind = entry.get("change_kind", "modify")
        expected_sha = entry.get("expected_worktree_sha256")
        expected_absent = entry.get("expected_absent", False)

        if not is_path_in_scope_func(path):
            excluded.append(path)
            continue

        if is_protected_dirty_func(path):
            excluded.append(path)
            continue

        if has_active_write_reservation_func(path):
            excluded.append(path)
            continue

        if change_kind in {"add", "modify"}:
            if expected_sha is None:
                excluded.append(path)
                continue
            try:
                actual = compute_file_worktree_sha256(path, worktree_root)
            except (FileNotFoundError, OSError):
                excluded.append(path)
                continue
            if actual != expected_sha:
                excluded.append(path)
                continue
        elif change_kind == "delete":
            if not expected_absent:
                excluded.append(path)
                continue
            full = Path(worktree_root) / path
            if full.exists():
                excluded.append(path)
                continue

        prepared.append(path)

    if excluded and not prepared:
        reason = excluded[0] if excluded else "unknown"
        return PreparationResult(
            ok=False,
            refusal_code="all_paths_excluded",
            refusal_detail=(
                f"All requested paths excluded. First excluded: {reason}. "
                "Check scope, dirty guard, reservations, and file-state hashes."
            ),
        )

    existing_staged = set(get_staged_paths(worktree_root))
    prepared_set = set(prepared)
    unrelated = existing_staged - prepared_set
    if unrelated:
        return PreparationResult(
            ok=False,
            refusal_code="unrelated_staged_paths_present",
            refusal_detail=(
                f"Unrelated staged paths detected: {sorted(unrelated)}. "
                "Unstage or include them in the preparation request."
            ),
        )

    if not stage_paths_literal(prepared, worktree_root):
        return PreparationResult(
            ok=False,
            refusal_code="staging_failed",
            refusal_detail="Git add failed. Check repository state.",
        )

    post_digest = compute_index_tree_digest(worktree_root)

    return PreparationResult(
        ok=True,
        pre_index_tree_digest=pre_digest,
        post_index_tree_digest=post_digest,
        prepared_paths=prepared,
        excluded_paths=excluded,
    )


__all__ = [
    "IndexStateInspection",
    "PreparationResult",
    "commit_prepared_index",
    "compute_file_worktree_sha256",
    "compute_head_tree_digest",
    "compute_index_tree_digest",
    "get_current_branch",
    "get_staged_paths",
    "has_conflicts",
    "inspect_index_state",
    "is_detached_head",
    "prepare_index_for_checkpoint",
    "stage_paths_literal",
]
