"""Rig Relay Receipt Envelope — content-light canonical receipt wrapper.

Provides the ReceiptEnvelope model and build_receipt_envelope() helper that can
wrap existing tool/runtime/governance receipts with actor, subject, decision,
and evidence metadata.

All envelope data is content-light: no raw payloads, stdout, stderr, file
contents, diffs, snippets, or secrets.

Provenance (Rig-to-Relay porting doctrine):
  Pattern source: Rig's receipt_envelope.py (ReceiptActor, ReceiptSubject,
  ReceiptInput, ReceiptOutput, ReceiptDecision, ReceiptEvidence,
  ReceiptEnvelope) adapted as a relay-native Pydantic module.
  Porting status: reimplement (relay_owned).
  See docs/governance/rig-to-relay-pattern-inventory.md for pattern map.
  Not a copy of Rig's product domain — uses relay-native field names,
  Pydantic BaseModel, StrEnum, extra="forbid", and content-light conventions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import hashlib
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.coordination._canonical_json import dump_canonical_json

# ── Placeholder constants ─────────────────────────────────────────────

PLACEHOLDER_UNKNOWN: str = "unknown"
PLACEHOLDER_UNAVAILABLE: str = "unavailable"
PLACEHOLDER_NO_RECEIPT: str = "no_receipt"

# ── Enums ─────────────────────────────────────────────────────────────


class ReceiptActorKind(StrEnum):
    """Kinds of actors that can perform or initiate receipted actions."""

    HUMAN = "human"
    AGENT = "agent"
    TOOL = "tool"
    RUNTIME = "runtime"
    SYSTEM = "system"


class ReceiptSubjectKind(StrEnum):
    """Kinds of subjects that can be acted upon by receipted operations."""

    TOOL_INVOCATION = "tool_invocation"
    RUNTIME_INVOCATION = "runtime_invocation"
    GOVERNANCE_DECISION = "governance_decision"
    WORKTREE = "worktree"
    PROJECTION = "projection"
    SESSION = "session"
    ARTIFACT = "artifact"


class ReceiptEvidenceKind(StrEnum):
    """Kinds of evidence that can be attached to a receipt."""

    SHA256 = "sha256"
    SCHEMA = "schema"
    RECEIPT_INDEX = "receipt_index"
    GOVERNANCE_DECISION = "governance_decision"
    RUNTIME_EVENT = "runtime_event"
    TOOL_RECEIPT = "tool_receipt"
    PROJECTION_INTEGRITY = "projection_integrity"


# ── Models ────────────────────────────────────────────────────────────


class ReceiptActor(BaseModel):
    """Who or what performed the receipted action.

    Content-light: no secrets, credentials, or raw identifiers.
    """

    model_config = ConfigDict(extra="forbid")

    actor_id: str
    actor_kind: ReceiptActorKind
    display_name: str | None = None
    is_human: bool = False
    is_authoritative: bool = False


class ReceiptSubject(BaseModel):
    """What was acted upon by the receipted operation.

    Content-light: no raw file contents, diffs, or payloads.
    """

    model_config = ConfigDict(extra="forbid")

    subject_id: str
    subject_kind: ReceiptSubjectKind
    workspace_id: str | None = None
    session_id: str | None = None
    path: str | None = None


class ReceiptInput(BaseModel):
    """An input to the receipted operation.

    Content-light: only identifiers, hashes, and byte counts.
    """

    model_config = ConfigDict(extra="forbid")

    input_id: str | None = None
    input_kind: str
    input_sha256: str | None = None
    input_bytes: int | None = None


class ReceiptOutput(BaseModel):
    """An output from the receipted operation.

    Content-light: only identifiers, hashes, byte counts, and status.
    """

    model_config = ConfigDict(extra="forbid")

    output_id: str | None = None
    output_kind: str
    output_sha256: str | None = None
    output_bytes: int | None = None
    status: str | None = None


class ReceiptEvidence(BaseModel):
    """Evidence or artifacts associated with the receipt.

    Content-light: only identifiers, hashes, schema versions, and URIs.
    """

    model_config = ConfigDict(extra="forbid")

    evidence_id: str | None = None
    evidence_kind: ReceiptEvidenceKind
    evidence_sha256: str | None = None
    schema_version: str | None = None
    uri: str | None = None


class ReceiptDecision(BaseModel):
    """The decision or authority classification for the receipt.

    Content-light: no policy documents or raw evaluation context.
    """

    model_config = ConfigDict(extra="forbid")

    decision: str
    rationale: str | None = None
    gate: str | None = None
    governance_decision_id: str | None = None


class ReceiptEnvelope(BaseModel):
    """Canonical content-light receipt envelope.

    Wraps any receipt (tool, runtime, governance) with actor, subject,
    decision, and evidence metadata. All content is content-light:
    no raw payloads, stdout, stderr, file contents, diffs, snippets,
    or secrets.

    Deterministic when ``envelope_id`` and ``created_at`` are supplied
    explicitly — identical inputs produce identical output.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.receipt_envelope.v1"
    envelope_id: str
    receipt_kind: str
    actor: ReceiptActor
    subject: ReceiptSubject
    input: ReceiptInput | None = None
    output: ReceiptOutput | None = None
    decision: ReceiptDecision | None = None
    evidence: list[ReceiptEvidence] = Field(default_factory=list)
    created_at: str


