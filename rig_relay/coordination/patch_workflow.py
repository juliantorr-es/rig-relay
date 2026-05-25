from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import os
from pathlib import Path
import threading
from typing import Literal

from rig_relay.coordination.patch_proposal import (
    PatchDecision,
    PatchProposal,
    compute_candidate_fingerprint,
)

_DECISIONS_DIR = ".fleet/patch-decisions"
_PROPOSALS_DIR = ".fleet/patch-proposals"


class PatchWorkflowError(Exception):
    pass


class PatchProposalNotFoundError(PatchWorkflowError):
    pass


class PatchProposalStateError(PatchWorkflowError):
    pass


class PatchWorkflowStore:
    def __init__(self, coordination_root: Path) -> None:
        self._root = coordination_root

    def proposal_path(self, proposal_id: str) -> Path:
        return self._root / _PROPOSALS_DIR / f"{proposal_id}.json"

    def decision_path(self, decision_id: str) -> Path:
        return self._root / _DECISIONS_DIR / f"{decision_id}.json"

    def load_proposal(self, proposal_id: str) -> PatchProposal:
        path = self.proposal_path(proposal_id)
        if not path.is_file():
            raise PatchProposalNotFoundError(proposal_id)
        return PatchProposal.model_validate_json(path.read_text(encoding="utf-8"))

    def save_proposal(self, proposal: PatchProposal) -> Path:
        path = self.proposal_path(proposal.proposal_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
        return path

    def save_decision(self, decision: PatchDecision) -> Path:
        path = self.decision_path(decision.decision_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(decision.model_dump_json(indent=2), encoding="utf-8")
        return path

    def find_by_idempotency_key(self, key: str) -> PatchProposal | None:
        """Look up an existing proposal by its idempotency key.

        Scans `.fleet/patch-proposals/` for a proposal whose
        ``idempotency_key`` matches. Returns ``None`` if no
        match is found.
        """
        proposals_glob = self._root / _PROPOSALS_DIR
        if not proposals_glob.is_dir():
            return None
        for path in sorted(proposals_glob.glob("*.json")):
            try:
                proposal = PatchProposal.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except Exception:
                continue
            if proposal.idempotency_key == key:
                return proposal
        return None

    _create_lock = threading.Lock()

    def create_or_replay_pending_proposal(
        self, *, proposal: PatchProposal, fingerprint: str
    ) -> tuple[PatchProposal, str]:
        """Atomic create-or-replay for idempotent proposal persistence.

        Under a per-store lock, looks up the proposal's idempotency_key.
        If an existing proposal is found with the same key:
        - Same fingerprint → returns the existing proposal with status
          ``replayed``.
        - Different fingerprint → raises ``ProposalIdempotencyConflictError``.

        If no existing proposal is found with the key, persists the new
        proposal and returns it with status ``created``.

        Returns a tuple of (proposal, status) where status is one of
        ``"created"`` or ``"replayed"``.
        """
        key = proposal.idempotency_key
        if not key:
            raise PatchWorkflowError("idempotency_key is required for create_or_replay")
        with self._create_lock:
            existing = self.find_by_idempotency_key(key)
            if existing is not None:
                existing_fp = compute_candidate_fingerprint(
                    file_path=(
                        list(existing.expected_before_sha256.keys())[0]
                        if existing.expected_before_sha256
                        else ""
                    ),
                    before_hash=(
                        list(existing.expected_before_sha256.values())[0]
                        if existing.expected_before_sha256
                        else ""
                    ),
                    after_hash=(
                        list(existing.candidate_after_sha256.values())[0]
                        if existing.candidate_after_sha256
                        else ""
                    ),
                )
                if existing_fp == fingerprint:
                    return existing, "replayed"
                raise ProposalIdempotencyConflictError(
                    f"idempotency_key {key!r} already used with "
                    f"a different request; stored fingerprint "
                    f"{existing_fp[:16]}... != request fingerprint "
                    f"{fingerprint[:16]}..."
                )
            self.save_proposal(proposal)
            return proposal, "created"


class ProposalIdempotencyConflictError(PatchWorkflowError):
    """Raised when an idempotency key is reused with different content."""


class ProposalTransitionError(PatchWorkflowError):
    """Raised when an illegal proposal status transition is attempted."""


@contextmanager
def proposal_continuation_context(
    coordination_root: Path, proposal_id: str
) -> Iterator[int]:
    """Acquire a cross-process continuation lock for a proposal.

    The lock spans apply, checkpoint, push, terminal receipt persistence,
    and state projection repair. Transition operations called inside this
    context may receive the lock token via ``_lock_fd`` to avoid
    self-reacquisition.

    The returned file descriptor must not be manually closed; release
    is handled by the context manager.
    """
    lock_dir = coordination_root / _PROPOSALS_DIR
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{proposal_id}.lock"
    if not lock_path.exists():
        lock_path.touch()
    fd = os.open(str(lock_path), os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        yield fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def transition_proposal_status(
    coordination_root: Path,
    proposal_id: str,
    from_status: str,
    to_status: str,
    *,
    _lock_fd: int | None = None,
) -> PatchProposal:
    """Atomically transition a proposal's status.

    If ``_lock_fd`` is provided, the caller already holds the
    continuation lock and it is used for exclusive access without
    reacquisition. Otherwise a temporary lock is acquired and released.
    """
    store = PatchWorkflowStore(coordination_root)
    if _lock_fd is not None:
        return _transition_under_lock(store, proposal_id, from_status, to_status)

    lock_path = store._root / _PROPOSALS_DIR / f"{proposal_id}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        return _transition_under_lock(store, proposal_id, from_status, to_status)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _transition_under_lock(
    store: PatchWorkflowStore, proposal_id: str, from_status: str, to_status: str
) -> PatchProposal:
    """Perform the atomic status transition assuming the lock is held."""
    current = store.load_proposal(proposal_id)
    if current.status != from_status:
        raise ProposalTransitionError(
            f"Expected proposal {proposal_id!r} status "
            f"{from_status!r}, got {current.status!r}"
        )
    updated = current.model_copy(update={"status": to_status})
    path = store.proposal_path(proposal_id)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
    temp.replace(path)
    return updated


def record_patch_decision(
    coordination_root: Path, decision: PatchDecision
) -> tuple[PatchProposal, PatchDecision]:
    store = PatchWorkflowStore(coordination_root)
    proposal = store.load_proposal(decision.proposal_id)
    if proposal.status != "pending":
        raise PatchProposalStateError(
            f"proposal {proposal.proposal_id} is not pending: {proposal.status}"
        )

    next_status = _decision_to_status(decision.decision)
    proposal = proposal.model_copy(update={"status": next_status})
    store.save_proposal(proposal)
    store.save_decision(decision)
    return proposal, decision


def create_patch_decision(
    *,
    proposal_id: str,
    decided_by: str,
    decision: Literal["accepted", "rejected", "needs_revision", "superseded"],
    reason: str,
    decision_id: str | None = None,
) -> PatchDecision:
    return PatchDecision(
        decision_id=decision_id
        or f"dec-{proposal_id}-{datetime.now(UTC).timestamp():.0f}",
        proposal_id=proposal_id,
        decided_by=decided_by,
        decision=decision,
        reason=reason,
    )


def _decision_to_status(decision: str) -> str:
    match decision:
        case "accepted":
            return "accepted"
        case "rejected":
            return "rejected"
        case "needs_revision":
            return "needs_revision"
        case "superseded":
            return "superseded"
        case _:
            raise PatchWorkflowError(f"unknown decision: {decision}")


def create_pending_proposal(
    *,
    coordination_root: Path,
    file_path: str,
    before_hash: str,
    after_hash: str,
    title: str = "",
    summary: str = "",
    proposal_id: str | None = None,
    idempotency_key: str | None = None,
) -> PatchProposal:
    """Create and persist a pending PatchProposal from a computed candidate.

    This is the canonical persistence boundary for non-mutating proposal
    workflows. It accepts a computed candidate descriptor (file path,
    before/after hashes) and persists a pending PatchProposal through
    PatchWorkflowStore.

    Returns the persisted PatchProposal.
    """
    import uuid

    from rig_relay.coordination.patch_proposal import PatchProposal
    from rig_relay.coordination.patch_workflow import PatchWorkflowStore

    pid = proposal_id or f"prop-{uuid.uuid4().hex[:12]}"
    sha_prefix = "sha256:"
    before_hex = (
        before_hash[len(sha_prefix) :]
        if before_hash.startswith(sha_prefix)
        else before_hash
    )
    after_hex = (
        after_hash[len(sha_prefix) :]
        if after_hash.startswith(sha_prefix)
        else after_hash
    )

    proposal = PatchProposal(
        proposal_id=pid,
        mission_id="",
        agent_id="",
        title=title or f"Search-replace proposal for {file_path}",
        summary=summary or f"Proposes a change to {file_path}",
        status="pending",
        touched_paths=[file_path],
        touched_path_hashes=[before_hash],
        expected_before_sha256={file_path: f"{sha_prefix}{before_hex}"},
        candidate_after_sha256={file_path: after_hex},
        idempotency_key=idempotency_key or None,
    )
    after_hex = (
        after_hash[len(sha_prefix) :]
        if after_hash.startswith(sha_prefix)
        else after_hash
    )

    proposal = PatchProposal(
        proposal_id=pid,
        mission_id="",
        agent_id="",
        title=title or f"Search-replace proposal for {file_path}",
        summary=summary or f"Proposes a change to {file_path}",
        status="pending",
        touched_paths=[file_path],
        touched_path_hashes=[before_hash],
        expected_before_sha256={file_path: before_hex},
        candidate_after_sha256={file_path: after_hex},
        idempotency_key=idempotency_key or None,
    )
    store = PatchWorkflowStore(coordination_root)
    store.save_proposal(proposal)
    return proposal


__all__ = [
    "PatchProposalNotFoundError",
    "PatchProposalStateError",
    "PatchWorkflowError",
    "PatchWorkflowStore",
    "ProposalIdempotencyConflictError",
    "ProposalTransitionError",
    "create_patch_decision",
    "create_pending_proposal",
    "proposal_continuation_context",
    "record_patch_decision",
    "transition_proposal_status",
]
