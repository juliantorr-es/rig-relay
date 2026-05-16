"""Validation cache — strict content-light cache records for validate checks.

Cache key includes check name/kind, normalized command fingerprint, cwd,
input file fingerprints (pyproject.toml, uv.lock, pytest config, schemas),
Python version, tool versions. Not git HEAD alone.

Reuse policy:
  - passed results reused by default
  - failed results written but NOT reused unless allow_failed_cache_reuse=true
  - corrupt/invalid record causes rerun
  - changed input causes rerun
  - force_rerun bypasses cache
  - disabled bypasses cache
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import platform
import subprocess

from pydantic import BaseModel, ConfigDict, Field

# ── Default cache root (project-local) ────────────────────────────────

DEFAULT_CACHE_ROOT = ".build/rig/validation-cache"

# ── Cache key path constants ──────────────────────────────────────────

_KNOWN_CONFIG_FILES: tuple[str, ...] = (
    "pyproject.toml",
    "uv.lock",
    "pytest.ini",
    "setup.cfg",
    "tox.ini",
)
_SCHEMA_DIR = "docs/schemas"


# ── Cache status literals ─────────────────────────────────────────────

CACHE_STATUS_DISABLED: str = "disabled"
CACHE_STATUS_HIT: str = "hit"
CACHE_STATUS_MISS_RAN: str = "miss_ran"
CACHE_STATUS_MISS_CHANGED_INPUTS: str = "miss_changed_inputs"
CACHE_STATUS_MISS_MISSING_RECORD: str = "miss_missing_record"
CACHE_STATUS_MISS_FAILED_REUSE_DISABLED: str = "miss_failed_reuse_disabled"
CACHE_STATUS_MISS_FORCE_RERUN: str = "miss_force_rerun"
CACHE_STATUS_BLOCKED_RUNNING: str = "blocked_running"
CACHE_STATUS_ERROR: str = "error"

VALID_CACHE_STATUSES: frozenset[str] = frozenset({
    CACHE_STATUS_DISABLED,
    CACHE_STATUS_HIT,
    CACHE_STATUS_MISS_RAN,
    CACHE_STATUS_MISS_CHANGED_INPUTS,
    CACHE_STATUS_MISS_MISSING_RECORD,
    CACHE_STATUS_MISS_FAILED_REUSE_DISABLED,
    CACHE_STATUS_MISS_FORCE_RERUN,
    CACHE_STATUS_BLOCKED_RUNNING,
    CACHE_STATUS_ERROR,
})

# ── Cache policy literals ──────────────────────────────────────────────

CACHE_POLICY_ENABLED: str = "enabled"
CACHE_POLICY_DISABLED: str = "disabled"
CACHE_POLICY_FORCE_RERUN: str = "force_rerun"

VALID_CACHE_POLICIES: frozenset[str] = frozenset({
    CACHE_POLICY_ENABLED,
    CACHE_POLICY_DISABLED,
    CACHE_POLICY_FORCE_RERUN,
})


# ── Models ────────────────────────────────────────────────────────────


class ValidationCacheRequest(BaseModel):
    """Request to look up or create a cache record for one validate check."""

    model_config = ConfigDict(extra="forbid")

    check_id: str
    command_kind: str
    command_fingerprint: str
    cwd: str
    repo_root: str | None = None


class ValidationCacheRecord(BaseModel):
    """Persistent cache record for one validate check run.

    Contains no raw stdout/stderr — only hashes, counts, statuses,
    fingerprints, and metadata.
    """

    model_config = ConfigDict(extra="forbid")

    # ── Identity ──────────────────────────────────────────────
    cache_key: str
    check_id: str
    command_kind: str
    command_fingerprint: str

    # ── Input fingerprint ─────────────────────────────────────
    input_fingerprint: str
    input_file_fingerprints: dict[str, str] = Field(default_factory=dict)

    # ── Result ────────────────────────────────────────────────
    status: str
    exit_code: int | None = None
    duration_ms: float | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    stdout_bytes: int | None = None
    stderr_bytes: int | None = None
    failure_kind: str | None = None

    # ── Metadata ──────────────────────────────────────────────
    created_at: str = ""
    validation_phase: str | None = None
    worker_count: int | None = None
    distribution: str | None = None
    schema_version: str = "rig.relay.validate_cache_record.v1"

    # ── Warnings ──────────────────────────────────────────────
    warnings: list[str] = Field(default_factory=list)

    def is_passed(self) -> bool:
        return self.status == "passed"

    def is_stale(self, max_age_hours: int = 4) -> bool:
        """Check if record is older than max_age_hours."""
        if not self.created_at:
            return True
        try:
            created = datetime.fromisoformat(self.created_at)
            return (datetime.now(UTC) - created) > timedelta(hours=max_age_hours)
        except (ValueError, TypeError):
            return True

    def record_sha256(self) -> str:
        """Content hash of the record for integrity verification."""
        canonical = self.model_dump(mode="json", exclude={"created_at"})
        raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ValidationCacheLookupResult(BaseModel):
    """Result of a cache lookup for one check."""

    model_config = ConfigDict(extra="forbid")

    cache_status: str = CACHE_STATUS_DISABLED
    cache_key: str | None = None
    input_fingerprint: str | None = None
    record: ValidationCacheRecord | None = None
    record_sha256: str | None = None
    reused_from: str | None = None
    error: str | None = None


# ── Cache key computation ──────────────────────────────────────────────


def _file_fingerprint(path: Path) -> str:
    """Compute SHA256 of a file's content. Returns empty string if missing."""
    if not path.is_file():
        return ""
    try:
        data = path.read_bytes()
        return hashlib.sha256(data).hexdigest()
    except (OSError, PermissionError):
        return ""


