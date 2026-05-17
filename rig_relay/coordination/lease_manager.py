"""PathLeaseManager — runtime-facing path lease API wrapping CoordinationStore.

Provides claim_paths, release_paths, renew_lease, and query_active_leases
with exclusive_write vs shared_read semantics.

Lease semantics:
- exclusive_write blocks both read and write leases on overlapping paths.
- shared_read allows coexistence with other read leases.
- Same-owner renewal is always allowed.
- Release requires matching session_id + task_id (owner identity).
- Expired/stale leases are reported but not silently deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.coordination.store import CoordinationStore

# ── Constants ──────────────────────────────────────────────────────────

_SCHEMA_VERSION = "rig.relay.lease_manager_result.v1"

DEFAULT_LEASE_TTL_SECONDS = 120
"""Default TTL for path leases when no explicit TTL is provided.

Set to 120 seconds as a crash-recovery fallback. Tool execution should
release leases in a finally path; the TTL ensures stale leases are
reclaimed even if the holder crashes.
"""


# ── Enums ──────────────────────────────────────────────────────────────


class LeaseStatusValue(StrEnum):
    """Status strings for lease operations."""

    GRANTED = "granted"
    CONFLICT = "conflict"
    STALE = "stale"
    NOT_FOUND = "not_found"
    NOT_OWNER = "not_owner"
    ERROR = "error"


# ── Result models ──────────────────────────────────────────────────────


class PathLease(BaseModel):
    """A granted path lease — content-light copy of the reservation state."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.path_lease.v1"
    session_id: str
    task_id: str
    mode: Literal["read", "write"]
    paths: list[str] = Field(default_factory=list)
    expires_at: str
    status: str = "active"
    created_at: str = ""


