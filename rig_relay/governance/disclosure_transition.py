"""Governed Disclosure Transition Authority — canonical orchestration spine
for disclosure lifecycle.

Owns: transition identity, durable append-only state, exclusive corridor
lock, idempotent downstream persistence, crash recovery, execute/resume/recover.

Does NOT own:
- authorization issue/validate/consume (delegates to disclosure_authorization)
- manifest construction (delegates to protected_content)
- ZIP bundle generation (delegates to bundle_builder)
- CLI output formatting (CLI consumes this, formats output)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
from typing import Any

# ═════════════════════════════════════════════════════════════════════════
# Transition states
# ═════════════════════════════════════════════════════════════════════════


class TransitionStatus(StrEnum):
    PREPARED = "prepared"
    AUTHORIZATION_CONSUMED = "authorization_consumed"
    PROJECTION_RECEIPT_PERSISTED = "projection_receipt_persisted"
    MANIFEST_APPLIED = "manifest_applied"
    DISCLOSURE_EVENT_RECORDED = "disclosure_event_recorded"
    COMPLETED = "completed"
    RECOVERY_REQUIRED = "recovery_required"
    REFUSED = "refused"
    CONFLICT = "conflict"
    CORRUPT = "corrupt"


VALID_STATUS_PROGRESSION: dict[TransitionStatus, frozenset[TransitionStatus]] = {
    TransitionStatus.PREPARED: frozenset({
        TransitionStatus.AUTHORIZATION_CONSUMED,
        TransitionStatus.REFUSED,
    }),
    TransitionStatus.AUTHORIZATION_CONSUMED: frozenset({
        TransitionStatus.PROJECTION_RECEIPT_PERSISTED,
        TransitionStatus.REFUSED,
        TransitionStatus.RECOVERY_REQUIRED,
    }),
    TransitionStatus.PROJECTION_RECEIPT_PERSISTED: frozenset({
        TransitionStatus.MANIFEST_APPLIED,
        TransitionStatus.REFUSED,
        TransitionStatus.RECOVERY_REQUIRED,
    }),
    TransitionStatus.MANIFEST_APPLIED: frozenset({
        TransitionStatus.DISCLOSURE_EVENT_RECORDED,
        TransitionStatus.REFUSED,
        TransitionStatus.RECOVERY_REQUIRED,
    }),
    TransitionStatus.DISCLOSURE_EVENT_RECORDED: frozenset({
        TransitionStatus.COMPLETED,
        TransitionStatus.RECOVERY_REQUIRED,
    }),
    TransitionStatus.COMPLETED: frozenset(),
    TransitionStatus.REFUSED: frozenset(),
    TransitionStatus.CONFLICT: frozenset(),
    TransitionStatus.CORRUPT: frozenset(),
    TransitionStatus.RECOVERY_REQUIRED: frozenset({
        TransitionStatus.PROJECTION_RECEIPT_PERSISTED,
        TransitionStatus.MANIFEST_APPLIED,
        TransitionStatus.DISCLOSURE_EVENT_RECORDED,
        TransitionStatus.COMPLETED,
    }),
}


# ═════════════════════════════════════════════════════════════════════════
# Transition model
# ═════════════════════════════════════════════════════════════════════════

TRANSITION_SCHEMA_VERSION = "rig.relay.disclosure_transition_event.v1"
TERMINAL_STATUSES: frozenset[TransitionStatus] = frozenset({
    TransitionStatus.COMPLETED,
    TransitionStatus.REFUSED,
    TransitionStatus.CONFLICT,
    TransitionStatus.CORRUPT,
})


@dataclass
class DisclosureTransition:
    schema_version: str = TRANSITION_SCHEMA_VERSION
    transition_id: str = ""
    authorization_id: str = ""
    evidence_digest: str = ""
    projection_id: str = ""
    disclosure_class: str = ""
    selector_digest: str | None = None
    selector_required_class: str | None = None
    manifest_digest_before: str = ""
    manifest_digest_after: str | None = None
    recipient_class: str = ""
    provider_or_channel: str = ""
    purpose: str | None = None
    status: TransitionStatus = TransitionStatus.PREPARED
    parent_transition_digest: str | None = None
    downstream_event_id: str | None = None
    downstream_receipt_digest: str | None = None
    recovery_detail: str | None = None
    transition_digest: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    sequence: int = 0
    corrupt_detail: str | None = None

    def compute_digest(self) -> str:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "transition_id": self.transition_id,
            "authorization_id": self.authorization_id,
            "evidence_digest": self.evidence_digest,
            "projection_id": self.projection_id,
            "disclosure_class": self.disclosure_class,
            "selector_digest": self.selector_digest,
            "selector_required_class": self.selector_required_class,
            "manifest_digest_before": self.manifest_digest_before,
            "manifest_digest_after": self.manifest_digest_after,
            "status": self.status.value,
            "parent_transition_digest": self.parent_transition_digest,
            "downstream_event_id": self.downstream_event_id,
            "downstream_receipt_digest": self.downstream_receipt_digest,
            "sequence": self.sequence,
        }
        payload["transition_digest"] = ""
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    def seal(self) -> None:
        self.transition_digest = self.compute_digest()

    def to_event(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "transition_id": self.transition_id,
            "authorization_id": self.authorization_id,
            "evidence_digest": self.evidence_digest,
            "projection_id": self.projection_id,
            "disclosure_class": self.disclosure_class,
            "selector_digest": self.selector_digest,
            "selector_required_class": self.selector_required_class,
            "manifest_digest_before": self.manifest_digest_before,
            "manifest_digest_after": self.manifest_digest_after,
            "status": self.status.value,
            "parent_transition_digest": self.parent_transition_digest,
            "downstream_event_id": self.downstream_event_id,
            "downstream_receipt_digest": self.downstream_receipt_digest,
            "recovery_detail": self.recovery_detail,
            "corrupt_detail": self.corrupt_detail,
            "transition_digest": self.transition_digest,
            "created_at": self.created_at,
            "sequence": self.sequence,
        }

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


# ═════════════════════════════════════════════════════════════════════════
# Store and locking
# ═════════════════════════════════════════════════════════════════════════


def _transition_store_root() -> Path:
    return Path(".build/rig-relay/governance/disclosure-transitions")


def _transition_ledger_path() -> Path:
    return _transition_store_root() / "transitions.jsonl"


_transition_lock = threading.Lock()
_transition_lock_fd: int | None = None


def _acquire_transition_lock() -> None:
    global _transition_lock_fd
    _transition_lock.acquire()
    root = _transition_store_root()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = _transition_store_root() / "transition.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    _transition_lock_fd = fd


def _release_transition_lock() -> None:
    global _transition_lock_fd
    if _transition_lock_fd is not None:
        fcntl.flock(_transition_lock_fd, fcntl.LOCK_UN)
        try:
            os.close(_transition_lock_fd)
        except OSError:
            pass
        _transition_lock_fd = None
    _transition_lock.release()


def _append_transition_event(event: dict[str, Any]) -> None:
    ledger = _transition_ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    with open(ledger, "a") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


# ═════════════════════════════════════════════════════════════════════════
# Ledger replay (fixed — scans by authorization_id, not transition_id)
# ═════════════════════════════════════════════════════════════════════════


def _load_all_ledger_events() -> list[dict[str, Any]]:
    """Load and validate every event in the ledger. Skips malformed lines."""
    ledger = _transition_ledger_path()
    if not ledger.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in ledger.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        events.append(ev)
    return events


def _find_transition_chain(transition_id: str) -> list[dict[str, Any]]:
    """Return all events for a specific transition_id, sorted by sequence."""
    events = _load_all_ledger_events()
    chain = [e for e in events if e.get("transition_id") == transition_id]
    chain.sort(key=lambda e: e.get("sequence", 0))
    return chain


def _find_transition_for_auth(
    authorization_id: str, evidence_digest: str
) -> list[dict[str, Any]]:
    """Find ledger events for this authorization + evidence pair."""
    events = _load_all_ledger_events()
    return [
        e
        for e in events
        if e.get("authorization_id") == authorization_id
        and e.get("evidence_digest") == evidence_digest
    ]


def _last_event_for_auth(
    authorization_id: str, evidence_digest: str
) -> dict[str, Any] | None:
    chain = _find_transition_for_auth(authorization_id, evidence_digest)
    if not chain:
        return None
    chain.sort(key=lambda e: e.get("sequence", 0))
    return chain[-1]


def _event_to_transition(ev: dict[str, Any]) -> DisclosureTransition | None:
    try:
        return DisclosureTransition(
            transition_id=ev.get("transition_id", ""),
            authorization_id=ev.get("authorization_id", ""),
            evidence_digest=ev.get("evidence_digest", ""),
            projection_id=ev.get("projection_id", ""),
            disclosure_class=ev.get("disclosure_class", ""),
            selector_digest=ev.get("selector_digest"),
            selector_required_class=ev.get("selector_required_class"),
            manifest_digest_before=ev.get("manifest_digest_before", ""),
            manifest_digest_after=ev.get("manifest_digest_after"),
            recipient_class=ev.get("recipient_class", ""),
            provider_or_channel=ev.get("provider_or_channel", ""),
            purpose=ev.get("purpose"),
            status=TransitionStatus(ev.get("status", "prepared")),
            parent_transition_digest=ev.get("parent_transition_digest"),
            downstream_event_id=ev.get("downstream_event_id"),
            downstream_receipt_digest=ev.get("downstream_receipt_digest"),
            recovery_detail=ev.get("recovery_detail"),
            corrupt_detail=ev.get("corrupt_detail"),
            transition_digest=ev.get("transition_digest", ""),
            created_at=ev.get("created_at", ""),
            sequence=ev.get("sequence", 0),
        )
    except (ValueError, KeyError):
        return None


def lookup_pending_transition(
    authorization_id: str, evidence_digest: str
) -> DisclosureTransition | None:
    """Find the latest non-terminal transition for this authorization+evidence."""
    last = _last_event_for_auth(authorization_id, evidence_digest)
    if last is None:
        return None
    t = _event_to_transition(last)
    if t is None or t.is_terminal():
        return None
    return t


def lookup_completed_transition(
    authorization_id: str, evidence_digest: str
) -> DisclosureTransition | None:
    """Find a completed transition, or None."""
    last = _last_event_for_auth(authorization_id, evidence_digest)
    if last is None:
        return None
    t = _event_to_transition(last)
    if t is None or not t.is_terminal():
        return None
    return t


# ═════════════════════════════════════════════════════════════════════════
# Transition lifecycle
# ═════════════════════════════════════════════════════════════════════════


def _generate_transition_id() -> str:
    return "dzt_" + secrets.token_hex(12)


def prepare_transition(
    authorization_id: str,
    evidence_digest: str,
    projection_id: str,
    disclosure_class: str,
    manifest_digest_before: str,
    recipient_class: str,
    provider_or_channel: str,
    purpose: str | None = None,
    selector_digest: str | None = None,
    selector_required_class: str | None = None,
) -> DisclosureTransition:
    # If there's already a transition for this auth+evidence, return it
    existing = lookup_pending_transition(authorization_id, evidence_digest)
    if existing is not None:
        return existing

    t = DisclosureTransition(
        transition_id=_generate_transition_id(),
        authorization_id=authorization_id,
        evidence_digest=evidence_digest,
        projection_id=projection_id,
        disclosure_class=disclosure_class,
        manifest_digest_before=manifest_digest_before,
        recipient_class=recipient_class,
        provider_or_channel=provider_or_channel,
        purpose=purpose,
        selector_digest=selector_digest,
        selector_required_class=selector_required_class,
        status=TransitionStatus.PREPARED,
        sequence=0,
    )
    t.seal()
    _append_transition_event(t.to_event())
    return t


def advance_transition(
    transition: DisclosureTransition, new_status: TransitionStatus, **updates: Any
) -> DisclosureTransition:
    parent_digest = transition.transition_digest
    next_seq = transition.sequence + 1
    t = DisclosureTransition(
        transition_id=transition.transition_id,
        authorization_id=transition.authorization_id,
        evidence_digest=transition.evidence_digest,
        projection_id=transition.projection_id,
        disclosure_class=transition.disclosure_class,
        selector_digest=transition.selector_digest,
        selector_required_class=transition.selector_required_class,
        manifest_digest_before=transition.manifest_digest_before,
        manifest_digest_after=updates.get(
            "manifest_digest_after", transition.manifest_digest_after
        ),
        recipient_class=transition.recipient_class,
        provider_or_channel=transition.provider_or_channel,
        purpose=transition.purpose,
        status=new_status,
        parent_transition_digest=parent_digest,
        downstream_event_id=updates.get(
            "downstream_event_id", transition.downstream_event_id
        ),
        downstream_receipt_digest=updates.get(
            "downstream_receipt_digest", transition.downstream_receipt_digest
        ),
        recovery_detail=updates.get("recovery_detail"),
        created_at=datetime.now(UTC).isoformat(),
        sequence=next_seq,
    )
    t.seal()
    _append_transition_event(t.to_event())
    return t


# ═════════════════════════════════════════════════════════════════════════
# Production API
# ═════════════════════════════════════════════════════════════════════════


def execute_disclosure_transition(
    *,
    authorization_id: str,
    evidence_digest: str,
    projection_id: str,
    disclosure_class: str,
    manifest_digest_before: str,
    recipient_class: str,
    provider_or_channel: str,
    purpose: str | None = None,
    selector_digest: str | None = None,
    selector_required_class: str | None = None,
    consume_fn: Any = None,
    persist_receipt_fn: Any = None,
    persist_manifest_fn: Any = None,
    persist_event_fn: Any = None,
) -> tuple[DisclosureTransition, str | None]:
    """Execute a complete disclosure transition through the governed corridor.

    Returns (transition, error_reason_or_None).
    """
    # Check for existing completed transition
    existing = lookup_completed_transition(authorization_id, evidence_digest)
    if existing is not None:
        return existing, None  # Already completed

    _acquire_transition_lock()
    try:
        # 1. Prepare
        t = prepare_transition(
            authorization_id=authorization_id,
            evidence_digest=evidence_digest,
            projection_id=projection_id,
            disclosure_class=disclosure_class,
            manifest_digest_before=manifest_digest_before,
            recipient_class=recipient_class,
            provider_or_channel=provider_or_channel,
            purpose=purpose,
            selector_digest=selector_digest,
            selector_required_class=selector_required_class,
        )

        # 2. Consume authorization
        if consume_fn is not None:
            result = consume_fn()
            if not result:
                advance_transition(
                    t,
                    TransitionStatus.REFUSED,
                    recovery_detail="Authorization consumption failed",
                )
                return t, "Authorization consumption failed"

        t = advance_transition(t, TransitionStatus.AUTHORIZATION_CONSUMED)

        # 3. Persist projection receipt
        if persist_receipt_fn is not None:
            receipt_info = persist_receipt_fn()
            if receipt_info:
                t = advance_transition(
                    t,
                    TransitionStatus.PROJECTION_RECEIPT_PERSISTED,
                    downstream_receipt_digest=receipt_info.get("digest"),
                )
        else:
            t = advance_transition(t, TransitionStatus.PROJECTION_RECEIPT_PERSISTED)

        # 4. Apply manifest mutation
        if persist_manifest_fn is not None:
            manifest_result = persist_manifest_fn()
            t = advance_transition(
                t,
                TransitionStatus.MANIFEST_APPLIED,
                manifest_digest_after=manifest_result.get("manifest_digest_after")
                if manifest_result
                else None,
            )
        else:
            t = advance_transition(t, TransitionStatus.MANIFEST_APPLIED)

        # 5. Persist disclosure event
        if persist_event_fn is not None:
            event_result = persist_event_fn()
            t = advance_transition(
                t,
                TransitionStatus.DISCLOSURE_EVENT_RECORDED,
                downstream_event_id=event_result.get("event_id")
                if event_result
                else None,
            )
        else:
            t = advance_transition(t, TransitionStatus.DISCLOSURE_EVENT_RECORDED)

        # 6. Terminal
        t = advance_transition(t, TransitionStatus.COMPLETED)
        return t, None

    except Exception as exc:
        return advance_transition(
            DisclosureTransition(
                transition_id="dzt_error",
                authorization_id=authorization_id,
                evidence_digest=evidence_digest,
                status=TransitionStatus.RECOVERY_REQUIRED,
            ),
            TransitionStatus.RECOVERY_REQUIRED,
            recovery_detail=str(exc),
        ), str(exc)
    finally:
        _release_transition_lock()


def resume_disclosure_transition(
    authorization_id: str, evidence_digest: str, **kwargs: Any
) -> tuple[DisclosureTransition, str | None]:
    """Resume an incomplete transition. Same as execute if no prior transition."""
    return execute_disclosure_transition(
        authorization_id=authorization_id, evidence_digest=evidence_digest, **kwargs
    )


__all__ = [
    "DisclosureTransition",
    "TransitionStatus",
    "advance_transition",
    "execute_disclosure_transition",
    "lookup_completed_transition",
    "lookup_pending_transition",
    "prepare_transition",
    "resume_disclosure_transition",
]
