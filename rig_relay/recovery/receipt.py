"""Content-light tool intent recovery receipt.

Never contains: raw model emission, normalized argument values, file content.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rig_relay.recovery.models import (
    RecoveryAdmissionDecision,
    RecoveryIntent,
    RecoveryRefusal,
    utcnow_iso,
)


class ToolIntentRecoveryReceipt(BaseModel):
    """Content-light receipt for a single recovery attempt.

    Serialized receipt contains only hashes, rule identifiers,
    and typed decisions — never raw emission or payload content.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.tool_intent_recovery_receipt.v1", frozen=True
    )
    receipt_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    manifest_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    original_emission_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    normalization_rules_applied: list[str] = Field(default_factory=list)
    candidate_count: int = 0
    selected_canonical_tool: str | None = None
    selected_tool_mutation_class: str | None = None
    selected_tool_determinism_class: str | None = None
    normalized_payload_sha256: str | None = None
    payload_schema_valid: bool = False
    admission_decision: RecoveryAdmissionDecision | None = None
    proposal_only: bool = False
    refused_reason: str | None = None
    receipt_sha256: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")

    @model_validator(mode="after")
    def _seal_receipt(self) -> ToolIntentRecoveryReceipt:
        if self.receipt_sha256 is None:
            self.receipt_sha256 = compute_receipt_digest(self)
        return self

    def verify_integrity(self) -> bool:
        expected = compute_receipt_digest(self)
        return self.receipt_sha256 == expected


def compute_receipt_digest(receipt: ToolIntentRecoveryReceipt) -> str:
    """Compute deterministic SHA256 of a receipt excluding receipt_sha256."""
    data = {
        "schema_version": receipt.schema_version,
        "receipt_id": receipt.receipt_id,
        "created_at": receipt.created_at,
        "manifest_digest": receipt.manifest_digest,
        "original_emission_sha256": receipt.original_emission_sha256,
        "normalization_rules_applied": sorted(receipt.normalization_rules_applied),
        "candidate_count": receipt.candidate_count,
        "selected_canonical_tool": receipt.selected_canonical_tool,
        "selected_tool_mutation_class": receipt.selected_tool_mutation_class,
        "selected_tool_determinism_class": receipt.selected_tool_determinism_class,
        "normalized_payload_sha256": receipt.normalized_payload_sha256,
        "payload_schema_valid": receipt.payload_schema_valid,
        "admission_decision": (
            str(receipt.admission_decision) if receipt.admission_decision else None
        ),
        "proposal_only": receipt.proposal_only,
        "refused_reason": receipt.refused_reason,
    }
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


def build_recovery_receipt_from_intent(
    receipt_id: str,
    intent: RecoveryIntent,
    manifest_digest: str,
    emission_sha256: str,
    admission_result: RecoveryAdmissionDecision | None = None,
    proposal_only: bool = False,
) -> ToolIntentRecoveryReceipt:
    return ToolIntentRecoveryReceipt(
        receipt_id=receipt_id,
        manifest_digest=manifest_digest,
        original_emission_sha256=emission_sha256,
        normalization_rules_applied=sorted(intent.rules_applied),
        candidate_count=1,
        selected_canonical_tool=intent.canonical_tool_name,
        selected_tool_mutation_class=intent.mutation_class,
        selected_tool_determinism_class=intent.determinism_class,
        normalized_payload_sha256=intent.payload_digest,
        payload_schema_valid=True,
        admission_decision=admission_result,
        proposal_only=proposal_only,
    )


def build_recovery_receipt_from_refusal(
    receipt_id: str,
    refusal: RecoveryRefusal,
    manifest_digest: str,
    emission_sha256: str,
) -> ToolIntentRecoveryReceipt:
    return ToolIntentRecoveryReceipt(
        receipt_id=receipt_id,
        manifest_digest=manifest_digest,
        original_emission_sha256=emission_sha256,
        normalization_rules_applied=sorted(refusal.rules_attempted),
        candidate_count=refusal.candidate_count,
        payload_schema_valid=False,
        refused_reason=f"{refusal.refusal_code}: {refusal.reason}",
    )
