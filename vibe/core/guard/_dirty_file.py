from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import subprocess
from typing import ClassVar

from vibe.core.logger import logger


@dataclass(frozen=True)
class DirtyFileSnapshot:
    """Immutable snapshot of a single dirty file at mission start."""

    relative_path: str
    index_status: str  # XY from porcelain: ' M', 'A ', '??', etc.
    worktree_status: str
    is_untracked: bool
    is_conflicted: bool
    blob_before_sha256: str | None  # sha256:<hex> of file bytes, None if untracked (no git blob)
    file_bytes_sha256: str | None  # sha256:<hex> of file bytes, None if file didn't exist


@dataclass
class DirtyFileGuard:
    """Captures dirty file state at mission start and gates write operations.

    Singleton lifecycle — call ``get_guard()`` to obtain the instance.
    Use ``reset_guard()`` in tests.
    """

    dirty_snapshots: dict[str, DirtyFileSnapshot] = field(default_factory=dict)
    _captured: bool = False
    _repo_root: Path | None = None

    _STATUS_LINE_PATH_OFFSET: ClassVar[int] = 3

    # ── public API ──────────────────────────────────────────────

    def capture(self) -> None:
        """Run ``git status --porcelain=v1`` and hash every dirty file."""
        if self._captured:
            return

        self._repo_root = Path.cwd().resolve()
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
            logger.warning("DirtyFileGuard: git status failed: %s", exc)
            self._captured = True
            return

        for line in result.stdout.splitlines():
            snapshot = self._parse_line(line)
            if snapshot is not None:
                self.dirty_snapshots[snapshot.relative_path] = snapshot

        self._captured = True

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

    def check_write_file(
        self,
        path: str | Path,
        *,
        allow_overwrite_protected: bool = False,
        expected_before_sha256: str | None = None,
    ) -> WriteGuardResult:
        """Check whether a ``write_file`` operation should proceed.

        Returns:
            WriteGuardResult with ``allowed`` and a structured reason.
        """
        self.capture()
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

    def check_search_replace(
        self,
        path: str | Path,
        *,
        expected_before_sha256: str | None = None,
    ) -> WriteGuardResult:
        """Check whether a ``search_replace`` operation on a protected file should proceed."""
        self.capture()
        key = self._normalize_path(path)
        snapshot = self.dirty_snapshots.get(key)

        if snapshot is None:
            return WriteGuardResult(allowed=True, reason="file_was_clean")

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

    def blocked_git_commands(self) -> frozenset[str]:
        """Return the set of destructive git commands blocked by the guard."""
        return frozenset(
            {
                "git restore",
                "git checkout",
                "git reset",
                "git clean",
                "git stash",
            }
        )

    def is_destructive_git_command(self, command: str) -> tuple[bool, str | None]:
        """Check if *command* is a blocked destructive git operation.

        Returns:
            (is_blocked, reason) — reason is None if not blocked.
        """
        stripped = command.strip()
        for blocked in self.blocked_git_commands():
            if stripped == blocked or stripped.startswith(blocked + " "):
                return True, (
                    f"'{blocked}' is a destructive git command that would discard "
                    "changes to protected files. Use built-in git tools or ask the "
                    "user to perform this operation manually."
                )
        return False, None

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

        # Handle rename: "R  old -> new"
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
