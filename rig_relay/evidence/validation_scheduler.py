"""Validation scheduler — lock management, coalescing, bounded parallelism.

Handles:
- Per-cache-key running lock (prevents duplicate execution)
- Lock expiry/staleness detection
- Bounded pytest xdist flag injection
- Lifecycle phase warnings
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

# ── Default schedules root ────────────────────────────────────────────

DEFAULT_SCHEDULER_ROOT = ".build/rig/validation-scheduler"

# ── Scheduler status literals ─────────────────────────────────────────

SCHEDULER_NOT_SCHEDULED: str = "not_scheduled"
SCHEDULER_QUEUED: str = "queued"
SCHEDULER_COALESCED: str = "coalesced"
SCHEDULER_RUNNING: str = "running"
SCHEDULER_COMPLETED: str = "completed"
SCHEDULER_BLOCKED_DUPLICATE: str = "blocked_duplicate"
SCHEDULER_POLICY_REFUSED: str = "policy_refused"

VALID_SCHEDULER_STATUSES: frozenset[str] = frozenset({
    SCHEDULER_NOT_SCHEDULED,
    SCHEDULER_QUEUED,
    SCHEDULER_COALESCED,
    SCHEDULER_RUNNING,
    SCHEDULER_COMPLETED,
    SCHEDULER_BLOCKED_DUPLICATE,
    SCHEDULER_POLICY_REFUSED,
})

# ── Parallel status literals ──────────────────────────────────────────

PARALLEL_DISABLED: str = "disabled"
PARALLEL_ENABLED: str = "enabled"
PARALLEL_NOT_APPLICABLE: str = "not_applicable"
PARALLEL_REFUSED: str = "refused"

VALID_PARALLEL_STATUSES: frozenset[str] = frozenset({
    PARALLEL_DISABLED,
    PARALLEL_ENABLED,
    PARALLEL_NOT_APPLICABLE,
    PARALLEL_REFUSED,
})

# ── Validation phase literals ─────────────────────────────────────────

PHASE_EDIT: str = "edit"
PHASE_PRE_REPORT: str = "pre_report"
PHASE_CLEANUP: str = "cleanup"
PHASE_FINAL: str = "final"

VALID_PHASES: frozenset[str] = frozenset({
    PHASE_EDIT,
    PHASE_PRE_REPORT,
    PHASE_CLEANUP,
    PHASE_FINAL,
})

# ── Lock constants ────────────────────────────────────────────────────

_LOCK_STALE_SECONDS: int = 300  # 5 minutes
_LOCK_HEARTBEAT_SECONDS: int = 60  # heartbeat every 60s

# ── Parallel constants ────────────────────────────────────────────────

_DEFAULT_MAX_WORKERS: int = 4
_XDIST_SHORT_FLAG_PREFIX = "-n"
_MIN_PYTEST_ARG_COUNT = 2


# ── Models ────────────────────────────────────────────────────────────


class ValidationLock(BaseModel):
    """Running lock for one cache key."""

    model_config = ConfigDict(extra="forbid")

    cache_key: str
    started_at: str
    last_heartbeat_at: str
    session_id: str | None = None
    pid: int | None = None

    def is_stale(self, max_age_seconds: int = _LOCK_STALE_SECONDS) -> bool:
        """Check if lock is stale (no heartbeat within max_age_seconds)."""
        try:
            last = datetime.fromisoformat(self.last_heartbeat_at)
            return (datetime.now(UTC) - last) > timedelta(seconds=max_age_seconds)
        except (ValueError, TypeError):
            return True


class ValidationSchedulerState(BaseModel):
    """Persistent state for the validation scheduler."""

    model_config = ConfigDict(extra="forbid")

    active_locks: dict[str, ValidationLock] = Field(default_factory=dict)


# ── Parallel policy helpers ────────────────────────────────────────────


def _has_xdist_flag(argv: list[str]) -> bool:
    """Check if argv already contains an xdist flag."""
    for arg in argv:
        if arg in {"-n", "--numprocesses", "--dist"}:
            return True
        if arg.startswith(_XDIST_SHORT_FLAG_PREFIX) and len(arg) > len(_XDIST_SHORT_FLAG_PREFIX):
            return True
    return False


def _xdist_available() -> bool:
    """Check if pytest-xdist is importable."""
    try:
        import xdist  # noqa: F401

        return True
    except ImportError:
        return False


def _is_pytest_command(argv: list[str]) -> bool:
    """Check if argv looks like a pytest invocation."""
    return len(argv) >= _MIN_PYTEST_ARG_COUNT and any("pytest" in arg for arg in argv)


def _is_focused_test(argv: list[str]) -> bool:
    """Check if argv targets a single test file."""
    for arg in argv:
        if arg.endswith(".py") and "/" in arg:
            return True
        if "::" in arg:  # pytest node ID
            return True
    return False


def _is_schema_validation(argv: list[str]) -> bool:
    """Check if argv targets schema validation."""
    return any("schema" in arg.lower() for arg in argv)


def _is_ruff_pyright(argv: list[str]) -> bool:
    """Check if argv targets ruff or pyright."""
    for arg in argv:
        if arg in {"ruff", "pyright"}:
            return True
    return False


def apply_parallel_policy(
    argv: list[str], parallel_policy: str, max_workers: int | None, distribution: str
) -> tuple[list[str], str, str | None]:
    """Apply bounded parallel policy to a command.

    Returns (modified_argv, parallel_status, warning_or_none).
    """
    modified = list(argv)
    parallel_status = PARALLEL_NOT_APPLICABLE
    warning: str | None = None

    if _is_pytest_command(argv):
        if _is_schema_validation(argv):
            warning = "schema_validation_stays_serial"
        elif _is_ruff_pyright(argv):
            pass
        elif _has_xdist_flag(argv):
            warning = "already_has_xdist_flag"
        elif parallel_policy == "disabled":
            parallel_status = PARALLEL_DISABLED
        elif parallel_policy != "force" and _is_focused_test(argv):
            warning = "focused_test_stays_serial"
        elif not _xdist_available():
            parallel_status = PARALLEL_REFUSED
            warning = "pytest_xdist_not_available"
        else:
            effective_workers = max_workers or min(
                _DEFAULT_MAX_WORKERS, os.cpu_count() or 1
            )
            insert_at = 1 if len(modified) > 1 else len(modified)
            modified[insert_at:insert_at] = [
                "-n",
                str(effective_workers),
                "--dist",
                distribution,
            ]
            parallel_status = PARALLEL_ENABLED
    return modified, parallel_status, warning


# ── Lifecycle phase warnings ──────────────────────────────────────────


def check_lifecycle_policy(
    validation_phase: str, profile: str, argv: list[str]
) -> list[str]:
    """Emit warnings based on validation phase and request scope.

    Returns list of warning strings.
    """
    warnings: list[str] = []

    is_full_suite = profile in {"full", "python", "schemas"} or any(
        "pytest" in arg for arg in argv
    )

    if validation_phase == PHASE_EDIT and is_full_suite:
        warnings.append("full_suite_during_edit_phase")

    return warnings


# ── Lock store ────────────────────────────────────────────────────────


class ValidationSchedulerStore:
    """File-backed lock store for the validation scheduler.

    Each lock is stored as a JSON file under scheduler_root/locks/<prefix>/
    named by cache_key hash.
    """

    def __init__(self, scheduler_root: str | Path | None = None) -> None:
        self._root = (
            Path(scheduler_root) if scheduler_root else Path(DEFAULT_SCHEDULER_ROOT)
        )

    def _lock_path(self, cache_key: str) -> Path:
        suffix = cache_key.removeprefix("sha256:")
        if not suffix:
            import hashlib

            suffix = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        prefix = suffix[:2]
        return self._root / "locks" / prefix / f"{suffix}.lock.json"

    def acquire_lock(
        self, cache_key: str, session_id: str | None = None
    ) -> tuple[bool, str | None]:
        """Try to acquire a running lock.

        Returns (acquired, blocking_cache_key_or_none).
        """
        path = self._lock_path(cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                lock = ValidationLock.model_validate(data)
                if not lock.is_stale():
                    return False, cache_key
            except (json.JSONDecodeError, ValueError):
                pass  # Stale/corrupt → overwrite

        lock = ValidationLock(
            cache_key=cache_key,
            started_at=datetime.now(UTC).isoformat(),
            last_heartbeat_at=datetime.now(UTC).isoformat(),
            session_id=session_id,
            pid=os.getpid(),
        )
        path.write_text(
            json.dumps(lock.model_dump(mode="json"), indent=2), encoding="utf-8"
        )
        return True, None

    def has_active_lock(self, cache_key: str) -> bool:
        """Check if a non-stale lock exists for this key."""
        path = self._lock_path(cache_key)
        if not path.is_file():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            lock = ValidationLock.model_validate(data)
            return not lock.is_stale()
        except (json.JSONDecodeError, ValueError):
            return False

    def release_lock(self, cache_key: str) -> bool:
        """Release a running lock. Returns True if released."""
        path = self._lock_path(cache_key)
        if path.is_file():
            path.unlink()
            return True
        return False

    def _release_stale_locks_in_prefix(
        self, prefix_dir: Path, max_age_seconds: int
    ) -> int:
        if not prefix_dir.is_dir():
            return 0
        count = 0
        for f in prefix_dir.iterdir():
            if f.suffix != ".json":
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                lock = ValidationLock.model_validate(data)
                if lock.is_stale(max_age_seconds=max_age_seconds):
                    f.unlink()
                    count += 1
            except (json.JSONDecodeError, ValueError):
                f.unlink()
                count += 1
        return count

    def release_stale_locks(self, max_age_seconds: int = _LOCK_STALE_SECONDS) -> int:
        """Release all stale locks. Returns count released."""
        locks_dir = self._root / "locks"
        if not locks_dir.is_dir():
            return 0
        count = 0
        for prefix_dir in locks_dir.iterdir():
            count += self._release_stale_locks_in_prefix(prefix_dir, max_age_seconds)
        return count

    def _count_active_locks_in_prefix(self, prefix_dir: Path) -> int:
        if not prefix_dir.is_dir():
            return 0
        count = 0
        for f in prefix_dir.iterdir():
            if f.suffix != ".json":
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                lock = ValidationLock.model_validate(data)
                if not lock.is_stale():
                    count += 1
            except (json.JSONDecodeError, ValueError):
                pass
        return count

    @property
    def active_lock_count(self) -> int:
        """Count of non-stale locks."""
        locks_dir = self._root / "locks"
        if not locks_dir.is_dir():
            return 0
        count = 0
        for prefix_dir in locks_dir.iterdir():
            count += self._count_active_locks_in_prefix(prefix_dir)
        return count


# ── Helper: default cache root resolution ──────────────────────────────


def resolve_cache_root(cache_root: str | None, workspace_root: str | None) -> Path:
    """Resolve the effective cache root path."""
    if cache_root:
        return Path(cache_root)
    if workspace_root:
        return Path(workspace_root) / ".build" / "rig" / "validation-cache"
    return Path(".build/rig/validation-cache")


def resolve_scheduler_root(
    scheduler_root: str | None, workspace_root: str | None
) -> Path:
    """Resolve the effective scheduler root path."""
    if scheduler_root:
        return Path(scheduler_root)
    if workspace_root:
        return Path(workspace_root) / ".build" / "rig" / "validation-scheduler"
    return Path(".build/rig/validation-scheduler")


__all__ = [
    "DEFAULT_SCHEDULER_ROOT",
    "PARALLEL_DISABLED",
    "PARALLEL_ENABLED",
    "PARALLEL_NOT_APPLICABLE",
    "PARALLEL_REFUSED",
    "PHASE_CLEANUP",
    "PHASE_EDIT",
    "PHASE_FINAL",
    "PHASE_PRE_REPORT",
    "SCHEDULER_BLOCKED_DUPLICATE",
    "SCHEDULER_COALESCED",
    "SCHEDULER_COMPLETED",
    "SCHEDULER_NOT_SCHEDULED",
    "SCHEDULER_POLICY_REFUSED",
    "SCHEDULER_QUEUED",
    "SCHEDULER_RUNNING",
    "VALID_PARALLEL_STATUSES",
    "VALID_PHASES",
    "VALID_SCHEDULER_STATUSES",
    "ValidationLock",
    "ValidationSchedulerState",
    "ValidationSchedulerStore",
    "apply_parallel_policy",
    "check_lifecycle_policy",
    "resolve_cache_root",
    "resolve_scheduler_root",
]
