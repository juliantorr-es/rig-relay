"""Generic Disclosure Authorization Authority v1.

Governed, narrow-scoped temporary disclosure rights over opaque
evidence objects. Supports issue, validate, consume, expire, and
refuse semantics with evidence-freshness enforcement.

Lane A owns this generic authority substrate. Lane B will later
consume it for Git-specific disclosure implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum, auto
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading

from pydantic import BaseModel, ConfigDict, Field

# ── Disclosure classes ────────────────────────────────────────────────────────


class DisclosureClass(StrEnum):
    PATH_IDENTITY = auto()
    PATH_INVENTORY = auto()
    BRANCH_IDENTITY = auto()
    BRANCH_ENUMERATION = auto()
    COMMIT_SUBJECT = auto()
    COMMIT_BODY = auto()
    COMMIT_PATCH = auto()
    METADATA_DISCLOSURE = auto()
    RAW_CONTENT = auto()


# The default policy blocks broad raw-content disclosure.
# Narrow classes are permitted by default.
RESTRICTED_DISCLOSURE_CLASSES: frozenset[str] = frozenset({
    DisclosureClass.RAW_CONTENT.value,
    DisclosureClass.COMMIT_PATCH.value,
})


# ── Authorization receipt model ──────────────────────────────────────────────


DISCLOSURE_AUTHZ_SCHEMA_VERSION = "rig.relay.disclosure_authorization_receipt.v1"


class DisclosureAuthorizationReceipt(BaseModel):
    """Narrow-scoped temporary disclosure authorization receipt.

    Binds to a specific evidence digest and disclosure class.
    Supports single-use or bounded-use consumption.
    Carries issuance identity, expiry, and integrity digest.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = DISCLOSURE_AUTHZ_SCHEMA_VERSION
    authorization_id: str = Field(default_factory=lambda: _generate_id())
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    evidence_digest: str = ""
    disclosure_class: str = ""
    requested_selector: str | None = None
    actor_identity: str = ""
    producer_identity: str = ""
    purpose: str = ""
    issued_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str = ""
    one_time: bool = True
    max_uses: int = 1
    use_count: int = 0
    consumed: bool = False
    receipt_sha256: str = ""

    def recompute_integrity(self) -> str:
        payload = self.model_dump(exclude={"receipt_sha256"})
        payload["receipt_sha256"] = ""
        payload_data = json.dumps(payload, sort_keys=True).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload_data).hexdigest()

    def seal(self) -> None:
        self.receipt_sha256 = self.recompute_integrity()

    def verify_integrity(self) -> bool:
        return self.receipt_sha256 == self.recompute_integrity()


# ── Outcomes ─────────────────────────────────────────────────────────────────


class DisclosureOutcome(StrEnum):
    ISSUED = auto()
    VALID = auto()
    EXPIRED = auto()
    CONSUMED = auto()
    EVIDENCE_MISMATCH = auto()
    UNSUPPORTED_CLASS = auto()
    CLASS_MISMATCH = auto()
    SELECTOR_MISMATCH = auto()
    SELECTOR_UNAUTHORIZED = auto()
    SELECTOR_REQUIRED_CLASS_MISMATCH = auto()
    NOT_FOUND = auto()
    CORRUPT = auto()
    ALREADY_CONSUMED = auto()
    ALREADY_EXPIRED = auto()
    UNKNOWN = auto()


@dataclass(slots=True)
class DisclosureResult:
    outcome: DisclosureOutcome
    authorization_id: str = ""
    receipt: DisclosureAuthorizationReceipt | None = None
    error_detail: str = ""

    @property
    def is_authorized(self) -> bool:
        return self.outcome in {DisclosureOutcome.ISSUED, DisclosureOutcome.VALID}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _generate_id() -> str:
    return "disc_" + secrets.token_hex(16)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Exclusive consumption locking ─────────────────────────────────────────────

