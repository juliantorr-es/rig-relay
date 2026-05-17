"""Rig Relay Worktree Manager — P1b.

Relay-native worktree lifecycle for agent/lane execution isolation.
Operates on git worktrees under a configurable worktree_root, not the
main working tree. No force-removal of dirty worktrees. No execution
integration yet.

Usage:
    from rig_relay.coordination.worktree_manager import WorktreeManager

    mgr = WorktreeManager(
        repo_root=Path("/path/to/repo"),
        worktree_root=Path("/path/to/repo/.rig/relay/worktrees"),
    )
    result = mgr.create(workspace_id="lane-42", branch_name="feat/lane-42")
    if result.status == "created":
        print(f"Worktree at {result.record.path}")
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import logging
from pathlib import Path
import re
import subprocess
import time
from typing import ClassVar, final

from pydantic import BaseModel, ConfigDict

from rig_relay.tracing.golden_path import build_golden_path_event
from rig_relay.tracing.store import get_default_trace_store

logger = logging.getLogger(__name__)


def _emit_worktree_trace(event_type: str, *, payload: dict | None = None) -> None:
    """Emit a content-light worktree trace event. Non-fatal on error."""
    try:
        store = get_default_trace_store()
        event = build_golden_path_event(event_type=event_type, payload=payload or {})
        store.write(event)
    except Exception:
        pass


# ── Constants ──────────────────────────────────────────────────────────

DEFAULT_WORKTREE_ROOT_NAME = ".rig/relay/worktrees"

# Max allowed values for safety
_MAX_WORKSPACE_ID_LENGTH = 64
_MAX_BRANCH_NAME_LENGTH = 255
_SHA_HEX_LENGTH = 40
_GIT_COMMAND_TIMEOUT = 30.0
_GIT_STATUS_TIMEOUT = 10.0
_OUTPUT_CAP_BYTES = 10 * 1024  # 10 KB cap for git output

# Disallowed characters in branch names (git refname restrictions)
_UNSAFE_BRANCH_CHARS = re.compile(r"[ ~^:?*\[\\]")

# Disallowed path segments (path traversal)
_UNSAFE_PATH_SEGMENTS = frozenset({"..", "~"})


# ── Enums ──────────────────────────────────────────────────────────────


class WorktreeStatus(StrEnum):
    """Status of a tracked worktree."""

    HEALTHY = "healthy"
    MISSING = "missing"
    DIRTY = "dirty"
    STALE = "stale"
    REMOVED = "removed"
    ERROR = "error"


class WorktreeOperationKind(StrEnum):
    """Kind of worktree operation."""

    CREATE = "create"
    REMOVE = "remove"
    LIST = "list"
    INSPECT = "inspect"
    GET_HEAD = "get_head"


# ── Models ─────────────────────────────────────────────────────────────


class WorktreeRecord(BaseModel):
    """Content-light record of a single worktree.

    No raw git output, no diffs, no file contents.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.worktree.v1"
    workspace_id: str
    branch_name: str | None = None
    path: str
    head_sha: str | None = None
    status: WorktreeStatus = WorktreeStatus.HEALTHY
    created_at: str | None = None
    removed_at: str | None = None
    refusal_reason: str | None = None
    error_kind: str | None = None


