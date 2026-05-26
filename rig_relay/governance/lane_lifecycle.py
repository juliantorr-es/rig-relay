"""Lane and Promotion Lifecycle Authority v1.

Append-only lane lifecycle contract governing the state machine from
lane claim through promotion to consumption. Defines what states and
evidence exist when a future lane is created, claimed, ready, validated,
accepted, promoted, parked, refused, failed, or consumed.

Does NOT launch worktrees, sesssions, agents, or OpenCode.
Does NOT call GitHub, push branches, or merge refs.
Does NOT wire AgentLoop, Ralph, fleet, or subagents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, auto
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading

from pydantic import BaseModel, ConfigDict, Field

# ── Lane lifecycle states ────────────────────────────────────────────────────


class LaneLifecycleState(StrEnum):
    CLAIMED = auto()
    READY_REQUESTED = auto()
    READY_REFUSED = auto()
    VALIDATED = auto()
    ACCEPTED = auto()
    REFUSED = auto()
    PROMOTED = auto()
    PROMOTION_REFUSED = auto()
    CONSUMED = auto()
    FAILED = auto()
    PARKED = auto()


TERMINAL_STATES: frozenset[str] = frozenset({
    LaneLifecycleState.CONSUMED.value,
    LaneLifecycleState.REFUSED.value,
    LaneLifecycleState.FAILED.value,
    LaneLifecycleState.PARKED.value,
})


_VALID_TRANSITIONS: dict[str, set[str]] = {
    LaneLifecycleState.CLAIMED.value: {
        LaneLifecycleState.READY_REQUESTED.value,
        LaneLifecycleState.FAILED.value,
        LaneLifecycleState.PARKED.value,
        LaneLifecycleState.REFUSED.value,
    },
    LaneLifecycleState.READY_REQUESTED.value: {
        LaneLifecycleState.READY_REFUSED.value,
        LaneLifecycleState.VALIDATED.value,
        LaneLifecycleState.PARKED.value,
    },
    LaneLifecycleState.READY_REFUSED.value: {
        LaneLifecycleState.READY_REQUESTED.value,
        LaneLifecycleState.PARKED.value,
    },
    LaneLifecycleState.VALIDATED.value: {
        LaneLifecycleState.ACCEPTED.value,
        LaneLifecycleState.REFUSED.value,
        LaneLifecycleState.PARKED.value,
    },
    LaneLifecycleState.ACCEPTED.value: {
        LaneLifecycleState.PROMOTED.value,
        LaneLifecycleState.PROMOTION_REFUSED.value,
        LaneLifecycleState.FAILED.value,
        LaneLifecycleState.PARKED.value,
    },
    LaneLifecycleState.PROMOTED.value: {
        LaneLifecycleState.CONSUMED.value,
        LaneLifecycleState.PARKED.value,
    },
    LaneLifecycleState.PROMOTION_REFUSED.value: {
        LaneLifecycleState.ACCEPTED.value,
        LaneLifecycleState.PARKED.value,
    },
}


# ── Events ───────────────────────────────────────────────────────────────────


_LIFECYCLE_SCHEMA = "rig.relay.lane_lifecycle_event.v1"


class LaneLifecycleEventKind(StrEnum):
    LANE_CLAIMED = auto()
    READY_REQUESTED = auto()
    READY_REFUSED = auto()
    VALIDATION_PASSED = auto()
    VALIDATION_FAILED = auto()
    ACCEPTED = auto()
    REFUSED = auto()
    PROMOTED = auto()
    PROMOTION_REFUSED = auto()
    CONSUMED = auto()
    FAILED = auto()
    PARKED = auto()


class LaneLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = _LIFECYCLE_SCHEMA
    event_id: str = Field(default_factory=lambda: secrets.token_hex(16))
    event_kind: LaneLifecycleEventKind
    lane_id: str = ""
    mission_id: str = ""
    base_revision: str = ""
    branch_identity: str = ""
    worktree_identity: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    producer: str = ""
    prior_event_digest: str | None = None
    integrity_digest: str = ""

    # Evidence references (content-light: hashes and identifiers only)
    claimed_path_evidence_sha256: str | None = None
    readiness_request_id: str | None = None
    proof_bundle_sha256: str | None = None
    validation_decision_sha256: str | None = None
    acceptance_reason: str | None = None
    refusal_reason: str | None = None
    promotion_target: str | None = None
    promotion_source_sha256: str | None = None

    def recompute_integrity(self) -> str:
        payload = self.model_dump(exclude={"integrity_digest"})
        payload["integrity_digest"] = ""
        payload_data = json.dumps(payload, sort_keys=True).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload_data).hexdigest()

    def seal(self) -> None:
        self.integrity_digest = self.recompute_integrity()

    def verify_integrity(self) -> bool:
        return self.integrity_digest == self.recompute_integrity()


# ── Outcome model ────────────────────────────────────────────────────────────


class LaneTransitionOutcome(StrEnum):
    ACCEPTED = auto()
    INVALID_TRANSITION = auto()
    ALREADY_TERMINAL = auto()
    DUPLICATE_ALREADY_CURRENT = auto()
    MISSING_REQUIRED_EVIDENCE = auto()
    LEDGER_WRITE_FAILED = auto()
    STALE_BASE = auto()
    CORRUPT_LEDGER = auto()
    CONFLICTING_TERMINAL = auto()
    PROMOTED_WITHOUT_ACCEPTANCE = auto()
    CONSUMED_WITHOUT_PROMOTION = auto()
    PARKED_LANE_PRESERVED = auto()


@dataclass(slots=True)
class LaneTransitionResult:
    outcome: LaneTransitionOutcome
    lane_id: str = ""
    event_id: str | None = None
    error_detail: str = ""

    @property
    def succeeded(self) -> bool:
        return self.outcome == LaneTransitionOutcome.ACCEPTED


# ── Ledger infrastructure ────────────────────────────────────────────────────


def _store_root() -> Path:
    return Path(".build/rig-relay/desktop/lane-lifecycle")


def _ledger_path(lane_id: str) -> Path:
    return _store_root() / f"{lane_id}.jsonl"


_lock_fds: dict[str, int] = {}
_lock_mutex = threading.Lock()


def _acquire_lane_lock(lane_id: str) -> bool:
    path = _ledger_path(lane_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    try:
        fd = os.open(
            str(path.with_suffix(".jsonl.lock")), os.O_RDWR | os.O_CREAT, 0o644
        )
        fcntl.flock(fd, fcntl.LOCK_EX)
        with _lock_mutex:
            _lock_fds[lane_id] = fd
        return True
    except OSError:
        return False


def _release_lane_lock(lane_id: str) -> None:
    with _lock_mutex:
        fd = _lock_fds.pop(lane_id, None)
    if fd is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        except OSError:
            pass


def _load_events(lane_id: str) -> list[LaneLifecycleEvent] | None:
    """Load events. Returns None on corrupt ledger, list on OK."""
    path = _ledger_path(lane_id)
    if not path.exists():
        return []

    from rig_relay.core.logger import logger

    events: list[LaneLifecycleEvent] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning("Corrupt lane lifecycle ledger JSON: %s", exc)
                    return None
                try:
                    event = LaneLifecycleEvent.model_validate(obj)
                except Exception as exc:
                    logger.warning("Invalid lane lifecycle event: %s", exc)
                    return None
                if not event.verify_integrity():
                    logger.warning("Lane lifecycle event integrity mismatch")
                    return None
                # Chain verification
                if events:
                    expected_prior = events[-1].integrity_digest
                    if event.prior_event_digest != expected_prior:
                        logger.warning("Broken lane lifecycle chain")
                        return None
                events.append(event)
    except OSError:
        return None
    return events


def _last_event(lane_id: str) -> LaneLifecycleEvent | None:
    events = _load_events(lane_id)
    if events is None:
        return None
    return events[-1] if events else None


# ── State resolution ─────────────────────────────────────────────────────────


def _event_kind_to_state(kind: LaneLifecycleEventKind) -> LaneLifecycleState:
    mapping: dict[LaneLifecycleEventKind, LaneLifecycleState] = {
        LaneLifecycleEventKind.LANE_CLAIMED: LaneLifecycleState.CLAIMED,
        LaneLifecycleEventKind.READY_REQUESTED: LaneLifecycleState.READY_REQUESTED,
        LaneLifecycleEventKind.READY_REFUSED: LaneLifecycleState.READY_REFUSED,
        LaneLifecycleEventKind.VALIDATION_PASSED: LaneLifecycleState.VALIDATED,
        LaneLifecycleEventKind.VALIDATION_FAILED: LaneLifecycleState.FAILED,
        LaneLifecycleEventKind.ACCEPTED: LaneLifecycleState.ACCEPTED,
        LaneLifecycleEventKind.REFUSED: LaneLifecycleState.REFUSED,
        LaneLifecycleEventKind.PROMOTED: LaneLifecycleState.PROMOTED,
        LaneLifecycleEventKind.PROMOTION_REFUSED: LaneLifecycleState.PROMOTION_REFUSED,
        LaneLifecycleEventKind.CONSUMED: LaneLifecycleState.CONSUMED,
        LaneLifecycleEventKind.FAILED: LaneLifecycleState.FAILED,
        LaneLifecycleEventKind.PARKED: LaneLifecycleState.PARKED,
    }
    return mapping.get(kind, LaneLifecycleState.FAILED)


def current_state(lane_id: str) -> LaneLifecycleState | None:
    """Resolve current lane state. None if no events."""
    events = _load_events(lane_id)
    if events is None:
        return None
    if not events:
        return None
    return _event_kind_to_state(events[-1].event_kind)


# ── Append event ─────────────────────────────────────────────────────────────


def _append_event(event: LaneLifecycleEvent, lane_id: str) -> str | None:
    """Append a lifecycle event under lock, flush, and fsync."""
    try:
        if not _acquire_lane_lock(lane_id):
            return None
    except Exception:
        return None

    try:
        if not event.event_id:
            event.event_id = secrets.token_hex(16)

        prior = _last_event(lane_id)
        if prior is not None:
            event.prior_event_digest = prior.integrity_digest

        event.seal()

        path = _ledger_path(lane_id)
        line_bytes = (event.model_dump_json() + "\n").encode("utf-8")
        with open(path, "ab") as f:
            pos_before = f.tell()
            f.write(line_bytes)
            f.flush()
            os.fsync(f.fileno())
            pos_after = f.tell()
            expected = len(line_bytes)
            actual = pos_after - pos_before
            if actual != expected:
                return None

        return event.event_id
    except OSError:
        return None
    finally:
        _release_lane_lock(lane_id)


# ── Transition authority ─────────────────────────────────────────────────────


def transition_lane(
    lane_id: str,
    event_kind: LaneLifecycleEventKind,
    *,
    mission_id: str = "",
    base_revision: str = "",
    branch_identity: str = "",
    worktree_identity: str = "",
    producer: str = "",
    claimed_path_evidence_sha256: str | None = None,
    readiness_request_id: str | None = None,
    proof_bundle_sha256: str | None = None,
    validation_decision_sha256: str | None = None,
    acceptance_reason: str | None = None,
    refusal_reason: str | None = None,
    promotion_target: str | None = None,
    promotion_source_sha256: str | None = None,
    require_proof: bool = True,
    require_acceptance_before_promotion: bool = True,
    require_promotion_before_consumption: bool = True,
    preserve_parked: bool = True,
) -> LaneTransitionResult:
    """Attempt a lane lifecycle transition.

    Args:
        lane_id: Lane identifier.
        event_kind: Desired transition event kind.
        require_proof: If True, READY_REQUESTED requires proof_bundle_sha256.
        require_acceptance_before_promotion: If True, PROMOTED requires ACCEPTED first.
        require_promotion_before_consumption: If True, CONSUMED requires PROMOTED first.
        preserve_parked: If True, PARKED lanes cannot transition out.

    Returns:
        LaneTransitionResult with outcome.
    """
    current = current_state(lane_id)
    target_state = _event_kind_to_state(event_kind)

    # 1. Check for corrupt ledger
    events = _load_events(lane_id)
    if events is None:
        return LaneTransitionResult(
            outcome=LaneTransitionOutcome.CORRUPT_LEDGER,
            lane_id=lane_id,
            error_detail="Lane lifecycle ledger is corrupt",
        )

    # 2. First event must be LANE_CLAIMED
    if current is None:
        if event_kind != LaneLifecycleEventKind.LANE_CLAIMED:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.INVALID_TRANSITION,
                lane_id=lane_id,
                error_detail="First event must be LANE_CLAIMED",
            )
    else:
        # 3. Parked lanes are preserved (before terminal check —
        # PARKED is a terminal state but has a distinct error message)
        if preserve_parked and current == LaneLifecycleState.PARKED:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.PARKED_LANE_PRESERVED,
                lane_id=lane_id,
                error_detail="Parked lanes cannot transition",
            )

        # 4. Terminal states refuse new transitions
        if current.value in TERMINAL_STATES:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.ALREADY_TERMINAL,
                lane_id=lane_id,
                error_detail=f"Lane is in terminal state: {current.value}",
            )

        # 5. Duplicate guard: same state as current is idempotent
        if target_state == current:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.DUPLICATE_ALREADY_CURRENT, lane_id=lane_id
            )

        # 6. Semantic gates (more specific than transition validity)
        if (
            event_kind == LaneLifecycleEventKind.PROMOTED
            and require_acceptance_before_promotion
            and current != LaneLifecycleState.ACCEPTED
        ):
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.PROMOTED_WITHOUT_ACCEPTANCE,
                lane_id=lane_id,
                error_detail="PROMOTED requires prior ACCEPTED state",
            )
        if (
            event_kind == LaneLifecycleEventKind.CONSUMED
            and require_promotion_before_consumption
            and current != LaneLifecycleState.PROMOTED
        ):
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.CONSUMED_WITHOUT_PROMOTION,
                lane_id=lane_id,
                error_detail="CONSUMED requires prior PROMOTED state",
            )

        # 7. Validate transition
        valid_targets = _VALID_TRANSITIONS.get(current.value, set())
        if target_state.value not in valid_targets:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.INVALID_TRANSITION,
                lane_id=lane_id,
                error_detail=(
                    f"Invalid transition from {current.value} "
                    f"to {target_state.value} via {event_kind.value}"
                ),
            )

        # 6. Validate transition
        valid_targets = _VALID_TRANSITIONS.get(current.value, set())
        if target_state.value not in valid_targets:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.INVALID_TRANSITION,
                lane_id=lane_id,
                error_detail=(
                    f"Invalid transition from {current.value} "
                    f"to {target_state.value} via {event_kind.value}"
                ),
            )

        # 6. Duplicate guard: same state as current is idempotent
        if target_state == current:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.DUPLICATE_ALREADY_CURRENT, lane_id=lane_id
            )

    # 2. First event must be LANE_CLAIMED
    if current is None:
        if event_kind != LaneLifecycleEventKind.LANE_CLAIMED:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.INVALID_TRANSITION,
                lane_id=lane_id,
                error_detail="First event must be LANE_CLAIMED",
            )
    else:
        # 3. Terminal states refuse new transitions
        if current.value in TERMINAL_STATES:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.ALREADY_TERMINAL,
                lane_id=lane_id,
                error_detail=f"Lane is in terminal state: {current.value}",
            )

        # 4. Parked lanes are preserved
        if preserve_parked and current == LaneLifecycleState.PARKED:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.PARKED_LANE_PRESERVED,
                lane_id=lane_id,
                error_detail="Parked lanes cannot transition",
            )

        # 5. Validate transition
        valid_targets = _VALID_TRANSITIONS.get(current.value, set())
        target_state = _event_kind_to_state(event_kind)
        if target_state.value not in valid_targets:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.INVALID_TRANSITION,
                lane_id=lane_id,
                error_detail=(
                    f"Invalid transition from {current.value} "
                    f"to {target_state.value} via {event_kind.value}"
                ),
            )

        # 6. Duplicate guard: same state as current is idempotent
        if target_state == current:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.DUPLICATE_ALREADY_CURRENT, lane_id=lane_id
            )

    # 7. Evidence requirements
    if event_kind == LaneLifecycleEventKind.READY_REQUESTED and require_proof:
        if not proof_bundle_sha256:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.MISSING_REQUIRED_EVIDENCE,
                lane_id=lane_id,
                error_detail="READY_REQUESTED requires proof_bundle_sha256",
            )

    if (
        event_kind == LaneLifecycleEventKind.PROMOTED
        and require_acceptance_before_promotion
    ):
        if current != LaneLifecycleState.ACCEPTED:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.PROMOTED_WITHOUT_ACCEPTANCE,
                lane_id=lane_id,
                error_detail="PROMOTED requires prior ACCEPTED state",
            )

    if (
        event_kind == LaneLifecycleEventKind.CONSUMED
        and require_promotion_before_consumption
    ):
        if current != LaneLifecycleState.PROMOTED:
            return LaneTransitionResult(
                outcome=LaneTransitionOutcome.CONSUMED_WITHOUT_PROMOTION,
                lane_id=lane_id,
                error_detail="CONSUMED requires prior PROMOTED state",
            )

    # 8. Stale base check
    if (
        current
        and base_revision
        and event_kind
        not in {LaneLifecycleEventKind.FAILED, LaneLifecycleEventKind.REFUSED}
    ):
        first_event = events[0] if events else None
        if first_event and first_event.base_revision:
            if base_revision != first_event.base_revision:
                return LaneTransitionResult(
                    outcome=LaneTransitionOutcome.STALE_BASE,
                    lane_id=lane_id,
                    error_detail=(
                        f"Base revision changed: was {first_event.base_revision}, "
                        f"now {base_revision}"
                    ),
                )

    # 9. Append event
    event = LaneLifecycleEvent(
        event_kind=event_kind,
        lane_id=lane_id,
        mission_id=mission_id,
        base_revision=base_revision,
        branch_identity=branch_identity,
        worktree_identity=worktree_identity,
        producer=producer,
        claimed_path_evidence_sha256=claimed_path_evidence_sha256,
        readiness_request_id=readiness_request_id,
        proof_bundle_sha256=proof_bundle_sha256,
        validation_decision_sha256=validation_decision_sha256,
        acceptance_reason=acceptance_reason,
        refusal_reason=refusal_reason,
        promotion_target=promotion_target,
        promotion_source_sha256=promotion_source_sha256,
    )

    event_id = _append_event(event, lane_id)
    if event_id is None:
        return LaneTransitionResult(
            outcome=LaneTransitionOutcome.LEDGER_WRITE_FAILED,
            lane_id=lane_id,
            error_detail="Failed to write lifecycle event to ledger",
        )

    # 10. Post-write verification
    verify_state = current_state(lane_id)
    if verify_state != target_state:
        return LaneTransitionResult(
            outcome=LaneTransitionOutcome.CONFLICTING_TERMINAL,
            lane_id=lane_id,
            error_detail=(
                f"Post-write state is {verify_state}, expected {target_state}. "
                f"Another transition may have occurred concurrently."
            ),
        )

    return LaneTransitionResult(
        outcome=LaneTransitionOutcome.ACCEPTED, lane_id=lane_id, event_id=event_id
    )


__all__ = [
    "TERMINAL_STATES",
    "LaneLifecycleEvent",
    "LaneLifecycleEventKind",
    "LaneLifecycleState",
    "LaneTransitionOutcome",
    "LaneTransitionResult",
    "current_state",
    "transition_lane",
]