# In-process lock (per process) + cross-process file lock (per store).
# Reuses the established Rig Relay pattern from coordination/store.py.
_consume_lock = threading.Lock()
_consume_lock_fd: int | None = None


def _acquire_consume_lock() -> None:
    global _consume_lock_fd
    _consume_lock.acquire()
    lock_path = _store_root() / "consume.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    _consume_lock_fd = fd


def _release_consume_lock() -> None:
    global _consume_lock_fd
    if _consume_lock_fd is not None:
        fcntl.flock(_consume_lock_fd, fcntl.LOCK_UN)
        try:
            os.close(_consume_lock_fd)
        except OSError:
            pass
        _consume_lock_fd = None
    _consume_lock.release()


def _atomic_write_receipt(receipt: DisclosureAuthorizationReceipt, path: Path) -> None:
    """Write receipt with atomic temp-file replace + fsync."""
    data = json.dumps(receipt.model_dump(), indent=2, sort_keys=True) + "\n"
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".json")
    try:
        os.write(fd, data.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        os.replace(tmp_path, str(path))
        # fsync parent directory for durability
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


def _store_root() -> Path:
    return Path(".build/rig-relay/desktop/disclosure-authorizations")


def _receipt_path(authorization_id: str) -> Path:
    """Path for a disclosure authorization receipt, keyed by stable authorization_id."""
    return _store_root() / f"{authorization_id}.json"


def _persist_receipt(receipt: DisclosureAuthorizationReceipt) -> str | None:
    store = _store_root()
    try:
        store.mkdir(parents=True, exist_ok=True)
        path = _receipt_path(receipt.authorization_id)
        path.write_text(
            json.dumps(receipt.model_dump(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return str(path)
    except OSError:
        return None


def _load_receipt(authorization_id: str) -> DisclosureAuthorizationReceipt | None:
    path = _receipt_path(authorization_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return DisclosureAuthorizationReceipt.model_validate(data)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None


# ── Issue authorization ──────────────────────────────────────────────────────


def issue_disclosure_authorization(
    *,
    evidence_digest: str,
    disclosure_class: str,
    requested_selector: str | None = None,
    actor_identity: str = "",
    producer_identity: str = "",
    purpose: str = "",
    ttl_minutes: int = 15,
    one_time: bool = True,
    max_uses: int = 1,
) -> DisclosureResult:
    """Issue a narrow-scoped disclosure authorization receipt.

    Args:
        evidence_digest: SHA256 digest of the opaque evidence object.
        disclosure_class: One of the DisclosureClass values.
        requested_selector: Optional pseudonymous selector within evidence.
        actor_identity: Identity of the requesting actor.
        producer_identity: Identity of the evidence producer.
        purpose: Documented purpose for the disclosure.
        ttl_minutes: Time-to-live in minutes.
        one_time: Whether the receipt is single-use.
        max_uses: Maximum uses (only meaningful when one_time=False).

    Returns:
        DisclosureResult with the sealed receipt on success.
    """
    valid_classes = {c.value for c in DisclosureClass}
    if disclosure_class not in valid_classes:
        return DisclosureResult(
            outcome=DisclosureOutcome.UNSUPPORTED_CLASS,
            error_detail=f"Unsupported disclosure class: {disclosure_class}. "
            f"Valid classes: {sorted(valid_classes)}",
        )

    now = datetime.now(UTC)
    expires = now + timedelta(minutes=ttl_minutes)

    receipt = DisclosureAuthorizationReceipt(
        evidence_digest=evidence_digest,
        disclosure_class=disclosure_class,
        requested_selector=requested_selector,
        actor_identity=actor_identity,
        producer_identity=producer_identity,
        purpose=purpose,
        issued_at=now.isoformat(),
        expires_at=expires.isoformat(),
        one_time=one_time,
        max_uses=max_uses,
    )
    receipt.seal()

    path = _persist_receipt(receipt)
    if path is None:
        return DisclosureResult(
            outcome=DisclosureOutcome.UNKNOWN,
            error_detail="Failed to persist disclosure authorization receipt",
        )

    return DisclosureResult(
        outcome=DisclosureOutcome.ISSUED,
        authorization_id=receipt.authorization_id,
        receipt=receipt,
    )


# ── Validate authorization ───────────────────────────────────────────────────


def validate_disclosure_authorization(
    authorization_id: str,
    *,
    current_evidence_digest: str | None = None,
    current_disclosure_class: str | None = None,
    current_selector_digest: str | None = None,
    current_required_selector_class: str | None = None,
) -> DisclosureResult:
    """Validate a disclosure authorization receipt against current evidence.

    Checks integrity, expiry, consumption, evidence freshness,
    disclosure class validity, and optional class/selector scope binding.

    Args:
        authorization_id: Stable authorization identifier (not receipt_sha256).
        current_evidence_digest: Current evidence digest for freshness check.
        current_disclosure_class: If provided, receipt's class must match.
        current_selector_digest: If provided, must match receipt's
            requested_selector. Fail-closed: a scoped receipt cannot
            authorize unscoped disclosure, and vice versa.
        current_required_selector_class: If provided, the manifest selector's
            required disclosure class must equal the receipt's class and the
            operation's class (three-way match).

    Returns:
        DisclosureResult with validation outcome.
    """
    receipt = _load_receipt(authorization_id)
    if receipt is None or not receipt.verify_integrity():
        outcome = (
            DisclosureOutcome.NOT_FOUND
            if receipt is None
            else DisclosureOutcome.CORRUPT
        )
        detail = (
            f"Receipt not found: {authorization_id}"
            if receipt is None
            else "Receipt integrity check failed"
        )
        return DisclosureResult(
            outcome=outcome,
            authorization_id=authorization_id
            if receipt is None
            else receipt.authorization_id,
            error_detail=detail,
        )

    # Expiry check
    try:
        expires = datetime.fromisoformat(receipt.expires_at)
        expired = datetime.now(UTC) >= expires
    except (ValueError, TypeError):
        return DisclosureResult(
            outcome=DisclosureOutcome.CORRUPT,
            authorization_id=receipt.authorization_id,
            error_detail="Invalid expires_at format",
        )
    if expired:
        return DisclosureResult(
            outcome=DisclosureOutcome.EXPIRED,
            authorization_id=receipt.authorization_id,
            receipt=receipt,
            error_detail=f"Receipt expired at {receipt.expires_at}",
        )

    # Consumption check
    consumed = (receipt.one_time and receipt.consumed) or (
        not receipt.one_time and receipt.use_count >= receipt.max_uses
    )
    if consumed:
        detail = (
            "One-time receipt already consumed"
            if receipt.one_time
            else f"Bounded-use receipt exhausted ({receipt.use_count}/{receipt.max_uses})"
        )
        return DisclosureResult(
            outcome=DisclosureOutcome.ALREADY_CONSUMED,
            authorization_id=receipt.authorization_id,
            receipt=receipt,
            error_detail=detail,
        )

    # Evidence freshness
    valid_classes = {c.value for c in DisclosureClass}
    if current_evidence_digest and receipt.evidence_digest != current_evidence_digest:
        return DisclosureResult(
            outcome=DisclosureOutcome.EVIDENCE_MISMATCH,
            authorization_id=receipt.authorization_id,
            receipt=receipt,
            error_detail=(
                f"Evidence digest mismatch: receipt bound to "
                f"{receipt.evidence_digest[:16]}..., "
                f"current evidence is {current_evidence_digest[:16]}..."
            ),
        )
    if receipt.disclosure_class not in valid_classes:
        return DisclosureResult(
            outcome=DisclosureOutcome.UNSUPPORTED_CLASS,
            authorization_id=receipt.authorization_id,
            receipt=receipt,
            error_detail=f"Unsupported disclosure class: {receipt.disclosure_class}",
        )

    # P4.2: Disclosure class and selector scope binding.
    # Only enforced when the caller provides disclosure context parameters.
    if current_disclosure_class or current_selector_digest:
        # Class binding
        if (
            current_disclosure_class
            and receipt.disclosure_class != current_disclosure_class
        ):
            return DisclosureResult(
                outcome=DisclosureOutcome.CLASS_MISMATCH,
                authorization_id=receipt.authorization_id,
                receipt=receipt,
                error_detail=(
                    f"Disclosure class mismatch: receipt authorized for "
                    f"'{receipt.disclosure_class}', requested "
                    f"'{current_disclosure_class}'"
                ),
            )

        # Selector scope binding (fail-closed)
        receipt_has_selector = bool(receipt.requested_selector)
        request_has_selector = bool(current_selector_digest)

        if receipt_has_selector and not request_has_selector:
            return DisclosureResult(
                outcome=DisclosureOutcome.SELECTOR_UNAUTHORIZED,
                authorization_id=receipt.authorization_id,
                receipt=receipt,
                error_detail=(
                    f"Selector-bound receipt cannot authorize unscoped disclosure. "
                    f"Receipt is bound to selector "
                    f"{receipt.requested_selector[:16]}..."
                ),
            )
        if request_has_selector and not receipt_has_selector:
            return DisclosureResult(
                outcome=DisclosureOutcome.SELECTOR_UNAUTHORIZED,
                authorization_id=receipt.authorization_id,
                receipt=receipt,
                error_detail=(
                    "Unscoped receipt cannot authorize selector-level disclosure. "
                    "Issue a new receipt with requested_selector."
                ),
            )
        if request_has_selector and receipt_has_selector:
            if receipt.requested_selector != current_selector_digest:
                return DisclosureResult(
                    outcome=DisclosureOutcome.SELECTOR_MISMATCH,
                    authorization_id=receipt.authorization_id,
                    receipt=receipt,
                    error_detail=(
                        f"Selector mismatch: receipt bound to "
                        f"{receipt.requested_selector[:16]}..., "
                        f"requested {current_selector_digest[:16]}..."
                    ),
                )

    # P4.3: Three-way selector required-class match.
    # When manifest selector requires a class, the receipt and operation
    # must both authorize exactly that class.
    if current_required_selector_class:
        if receipt.disclosure_class != current_required_selector_class:
            return DisclosureResult(
                outcome=DisclosureOutcome.SELECTOR_REQUIRED_CLASS_MISMATCH,
                authorization_id=receipt.authorization_id,
                receipt=receipt,
                error_detail=(
                    f"Selector requires class '{current_required_selector_class}' "
                    f"but receipt authorizes '{receipt.disclosure_class}'"
                ),
            )
        if (
            current_disclosure_class
            and current_disclosure_class != current_required_selector_class
        ):
            return DisclosureResult(
                outcome=DisclosureOutcome.SELECTOR_REQUIRED_CLASS_MISMATCH,
                authorization_id=receipt.authorization_id,
                receipt=receipt,
                error_detail=(
                    f"Selector requires class '{current_required_selector_class}' "
                    f"but operation requests '{current_disclosure_class}'"
                ),
            )

    return DisclosureResult(
        outcome=DisclosureOutcome.VALID,
        authorization_id=receipt.authorization_id,
        receipt=receipt,
    )


# ── Consume authorization ────────────────────────────────────────────────────


def consume_disclosure_authorization(
    authorization_id: str,
    *,
    current_evidence_digest: str | None = None,
    current_disclosure_class: str | None = None,
    current_selector_digest: str | None = None,
    current_required_selector_class: str | None = None,
) -> DisclosureResult:
    """Validate and consume a disclosure authorization receipt.

    First validates (with optional class/selector scope), then marks
    as consumed (atomically: the receipt is re-loaded after persist
    to verify consumption).

    Args:
        authorization_id: Stable authorization identifier.
        current_evidence_digest: Current evidence digest for freshness.
        current_disclosure_class: If provided, receipt's class must match.
        current_selector_digest: If provided, must match receipt's
            requested_selector (fail-closed).
        current_required_selector_class: If provided, manifest selector's
            required class, receipt class, and operation class must all match.

    Returns:
        DisclosureResult with outcome. Only CONSUMED signals success.
    """
    valid = validate_disclosure_authorization(
        authorization_id,
        current_evidence_digest=current_evidence_digest,
        current_disclosure_class=current_disclosure_class,
        current_selector_digest=current_selector_digest,
        current_required_selector_class=current_required_selector_class,
    )
    if not valid.is_authorized:
        return valid

    # P4.3: Exclusive consumption under lock across threads and processes
    _acquire_consume_lock()
    try:
        # Re-validate under lock to prevent race
        receipt = _load_receipt(authorization_id)
        if receipt is None or not receipt.verify_integrity():
            return DisclosureResult(
                outcome=DisclosureOutcome.CORRUPT,
                authorization_id=authorization_id,
                error_detail="Receipt lost or corrupted during lock acquisition",
            )

        # Re-check consumption state under lock
        consumed = (receipt.one_time and receipt.consumed) or (
            not receipt.one_time and receipt.use_count >= receipt.max_uses
        )
        if consumed:
            return DisclosureResult(
                outcome=DisclosureOutcome.ALREADY_CONSUMED,
                authorization_id=receipt.authorization_id,
                receipt=receipt,
                error_detail="Receipt already consumed (detected under lock)",
            )

        # Re-validate scope bindings under lock
        scope_valid = validate_disclosure_authorization(
            authorization_id,
            current_evidence_digest=current_evidence_digest,
            current_disclosure_class=current_disclosure_class,
            current_selector_digest=current_selector_digest,
            current_required_selector_class=current_required_selector_class,
        )
        if not scope_valid.is_authorized:
            return scope_valid

        # Now safe to consume
        receipt = scope_valid.receipt
        assert receipt is not None

        if receipt.one_time:
            receipt.consumed = True
        else:
            receipt.use_count += 1
        receipt.seal()

        _atomic_write_receipt(receipt, _receipt_path(receipt.authorization_id))

        # Re-verify
        reloaded = _load_receipt(receipt.authorization_id)
        if reloaded is None or not reloaded.verify_integrity():
            return DisclosureResult(
                outcome=DisclosureOutcome.CORRUPT,
                authorization_id=receipt.authorization_id,
                error_detail="Post-consume verification failed",
            )
        if receipt.one_time and not reloaded.consumed:
            return DisclosureResult(
                outcome=DisclosureOutcome.CORRUPT,
                authorization_id=receipt.authorization_id,
                error_detail="Consume flag not persisted",
            )

        return DisclosureResult(
            outcome=DisclosureOutcome.CONSUMED,
            authorization_id=receipt.authorization_id,
            receipt=reloaded,
        )
    finally:
        _release_consume_lock()


# ── Replay detection ─────────────────────────────────────────────────────────


def check_disclosure_replay(
    authorization_id: str, *, current_evidence_digest: str | None = None
) -> DisclosureResult:
    """Check whether a disclosure authorization would be accepted (non-mutating).

    Same validation logic as validate_disclosure_authorization but
    does not consume. Useful for pre-flight checks.
    """
    return validate_disclosure_authorization(
        authorization_id, current_evidence_digest=current_evidence_digest
    )


__all__ = [
    "DISCLOSURE_AUTHZ_SCHEMA_VERSION",
    "RESTRICTED_DISCLOSURE_CLASSES",
    "DisclosureAuthorizationReceipt",
    "DisclosureClass",
    "DisclosureOutcome",
    "DisclosureResult",
    "check_disclosure_replay",
    "consume_disclosure_authorization",
    "issue_disclosure_authorization",
    "validate_disclosure_authorization",
]