class WorktreeOperationResult(BaseModel):
    """Result of a worktree operation.

    Content-light: no raw git output, no diffs, no file contents.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.worktree.v1"
    operation: WorktreeOperationKind
    status: str
    record: WorktreeRecord | None = None
    records: list[WorktreeRecord] | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None


# ── Git command result (internal, not persisted) ─────────────────────


@dataclass(frozen=True)
class _GitCommandResult:
    """Result of running a git command."""

    returncode: int
    stdout: str
    stderr: str
    duration_ms: float
    stdout_truncated: bool = False
    stderr_truncated: bool = False


# ── WorktreeManager ────────────────────────────────────────────────────


class WorktreeManager:
    """Manage git worktrees for isolated agent/lane execution.

    Operates under ``worktree_root``, not the main working tree.
    Refuses to create worktrees with unsafe workspace_id or branch_name.
    Refuses to remove dirty worktrees without ``force=True``.
    """

    schema_version: ClassVar[str] = "rig.relay.worktree.v1"

    def __init__(self, repo_root: Path, worktree_root: Path | None = None) -> None:
        self._repo_root = repo_root.resolve()
        self._worktree_root = (
            worktree_root.resolve()
            if worktree_root is not None
            else (self._repo_root / DEFAULT_WORKTREE_ROOT_NAME).resolve()
        )

    # ── Public API ─────────────────────────────────────────────────

    def create(
        self, workspace_id: str, branch_name: str, base_ref: str = "HEAD"
    ) -> WorktreeOperationResult:
        """Create a linked worktree for *workspace_id*.

        Args:
            workspace_id: Unique identifier for the workspace/lane.
                Must be safe for use as a path segment.
            branch_name: Name for the new branch.
                Must be a valid git ref name.
            base_ref: Git ref to base the new branch on (default HEAD).

        Returns:
            WorktreeOperationResult with status "created", "refused", or "error".
        """
        # ── Validate inputs ──
        refuse = self._check_create_preconditions(workspace_id, branch_name)
        if refuse is not None:
            return refuse

        # ── Resolve worktree path ──
        worktree_path = self._worktree_root / workspace_id

        # ── Check path is under worktree_root (safety) ──
        if not self._is_path_under_root(worktree_path):
            return WorktreeOperationResult(
                operation=WorktreeOperationKind.CREATE,
                status="refused",
                refusal_reason=(
                    f"Resolved worktree path '{worktree_path}' is not under "
                    f"worktree root '{self._worktree_root}'"
                ),
                error_kind="unsafe_path",
            )

        # ── Check if worktree path already exists ──
        if worktree_path.exists():
            return WorktreeOperationResult(
                operation=WorktreeOperationKind.CREATE,
                status="refused",
                refusal_reason=(
                    f"Worktree path '{worktree_path}' already exists. "
                    "Use a different workspace_id or remove the existing worktree."
                ),
                error_kind="path_exists",
            )

        # ── Check repo_root is a git repo ──
        git_check = self._run_git(
            ["rev-parse", "--git-dir"], timeout=_GIT_STATUS_TIMEOUT
        )
        if git_check.returncode != 0:
            return WorktreeOperationResult(
                operation=WorktreeOperationKind.CREATE,
                status="error",
                refusal_reason=(
                    f"Not a git repository or git unavailable: {git_check.stderr.strip()}"
                ),
                error_kind="not_a_git_repo",
            )

        # ── Ensure worktree root exists ──
        self._worktree_root.mkdir(parents=True, exist_ok=True)

        # ── Create git worktree ──
        argv = ["worktree", "add", "-b", branch_name, str(worktree_path), base_ref]
        result = self._run_git(argv, timeout=_GIT_COMMAND_TIMEOUT)

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "unknown error"
            _emit_worktree_trace(
                "worktree.mutation.failed",
                payload={"operation": "git_create", "error": error_msg[:200]},
            )
            return WorktreeOperationResult(
                operation=WorktreeOperationKind.CREATE,
                status="error",
                refusal_reason=f"git worktree add failed: {error_msg}",
                error_kind="git_command_failed",
            )

        # ── Get head SHA ──
        head_sha = self._get_head_for_path(worktree_path)

        now = datetime.now(UTC).isoformat()
        _emit_worktree_trace(
            "worktree.mutation.started",
            payload={"operation": "create", "branch_name": branch_name},
        )
        record = WorktreeRecord(
            workspace_id=workspace_id,
            branch_name=branch_name,
            path=str(worktree_path),
            head_sha=head_sha,
            status=WorktreeStatus.HEALTHY,
            created_at=now,
        )

        return WorktreeOperationResult(
            operation=WorktreeOperationKind.CREATE, status="created", record=record
        )

    @final
    def remove(
        self, workspace_id: str, *, force: bool = False
    ) -> WorktreeOperationResult:
        """Remove a linked worktree for *workspace_id*.

        Refuses to remove dirty worktrees unless ``force=True``.

        Args:
            workspace_id: Workspace identifier whose worktree to remove.
            force: Allow removal of dirty worktrees. Default False.

        Returns:
            WorktreeOperationResult with status "removed", "refused", or "error".
        """
        # ── Validate workspace_id ──
        sanitize_error = self._sanitize_workspace_id(workspace_id)
        if sanitize_error:
            return WorktreeOperationResult(
                operation=WorktreeOperationKind.REMOVE,
                status="refused",
                refusal_reason=sanitize_error,
                error_kind="invalid_workspace_id",
            )

        worktree_path = self._worktree_root / workspace_id

        # ── Check if worktree exists ──
        if not worktree_path.exists():
            return WorktreeOperationResult(
                operation=WorktreeOperationKind.REMOVE,
                status="refused",
                refusal_reason=(f"Worktree path '{worktree_path}' does not exist."),
                error_kind="path_not_found",
            )

        # ── Check if worktree is dirty (unless force) ──
        if not force:
            dirty = self._is_worktree_dirty(worktree_path)
            if not dirty:
                _emit_worktree_trace(
                    "worktree.protected_files_preserved",
                    payload={"worktree_path": str(worktree_path)},
                )
            if dirty:
                return WorktreeOperationResult(
                    operation=WorktreeOperationKind.REMOVE,
                    status="refused",
                    refusal_reason=(
                        f"Worktree '{workspace_id}' at '{worktree_path}' has "
                        "uncommitted changes. Set force=True to remove anyway."
                    ),
                    error_kind="dirty_worktree",
                )

        # ── Remove git worktree ──
        argv = ["worktree", "remove", str(worktree_path)]
        if force:
            argv.insert(2, "--force")

        result = self._run_git(argv, timeout=_GIT_COMMAND_TIMEOUT)

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "unknown error"
            _emit_worktree_trace(
                "worktree.mutation.failed",
                payload={"operation": "git_remove", "error": error_msg[:200]},
            )
            return WorktreeOperationResult(
                operation=WorktreeOperationKind.REMOVE,
                status="error",
                refusal_reason=f"git worktree remove failed: {error_msg}",
                error_kind="git_command_failed",
            )

        now = datetime.now(UTC).isoformat()
        _emit_worktree_trace(
            "worktree.mutation.started",
            payload={"operation": "remove", "workspace_id": workspace_id},
        )
        _emit_worktree_trace(
            "worktree.mutation.completed",
            payload={"operation": "remove", "status": "removed"},
        )
        record = WorktreeRecord(
            workspace_id=workspace_id,
            path=str(worktree_path),
            status=WorktreeStatus.REMOVED,
            removed_at=now,
        )

        return WorktreeOperationResult(
            operation=WorktreeOperationKind.REMOVE, status="removed", record=record
        )

    @final
    def get_head_hash(self, workspace_id: str) -> str | None:
        """Return the current HEAD SHA for a worktree, or None."""
        sanitize_error = self._sanitize_workspace_id(workspace_id)
        if sanitize_error:
            return None

        worktree_path = self._worktree_root / workspace_id
        if not worktree_path.exists():
            return None

        return self._get_head_for_path(worktree_path)

    @final
    def list_worktrees(self) -> list[WorktreeRecord]:
        """List all worktrees managed by this WorktreeManager's worktree_root.

        Parses ``git worktree list --porcelain`` output and filters to only
        worktrees under ``worktree_root``.
        """
        result = self._run_git(
            ["worktree", "list", "--porcelain"], timeout=_GIT_COMMAND_TIMEOUT
        )
        if result.returncode != 0:
            logger.error("git worktree list --porcelain failed: %s", result.stderr)
            return []

        records: list[WorktreeRecord] = []
        entries = self._parse_porcelain_output(result.stdout)

        for entry in entries:
            worktree_abs_path = Path(entry.get("worktree", "")).resolve()
            if not self._is_path_under_root(worktree_abs_path):
                continue

            # Derive workspace_id from the relative path under worktree_root
            try:
                workspace_id = worktree_abs_path.relative_to(
                    self._worktree_root
                ).as_posix()
            except ValueError:
                continue

            head_sha = entry.get("head")
            branch_name = entry.get("branch")
            # If branch starts with "refs/heads/", strip prefix
            if branch_name and branch_name.startswith("refs/heads/"):
                branch_name = branch_name[len("refs/heads/") :]

            # Determine status
            # If the path doesn't exist on disk, mark as MISSING
            status = WorktreeStatus.HEALTHY
            if not worktree_abs_path.exists():
                status = WorktreeStatus.MISSING
            elif head_sha is None:
                status = WorktreeStatus.ERROR

            records.append(
                WorktreeRecord(
                    workspace_id=workspace_id,
                    branch_name=branch_name,
                    path=str(worktree_abs_path),
                    head_sha=head_sha,
                    status=status,
                )
            )

        return records

    @final
    def inspect(self, workspace_id: str) -> WorktreeRecord | None:
        """Return the WorktreeRecord for *workspace_id*, or None."""
        sanitize_error = self._sanitize_workspace_id(workspace_id)
        if sanitize_error:
            return None

        worktree_path = self._worktree_root / workspace_id
        if not worktree_path.exists():
            return None

        head_sha = self._get_head_for_path(worktree_path)
        dirty = self._is_worktree_dirty(worktree_path)

        # Parse porcelain for branch info
        result = self._run_git(
            ["worktree", "list", "--porcelain"], timeout=_GIT_COMMAND_TIMEOUT
        )
        branch_name: str | None = None
        if result.returncode == 0:
            entries = self._parse_porcelain_output(result.stdout)
            for entry in entries:
                entry_path = Path(entry.get("worktree", "")).resolve()
                if entry_path == worktree_path:
                    raw_branch = entry.get("branch")
                    if raw_branch and raw_branch.startswith("refs/heads/"):
                        branch_name = raw_branch[len("refs/heads/") :]
                    break

        status = WorktreeStatus.DIRTY if dirty else WorktreeStatus.HEALTHY

        return WorktreeRecord(
            workspace_id=workspace_id,
            branch_name=branch_name,
            path=str(worktree_path),
            head_sha=head_sha,
            status=status,
        )

    # ── Internal helpers ───────────────────────────────────────────

    def _check_create_preconditions(
        self, workspace_id: str, branch_name: str
    ) -> WorktreeOperationResult | None:
        """Check preconditions for worktree creation.

        Returns a WorktreeOperationResult (refused/error) if a precondition
        fails, or None if all checks pass.
        """
        # Workspace_id must be safe
        err = self._sanitize_workspace_id(workspace_id)
        if err:
            return WorktreeOperationResult(
                operation=WorktreeOperationKind.CREATE,
                status="refused",
                refusal_reason=err,
                error_kind="invalid_workspace_id",
            )
        # Branch name must be safe
        err = self._sanitize_branch_name(branch_name)
        if err:
            return WorktreeOperationResult(
                operation=WorktreeOperationKind.CREATE,
                status="refused",
                refusal_reason=err,
                error_kind="invalid_branch_name",
            )
        return None

    def _run_git(self, argv: list[str], *, timeout: float) -> _GitCommandResult:
        """Run a git command and return a structured result.

        Always uses ``cwd=self._repo_root``. No shell. Output is capped
        to ``_OUTPUT_CAP_BYTES``.
        """
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                ["git", *argv],
                capture_output=True,
                text=True,
                cwd=self._repo_root,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            elapsed = (time.perf_counter() - start) * 1000
            return _GitCommandResult(
                returncode=-1,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                duration_ms=elapsed,
            )
        except FileNotFoundError:
            elapsed = (time.perf_counter() - start) * 1000
            return _GitCommandResult(
                returncode=-1, stdout="", stderr="git not found", duration_ms=elapsed
            )
        except OSError as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return _GitCommandResult(
                returncode=-1, stdout="", stderr=str(exc), duration_ms=elapsed
            )

        elapsed = (time.perf_counter() - start) * 1000

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        stdout_truncated = False
        stderr_truncated = False

        if len(stdout) > _OUTPUT_CAP_BYTES:
            stdout = stdout[:_OUTPUT_CAP_BYTES]
            stdout_truncated = True
        if len(stderr) > _OUTPUT_CAP_BYTES:
            stderr = stderr[:_OUTPUT_CAP_BYTES]
            stderr_truncated = True

        return _GitCommandResult(
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=round(elapsed, 1),
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )

    def _sanitize_workspace_id(self, workspace_id: str) -> str | None:
        """Return an error message if *workspace_id* is unsafe, else None."""
        if not workspace_id:
            return "workspace_id must not be empty"

        if len(workspace_id) > _MAX_WORKSPACE_ID_LENGTH:
            return (
                f"workspace_id too long ({len(workspace_id)} chars, "
                f"max {_MAX_WORKSPACE_ID_LENGTH})"
            )

        # Disallow path separators and traversal
        if "/" in workspace_id or "\\" in workspace_id:
            return "workspace_id must not contain path separators"

        for segment in _UNSAFE_PATH_SEGMENTS:
            if segment in workspace_id.split("/"):
                return f"workspace_id must not contain '{segment}'"

        return None

    def _sanitize_branch_name(self, branch_name: str) -> str | None:
        """Return an error message if *branch_name* is unsafe, else None."""
        if not branch_name:
            return "branch_name must not be empty"
        if len(branch_name) > _MAX_BRANCH_NAME_LENGTH:
            return (
                f"branch_name too long ({len(branch_name)} chars, "
                f"max {_MAX_BRANCH_NAME_LENGTH})"
            )
        if _UNSAFE_BRANCH_CHARS.search(branch_name):
            return "branch_name contains unsafe characters: disallowed: ~ ^ : ? * [ \\"
        for prefix in (".", "-"):
            if branch_name.startswith(prefix):
                return f"branch_name must not start with '{prefix}'"
        if ".lock" in branch_name or ".." in branch_name or "@{" in branch_name:
            return "branch_name contains invalid git ref syntax"
        return None

    def _is_path_under_root(self, path: Path) -> bool:
        """Check if *path* is a child of worktree_root (or equal to it)."""
        try:
            path.resolve().relative_to(self._worktree_root)
            return True
        except ValueError:
            return False

    def _is_worktree_dirty(self, worktree_path: Path) -> bool:
        """Check if a worktree has uncommitted changes."""
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=worktree_path,
                stdin=subprocess.DEVNULL,
                timeout=_GIT_STATUS_TIMEOUT,
            )
            if proc.returncode != 0:
                return False
            return bool(proc.stdout.strip())
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return False

    def _get_head_for_path(self, worktree_path: Path) -> str | None:
        """Get HEAD SHA for a worktree path."""
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=worktree_path,
                stdin=subprocess.DEVNULL,
                timeout=_GIT_STATUS_TIMEOUT,
            )
            if proc.returncode != 0:
                return None
            sha = proc.stdout.strip()
            return sha if len(sha) == _SHA_HEX_LENGTH else None
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return None

    @staticmethod
    def _parse_porcelain_output(output: str) -> list[dict[str, str]]:
        """Parse ``git worktree list --porcelain`` output.

        Returns a list of dicts with keys: worktree, head, branch, (optional) locked, prunable.
        """
        entries: list[dict[str, str]] = []
        current: dict[str, str] = {}

        for line in output.splitlines():
            line = line.strip()
            if not line:
                if current:
                    entries.append(current)
                    current = {}
                continue

            if line.startswith("worktree "):
                current["worktree"] = line[len("worktree ") :]
            elif line.startswith("HEAD "):
                current["head"] = line[len("HEAD ") :]
            elif line.startswith("branch "):
                current["branch"] = line[len("branch ") :]
            elif line == "detached":
                current["branch"] = "detached"
            elif line == "locked":
                current["locked"] = "true"
            elif line == "prunable":
                current["prunable"] = "true"

        if current:
            entries.append(current)

        return entries


__all__ = [
    "DEFAULT_WORKTREE_ROOT_NAME",
    "WorktreeManager",
    "WorktreeOperationKind",
    "WorktreeOperationResult",
    "WorktreeRecord",
    "WorktreeStatus",
]