@lru_cache(maxsize=8)
def _tool_version(binary: str) -> str:
    """Get version string for a tool. Returns empty string if unavailable."""
    try:
        result = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=10
        )
        return hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()[:16]
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return ""


def _schema_fingerprints(root: Path) -> list[str]:
    schema_dir = root / _SCHEMA_DIR
    if not schema_dir.is_dir():
        return []
    schema_fps: list[str] = []
    try:
        for path in sorted(schema_dir.iterdir()):
            if path.suffix == ".json" and path.is_file():
                sfp = _file_fingerprint(path)
                if sfp:
                    schema_fps.append(sfp)
    except (OSError, ValueError):
        return []
    return schema_fps


def compute_input_fingerprint(
    repo_root: str | None, command_fingerprint: str, command_kind: str
) -> tuple[str, dict[str, str]]:
    """Compute a composite input fingerprint for cache invalidation.

    Includes:
    - command fingerprint
    - pyproject.toml, uv.lock, pytest config files if present
    - docs/schemas files for schema validation
    - Python version
    - tool versions (pytest, ruff, pyright)
    - cwd

    Returns (composite_fingerprint, file_fingerprints_dict).
    """
    parts: list[str] = [command_fingerprint]
    file_fps: dict[str, str] = {}

    root = Path(repo_root) if repo_root else Path.cwd()

    # Config files
    for cfg in _KNOWN_CONFIG_FILES:
        cfg_path = root / cfg
        fp = _file_fingerprint(cfg_path)
        if fp:
            file_fps[cfg] = fp
            parts.append(f"{cfg}:{fp}")

    # Schema files for schema validation
    if command_kind == "schema":
        schema_fps = _schema_fingerprints(root)
        if schema_fps:
            for p in sorted((root / _SCHEMA_DIR).iterdir()):
                if p.suffix == ".json" and p.is_file():
                    sfp = _file_fingerprint(p)
                    if sfp:
                        file_fps[str(p.relative_to(root))] = sfp
            combined = hashlib.sha256("".join(schema_fps).encode("utf-8")).hexdigest()
            parts.append(f"schemas:{combined}")

    # Python version
    py_ver = platform.python_version()
    parts.append(f"python:{py_ver}")

    # Tool versions (cheap)
    for tool in ("pytest", "ruff", "pyright"):
        tv = _tool_version(tool)
        if tv:
            parts.append(f"{tool}:{tv}")

    # cwd
    parts.append(f"cwd:{root.resolve()}")

    composite = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return composite, file_fps


def compute_cache_key(
    check_id: str,
    command_kind: str,
    command_fingerprint: str,
    input_fingerprint: str,
    cwd: str,
    repo_root: str | None = None,
) -> str:
    """Compute a deterministic cache key for a check run.

    Key components:
    - check_id and command_kind
    - normalized command fingerprint
    - input fingerprint (files, tools, python version)
    - cwd/repo_root
    """
    parts = [
        f"check:{check_id}",
        f"kind:{command_kind}",
        f"cmd:{command_fingerprint}",
        f"input:{input_fingerprint}",
        f"cwd:{cwd}",
    ]
    if repo_root:
        parts.append(f"root:{repo_root}")
    raw = "|".join(parts)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Cache store ────────────────────────────────────────────────────────


