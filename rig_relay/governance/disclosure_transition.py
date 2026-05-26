"""Governed Disclosure Transition Authority v2 — canonical orchestration spine
for the disclosure lifecycle.

v2 binds stable timestamps, compilation receipt digest, retention/training
assertions, and consumed authorization receipt digest in the PREPARED plan.
Recovery reconstructs all downstream artifacts deterministically from the
immutable plan.  v1 plans are rejected on recovery.

Owns: transition identity, durable append-only state, exclusive corridor
lock, idempotent downstream persistence, crash recovery, execute/recover.

Does NOT own:
- authorization issue/validate/consume (delegates to disclosure_authorization)
- manifest construction (delegates to protected_content)
- ZIP bundle generation (delegates to bundle_builder)
- CLI output formatting (CLI consumes this, formats output)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
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
# Transition model  (v2 — backward-incompatible plan extension)
# ═════════════════════════════════════════════════════════════════════════

TRANSITION_SCHEMA_VERSION = "rig.relay.disclosure_transition_event.v2"
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
    # --- v2 plan fields --------------------------------------------------
    retention_assertion: str | None = None
    training_use_assertion: str | None = None
    compilation_receipt_sha256: str = ""
    receipt_approved_at: str = ""
    disclosure_event_created_at: str = ""
    # -- v2 AUTHORIZATION_CONSUMED field -----------------------------------
    consumed_auth_receipt_digest: str | None = None
    # --- lifecycle fields ------------------------------------------------
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
            "retention_assertion": self.retention_assertion,
            "training_use_assertion": self.training_use_assertion,
            "compilation_receipt_sha256": self.compilation_receipt_sha256,
            "receipt_approved_at": self.receipt_approved_at,
            "disclosure_event_created_at": self.disclosure_event_created_at,
            "consumed_auth_receipt_digest": self.consumed_auth_receipt_digest,
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
            "recipient_class": self.recipient_class,
            "provider_or_channel": self.provider_or_channel,
            "purpose": self.purpose,
            "retention_assertion": self.retention_assertion,
            "training_use_assertion": self.training_use_assertion,
            "compilation_receipt_sha256": self.compilation_receipt_sha256,
            "receipt_approved_at": self.receipt_approved_at,
            "disclosure_event_created_at": self.disclosure_event_created_at,
            "consumed_auth_receipt_digest": self.consumed_auth_receipt_digest,
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
# Ledger replay
# ═════════════════════════════════════════════════════════════════════════


def _load_all_ledger_events() -> list[dict[str, Any]]:
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
    events = _load_all_ledger_events()
    chain = [e for e in events if e.get("transition_id") == transition_id]
    chain.sort(key=lambda e: e.get("sequence", 0))
    return chain


def _find_transition_for_auth(
    authorization_id: str, evidence_digest: str
) -> list[dict[str, Any]]:
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
            retention_assertion=ev.get("retention_assertion"),
            training_use_assertion=ev.get("training_use_assertion"),
            compilation_receipt_sha256=ev.get("compilation_receipt_sha256", ""),
            receipt_approved_at=ev.get("receipt_approved_at", ""),
            disclosure_event_created_at=ev.get("disclosure_event_created_at", ""),
            consumed_auth_receipt_digest=ev.get("consumed_auth_receipt_digest"),
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
    last = _last_event_for_auth(authorization_id, evidence_digest)
    if last is None:
        return None
    t = _event_to_transition(last)
    if t is None or not t.is_terminal():
        return None
    return t


# ═════════════════════════════════════════════════════════════════════════
# Test-only crash failpoint
# ═════════════════════════════════════════════════════════════════════════

_failpoint: Callable[[TransitionStatus], None] | None = None


def _inject_failpoint(hook: Callable[[TransitionStatus], None]) -> None:
    """Test-only injection seam. Production callers must never invoke this."""
    global _failpoint
    _failpoint = hook


def _maybe_crash(status: TransitionStatus) -> None:
    if _failpoint is not None:
        _failpoint(status)


# ═════════════════════════════════════════════════════════════════════════
# Durable write helpers
# ═════════════════════════════════════════════════════════════════════════


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomic temp-file replace + file fsync + parent-directory fsync."""
    content = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".json")
    try:
        os.write(fd, content)
        os.fsync(fd)
        os.close(fd)
        os.replace(tmp_path, str(path))
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _durable_append_jsonl(path: Path, event: dict[str, Any]) -> None:
    """Append + flush + fsync under exclusive flock for durable JSONL write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_APPEND)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ═════════════════════════════════════════════════════════════════════════
# Artifact identity helpers
# ═════════════════════════════════════════════════════════════════════════


def _receipt_identity(transition_id: str) -> str:
    return f"dza_{transition_id}"


def _event_identity(transition_id: str) -> str:
    return f"dze_{transition_id}"


def _output_dir() -> Path:
    return Path(".build/rig-relay/review_projection")


def _compilation_receipt_path(projection_id: str) -> Path:
    return _output_dir() / f"receipt_{projection_id}.json"


def _manifest_path(projection_id: str) -> Path:
    return _output_dir() / f"protected_content_manifest_{projection_id}.json"


def _disclosure_event_ledger_path() -> Path:
    return Path(".build/rig-relay/governance/disclosure_events.v1.jsonl")


# ═════════════════════════════════════════════════════════════════════════
# Downstream artifact persistence — idempotent, durable, plan-bound
# ═════════════════════════════════════════════════════════════════════════


def _build_disclosure_receipt(transition: DisclosureTransition) -> dict[str, Any]:
    """Build the review-projection DisclosureAuthorizationReceipt dict from
    the plan. Every field is deterministically derived from the plan or
    referenced on-disk artifacts validated against the plan.
    """
    from rig_relay.review_projection.models import DisclosureTarget

    rcpt_path = _compilation_receipt_path(transition.projection_id)
    if not rcpt_path.exists():
        raise FileNotFoundError(
            f"Compilation receipt missing for projection "
            f"{transition.projection_id}: {rcpt_path}"
        )
    actual_sha = hashlib.sha256(rcpt_path.read_bytes()).hexdigest()
    if actual_sha != transition.compilation_receipt_sha256:
        raise ValueError(
            f"Compilation receipt SHA256 mismatch: "
            f"bound {transition.compilation_receipt_sha256[:16]}..., "
            f"actual {actual_sha[:16]}..."
        )

    # re-read consumed auth receipt digest from durable plan
    from rig_relay.governance.disclosure_authorization import (
        _load_receipt as _load_gov_receipt,
    )

    auth_receipt = _load_gov_receipt(transition.authorization_id)
    auth_receipt_digest = auth_receipt.receipt_sha256 if auth_receipt else ""
    if (
        transition.consumed_auth_receipt_digest
        and transition.consumed_auth_receipt_digest != auth_receipt_digest
    ):
        raise ValueError(
            f"Authorization receipt digest mismatch: "
            f"bound {transition.consumed_auth_receipt_digest[:16]}..., "
            f"actual {auth_receipt_digest[:16]}..."
        )

    return {
        "schema_version": "rig.review_projection.disclosure_authorization.v1",
        "authorization_id": _receipt_identity(transition.transition_id),
        "projection_id": transition.projection_id,
        "candidate_zip_sha256": transition.evidence_digest,
        "compilation_receipt_sha256": transition.compilation_receipt_sha256,
        "recipient_class": DisclosureTarget(transition.recipient_class).value,
        "provider_or_channel": transition.provider_or_channel,
        "purpose_or_context": transition.purpose,
        "retention_assertion": transition.retention_assertion,
        "training_use_assertion": transition.training_use_assertion,
        "is_transmission_authorized": False,
        "approved_by": "governance_disclosure_authorization",
        "approved_at": transition.receipt_approved_at,
        "authorization_receipt_sha256": auth_receipt_digest,
        "human_export_approval_required": True,
        "controlled_disclosure_measures_recorded": True,
        "does_not_determine_trade_secret_protection": True,
        "recipient_conditions_are_user_asserted_not_verified": True,
    }


def _persist_receipt_durable(transition: DisclosureTransition) -> str:
    """Atomically persist the disclosure receipt, idempotent on transition_id."""
    rcpt_dir = _output_dir()
    rcpt_dir.mkdir(parents=True, exist_ok=True)
    rcpt_path = (
        rcpt_dir
        / f"disclosure_authorization_{_receipt_identity(transition.transition_id)}.json"
    )

    receipt_data = _build_disclosure_receipt(transition)

    if rcpt_path.exists():
        existing = json.loads(rcpt_path.read_text("utf-8"))
        for key, expected in receipt_data.items():
            actual = existing.get(key)
            if actual != expected:
                raise ValueError(
                    f"Existing receipt field {key} mismatch: "
                    f"expected {expected!r}, got {actual!r}"
                )
        return _receipt_identity(transition.transition_id)

    _atomic_write_json(rcpt_path, receipt_data)
    return _receipt_identity(transition.transition_id)


def _compute_post_mutation_manifest(
    manifest: Any, selector_digest: str
) -> tuple[Any, str]:
    """Apply the planned selector mutation to produce the post-image manifest
    and its digest.  Does NOT write to disk — caller owns persistence.
    """
    from rig_relay.review_projection.protected_content import (
        mark_selector_disclosed,
        seal_manifest,
    )

    clone_data = (
        manifest.model_copy(deep=True)
        if hasattr(manifest, "model_copy")
        else manifest.copy()
    )  # type: ignore[union-attr]
    mark_selector_disclosed(clone_data, selector_digest)
    seal_manifest(clone_data)
    return clone_data, clone_data.manifest_digest


def _validate_manifest_post_image(
    manifest: Any, expected_post_digest: str
) -> tuple[bool, str | None]:
    """Check whether the on-disk manifest digest matches the expected post-
    mutation image.
    """
    from rig_relay.review_projection.protected_content import compute_manifest_digest

    actual = compute_manifest_digest(manifest)
    if actual == expected_post_digest:
        return True, None
    return (
        False,
        f"post-image digest mismatch: expected {expected_post_digest[:16]}..., actual {actual[:16]}...",
    )


def _apply_manifest_mutation(transition: DisclosureTransition) -> str:
    """Two-image manifest validation and idempotent mutation.

    If manifest_digest_before matches the on-disk manifest → apply mutation.
    If the on-disk manifest already matches the exact permitted post-image → reuse.
    Otherwise → CORRUPT refusal.
    Returns the manifest_digest_after.
    """
    from rig_relay.review_projection.protected_content import (
        compute_manifest_digest,
        load_manifest_json,
        mark_selector_disclosed,
        seal_manifest,
    )

    mpath = _manifest_path(transition.projection_id)
    if not mpath.exists():
        raise FileNotFoundError(f"Manifest missing: {mpath}")

    manifest = load_manifest_json(str(mpath))
    if manifest is None:
        raise ValueError(f"Manifest corrupt or unloadable: {mpath}")

    current_digest = compute_manifest_digest(manifest)

    # Image 1: precondition
    if current_digest == transition.manifest_digest_before:
        selector = transition.selector_digest
        if selector:
            mark_selector_disclosed(manifest, selector)
            seal_manifest(manifest)
            _atomic_write_json(mpath, manifest.model_dump())
        else:
            seal_manifest(manifest)
            _atomic_write_json(mpath, manifest.model_dump())
        return manifest.manifest_digest

    # Image 2: exact permitted post-image — crash after durable write,
    # before MANIFEST_APPLIED transition advancement.
    post_image, post_digest = _compute_post_mutation_manifest(
        manifest, transition.selector_digest or ""
    )
    if current_digest == post_digest:
        return current_digest

    # Unknown state
    raise ValueError(
        f"Manifest digest does not match precondition "
        f"({transition.manifest_digest_before[:16]}...) "
        f"or expected post-image ({post_digest[:16]}...). "
        f"Current: {current_digest[:16]}.... Mutation refused."
    )


def _build_disclosure_event(
    transition: DisclosureTransition, manifest: Any | None = None
) -> dict[str, Any]:
    """Build the content-light disclosure event dict from the plan."""
    event: dict[str, Any] = {
        "schema_version": "rig.relay.disclosure_event.v1",
        "event_id": _event_identity(transition.transition_id),
        "authorization_id": transition.authorization_id,
        "authorization_receipt_sha256": (transition.consumed_auth_receipt_digest or ""),
        "evidence_digest": transition.evidence_digest,
        "disclosure_class": transition.disclosure_class,
        "recipient_class": transition.recipient_class,
        "projection_id": transition.projection_id,
        "created_at": transition.disclosure_event_created_at,
        "outcome": "authorized",
        "transition_id": transition.transition_id,
    }
    if manifest is not None:
        event["manifest_digest_before"] = transition.manifest_digest_before
        event["manifest_digest"] = (
            manifest.manifest_digest if hasattr(manifest, "manifest_digest") else ""
        )
    if transition.selector_digest:
        event["selector_digest"] = transition.selector_digest
        event["selector_disclosed"] = True
    if transition.manifest_digest_after:
        event["manifest_digest_after"] = transition.manifest_digest_after
    return event


def _persist_disclosure_event_durable(
    transition: DisclosureTransition, manifest: Any | None = None
) -> str:
    """Durably append the disclosure event, deduplicated by transition_id."""
    event = _build_disclosure_event(transition, manifest)
    ledger = _disclosure_event_ledger_path()
    event_id = _event_identity(transition.transition_id)

    if ledger.exists():
        for line in ledger.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                existing = json.loads(line)
            except json.JSONDecodeError:
                continue
            if existing.get("transition_id") == transition.transition_id:
                return event_id

    _durable_append_jsonl(ledger, event)
    return event_id


# ═════════════════════════════════════════════════════════════════════════
# Transition lifecycle — v2 plan preparation
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
    retention_assertion: str | None = None,
    training_use_assertion: str | None = None,
    compilation_receipt_sha256: str = "",
) -> DisclosureTransition:
    existing = lookup_pending_transition(authorization_id, evidence_digest)
    if existing is not None:
        return existing

    # Validate compilation receipt exists and matches if provided
    if compilation_receipt_sha256:
        rcpt_path = _compilation_receipt_path(projection_id)
        if not rcpt_path.exists():
            raise FileNotFoundError(
                f"Compilation receipt missing for projection "
                f"{projection_id}: {rcpt_path}"
            )
        actual_sha = hashlib.sha256(rcpt_path.read_bytes()).hexdigest()
        if actual_sha != compilation_receipt_sha256:
            raise ValueError(
                f"Compilation receipt SHA256 mismatch: "
                f"provided {compilation_receipt_sha256[:16]}..., "
                f"actual {actual_sha[:16]}..."
            )

    now = datetime.now(UTC).isoformat()

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
        retention_assertion=retention_assertion,
        training_use_assertion=training_use_assertion,
        compilation_receipt_sha256=compilation_receipt_sha256,
        receipt_approved_at=now,
        disclosure_event_created_at=now,
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
        retention_assertion=transition.retention_assertion,
        training_use_assertion=transition.training_use_assertion,
        compilation_receipt_sha256=transition.compilation_receipt_sha256,
        receipt_approved_at=transition.receipt_approved_at,
        disclosure_event_created_at=transition.disclosure_event_created_at,
        consumed_auth_receipt_digest=updates.get(
            "consumed_auth_receipt_digest", transition.consumed_auth_receipt_digest
        ),
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
# Production API — execute and recover
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
    retention_assertion: str | None = None,
    training_use_assertion: str | None = None,
    compilation_receipt_sha256: str = "",
) -> tuple[DisclosureTransition | None, str | None]:
    """Execute a complete disclosure transition through the governed corridor.

    All downstream artifacts are owned and durably persisted by the
    transition authority. No callback functions, no generic dicts.

    Returns (transition, error_reason_or_None).
    """
    from rig_relay.governance.disclosure_authorization import (
        DisclosureOutcome,
        consume_disclosure_authorization,
    )

    existing = lookup_completed_transition(authorization_id, evidence_digest)
    if existing is not None:
        return existing, None

    _acquire_transition_lock()
    try:
        # 1. PREPARED — durable plan
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
            retention_assertion=retention_assertion,
            training_use_assertion=training_use_assertion,
            compilation_receipt_sha256=compilation_receipt_sha256,
        )

        # 2. AUTHORIZATION_CONSUMED
        consume_result = consume_disclosure_authorization(
            authorization_id,
            current_evidence_digest=evidence_digest,
            current_disclosure_class=disclosure_class,
            current_selector_digest=selector_digest,
            current_required_selector_class=selector_required_class,
        )
        if consume_result.outcome != DisclosureOutcome.CONSUMED:
            ref = advance_transition(
                t,
                TransitionStatus.REFUSED,
                recovery_detail=(
                    f"Authorization consumption failed: "
                    f"{consume_result.outcome.value}"
                    f"{' — ' + consume_result.error_detail if consume_result.error_detail else ''}"
                ),
            )
            return (
                ref,
                consume_result.error_detail or "Authorization consumption failed",
            )

        consumed_digest = (
            consume_result.receipt.receipt_sha256 if consume_result.receipt else ""
        )
        t = advance_transition(
            t,
            TransitionStatus.AUTHORIZATION_CONSUMED,
            consumed_auth_receipt_digest=consumed_digest,
        )
        _maybe_crash(TransitionStatus.AUTHORIZATION_CONSUMED)

        # 3. PROJECTION_RECEIPT_PERSISTED
        try:
            receipt_id = _persist_receipt_durable(t)
        except (FileNotFoundError, ValueError, OSError) as exc:
            ref = advance_transition(
                t,
                TransitionStatus.REFUSED,
                recovery_detail=f"Receipt persistence failed: {exc}",
            )
            return ref, str(exc)

        t = advance_transition(
            t,
            TransitionStatus.PROJECTION_RECEIPT_PERSISTED,
            downstream_receipt_digest=receipt_id,
        )
        _maybe_crash(TransitionStatus.PROJECTION_RECEIPT_PERSISTED)

        # 4. MANIFEST_APPLIED — two-image validation rule
        try:
            manifest_digest_after = _apply_manifest_mutation(t)
        except (FileNotFoundError, ValueError, OSError) as exc:
            ref = advance_transition(
                t,
                TransitionStatus.CORRUPT,
                corrupt_detail=f"Manifest mutation failed: {exc}",
            )
            return ref, str(exc)

        t = advance_transition(
            t,
            TransitionStatus.MANIFEST_APPLIED,
            manifest_digest_after=manifest_digest_after,
        )
        _maybe_crash(TransitionStatus.MANIFEST_APPLIED)

        # 5. DISCLOSURE_EVENT_RECORDED
        try:
            from rig_relay.review_projection.protected_content import load_manifest_json

            manifest = load_manifest_json(str(_manifest_path(projection_id)))
        except Exception:
            manifest = None

        try:
            event_id = _persist_disclosure_event_durable(t, manifest)
        except (ValueError, OSError) as exc:
            ref = advance_transition(
                t,
                TransitionStatus.RECOVERY_REQUIRED,
                recovery_detail=f"Disclosure event persistence failed: {exc}",
            )
            return ref, str(exc)

        t = advance_transition(
            t,
            TransitionStatus.DISCLOSURE_EVENT_RECORDED,
            downstream_event_id=event_id,
            manifest_digest_after=manifest_digest_after,
        )
        _maybe_crash(TransitionStatus.DISCLOSURE_EVENT_RECORDED)

        # 6. COMPLETED
        t = advance_transition(t, TransitionStatus.COMPLETED)
        return t, None

    except Exception as exc:
        return None, str(exc)
    finally:
        _release_transition_lock()


def recover_disclosure_transition(
    authorization_id: str, evidence_digest: str
) -> tuple[DisclosureTransition | None, str | None]:
    """Recover an in-progress disclosure transition from durable evidence.

    Reads the PREPARED plan from the transition ledger. All governance
    fields come from the immutable plan — the caller supplies only lookup
    keys. v1 plans are rejected.

    Returns (transition, error_reason_or_None).
    """
    from rig_relay.governance.disclosure_authorization import (
        DisclosureOutcome,
        consume_disclosure_authorization,
    )

    last_event = _last_event_for_auth(authorization_id, evidence_digest)
    if last_event is None:
        return None, "no transition exists for this authorization and evidence digest"

    sv = last_event.get("schema_version", "")
    if sv != TRANSITION_SCHEMA_VERSION:
        return None, (
            f"incompatible transition plan schema {sv!r}, "
            f"expected {TRANSITION_SCHEMA_VERSION!r}"
        )

    plan = _event_to_transition(last_event)
    if plan is None:
        return None, "transition plan corrupt or unparseable"

    # Already terminal
    if plan.is_terminal():
        if plan.status == TransitionStatus.COMPLETED:
            plan.recovery_detail = "recovered_already_complete"
            return plan, None
        return plan, f"cannot recover terminal transition: {plan.status.value}"

    last_status = plan.status

    _acquire_transition_lock()
    try:
        t = plan

        # Resume from the NEXT step after last_status
        if last_status not in {
            TransitionStatus.AUTHORIZATION_CONSUMED,
            TransitionStatus.PROJECTION_RECEIPT_PERSISTED,
            TransitionStatus.MANIFEST_APPLIED,
            TransitionStatus.DISCLOSURE_EVENT_RECORDED,
        }:
            # Only PREPARED or unknown — must consume authorization first
            consume_result = consume_disclosure_authorization(
                authorization_id,
                current_evidence_digest=evidence_digest,
                current_disclosure_class=plan.disclosure_class,
                current_selector_digest=plan.selector_digest,
                current_required_selector_class=plan.selector_required_class,
            )
            if consume_result.outcome != DisclosureOutcome.CONSUMED:
                ref = advance_transition(
                    t,
                    TransitionStatus.REFUSED,
                    recovery_detail=(
                        f"Authorization consumption failed during recovery: "
                        f"{consume_result.outcome.value}"
                    ),
                )
                return (
                    ref,
                    consume_result.error_detail
                    or "Authorization consumption failed during recovery",
                )

            consumed_digest = (
                consume_result.receipt.receipt_sha256 if consume_result.receipt else ""
            )
            t = advance_transition(
                t,
                TransitionStatus.AUTHORIZATION_CONSUMED,
                consumed_auth_receipt_digest=consumed_digest,
            )

        # AUTHORIZATION_CONSUMED bound by plan — validate on-disk receipt
        if t.consumed_auth_receipt_digest:
            from rig_relay.governance.disclosure_authorization import (
                _load_receipt as _load_gov_receipt,
            )

            gov_receipt = _load_gov_receipt(authorization_id)
            if gov_receipt is None:
                ref = advance_transition(
                    t,
                    TransitionStatus.CORRUPT,
                    corrupt_detail="Authorization receipt missing after AUTHORIZATION_CONSUMED",
                )
                return ref, "Authorization receipt missing after AUTHORIZATION_CONSUMED"
            if gov_receipt.receipt_sha256 != t.consumed_auth_receipt_digest:
                ref = advance_transition(
                    t,
                    TransitionStatus.CORRUPT,
                    corrupt_detail=(
                        f"Authorization receipt digest mismatch: "
                        f"bound {t.consumed_auth_receipt_digest[:16]}..., "
                        f"actual {gov_receipt.receipt_sha256[:16]}..."
                    ),
                )
                return ref, "Authorization receipt digest mismatch during recovery"

        # Step 3: Receipt persistence (skip if already done)
        if last_status in {
            TransitionStatus.AUTHORIZATION_CONSUMED,
            TransitionStatus.PREPARED,
        }:
            try:
                receipt_id = _persist_receipt_durable(t)
            except (FileNotFoundError, ValueError, OSError) as exc:
                ref = advance_transition(
                    t,
                    TransitionStatus.RECOVERY_REQUIRED,
                    recovery_detail=f"Receipt persistence failed during recovery: {exc}",
                )
                return ref, str(exc)

            t = advance_transition(
                t,
                TransitionStatus.PROJECTION_RECEIPT_PERSISTED,
                downstream_receipt_digest=receipt_id,
            )

        # Step 4: Manifest application (skip if already applied)
        if last_status in {
            TransitionStatus.PROJECTION_RECEIPT_PERSISTED,
            TransitionStatus.AUTHORIZATION_CONSUMED,
            TransitionStatus.PREPARED,
        }:
            try:
                manifest_digest_after = _apply_manifest_mutation(t)
            except (FileNotFoundError, ValueError, OSError) as exc:
                ref = advance_transition(
                    t,
                    TransitionStatus.CORRUPT,
                    corrupt_detail=f"Manifest mutation failed during recovery: {exc}",
                )
                return ref, str(exc)

            t = advance_transition(
                t,
                TransitionStatus.MANIFEST_APPLIED,
                manifest_digest_after=manifest_digest_after,
            )

        # Step 5: Disclosure event (skip if already recorded)
        if last_status in {
            TransitionStatus.MANIFEST_APPLIED,
            TransitionStatus.PROJECTION_RECEIPT_PERSISTED,
            TransitionStatus.AUTHORIZATION_CONSUMED,
            TransitionStatus.PREPARED,
        }:
            try:
                from rig_relay.review_projection.protected_content import (
                    load_manifest_json,
                )

                manifest = load_manifest_json(str(_manifest_path(t.projection_id)))
            except Exception:
                manifest = None

            try:
                event_id = _persist_disclosure_event_durable(t, manifest)
            except (ValueError, OSError) as exc:
                ref = advance_transition(
                    t,
                    TransitionStatus.RECOVERY_REQUIRED,
                    recovery_detail=f"Disclosure event persistence failed during recovery: {exc}",
                )
                return ref, str(exc)

            t = advance_transition(
                t,
                TransitionStatus.DISCLOSURE_EVENT_RECORDED,
                downstream_event_id=event_id,
                manifest_digest_after=t.manifest_digest_after,
            )

        # Step 6: COMPLETED
        t = advance_transition(t, TransitionStatus.COMPLETED)
        t.recovery_detail = "recovered_and_completed"
        return t, None

    except Exception as exc:
        return None, str(exc)
    finally:
        _release_transition_lock()


__all__ = [
    "TRANSITION_SCHEMA_VERSION",
    "DisclosureTransition",
    "TransitionStatus",
    "advance_transition",
    "execute_disclosure_transition",
    "lookup_completed_transition",
    "lookup_pending_transition",
    "prepare_transition",
    "recover_disclosure_transition",
]
