"""Public Preparation Receipt Revocation Authority v1.

Governed public operation for revoking active preparation receipts.
Wraps the low-level receipt-store revocation primitive with explicit
authorization enforcement, typed outcomes, and bounded evidence emission.

Lane A owns this public authority boundary. Lane B and Lane C consumers
rely on the typed outcomes for validate/checkpoint refusal gating.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, auto
import json

from rig_relay.governance.auth_receipts import validate_receipt
from rig_relay.governance.receipt_store import (
    RevocationOutcome,
    revoke_preparation_receipt as _primitive_revoke,
)

# ── Public revocation outcome ────────────────────────────────────────────────


class PublicRevocationOutcome(StrEnum):
    REVOKED = auto()
    ALREADY_REVOKED = auto()
    AUTHORIZATION_MISSING = auto()
    AUTHORIZATION_INVALID = auto()
    AUTHORIZATION_EXPIRED = auto()
    AUTHORIZATION_ACTION_MISMATCH = auto()
    ALREADY_CONSUMED = auto()
    ALREADY_SUPERSEDED = auto()
    RECEIPT_NOT_FOUND = auto()
    RECEIPT_CORRUPT = auto()
    LIFECYCLE_AUTHORITY_CORRUPT = auto()
    CONFLICTING_TERMINAL = auto()
    LEDGER_WRITE_FAILED = auto()
    RACE_LOST = auto()


@dataclass(slots=True)
class PublicRevocationResult:
    outcome: PublicRevocationOutcome
    preparation_receipt_sha256: str = ""
    revocation_event_id: str | None = None
    authorization_receipt_sha256: str | None = None
    error_detail: str = ""
    evidence: dict | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome in {
            PublicRevocationOutcome.REVOKED,
            PublicRevocationOutcome.ALREADY_REVOKED,
        }


_EVIDENCE_SCHEMA = "rig.relay.revocation_evidence.v1"


def _build_evidence(
    outcome: PublicRevocationOutcome,
    receipt_sha256: str,
    event_id: str | None,
    authz_sha256: str | None,
) -> dict:
    return {
        "schema_version": _EVIDENCE_SCHEMA,
        "outcome": outcome.value,
        "preparation_receipt_sha256": receipt_sha256,
        "revocation_event_id": event_id,
        "authorization_receipt_sha256": authz_sha256,
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ── Outcome mapping ──────────────────────────────────────────────────────────


def _map_primitive_outcome(outcome: RevocationOutcome) -> PublicRevocationOutcome:
    mapping: dict[RevocationOutcome, PublicRevocationOutcome] = {
        RevocationOutcome.REVOKED: PublicRevocationOutcome.REVOKED,
        RevocationOutcome.ALREADY_REVOKED: PublicRevocationOutcome.ALREADY_REVOKED,
        RevocationOutcome.ALREADY_CONSUMED: PublicRevocationOutcome.ALREADY_CONSUMED,
        RevocationOutcome.ALREADY_SUPERSEDED: PublicRevocationOutcome.ALREADY_SUPERSEDED,
        RevocationOutcome.RECEIPT_NOT_FOUND: PublicRevocationOutcome.RECEIPT_NOT_FOUND,
        RevocationOutcome.RECEIPT_CORRUPT: PublicRevocationOutcome.RECEIPT_CORRUPT,
        RevocationOutcome.LIFECYCLE_AUTHORITY_CORRUPT: PublicRevocationOutcome.LIFECYCLE_AUTHORITY_CORRUPT,
        RevocationOutcome.CONFLICTING_TERMINAL: PublicRevocationOutcome.CONFLICTING_TERMINAL,
        RevocationOutcome.LEDGER_WRITE_FAILED: PublicRevocationOutcome.LEDGER_WRITE_FAILED,
    }
    return mapping.get(outcome, PublicRevocationOutcome.RACE_LOST)


# ── Public revocation operation ──────────────────────────────────────────────


REVOKE_ACTION = "preparation_receipt.revoke"


def revoke_preparation_receipt_public(
    preparation_receipt_sha256: str,
    *,
    authorization_receipt_json: str | None = None,
    producer: str = "revocation_authority.public",
) -> PublicRevocationResult:
    """Governed public preparation receipt revocation.

    Requires a valid authorization receipt for the action
    "preparation_receipt.revoke". The receipt must be valid,
    not expired, and carry the correct action.

    On success, delegates to the canonical receipt-store revocation
    primitive and produces typed bounded evidence.

    Returns:
        PublicRevocationResult with typed outcome, evidence, and
        authorization receipt SHA256 for audit.
    """
    # 1. Validate authorization
    if not authorization_receipt_json:
        return PublicRevocationResult(
            outcome=PublicRevocationOutcome.AUTHORIZATION_MISSING,
            preparation_receipt_sha256=preparation_receipt_sha256,
            error_detail="Authorization receipt required for receipt revocation",
        )

    try:
        authz_receipt: dict = json.loads(authorization_receipt_json)
    except (json.JSONDecodeError, TypeError):
        return PublicRevocationResult(
            outcome=PublicRevocationOutcome.AUTHORIZATION_INVALID,
            preparation_receipt_sha256=preparation_receipt_sha256,
            error_detail="Authorization receipt is not valid JSON",
        )

    valid, reason = validate_receipt(authz_receipt, REVOKE_ACTION)
    if not valid:
        if "expired" in reason.lower():
            return PublicRevocationResult(
                outcome=PublicRevocationOutcome.AUTHORIZATION_EXPIRED,
                preparation_receipt_sha256=preparation_receipt_sha256,
                authorization_receipt_sha256=authz_receipt.get("receipt_sha256", ""),
                error_detail=reason,
            )
        if "action" in reason.lower() or "mismatch" in reason.lower():
            return PublicRevocationResult(
                outcome=PublicRevocationOutcome.AUTHORIZATION_ACTION_MISMATCH,
                preparation_receipt_sha256=preparation_receipt_sha256,
                authorization_receipt_sha256=authz_receipt.get("receipt_sha256", ""),
                error_detail=reason,
            )
        return PublicRevocationResult(
            outcome=PublicRevocationOutcome.AUTHORIZATION_INVALID,
            preparation_receipt_sha256=preparation_receipt_sha256,
            authorization_receipt_sha256=authz_receipt.get("receipt_sha256", ""),
            error_detail=reason,
        )

    authz_sha256 = authz_receipt.get("receipt_sha256", "")

    # 2. Call canonical revocation primitive
    primitive_result = _primitive_revoke(preparation_receipt_sha256, producer=producer)

    public_outcome = _map_primitive_outcome(primitive_result.outcome)
    evidence = _build_evidence(
        public_outcome,
        preparation_receipt_sha256,
        primitive_result.revocation_event_id,
        authz_sha256,
    )

    return PublicRevocationResult(
        outcome=public_outcome,
        preparation_receipt_sha256=preparation_receipt_sha256,
        revocation_event_id=primitive_result.revocation_event_id,
        authorization_receipt_sha256=authz_sha256,
        error_detail=primitive_result.error_detail,
        evidence=evidence,
    )


__all__ = [
    "REVOKE_ACTION",
    "PublicRevocationOutcome",
    "PublicRevocationResult",
    "revoke_preparation_receipt_public",
]
