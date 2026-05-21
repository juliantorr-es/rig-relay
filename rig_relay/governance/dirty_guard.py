"""Rig Relay Dirty-File Guard — Governance Seam.

Owned by ``rig_relay.governance``. Legacy adapter at ``vibe.core.guard``.

Provides dirty-file snapshot/capture and write-protection logic for
guarding pre-existing user and parallel-agent changes during mission execution.

Usage:
    from rig_relay.governance.dirty_guard import (
        DirtyFileGuard, DirtyFileSnapshot, WriteGuardResult,
        DirtyGuardFailurePolicy, GuardCaptureReason,
        get_guard, reset_guard,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum, auto
import hashlib
import logging
from pathlib import Path
import subprocess
from typing import ClassVar
from uuid import uuid4

logger = logging.getLogger(__name__)


class DirtyGuardFailurePolicy(StrEnum):
    WARN_ALLOW = auto()
    FAIL_CLOSED_FOR_MUTATION = auto()


class GuardCaptureReason(StrEnum):
    AGENT_LOOP_INIT = "agent_loop_init"
    RESET_SESSION = "reset_session"
    FORK_CHILD = "fork_child"
    MANUAL_RECAPTURE = "manual_recapture"


@dataclass(frozen=True)
class DirtyFileSnapshot:
    """Immutable snapshot of a single dirty file at mission start."""

    relative_path: str
    index_status: str
    worktree_status: str
    is_untracked: bool
    is_conflicted: bool
    blob_before_sha256: str | None
    file_bytes_sha256: str | None


@dataclass
class DirtyFileGuard:
    """Captures dirty file state at mission start and gates write operations.

    Singleton lifecycle — call ``get_guard()`` to obtain the instance.
    Use ``reset_guard()`` in tests.
    """

    dirty_snapshots: dict[str, DirtyFileSnapshot] = field(default_factory=dict)
    _captured: bool = False
    _capture_failed: bool = False
    _repo_root: Path | None = None
    _capture_error: str | None = None

    # ── snapshot identity ────────────────────────────────────────

    baseline_id: str = ""
    captured_at: str | None = None
    capture_reason: GuardCaptureReason = GuardCaptureReason.AGENT_LOOP_INIT
    parent_baseline_id: str | None = None

    # ── failure policy ───────────────────────────────────────────

    failure_policy: DirtyGuardFailurePolicy = DirtyGuardFailurePolicy.WARN_ALLOW

    # ── mission tracking ────────────────────────────────────────

    touched_files: set[str] = field(default_factory=set)
    skipped_files: dict[str, str] = field(default_factory=dict)
    refused_writes: list[dict[str, str]] = field(default_factory=list)

    _STATUS_LINE_PATH_OFFSET: ClassVar[int] = 3
    _OPTIONS_CONSUMING_ARG: ClassVar[frozenset[str]] = frozenset({
        "-c",
        "-C",
        "--git-dir",
        "--work-tree",
        "--namespace",
        "--exec-path",
    })
    _idempotent_key: str = ""

    # ── public API ──────────────────────────────────────────────

    def capture(
        self,
        repo_root: Path | None = None,
        *,
        reason: GuardCaptureReason = GuardCaptureReason.AGENT_LOOP_INIT,
        failure_policy: DirtyGuardFailurePolicy | None = None,
        parent_baseline_id: str | None = None,
    ) -> None:
        """Run ``git status --porcelain=v1`` and hash every dirty file.

        Idempotent within the same baseline — subsequent calls are no-ops
        unless ``recapture()`` was called first.

        Args:
            repo_root: Override for the repo root. Defaults to ``Path.cwd()``.
            reason: Why this capture is happening.
            failure_policy: Override the guard's failure policy for this capture.
            parent_baseline_id: Parent baseline for child/fork sessions.
        """
        if self._captured:
            return

        self._repo_root = (repo_root or Path.cwd()).resolve()
        self.capture_reason = reason
        self.parent_baseline_id = parent_baseline_id
        self.baseline_id = uuid4().hex
        self.captured_at = datetime.now(UTC).isoformat()

        if failure_policy is not None:
            self.failure_policy = failure_policy

        try:
            result = subprocess.run(
                ["git", "--no-optional-locks", "status", "--porcelain=v1"],
                capture_output=True,
                check=True,
                cwd=self._repo_root,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=10,
            )
        except Exception as exc:
            self._capture_error = str(exc)
            self._captured = False
            self._capture_failed = True
            self.baseline_id = ""
            logger.warning("DirtyFileGuard: git status failed: %s", exc)
            logger.error(
                "dirty_guard.capture_failed "
                "baseline_id= session_id= "
                "error_class=%s severity=critical",
                type(exc).__name__,
            )
            return

        for line in result.stdout.splitlines():
            snapshot = self._parse_line(line)
            if snapshot is not None:
                self.dirty_snapshots[snapshot.relative_path] = snapshot

        self._captured = True
        logger.info(
            "dirty_guard.capture succeeded baseline_id=%s dirty_file_count=%s",
            self.baseline_id,
            len(self.dirty_snapshots),
        )

    def recapture(
        self,
        repo_root: Path | None = None,
        *,
        reason: GuardCaptureReason = GuardCaptureReason.MANUAL_RECAPTURE,
        failure_policy: DirtyGuardFailurePolicy | None = None,
    ) -> None:
        """Force a new capture, generating a new baseline.

        Preserves the current baseline as ``parent_baseline_id``.
        Resets tracking counters (touched, skipped, refused).
        """
        old_baseline = self.baseline_id
        self.dirty_snapshots.clear()
        self.touched_files.clear()
        self.skipped_files.clear()
        self.refused_writes.clear()
        self._captured = False
        self._capture_error = None
        self.baseline_id = ""
        self.captured_at = None
        self.capture(
            repo_root=repo_root,
            reason=reason,
            failure_policy=failure_policy,
            parent_baseline_id=old_baseline if old_baseline else None,
        )

    @property
    def capture_succeeded(self) -> bool:
        return (
            self._captured and not self._capture_failed and self._capture_error is None
        )

    @property
    def capture_failed(self) -> bool:
        return self._capture_failed

    def is_protected(self, path: str | Path) -> bool:
        """Return True if *path* was dirty at mission start."""
        self.capture()
        key = self._normalize_path(path)
        return key in self.dirty_snapshots

    def snapshot_for(self, path: str | Path) -> DirtyFileSnapshot | None:
        """Return the mission-start snapshot for *path*, or None."""
        self.capture()
        key = self._normalize_path(path)
        return self.dirty_snapshots.get(key)

    def _check_capture_failed(self) -> WriteGuardResult | None:
        """Return a refusal if capture failed, else None.

        Capture failure always blocks mutation writes regardless of failure_policy.
        """
        if self._capture_failed:
            return WriteGuardResult(
                allowed=False,
                reason="dirty_guard_capture_failed",
                detail=(
                    "Dirty file guard capture failed. Mutation tools are blocked. "
                    f"Capture error: {self._capture_error}"
                ),
            )
        return None

    def _verify_protected_file_hash(
        self,
        key: str,
        snapshot: DirtyFileSnapshot,
        *,
        expected_before_sha256: str | None,
    ) -> WriteGuardResult:
        """Verify expected hash for a protected file. Caller already confirmed file is dirty."""
        current_hash = self._hash_file(key)
        if current_hash is None:
            return WriteGuardResult(
                allowed=False,
                reason="protected_file_missing",
                detail=f"File '{key}' was dirty at mission start but no longer exists.",
                snapshot=snapshot,
            )

        if expected_before_sha256 is None:
            return WriteGuardResult(
                allowed=False,
                reason="protected_file_missing_expected_hash",
                detail=(
                    f"File '{key}' was dirty at mission start. "
                    "Provide expected_before_sha256 matching the current file bytes."
                ),
                snapshot=snapshot,
            )

        if expected_before_sha256 != current_hash:
            return WriteGuardResult(
                allowed=False,
                reason="protected_file_stale_hash",
                detail=(
                    f"File '{key}' bytes no longer match expected_before_sha256. "
                    f"Expected {expected_before_sha256}, current {current_hash}. "
                    "Re-read the file and apply a narrower patch preserving existing changes."
                ),
                snapshot=snapshot,
            )

        return WriteGuardResult(allowed=True, reason="protected_file_hash_matched")

    def check_write_file(
        self,
        path: str | Path,
        *,
        allow_overwrite_protected: bool = False,
        expected_before_sha256: str | None = None,
    ) -> WriteGuardResult:
        """Check whether a ``write_file`` operation should proceed."""
        self.capture()

        if refusal := self._check_capture_failed():
            return refusal

        key = self._normalize_path(path)
        snapshot = self.dirty_snapshots.get(key)

        if snapshot is None:
            return WriteGuardResult(allowed=True, reason="file_was_clean")

        if not allow_overwrite_protected:
            return WriteGuardResult(
                allowed=False,
                reason="protected_file_no_overwrite_flag",
                detail=(
                    f"File '{key}' was dirty at mission start. "
                    "Set allow_overwrite_protected=true and expected_before_sha256 "
                    "to overwrite, or use search_replace for a targeted patch."
                ),
                snapshot=snapshot,
            )

        return self._verify_protected_file_hash(
            key, snapshot, expected_before_sha256=expected_before_sha256
        )

    def check_search_replace(
        self, path: str | Path, *, expected_before_sha256: str | None = None
    ) -> WriteGuardResult:
        """Check whether a ``search_replace`` operation on a protected file should proceed."""
        self.capture()

        if refusal := self._check_capture_failed():
            return refusal

        key = self._normalize_path(path)
        snapshot = self.dirty_snapshots.get(key)

        if snapshot is None:
            return WriteGuardResult(allowed=True, reason="file_was_clean")

        return self._verify_protected_file_hash(
            key, snapshot, expected_before_sha256=expected_before_sha256
        )

    def blocked_git_commands(self) -> frozenset[str]:
        """Return the set of destructive git commands blocked by the guard."""
        return frozenset({
            "git restore",
            "git checkout",
            "git reset",
            "git clean",
            "git stash",
            "git commit --amend",
            "git push --force",
            "git push --force-with-lease",
        })

    def _parse_git_subcommand(self, command: str) -> str | None:
        """Extract effective git subcommand and args, skipping global options.

        Handles ``-c key=value``, ``-C <path>``, ``--git-dir=<path>``,
        ``--git-dir <path>``, ``--work-tree=<path>``, and other options
        that can appear before the git subcommand.
        """
        tokens = command.strip().split()
        if not tokens or tokens[0] != "git":
            return None

        i = 1
        while i < len(tokens):
            token = tokens[i]

            if token in self._OPTIONS_CONSUMING_ARG:
                i += 2
                continue

            if token.startswith("--") and "=" in token:
                i += 1
                continue

            if token.startswith("-"):
                i += 1
                continue

            break

        if i >= len(tokens):
            return None

        return "git " + " ".join(tokens[i:])

    def is_destructive_git_command(self, command: str) -> tuple[bool, str | None]:
        """Check if *command* is a blocked destructive git operation."""
        effective = self._parse_git_subcommand(command)
        if effective is None:
            return False, None

        for blocked in self.blocked_git_commands():
            if (
                effective == blocked
                or effective.startswith(blocked + " ")
                or effective.startswith(blocked + "=")
            ):
                return True, (
                    f"'{blocked}' is a destructive git command that would discard "
                    "changes to protected files. Use built-in git tools or ask the "
                    "user to perform this operation manually."
                )
        return False, None

    def mark_touched(self, path: str | Path) -> None:
        key = self._normalize_path(path)
        self.touched_files.add(key)
        self.skipped_files.pop(key, None)

    def mark_skipped(self, path: str | Path, reason: str) -> None:
        key = self._normalize_path(path)
        if key not in self.touched_files:
            self.skipped_files[key] = reason

    def record_refusal(self, path: str | Path, reason: str) -> None:
        key = self._normalize_path(path)
        self.refused_writes.append({"path": key, "reason": reason})

    def report(self) -> dict:
        """Return a structured summary of dirty-file guard activity."""
        self.capture()
        pre_existing = sorted(self.dirty_snapshots.keys())
        touched = sorted(self.touched_files)
        skipped = sorted(self.skipped_files.keys())
        return {
            "baseline_id": self.baseline_id,
            "captured_at": self.captured_at,
            "capture_reason": self.capture_reason.value,
            "parent_baseline_id": self.parent_baseline_id,
            "repo_root": str(self._repo_root) if self._repo_root else None,
            "capture_method": "git status --porcelain=v1",
            "capture_succeeded": self.capture_succeeded,
            "capture_failed": self._capture_failed,
            "capture_error": self._capture_error,
            "failure_policy": self.failure_policy.value,
            "dirty_files_before_mission": pre_existing,
            "dirty_file_count": len(pre_existing),
            "files_touched_by_mission": touched,
            "protected_files_skipped": skipped,
            "skipped_reasons": {k: self.skipped_files[k] for k in skipped},
            "refused_write_attempts": list(self.refused_writes),
        }

    # ── internal helpers ─────────────────────────────────────────

    def _normalize_path(self, path: str | Path) -> str:
        p = Path(path)
        if not p.is_absolute():
            p = (self._repo_root / p) if self._repo_root else p.resolve()
        else:
            p = p.resolve()
        try:
            return p.relative_to(self._repo_root or Path.cwd()).as_posix()
        except ValueError:
            return p.as_posix()

    def _parse_line(self, line: str) -> DirtyFileSnapshot | None:
        if not line or len(line) < self._STATUS_LINE_PATH_OFFSET:
            return None
        status = line[:2]
        raw_path = line[self._STATUS_LINE_PATH_OFFSET :]
        rel = Path(raw_path).as_posix()

        if " -> " in rel:
            rel = rel.split(" -> ")[-1]

        file_path = (self._repo_root / rel) if self._repo_root else Path(rel)
        file_bytes_hash = self._hash_path(file_path)
        blob_hash = None if status == "??" else file_bytes_hash

        return DirtyFileSnapshot(
            relative_path=rel,
            index_status=status[0],
            worktree_status=status[1],
            is_untracked=status == "??",
            is_conflicted="U" in status,
            blob_before_sha256=blob_hash,
            file_bytes_sha256=file_bytes_hash,
        )

    @staticmethod
    def _hash_path(path: Path) -> str | None:
        try:
            data = path.read_bytes()
            return f"sha256:{hashlib.sha256(data).hexdigest()}"
        except (OSError, PermissionError):
            return None

    def _hash_file(self, rel_path: str) -> str | None:
        file_path = (self._repo_root / rel_path) if self._repo_root else Path(rel_path)
        return self._hash_path(file_path)


@dataclass(frozen=True)
class WriteGuardResult:
    allowed: bool
    reason: str
    detail: str | None = None
    snapshot: DirtyFileSnapshot | None = None


# ── singleton ─────────────────────────────────────────────────────

_guard: DirtyFileGuard | None = None


def get_guard() -> DirtyFileGuard:
    global _guard
    if _guard is None:
        _guard = DirtyFileGuard()
    return _guard


def reset_guard() -> None:
    global _guard
    _guard = None


__all__ = [
    "DirtyFileGuard",
    "DirtyFileSnapshot",
    "DirtyGuardFailurePolicy",
    "GuardCaptureReason",
    "WriteGuardResult",
    "get_guard",
    "reset_guard",
]
