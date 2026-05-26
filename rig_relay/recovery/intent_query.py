"""Recovery Intent Evidence Query Service v1.

Content-light read-side query over canonical materialization receipts
and execution/projection evidence. Never exposes raw payloads, file
contents, secrets, or unrestricted paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from rig_relay.recovery.intent_authority import DurableRecoveryIntentAuthority


def _sha256(data: str) -> str:
    return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


@dataclass
class IntentQueryResult:
    """Content-light projection of a canonical intent's status."""

    intent_id: str = ""
    status: str = "missing"
    canonical_tool_name: str = ""
    execution_class: str = ""
    payload_digest: str = ""
    manifest_digest: str = ""
    recovery_receipt_sha256: str = ""
    binding_disposition: str = "unbound"
    validation_profile_available: bool = False
    bounded_paths_available: bool = False
    payload_retrievable: bool = False
    outcome_projection_exists: bool = False
    materialization_kind: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "status": self.status,
            "canonical_tool_name": self.canonical_tool_name,
            "execution_class": self.execution_class,
            "payload_digest": self.payload_digest,
            "manifest_digest": self.manifest_digest,
            "recovery_receipt_sha256": self.recovery_receipt_sha256,
            "binding_disposition": self.binding_disposition,
            "validation_profile_available": self.validation_profile_available,
            "bounded_paths_available": self.bounded_paths_available,
            "payload_retrievable": self.payload_retrievable,
            "outcome_projection_exists": self.outcome_projection_exists,
            "materialization_kind": self.materialization_kind,
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


class RecoveryIntentQueryService:
    """Read-side query over canonical materialization receipts.

    Content-light: never exposes raw payloads, file content, source
    code, secrets, credentials, or unrestricted paths.
    """

    def __init__(self, authority: DurableRecoveryIntentAuthority) -> None:
        self._authority = authority

    def query_by_handoff_binding(
        self, recovery_receipt_sha256: str, payload_digest: str
    ) -> IntentQueryResult:
        receipt = self._authority.load_intent(recovery_receipt_sha256, payload_digest)
        if receipt is None:
            return IntentQueryResult(
                intent_id=_compute_intent_id(recovery_receipt_sha256, payload_digest),
                status="missing",
                recovery_receipt_sha256=recovery_receipt_sha256,
                payload_digest=payload_digest,
            )
        intent_id = receipt.get("intent_id", "")
        payload_ok = (
            self._authority.retrieve_payload(intent_id, payload_digest) is not None
        )
        return IntentQueryResult(
            intent_id=intent_id,
            status="materialized",
            canonical_tool_name=receipt.get("canonical_tool_name", ""),
            execution_class=receipt.get("execution_class", ""),
            payload_digest=receipt.get("payload_digest", ""),
            manifest_digest=receipt.get("manifest_digest", ""),
            recovery_receipt_sha256=receipt.get("recovery_receipt_sha256", ""),
            binding_disposition="bound",
            validation_profile_available=bool(receipt.get("validation_profile")),
            bounded_paths_available=bool(receipt.get("bounded_paths")),
            payload_retrievable=payload_ok,
            materialization_kind=receipt.get("materialization_kind", ""),
            created_at=receipt.get("created_at", ""),
        )

    def query_by_intent_id(self, intent_id: str) -> IntentQueryResult:
        """Look up by stable intent identifier.

        Loads the receipt through the same verified load_intent path
        to ensure schema/digest/payload integrity verification.
        """
        # Find the receipt to extract composite key
        raw_receipt = self._authority._load_receipt_by_intent_id(intent_id)
        if raw_receipt is None:
            return IntentQueryResult(intent_id=intent_id, status="missing")
        receipt_sha = raw_receipt.get("recovery_receipt_sha256", "")
        payload_digest = raw_receipt.get("payload_digest", "")
        # Re-load through verified path (checks digest + payload)
        receipt = self._authority.load_intent(receipt_sha, payload_digest)
        if receipt is None:
            return IntentQueryResult(intent_id=intent_id, status="corrupt")
        payload_ok = (
            self._authority.retrieve_payload(intent_id, payload_digest) is not None
        )
        return IntentQueryResult(
            intent_id=intent_id,
            status="materialized" if payload_ok else "corrupt",
            canonical_tool_name=receipt.get("canonical_tool_name", ""),
            execution_class=receipt.get("execution_class", ""),
            payload_digest=payload_digest,
            manifest_digest=receipt.get("manifest_digest", ""),
            recovery_receipt_sha256=receipt_sha,
            binding_disposition="bound",
            validation_profile_available=bool(receipt.get("validation_profile")),
            bounded_paths_available=bool(receipt.get("bounded_paths")),
            payload_retrievable=payload_ok,
            materialization_kind=receipt.get("materialization_kind", ""),
            created_at=receipt.get("created_at", ""),
        )


def _compute_intent_id(recovery_receipt_sha256: str, payload_digest: str) -> str:
    raw = f"{recovery_receipt_sha256}|{payload_digest}"
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


__all__ = ["IntentQueryResult", "RecoveryIntentQueryService"]