# ── Builder ───────────────────────────────────────────────────────────


def _compute_payload_sha256(payload: dict[str, Any] | BaseModel) -> str:
    """Compute a SHA256 hash of a canonical JSON representation of payload."""
    if isinstance(payload, BaseModel):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    canonical = dump_canonical_json(data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_receipt_envelope(
    *,
    envelope_id: str | None = None,
    receipt_kind: str,
    actor: ReceiptActor,
    subject: ReceiptSubject,
    receipt_payload: dict[str, Any] | BaseModel | None = None,
    decision: ReceiptDecision | None = None,
    evidence_override: list[ReceiptEvidence] | None = None,
    created_at: str | None = None,
) -> ReceiptEnvelope:
    """Build a content-light ReceiptEnvelope from available inputs.

    Accepts an optional receipt payload (Model or dict) and records a
    SHA256 hash as ``ReceiptEvidence`` — never stores the raw payload.

    Pure function: no side effects, no file reads, no persistence.

    Args:
        envelope_id: Unique envelope identifier. Auto-generated (UUID4)
            if not provided. For deterministic output, always pass this.
        receipt_kind: The kind of receipt (e.g. ``"tool_invocation"``,
            ``"governance_decision"``, ``"runtime_event"``).
        actor: Who/what performed the receipted action.
        subject: What was acted upon.
        receipt_payload: Optional receipt data (Model or dict). Its
            canonical SHA256 is recorded as evidence; raw data is discarded.
        decision: Optional ReceiptDecision to attach.
        evidence_override: Optional list of ReceiptEvidence to attach
            directly. When combined with a receipt_payload, both are included.
        created_at: ISO 8601 timestamp. Auto-generated (current UTC) if
            not provided. For deterministic output, always pass this.

    Returns:
        A ReceiptEnvelope with all fields populated.

    Raises:
        TypeError: If ``receipt_payload`` is neither a dict nor a BaseModel.
    """
    env_id = envelope_id or str(uuid.uuid4())
    stamp = created_at or datetime.now(UTC).isoformat()

    evidence: list[ReceiptEvidence] = list(evidence_override or [])

    if receipt_payload is not None:
        if not isinstance(receipt_payload, (dict, BaseModel)):
            msg = (
                f"receipt_payload must be a dict or BaseModel, "
                f"got {type(receipt_payload).__name__}"
            )
            raise TypeError(msg)
        payload_hash = _compute_payload_sha256(receipt_payload)
        evidence.append(
            ReceiptEvidence(
                evidence_id=env_id,
                evidence_kind=ReceiptEvidenceKind.TOOL_RECEIPT,
                evidence_sha256=payload_hash,
            )
        )

    return ReceiptEnvelope(
        schema_version="rig.relay.receipt_envelope.v1",
        envelope_id=env_id,
        receipt_kind=receipt_kind,
        actor=actor,
        subject=subject,
        input=None,
        output=None,
        decision=decision,
        evidence=evidence,
        created_at=stamp,
    )


__all__ = [
    "PLACEHOLDER_NO_RECEIPT",
    "PLACEHOLDER_UNAVAILABLE",
    "PLACEHOLDER_UNKNOWN",
    "ReceiptActor",
    "ReceiptActorKind",
    "ReceiptDecision",
    "ReceiptEnvelope",
    "ReceiptEvidence",
    "ReceiptEvidenceKind",
    "ReceiptInput",
    "ReceiptOutput",
    "ReceiptSubject",
    "ReceiptSubjectKind",
    "build_receipt_envelope",
]
