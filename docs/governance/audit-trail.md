# Audit Trail Store

## Purpose

The `AuditTrailStore` provides an append-only, file-backed audit log for Rig Relay
runtime events. It is the local-first persistence layer for P3b (Workspace Audit Trail).

## Design

- **Append-only JSONL**: Each event is a single JSON line appended to
  `audit.jsonl`. Lines are never modified or deleted after write.
- **Content-light**: Events contain references (IDs, SHA256 hashes, envelope IDs)
  but never raw payloads, file contents, diffs, snippets, or secrets.
- **Durability**: `os.fsync()` is called after every append to guarantee
  the write reaches disk before returning.
- **Sequence**: `next_sequence()` counts existing lines (not a separate counter
  file). Sequence numbers are monotonic integers starting at 1.
- **Malformed-line tolerance**: On read, invalid JSON lines are returned as
  errors with positions — they never raise.
- **Ordering**: Events are sorted by `(sequence, timestamp)`.

## Module: `rig_relay/evidence/audit_trail.py`

| Symbol | Kind | Description |
|--------|------|-------------|
| `AuditActionKind` | `StrEnum` | 10 canonical action types (`receipt_created`, `decision_recorded`, `execution_requested`, …) |
| `AuditDecisionKind` | `StrEnum` | 6 decision outcomes (`allowed`, `blocked`, `refused`, `completed`, `failed`, `informational`) |
| `AuditEvent` | `BaseModel` | Pydantic model with `extra="forbid"`, 14 fields (6 required) |
| `AuditTrailStore` | class | Append-only JSONL store with `path` property |
| `AuditStoreReadError` | exception | Raised only for store-level errors (never per-line parse errors) |

### AuditEvent required fields

`schema_version`, `event_id`, `sequence`, `timestamp`, `action`, `decision`

### AuditEvent optional fields

`workspace_id`, `session_id`, `actor`, `subject`, `envelope_id`, `envelope`,
`evidence_sha256`, `notes`

### AuditTrailStore API

| Method | Description |
|--------|-------------|
| `append(event)` | Append a single `AuditEvent` with fsync |
| `append_audit_event(...)` | Convenience: creates `AuditEvent` from kwargs, auto-computes sequence, then appends |
| `read_events()` | Returns `(events, errors)` — events sorted by `(sequence, timestamp)` |
| `next_sequence()` | Returns next sequence number (count of existing lines + 1) |
| `latest_event()` | Returns the most recent event, or `None` for an empty store |

## Schema

- File: `docs/schemas/rig.relay.audit_event.v1.schema.json`
- Type: Draft 7
- Required fields (top-level): 6
- `$defs` are self-contained (definitions inlined from `receipt_envelope.v1` schema)
- `additionalProperties: false` everywhere

## Supervisor Integration (P3b)

The `RuntimeSupervisor` produces `AuditEvent` records from terminal execution
events when configured with an ``audit_trail_store``.

- **Action**: ``EXECUTION_COMPLETED`` — one audit event per terminal event.
- **Decision**: ``COMPLETED`` (exit code 0), ``FAILED`` (non-zero or timeout),
  ``REFUSED`` (blocked by lease/governance).
- **Envelope**: Embedded `ReceiptEnvelope` with runtime invocation subject,
  execution request input, terminal output (hashes/bytes), and terminal event
  hash as evidence.
- **Failure safety**: If audit append fails, a `RuntimeWarningEvent` is
  emitted and the terminal event is still delivered.

See `docs/governance/runtime-supervisor.md` for constructor args and behavior.

## Related

- `rig_relay/evidence/receipt_envelope.py` — `ReceiptEnvelope`, `ReceiptActor`,
  `ReceiptSubject` models referenced by `AuditEvent`
- `rig_relay/runtime/supervisor.py` — `RuntimeSupervisor` audit integration
- `docs/schemas/rig.relay.audit_event.v1.schema.json`
- `docs/governance/runtime-supervisor.md`
- `tests/evidence/test_audit_trail.py`
- `tests/runtime/test_runtime_supervisor.py` (see ``TestAuditIntegration``)

## Tamper Evidence

This store provides append-only JSONL persistence with best-effort fsync
durability. It does **not** provide cryptographic tamper evidence. Hash-chain
tamper evidence is designed separately — see
[docs/governance/audit-trail-tamper-evidence.md](audit-trail-tamper-evidence.md).
