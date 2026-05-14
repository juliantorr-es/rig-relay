# Receipt Envelope

## Status

**Implemented (P3a, 2026-05).** Source: `rig_relay/evidence/receipt_envelope.py`.

Provides a content-light canonical receipt envelope model and builder that
wraps existing tool/runtime/governance receipts with actor, subject, decision,
and evidence metadata.

## Purpose

The ReceiptEnvelope is a **unified wrapper** for all receipt types in Rig Relay.
It does not replace existing tool receipts (BashReceipt, WriteFileReceipt, etc.)
or the receipt index — it wraps them with common metadata so that consumers
(tools, audit trails, projections) get a consistent interface.

## Core Rules

1. **All envelope data is content-light.**
   - No raw payloads, stdout, stderr, file contents, diffs, snippets, or secrets.
   - SHA256 hashes replace raw content.
   - Byte counts replace full content references.

2. **The builder is a pure function.**
   - No side effects, no file reads, no persistence.
   - Deterministic when `envelope_id` and `created_at` are supplied explicitly.
   - Accepts both dict and Pydantic BaseModel payloads.

3. **Payloads are hashed, not stored.**
   - `build_receipt_envelope()` accepts an optional `receipt_payload` parameter.
   - The payload's canonical SHA256 is recorded as `ReceiptEvidence`.
   - The raw payload is discarded after hashing.

## Models

### Enums

| Enum | Values | Description |
|------|--------|-------------|
| `ReceiptActorKind` | human, agent, tool, runtime, system | Kinds of actors |
| `ReceiptSubjectKind` | tool_invocation, runtime_invocation, governance_decision, worktree, projection, session, artifact | Kinds of subjects |
| `ReceiptEvidenceKind` | sha256, schema, receipt_index, governance_decision, runtime_event, tool_receipt, projection_integrity | Kinds of evidence |

### Models

| Model | Key Fields | Description |
|-------|-----------|-------------|
| `ReceiptActor` | actor_id, actor_kind, display_name, is_human, is_authoritative | Who/what performed the action |
| `ReceiptSubject` | subject_id, subject_kind, workspace_id, session_id, path | What was acted upon |
| `ReceiptInput` | input_id, input_kind, input_sha256, input_bytes | Input to the operation |
| `ReceiptOutput` | output_id, output_kind, output_sha256, output_bytes, status | Output from the operation |
| `ReceiptEvidence` | evidence_id, evidence_kind, evidence_sha256, schema_version, uri | Evidence artifact reference |
| `ReceiptDecision` | decision, rationale, gate, governance_decision_id | Authority classification |
| `ReceiptEnvelope` | schema_version, envelope_id, receipt_kind, actor, subject, input, output, decision, evidence, created_at | Canonical wrapper |

All models use `ConfigDict(extra="forbid")`.

## Builder

```python
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
) -> ReceiptEnvelope
```

- Auto-generates `envelope_id` (UUID4) and `created_at` (current UTC) when omitted.
- Pass explicit values for deterministic output.
- `receipt_payload` is hashed (SHA256) and recorded as `ReceiptEvidence` — never stored raw.

## Placeholder Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `PLACEHOLDER_UNKNOWN` | `"unknown"` | Unknown or missing value |
| `PLACEHOLDER_UNAVAILABLE` | `"unavailable"` | Unavailable data |
| `PLACEHOLDER_NO_RECEIPT` | `"no_receipt"` | Explicit absence of a receipt |

## Relationship to Existing Systems

### Tool Receipts
Existing tool receipts (BashReceipt, WriteFileReceipt, SearchReplaceReceipt,
ValidateReceipt) contain the full, content-light receipt data for each tool.
The ReceiptEnvelope wraps these with actor/subject/decision/evidence metadata
without duplicating their fields.

### Receipt Index
The receipt index (`rig_relay/evidence/receipt_index.py`) stores indexed records
from observability JSONL. These `ToolReceiptIndexRecord` instances are natural
inputs to `build_receipt_envelope()` — their `model_dump(mode="json")` dict can
be passed as `receipt_payload`.

### Governance Decisions
`GateDecision` models (from `rig_relay/governance/decisions.py`) can be wrapped
using `ReceiptEnvelope(receipt_kind="governance_decision")` with the decision's
key fields mapped into `ReceiptDecision`.

### Runtime Models
`RuntimeProviderDescriptor` and `RuntimeCapability` (from
`rig_relay/runtime/models.py`) can be referenced via `ReceiptEvidence` with
`evidence_kind="schema"` and the model's `schema_version`.

## Audit Trail Integration (P3b)

The `RuntimeSupervisor` uses `ReceiptEnvelope` as the content-light envelope
for audit events. When a terminal execution event occurs, a `ReceiptEnvelope`
is built with:

- **Actor**: `audit_actor` or a runtime default
- **Subject**: `RUNTIME_INVOCATION` with lease/request context
- **Input**: Execution request reference (request SHA256)
- **Output**: Terminal status, stdout/stderr hashes and byte counts
- **Evidence**: SHA256 hash of the terminal event
- **Decision**: Completed/failed/refused mapping

The envelope is embedded directly in the `AuditEvent` via the ``envelope``
field. ReceiptEnvelopes are not persisted independently — they are embedded
in audit events for append-only storage.

## Future Integration

- **Receipt Persistence:** ReceiptEnvelopes can be persisted as JSONL (same
  pattern as observability JSONL). No persistence is implemented yet.
- **Receipt Signing:** Future signing would operate on the canonical JSON
  representation of the ReceiptEnvelope (not on inner payloads).

## Schema

Schema file: `docs/schemas/rig.relay.receipt_envelope.v1.schema.json`

- Draft 7
- `additionalProperties: false` at all levels
- Nullable fields (`["string", "null"]`, `["integer", "null"]`)
- Enum validation for `ReceiptActorKind`, `ReceiptSubjectKind`, `ReceiptEvidenceKind`
- Schema version constant: `rig.relay.receipt_envelope.v1`

## Cross-References

- [Rig Runtime Port Roadmap](../audits/rig-runtime-port/port-roadmap.md)
- [Rig-to-Relay Runtime Audit](../audits/rig-runtime-port/rig-to-relay-runtime-audit.md)
- [Rig-to-Relay Concept Map](../audits/rig-runtime-port/concept-map.md)
- [Receipt Envelope Schema](../schemas/rig.relay.receipt_envelope.v1.schema.json)
- [Receipt Index](../evidence/receipt_index.py)
- [Governance Decisions](../governance/decisions.py)
- [Runtime Models](../runtime/models.py)
