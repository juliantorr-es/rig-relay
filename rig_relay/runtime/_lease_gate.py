"""Lease gate for runtime tool execution.

Extracted from tool_invocation_execution.py to eliminate duplicated
lease claim/release logic across the five execute_* methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rig_relay.coordination.lease_manager import DEFAULT_LEASE_TTL_SECONDS
from rig_relay.core.logger import logger


@dataclass
class LeaseClaimOutcome:
    """Result of a lease claim attempt.

    Does not reference RuntimeToolExecutionResult to avoid circular
    imports. The caller converts blocked outcomes to execution results.
    """

    blocked: bool = False
    granted: bool = False
    lease_info: tuple[str, str, list[str]] | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None
    intent_id: str | None = None
    tool_name: str | None = None


def claim_mutation_lease(
    envelope: Any, file_path: str, coordination_root: Path
) -> LeaseClaimOutcome:
    """Claim a path lease for a mutation tool.

    Attempts to acquire an exclusive_write lease on the given file path.
    Returns a LeaseClaimOutcome indicating whether the claim was granted or blocked.

    Coordination policy:
    - If coordination_enabled is False on the envelope, lease is skipped
      and execution proceeds without a lease.
    - If coordination_enabled is True and session/task/file_path are present,
      a lease must be acquired or the mutation is BLOCKED.
    - Store errors do not silently allow mutation when coordination is enabled.
    """
    coordination_enabled = getattr(envelope, "coordination_enabled", True)

    if (
        not coordination_enabled
        or not envelope.session_id
        or not envelope.task_id
        or not file_path
    ):
        return LeaseClaimOutcome(blocked=False, granted=False, lease_info=None)

    try:
        from rig_relay.coordination.lease_manager import PathLeaseManager

        manager = PathLeaseManager(coordination_root)
        result = manager.claim_paths(
            session_id=envelope.session_id,
            task_id=envelope.task_id,
            mode="exclusive_write",
            paths=[file_path],
            ttl_seconds=envelope.lease_ttl_seconds or DEFAULT_LEASE_TTL_SECONDS,
        )
        if result.status == "conflict":
            return LeaseClaimOutcome(
                blocked=True,
                error_kind=result.error_kind or "lease_conflict",
                refusal_reason=result.refusal_reason or "Path lease conflict",
                intent_id=getattr(envelope, "invocation_id", ""),
                tool_name=str(getattr(envelope, "tool_name", "unknown")),
            )
        if result.status == "granted":
            return LeaseClaimOutcome(
                blocked=False,
                granted=True,
                lease_info=(envelope.session_id, envelope.task_id, [file_path]),
            )
        return LeaseClaimOutcome(
            blocked=True,
            error_kind=result.error_kind or "lease_error",
            refusal_reason=result.refusal_reason
            or "Lease acquisition returned unexpected status",
            intent_id=getattr(envelope, "invocation_id", ""),
            tool_name=str(getattr(envelope, "tool_name", "unknown")),
        )
    except Exception:
        return LeaseClaimOutcome(
            blocked=True,
            error_kind="lease_store_error",
            refusal_reason="Lease store error prevented lease acquisition",
            intent_id=getattr(envelope, "invocation_id", ""),
            tool_name=str(getattr(envelope, "tool_name", "unknown")),
        )


def release_mutation_lease(
    coordination_root: Path, session_id: str, task_id: str, paths: list[str]
) -> None:
    """Release a previously acquired mutation lease.

    Best-effort: failures are silently ignored so lease release
    never breaks tool execution or result construction.
    """
    if not session_id or not task_id or not paths:
        return
    try:
        from rig_relay.coordination.lease_manager import PathLeaseManager

        manager = PathLeaseManager(coordination_root)
        manager.release_paths(session_id=session_id, task_id=task_id, paths=paths)
    except Exception:
        logger.warning(
            "Lease release failed for session=%s task=%s paths=%s",
            session_id,
            task_id,
            paths,
        )


def resolve_coordination_root(
    worktree_path: str | None = None, repo_root: str | None = None
) -> Path:
    """Resolve the coordination store root from envelope fields.

    Prefers worktree_path, then repo_root, then CWD.
    """
    base = worktree_path or repo_root or Path.cwd().as_posix()
    return Path(base) / ".build" / "rig-relay" / "coordination"


__all__ = [
    "LeaseClaimOutcome",
    "claim_mutation_lease",
    "release_mutation_lease",
    "resolve_coordination_root",
]