class ValidationCacheStore:
    """File-backed validation cache store.

    Each cache record is stored as a JSON file under cache_root/<prefix>/
    named by cache_key hash. Content-light: no raw stdout/stderr.
    """

    def __init__(self, cache_root: str | Path | None = None) -> None:
        self._root = Path(cache_root) if cache_root else Path(DEFAULT_CACHE_ROOT)

    def _record_path(self, cache_key: str) -> Path:
        """Compute filesystem path for a cache key."""
        # Use the sha256 suffix after "sha256:" if present
        suffix = cache_key.removeprefix("sha256:")
        if not suffix:
            suffix = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        prefix = suffix[:2]
        return self._root / "records" / prefix / f"{suffix}.json"

    def lookup(self, cache_key: str) -> ValidationCacheLookupResult:
        """Look up a cache record by key. Returns lookup result."""
        path = self._record_path(cache_key)
        if not path.is_file():
            return ValidationCacheLookupResult(
                cache_status=CACHE_STATUS_MISS_MISSING_RECORD, cache_key=cache_key
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            record = ValidationCacheRecord.model_validate(data)
            computed_sha = record.record_sha256()
            return ValidationCacheLookupResult(
                cache_status=CACHE_STATUS_HIT,
                cache_key=cache_key,
                input_fingerprint=record.input_fingerprint,
                record=record,
                record_sha256=computed_sha,
            )
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            return ValidationCacheLookupResult(
                cache_status=CACHE_STATUS_MISS_MISSING_RECORD,
                cache_key=cache_key,
                error=f"corrupt_cache_record: {exc}",
            )

    def store(self, record: ValidationCacheRecord) -> Path:
        """Persist a cache record. Returns the path written."""
        path = self._record_path(record.cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = record.model_dump(mode="json")
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def delete(self, cache_key: str) -> bool:
        """Delete a cache record. Returns True if deleted."""
        path = self._record_path(cache_key)
        if path.is_file():
            path.unlink()
            return True
        return False

    def clear_all(self) -> int:
        """Delete all cache records. Returns count deleted."""
        records_dir = self._root / "records"
        if not records_dir.is_dir():
            return 0
        count = 0
        for prefix_dir in records_dir.iterdir():
            if prefix_dir.is_dir():
                for f in prefix_dir.iterdir():
                    if f.suffix == ".json":
                        f.unlink()
                        count += 1
        return count

    @property
    def root(self) -> Path:
        return self._root


def decide_cache_eligibility(
    cache_policy: str, lookup: ValidationCacheLookupResult, allow_failed_reuse: bool
) -> tuple[str, str | None]:
    """Decide whether to use a cached result or run.

    Returns (cache_status, reason_or_none).
    """
    status = CACHE_STATUS_DISABLED
    reason: str | None = None
    if cache_policy == CACHE_POLICY_FORCE_RERUN:
        status = CACHE_STATUS_MISS_FORCE_RERUN
        reason = "force_rerun_policy"
    elif cache_policy == CACHE_POLICY_DISABLED:
        status = CACHE_STATUS_DISABLED
    elif (
        lookup.cache_status == CACHE_STATUS_MISS_MISSING_RECORD or lookup.record is None
    ):
        status = CACHE_STATUS_MISS_MISSING_RECORD
    elif lookup.record.is_passed():
        status = CACHE_STATUS_HIT
    elif allow_failed_reuse:
        status = CACHE_STATUS_HIT
        reason = "reused_failed_result"
    else:
        status = CACHE_STATUS_MISS_FAILED_REUSE_DISABLED
        reason = "failed_result_not_reused"
    return status, reason


__all__ = [
    "CACHE_POLICY_DISABLED",
    "CACHE_POLICY_ENABLED",
    "CACHE_POLICY_FORCE_RERUN",
    "CACHE_STATUS_BLOCKED_RUNNING",
    "CACHE_STATUS_DISABLED",
    "CACHE_STATUS_ERROR",
    "CACHE_STATUS_HIT",
    "CACHE_STATUS_MISS_CHANGED_INPUTS",
    "CACHE_STATUS_MISS_FAILED_REUSE_DISABLED",
    "CACHE_STATUS_MISS_FORCE_RERUN",
    "CACHE_STATUS_MISS_MISSING_RECORD",
    "CACHE_STATUS_MISS_RAN",
    "DEFAULT_CACHE_ROOT",
    "VALID_CACHE_POLICIES",
    "VALID_CACHE_STATUSES",
    "ValidationCacheLookupResult",
    "ValidationCacheRecord",
    "ValidationCacheRequest",
    "ValidationCacheStore",
    "compute_cache_key",
    "compute_input_fingerprint",
    "decide_cache_eligibility",
]
