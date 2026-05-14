"""Rig Relay ExecutionLease Model and Store — Ported from Rig domain/execution/models.py.

Defines the time-bounded authorization to execute a command in a workspace/worktree lane.
Provides a file-backed store for lease persistence with TTL enforcement.

Provenance (Rig-to-Relay porting doctrine):
  Porting status: reimplement (Rig source: rig/domain/execution/models.py).
  Adaptations: Pydantic BaseModel with extra="forbid" instead of frozen dataclass;
  relay-native status vocabulary (ExecutionLeaseStatus); standalone file-backed store
  (not embedded in CoordinationStore); explicit state-machine transitions on acquire/release/expire.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from rig_relay.coordination._canonical_json import dump_canonical_json
from rig_relay.runtime.execution_request import ExecutionRequest

# ── Constants ──────────────────────────────────────────────────────────

_SCHEMA_VERSION = "rig.relay.execution_lease.v1"
_SCHEMA_VERSION_RESULT = "rig.relay.execution_lease_result.v1"

# ── Enums ──────────────────────────────────────────────────────────────


class ExecutionLeaseStatus(StrEnum):
    """Status of an execution lease lifecycle.

    Ordering: pending → active → (released | expired | cancelled | failed).
    """

    PENDING = "pending"
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ── Models ──────────────────────────────────────────────────────────────


class ExecutionLease(BaseModel):
    """Time-bounded authorization to execute a specific ExecutionRequest.

    A lease represents the right to execute a bound command in a workspace/worktree lane.
    It is acquired before execution starts, has a TTL, and must be released on completion
    or auto-expired after the TTL passes.

    Content-light: no raw output, no command transcript beyond argv list,
    no environment secrets beyond explicitly provided env_overlay.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION
    lease_id: str
    request: ExecutionRequest
    workspace_id: str | None = None
    worktree_path: str | None = None
    acquired_at: str
    expires_at: str
    released_at: str | None = None
    status: ExecutionLeaseStatus
    refusal_reason: str | None = None
    error_kind: str | None = None