class LeaseClaimResult(BaseModel):
    """Result of a lease claim operation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION
    status: (
        str  # "granted" | "conflict" | "stale" | "not_found" | "not_owner" | "error"
    )
    lease: PathLease | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None


# ── Manager ────────────────────────────────────────────────────────────


class PathLeaseManager:
    """Runtime-facing path lease manager.

    Wraps CoordinationStore with an API shaped for runtime lease acquisition
    before tool execution.

    Usage:
        manager = PathLeaseManager(coordination_root)
        result = manager.claim_paths(
            session_id="sess-1", task_id="task-1",
            mode="exclusive_write", paths=["src/main.py"],
            ttl_seconds=120,
        )
        if result.status == "granted":
            # proceed with tool execution
            ...
            manager.release_paths(session_id="sess-1", task_id="task-1", paths=["src/main.py"])
    """

    def __init__(self, coordination_root: Path) -> None:
        self._store = CoordinationStore(coordination_root)

    def claim_paths(
        self,
        *,
        session_id: str,
        task_id: str,
        mode: Literal["exclusive_write", "shared_read"],
        paths: list[str],
        ttl_seconds: int,
    ) -> LeaseClaimResult:
        """Claim a path lease.

        Args:
            session_id: Owner session.
            task_id: Owner task.
            mode: "exclusive_write" (blocks both read and write) or
                  "shared_read" (blocks write but allows other reads).
            paths: List of file paths to lease.
            ttl_seconds: Time-to-live in seconds.

        Returns:
            LeaseClaimResult with status and optional lease.
        """
        if not paths:
            return LeaseClaimResult(
                status="error",
                error_kind="no_paths",
                refusal_reason="At least one path required for lease claim",
            )

        # Map public mode to store mode
        store_mode: Literal["read", "write"] = (
            "write" if mode == "exclusive_write" else "read"
        )

        result = self._store.reserve_paths(
            session_id=session_id,
            task_id=task_id,
            mode=store_mode,
            paths=paths,
            ttl_seconds=ttl_seconds,
        )

        if not result.allowed:
            error_kind = result.conflict.kind if result.conflict else "conflict"
            return LeaseClaimResult(
                status="conflict",
                error_kind=error_kind,
                refusal_reason=(
                    result.conflict.recommended_resolution
                    if result.conflict
                    else "Path lease conflict"
                ),
            )

        reservation = result.reservation
        if reservation is None:
            return LeaseClaimResult(
                status="error",
                error_kind="missing_reservation",
                refusal_reason="Store returned success but no reservation object",
            )

        return LeaseClaimResult(
            status="granted",
            lease=PathLease(
                session_id=reservation.session_id,
                task_id=reservation.task_id,
                mode=store_mode,
                paths=reservation.paths,
                expires_at=reservation.expires_at or "",
                status=reservation.status,
                created_at=reservation.created_at,
            ),
        )

    def release_paths(
        self, *, session_id: str, task_id: str, paths: list[str]
    ) -> LeaseClaimResult:
        """Release a path lease.

        Requires matching session_id and task_id (owner identity).
        Delegates entirely to the store for digester-guarded writes.
        """
        if not paths:
            return LeaseClaimResult(
                status="not_found",
                error_kind="no_paths",
                refusal_reason="At least one path required for lease release",
            )

        try:
            self._store.release_paths(
                session_id=session_id, task_id=task_id, paths=paths
            )
        except Exception as e:
            return LeaseClaimResult(
                status="error", error_kind="release_failed", refusal_reason=str(e)
            )

        return LeaseClaimResult(status="granted")

    def renew_lease(
        self, *, session_id: str, task_id: str, paths: list[str], ttl_seconds: int
    ) -> LeaseClaimResult:
        """Renew an existing lease by extending its TTL.

        Delegates to the store, which treats same-owner reservation as renewal.
        """
        if not paths:
            return LeaseClaimResult(
                status="not_found",
                error_kind="no_paths",
                refusal_reason="At least one path required for lease renewal",
            )

        result = self._store.reserve_paths(
            session_id=session_id,
            task_id=task_id,
            mode="read",
            paths=paths,
            ttl_seconds=ttl_seconds,
        )

        if not result.allowed:
            return LeaseClaimResult(
                status="conflict",
                error_kind=result.conflict.kind if result.conflict else "conflict",
                refusal_reason=(
                    result.conflict.recommended_resolution
                    if result.conflict
                    else "Path lease conflict during renewal"
                ),
            )

        return LeaseClaimResult(status="granted")

    def query_active_leases(
        self, *, session_id: str | None = None, task_id: str | None = None
    ) -> list[PathLease]:
        """Return all active leases, optionally filtered by owner.

        Args:
            session_id: Optional filter by session.
            task_id: Optional filter by task.

        Returns:
            List of PathLease objects for active (non-expired, non-stale) leases.
        """
        now = datetime.now(UTC)
        active: list[PathLease] = []
        lease_dir = self._store.root / "leases" / "paths"

        for entry in lease_dir.glob("*.json"):
            try:
                raw = entry.read_text(encoding="utf-8")
                data = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                continue

            if data.get("status") != "active":
                continue

            if session_id and data.get("session_id") != session_id:
                continue
            if task_id and data.get("task_id") != task_id:
                continue

            expires_at = data.get("expires_at", "")
            if expires_at:
                try:
                    expires_dt = datetime.fromisoformat(
                        expires_at.replace("Z", "+00:00")
                    )
                    if expires_dt < now:
                        continue  # expired, skip
                except (ValueError, TypeError):
                    pass

            active.append(
                PathLease(
                    session_id=data.get("session_id", ""),
                    task_id=data.get("task_id", ""),
                    mode=data.get("mode", "read"),
                    paths=data.get("paths", []),
                    expires_at=expires_at,
                    status=data.get("status", "active"),
                    created_at=data.get("created_at", ""),
                )
            )

        return active


__all__ = [
    "DEFAULT_LEASE_TTL_SECONDS",
    "LeaseClaimResult",
    "PathLease",
    "PathLeaseManager",
]
