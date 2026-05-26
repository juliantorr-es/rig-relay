"""Isolated Git Transaction Index and Compare-and-Swap Branch Advance (A5).

Constructs checkpoint commits in a temporary isolated Git index, creates
commit objects via explicit plumbing, and advances the target branch
only through an atomic compare-and-swap ref update.

The ambient repository index is never read and never modified.
Foreign staged changes, uncommitted dirty files, and untracked
files are never captured in the candidate tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
import os
from pathlib import Path
import secrets
import subprocess


class TransactionPhase(StrEnum):
    INIT = auto()
    INDEX_INITIALIZED = auto()
    PATHS_POPULATED = auto()
    TREE_BUILT = auto()
    COMMIT_CREATED = auto()
    REF_ADVANCED = auto()
    TERMINAL_WRITTEN = auto()
    CONSUMED = auto()
    COMPLETED = auto()


class RefAdvanceOutcome(StrEnum):
    ACCEPTED = auto()
    STALE_PARENT = auto()
    REF_NOT_FOUND = auto()
    DETACHED_HEAD = auto()
    TRANSACTION_ERROR = auto()


@dataclass(slots=True)
class TransactionResult:
    phase: TransactionPhase = TransactionPhase.INIT
    ref_outcome: RefAdvanceOutcome | None = None
    parent_sha: str | None = None
    new_commit_sha: str | None = None
    tree_sha: str | None = None
    branch: str = ""
    repo_root: Path = field(default_factory=Path)
    error_detail: str = ""
    committed: bool = False

    @property
    def is_accepted(self) -> bool:
        return self.ref_outcome == RefAdvanceOutcome.ACCEPTED

    @property
    def branch_advanced(self) -> bool:
        return self.phase in {
            TransactionPhase.REF_ADVANCED,
            TransactionPhase.CONSUMED,
            TransactionPhase.COMPLETED,
        }


def _git(
    *args: str, cwd: Path, env: dict[str, str] | None = None, timeout: int = 15
) -> subprocess.CompletedProcess:
    merged_env: dict[str, str] = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["git", "--no-optional-locks", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=merged_env,
        timeout=timeout,
    )


def _git_pipe(
    *args: str,
    cwd: Path,
    input_text: str,
    env: dict[str, str] | None = None,
    timeout: int = 15,
) -> subprocess.CompletedProcess:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["git", "--no-optional-locks", *args],
        input=input_text,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=merged_env,
        timeout=timeout,
    )


# ═══════════════════════════════════════════════════════════════════════
# ── Isolated Index Construction ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def _temp_index_path(repo_root: Path) -> Path:
    tid = secrets.token_hex(12)
    return repo_root / ".git" / f"rig-relay-txn-{tid}.index"


def initialize_isolated_index(
    parent_sha: str, repo_root: Path
) -> tuple[Path | None, str]:
    """Create a temporary index initialized from parent_sha's tree.

    Uses GIT_INDEX_FILE and git read-tree.
    Returns (index_path, error_detail). index_path is None on failure.
    """
    tmp_idx = _temp_index_path(repo_root)
    try:
        result = _git(
            "read-tree", parent_sha, cwd=repo_root, env={"GIT_INDEX_FILE": str(tmp_idx)}
        )
        if result.returncode != 0:
            return None, f"read-tree failed: {result.stderr.strip()}"
        return tmp_idx, ""
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, f"index init failed: {exc}"


def add_path_to_isolated_index(
    index_path: Path, path: str, repo_root: Path
) -> tuple[bool, str]:
    """Add a single file path from the working tree to an isolated index.

    Uses git add on the specific path under GIT_INDEX_FILE.
    The file's current working-tree content is hashed into the index.
    Returns (ok, error_detail).
    """
    try:
        result = _git(
            "add", "--", path, cwd=repo_root, env={"GIT_INDEX_FILE": str(index_path)}
        )
        if result.returncode != 0:
            return False, f"git add {path} failed: {result.stderr.strip()}"
        return True, ""
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"add path {path} failed: {exc}"


def write_tree_from_isolated_index(
    index_path: Path, repo_root: Path
) -> tuple[str | None, str]:
    """Write a tree object from the isolated index.

    Returns (tree_sha, error_detail). tree_sha is None on failure.
    """
    try:
        result = _git(
            "write-tree", cwd=repo_root, env={"GIT_INDEX_FILE": str(index_path)}
        )
        if result.returncode != 0:
            return None, f"write-tree failed: {result.stderr.strip()}"
        return result.stdout.strip(), ""
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, f"write-tree failed: {exc}"


# ═══════════════════════════════════════════════════════════════════════
# ── Commit Construction ─────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def create_commit_object(
    tree_sha: str,
    parent_sha: str,
    message: str,
    preparation_receipt_sha256: str,
    repo_root: Path,
) -> tuple[str | None, str]:
    """Create a commit object from explicit tree and parent.

    Uses git commit-tree. Adds Rig-Preparation-Receipt-SHA256
    as a structured trailer.

    Returns (commit_sha, error_detail). commit_sha is None on failure.
    """
    commit_input = (
        f"{message}\n\nRig-Preparation-Receipt-SHA256: {preparation_receipt_sha256}\n"
    )
    try:
        result = _git_pipe(
            "commit-tree",
            tree_sha,
            "-p",
            parent_sha,
            "-F",
            "-",
            cwd=repo_root,
            input_text=commit_input,
        )
        if result.returncode != 0:
            return None, f"commit-tree failed: {result.stderr.strip()}"
        return result.stdout.strip(), ""
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, f"commit-tree failed: {exc}"


# ═══════════════════════════════════════════════════════════════════════
# ── Compare-and-Swap Branch Advance ─────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def advance_branch_cas(
    branch: str, new_commit: str, expected_old: str, repo_root: Path
) -> RefAdvanceOutcome:
    """Atomically advance branch ref iff it still points to expected_old.

    Uses git update-ref <ref> <new> <old>.
    Returns ACCEPTED, STALE_PARENT, or TRANSACTION_ERROR.
    """
    ref = f"refs/heads/{branch}"
    try:
        result = _git("update-ref", ref, new_commit, expected_old, cwd=repo_root)
        if result.returncode == 0:
            return RefAdvanceOutcome.ACCEPTED
        stderr = result.stderr.strip().lower() if result.stderr else ""
        if "cannot lock" in stderr or "expected" in stderr or "not at" in stderr:
            return RefAdvanceOutcome.STALE_PARENT
        return RefAdvanceOutcome.TRANSACTION_ERROR
    except (subprocess.TimeoutExpired, OSError):
        return RefAdvanceOutcome.TRANSACTION_ERROR


def get_current_branch(repo_root: Path) -> tuple[str | None, str]:
    """Get the current branch name. Returns (branch_name, error)."""
    try:
        result = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_root)
        if result.returncode != 0:
            return None, "failed to resolve HEAD"
        branch = result.stdout.strip()
        if not branch or branch == "HEAD":
            return None, f"not on a branch: {branch}"
        return branch, ""
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, f"branch detection failed: {exc}"


def get_head_sha(repo_root: Path) -> tuple[str | None, str]:
    """Get the current HEAD commit SHA."""
    try:
        result = _git("rev-parse", "HEAD", cwd=repo_root)
        if result.returncode != 0:
            return None, f"rev-parse HEAD failed: {result.stderr.strip()}"
        return result.stdout.strip(), ""
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, f"HEAD resolution failed: {exc}"


# ═══════════════════════════════════════════════════════════════════════
# ── Full Isolated Transaction ───────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def execute_isolated_checkpoint_transaction(
    *,
    repo_root: Path,
    branch: str,
    parent_sha: str,
    authorized_paths: list[str],
    preparation_receipt_sha256: str,
    commit_message: str,
) -> TransactionResult:
    """Execute a complete isolated checkpoint transaction.

    Phases:
    1. Create temporary index from parent tree
    2. Populate only authorized paths from working tree
    3. Write candidate tree
    4. Create commit object
    5. Compare-and-swap branch ref advance
    6. Clean up temporary index

    The ambient Git index is never read, never modified.
    Foreign staged/dirty/untracked files are never captured.
    """
    result = TransactionResult(
        phase=TransactionPhase.INIT,
        parent_sha=parent_sha,
        branch=branch,
        repo_root=repo_root,
    )

    # 1. Initialize isolated index from parent tree
    tmp_idx, err = initialize_isolated_index(parent_sha, repo_root)
    if tmp_idx is None:
        result.error_detail = f"index initialization: {err}"
        return result
    result.phase = TransactionPhase.INDEX_INITIALIZED

    # 2. Populate authorized paths
    for path in authorized_paths:
        ok, err = add_path_to_isolated_index(tmp_idx, path, repo_root)
        if not ok:
            result.error_detail = f"path population ({path}): {err}"
            _cleanup_index(tmp_idx)
            return result
    result.phase = TransactionPhase.PATHS_POPULATED

    # 3. Write candidate tree
    tree_sha, err = write_tree_from_isolated_index(tmp_idx, repo_root)
    if tree_sha is None:
        result.error_detail = f"tree write: {err}"
        _cleanup_index(tmp_idx)
        return result
    result.tree_sha = tree_sha
    result.phase = TransactionPhase.TREE_BUILT

    # Clean up temp index — no longer needed after tree write
    _cleanup_index(tmp_idx)

    # 4. Create commit object
    commit_sha, err = create_commit_object(
        tree_sha=tree_sha,
        parent_sha=parent_sha,
        message=commit_message,
        preparation_receipt_sha256=preparation_receipt_sha256,
        repo_root=repo_root,
    )
    if commit_sha is None:
        result.error_detail = f"commit creation: {err}"
        return result
    result.new_commit_sha = commit_sha
    result.phase = TransactionPhase.COMMIT_CREATED

    # 5. Compare-and-swap branch ref advance
    ref_result = advance_branch_cas(branch, commit_sha, parent_sha, repo_root)
    result.ref_outcome = ref_result
    if ref_result == RefAdvanceOutcome.ACCEPTED:
        result.phase = TransactionPhase.REF_ADVANCED
        result.committed = True
    else:
        result.error_detail = f"ref advance refused: {ref_result}"
        # Commit object is orphaned — not a completed checkpoint
        return result

    result.phase = TransactionPhase.COMPLETED
    return result


def _cleanup_index(index_path: Path) -> None:
    try:
        index_path.unlink(missing_ok=True)
    except OSError:
        pass


def is_commit_reachable(commit_sha: str, branch: str, repo_root: Path) -> bool:
    """Check whether a commit is reachable from the current branch tip.

    Uses git merge-base --is-ancestor.
    """
    try:
        result = _git(
            "merge-base",
            "--is-ancestor",
            commit_sha,
            f"refs/heads/{branch}",
            cwd=repo_root,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


__all__ = [
    "RefAdvanceOutcome",
    "TransactionPhase",
    "TransactionResult",
    "add_path_to_isolated_index",
    "advance_branch_cas",
    "create_commit_object",
    "execute_isolated_checkpoint_transaction",
    "get_current_branch",
    "get_head_sha",
    "initialize_isolated_index",
    "is_commit_reachable",
    "write_tree_from_isolated_index",
]
