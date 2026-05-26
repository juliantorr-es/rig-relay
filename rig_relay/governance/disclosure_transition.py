"""Governed Disclosure Transition Authority — canonical orchestration spine
for disclosure lifecycle.

Owns: transition identity, durable append-only state, exclusive corridor
lock, idempotent downstream persistence, crash recovery.

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


# ═════════════════════════════════════════════════════════════════════════
# Transition model
# ═════════════════════════════════════════════════════════════════════════

TRANSITION_SCHEMA_VERSION = "rig.relay.disclosure_transition_event.v1"


@dataclass
class DisclosureTransition:
    """Content-light disclosure transition record.

    Append-only: each status change produces a new event in the ledger.
    The current state is reconstructable by replaying the ledger.
    """

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
    downstream_receipt_path: str | None = None
    recovery_detail: str | None = None
    transition_digest: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    sequence: int = 0

    def compute_digest(self) -> str:
        payload = {
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
            "downstream_receipt_path": self.downstream_receipt_path,
            "recovery_detail": self.recovery_detail,
            "transition_digest": self.transition_digest,
            "created_at": self.created_at,
            "sequence": self.sequence,
        }


# ═════════════════════════════════════════════════════════════════════════
# Transition store
# ═════════════════════════════════════════════════════════════════════════


def _transition_store_root() -> Path:
    return Path(".build/rig-relay/governance/disclosure-transitions")


def _transition_ledger_path() -> Path:
    return _transition_store_root() / "transitions.jsonl"


def _transition_lock_path() -> Path:
    return _transition_store_root() / "transition.lock"


_transition_lock = threading.Lock()
_transition_lock_fd: int | None = None


def _acquire_transition_lock() -> None:
    global _transition_lock_fd
    _transition_lock.acquire()
    root = _transition_store_root()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = _transition_lock_path()
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
    """fsynced append to JSONL transition ledger."""
    ledger = _transition_ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    with open(ledger, "a") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def _read_transition_events(transition_id: str) -> list[dict[str, Any]]:
    """Replay ledger for a specific transition."""
    ledger = _transition_ledger_path()
    if not ledger.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("transition_id") == transition_id:
            events.append(ev)
    return events


def _find_existing_transition(
    authorization_id: str, evidence_digest: str
) -> DisclosureTransition | None:
    """Find the most recent incomplete or completed transition for this
    authorization + evidence pair.
    """
    events = _read_transition_events(authorization_id)
    if not events:
        return None

    last = events[-1]
    if last.get("evidence_digest") != evidence_digest:
        return None

    t = DisclosureTransition(
        transition_id=last["transition_id"],
        authorization_id=last["authorization_id"],
        evidence_digest=last.get("evidence_digest", ""),
        projection_id=last.get("projection_id", ""),
        disclosure_class=last.get("disclosure_class", ""),
        selector_digest=last.get("selector_digest"),
        selector_required_class=last.get("selector_required_class"),
        manifest_digest_before=last.get("manifest_digest_before", ""),
        manifest_digest_after=last.get("manifest_digest_after"),
        recipient_class=last.get("recipient_class", ""),
        provider_or_channel=last.get("provider_or_channel", ""),
        purpose=last.get("purpose"),
        status=TransitionStatus(last["status"]),
        parent_transition_digest=last.get("parent_transition_digest"),
        downstream_event_id=last.get("downstream_event_id"),
        downstream_receipt_path=last.get("downstream_receipt_path"),
        recovery_detail=last.get("recovery_detail"),
        transition_digest=last.get("transition_digest", ""),
        created_at=last.get("created_at", ""),
        sequence=last.get("sequence", 0),
    )
    return t


# ═════════════════════════════════════════════════════════════════════════
# Transition lifecycle
# ═════════════════════════════════════════════════════════════════════════


def _generate_transition_id() -> str:
    return "dzt_" + secrets.token_hex(12)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


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
        manifest_digest_after=transition.manifest_digest_after
        or updates.get("manifest_digest_after"),
        recipient_class=transition.recipient_class,
        provider_or_channel=transition.provider_or_channel,
        purpose=transition.purpose,
        status=new_status,
        parent_transition_digest=parent_digest,
        downstream_event_id=transition.downstream_event_id
        or updates.get("downstream_event_id"),
        downstream_receipt_path=transition.downstream_receipt_path
        or updates.get("downstream_receipt_path"),
        recovery_detail=updates.get("recovery_detail"),
        created_at=_now_iso(),
        sequence=next_seq,
    )
    t.seal()
    _append_transition_event(t.to_event())
    return t


def lookup_pending_transition(
    authorization_id: str, evidence_digest: str
) -> DisclosureTransition | None:
    """Find an existing incomplete transition. None if no prior transition."""
    return _find_existing_transition(authorization_id, evidence_digest)