class ExecutionLeaseResult(BaseModel):
    """Result of a lease operation (acquire, release, etc.).

    Carries the lease if successful, or structured error information otherwise.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION_RESULT
    status: str  # "granted" | "released" | "already_released" | "already_expired" | "not_found" | "error"
    lease: ExecutionLease | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None


# ── Store ──────────────────────────────────────────────────────────────


def _validate_lease_id(lease_id: str) -> None:
    """Reject lease_id values that could escape the lease directory."""
    if not lease_id:
        raise ValueError("lease_id must be non-empty")
    if lease_id.startswith("."):
        raise ValueError(f"lease_id must not start with '.': {lease_id!r}")
    if "/" in lease_id or "\\" in lease_id:
        raise ValueError(f"lease_id must not contain path separators: {lease_id!r}")


def _now_str() -> str:
    return datetime.now(UTC).isoformat()


class ExecutionLeaseStore:
    """File-backed store for execution leases.

    Leases are persisted as individual JSON files under a configurable root directory.
    Filenames are derived from lease_id (with path-traversal protection).
    Uses atomic write via temp-file + replace pattern.

    No SQLite. No coordination store coupling. Content-light only.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True)

    def _lease_path(self, lease_id: str) -> Path:
        _validate_lease_id(lease_id)
        return self._root / f"{lease_id}.json"

    def _write_lease(self, lease: ExecutionLease) -> None:
        path = self._lease_path(lease.lease_id)
        text = dump_canonical_json(lease.model_dump(exclude_none=True))
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)

    def _read_lease(self, lease_id: str) -> ExecutionLease | None:
        path = self._lease_path(lease_id)
        if not path.is_file():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            return ExecutionLease.model_validate_json(raw)
        except (json.JSONDecodeError, ValueError, KeyError):
            return None

    def acquire(
        self,
        request: ExecutionRequest,
        ttl_seconds: int,
        enforce_exclusive_worktree: bool = True,
    ) -> ExecutionLeaseResult:
        """Acquire a new execution lease for the given request.

        Creates an active lease with expires_at = now + ttl_seconds.
        Returns a structured result with the lease on success.

        When enforce_exclusive_worktree is True (default), refuses if an
        ACTIVE (non-expired) lease already exists for the same worktree_path
        or (if worktree_path is absent) the same workspace_id.
        """
        if ttl_seconds <= 0:
            return ExecutionLeaseResult(
                status="error",
                error_kind="invalid_ttl",
                refusal_reason=f"ttl_seconds must be positive, got {ttl_seconds}",
            )

        # ── Check for conflicting active leases ─────────────────────
        if enforce_exclusive_worktree:
            candidate_wt = request.worktree_path
            candidate_ws = request.workspace_id
            now = datetime.now(UTC)

            for existing in self._iter_leases():
                if existing.status != ExecutionLeaseStatus.ACTIVE:
                    continue
                # Skip expired leases
                try:
                    expires = datetime.fromisoformat(
                        existing.expires_at.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    continue
                if expires <= now:
                    continue

                # Check worktree_path conflict
                if candidate_wt and existing.worktree_path == candidate_wt:
                    return ExecutionLeaseResult(
                        status="refused",
                        error_kind="active_worktree_lease_exists",
                        refusal_reason=(
                            f"Active lease {existing.lease_id} already exists"
                            f" for worktree_path={candidate_wt!r}"
                        ),
                    )

                # Check workspace_id conflict when worktree_path absent
                if (
                    not candidate_wt
                    and candidate_ws
                    and existing.workspace_id == candidate_ws
                ):
                    return ExecutionLeaseResult(
                        status="refused",
                        error_kind="active_workspace_lease_exists",
                        refusal_reason=(
                            f"Active lease {existing.lease_id} already exists"
                            f" for workspace_id={candidate_ws!r}"
                        ),
                    )

        now = _now_str()
        expires = (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()

        lease = ExecutionLease(
            lease_id=request.request_id,
            request=request,
            workspace_id=request.workspace_id,
            worktree_path=request.worktree_path,
            acquired_at=now,
            expires_at=expires,
            released_at=None,
            status=ExecutionLeaseStatus.ACTIVE,
            refusal_reason=None,
            error_kind=None,
        )

        self._write_lease(lease)
        return ExecutionLeaseResult(status="granted", lease=lease)

    def read(self, lease_id: str) -> ExecutionLease | None:
        """Read a lease by ID. Returns None if not found or malformed."""
        return self._read_lease(lease_id)

    def release(self, lease_id: str) -> ExecutionLeaseResult:
        """Release an active lease.

        State transitions:
        - active → released (sets released_at)
        - expired → already_expired (no mutation)
        - released → already_released (no mutation)
        - cancelled → already_released (no mutation)
        - failed → already_released (no mutation)
        - not found → not_found (no mutation)
        """
        lease = self._read_lease(lease_id)
        if lease is None:
            return ExecutionLeaseResult(
                status="not_found",
                error_kind="lease_not_found",
                refusal_reason=f"No lease found for lease_id={lease_id!r}",
            )

        if lease.status == ExecutionLeaseStatus.EXPIRED:
            return ExecutionLeaseResult(
                status="already_expired",
                lease=lease,
                error_kind="lease_already_expired",
                refusal_reason=f"Lease {lease_id!r} already expired at {lease.expires_at}",
            )

        if lease.status in {
            ExecutionLeaseStatus.RELEASED,
            ExecutionLeaseStatus.CANCELLED,
            ExecutionLeaseStatus.FAILED,
        }:
            return ExecutionLeaseResult(
                status="already_released",
                lease=lease,
                error_kind="lease_already_released",
                refusal_reason=f"Lease {lease_id!r} already {lease.status}",
            )

        # Active → released
        lease.released_at = _now_str()
        lease.status = ExecutionLeaseStatus.RELEASED
        self._write_lease(lease)
        return ExecutionLeaseResult(status="released", lease=lease)

    def expire_stale(self, now: datetime | None = None) -> list[ExecutionLease]:
        """Mark all active leases as expired when now >= expires_at.

        Returns the list of leases that were expired. Non-mutating for
        already-expired, released, cancelled, or failed leases.
        """
        cutoff = now if now is not None else datetime.now(UTC)
        expired: list[ExecutionLease] = []

        for lease in self._iter_leases():
            try:
                expires = datetime.fromisoformat(
                    lease.expires_at.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                continue

            if lease.status == ExecutionLeaseStatus.ACTIVE and expires <= cutoff:
                lease.status = ExecutionLeaseStatus.EXPIRED
                self._write_lease(lease)
                expired.append(lease)

        return expired

    def list_leases(self) -> list[ExecutionLease]:
        """Return all leases sorted by lease_id."""
        return sorted(self._iter_leases(), key=lambda l: l.lease_id)

    def _iter_leases(self) -> list[ExecutionLease]:
        leases: list[ExecutionLease] = []
        for lease_path in sorted(self._root.glob("*.json")):
            try:
                raw = lease_path.read_text(encoding="utf-8")
                leases.append(ExecutionLease.model_validate_json(raw))
            except (json.JSONDecodeError, ValueError, KeyError):
                continue
        return leases


__all__ = [
    "ExecutionLease",
    "ExecutionLeaseResult",
    "ExecutionLeaseStatus",
    "ExecutionLeaseStore",
]
