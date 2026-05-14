# Runtime Tool Invocation Result Contract

**File:** `docs/governance/runtime-tool-invocation-result-contract.md`

## Overview

This document defines the contract between the runtime adapter execution layer and the evidence/audit layer for tool invocation results and receipts. It covers what data is recorded, how it flows between layers, and what is explicitly forbidden.

## Data Flow

```
RuntimeToolIntent → RuntimeToolInvocationEnvelope → Tool → ToolResult → ToolReceipt
                                                                           ↓
                                                              RuntimeToolExecutionResult
                                                                           ↓
                                                              ReceiptEnvelope
                                                                           ↓
                                                              AuditEvent
```

## Layer Boundaries

### Layer 1: Invocation Envelope
- **Contains:** Tool input payload (file content, SEARCH/REPLACE blocks, argv, profile/paths)
- **Content-light:** NO — operational input for tool execution
- **Never stored as evidence:** Payload is consumed by the tool and discarded
- **Schema:** `rig.relay.runtime_tool_invocation.v1`

### Layer 2: Tool Result
- **Contains:** Full operational output (stdout, stderr, check results, file content after edit)
- **Content-light:** NO — contains data for rendering and user feedback
- **Never stored as evidence:** Result is ephemeral; only receipt persists
- **Schema:** Tool-specific (e.g. `rig.relay.validate_result.v1`)

### Layer 3: Tool Receipt
- **Contains:** Content-light view — SHA256 hashes, byte counts, statuses, blocker counts
- **Content-light:** YES — no raw stdout, stderr, file content, diffs
- **Persisted as evidence:** Yes, via ReceiptEnvelope
- **Schema:** Tool-specific (e.g. `rig.relay.validate_receipt.v1`)

### Layer 4: RuntimeToolExecutionResult
- **Contains:** Adapter status + tool receipt SHA256 + timing + linkage IDs
- **Content-light:** YES — only IDs, statuses, hashes, timing
- **Persisted as evidence:** Via receipt envelope wrapping
- **Schema:** `rig.relay.runtime_tool_execution_result.v1`

### Layer 5: ReceiptEnvelope
- **Contains:** Canonical wrapper with actor, subject, decision, evidence references
- **Content-light:** YES — only IDs, hashes, schema versions
- **Persisted as evidence:** Yes, primary evidence record
- **Schema:** `rig.relay.receipt_envelope.v1`

### Layer 6: AuditEvent
- **Contains:** Action/decision metadata + reference to ReceiptEnvelope
- **Content-light:** YES — only IDs, action/decision kinds, references
- **Persisted:** Yes, append-only JSONL trail
- **Schema:** `rig.relay.audit_event.v1`

## Receipt Hashing

- `receipt_sha256` in `RuntimeToolExecutionResult` = SHA256 of the tool receipt's canonical JSON (`model_dump(mode="json"), sort_keys=True`)
- `evidence_sha256` in `ReceiptEnvelope` = SHA256 of the receipt payload's canonical JSON (computed by `build_receipt_envelope()`)
- `evidence_sha256` in `AuditEvent` = SHA256 of related evidence payload

These are three distinct hashes for three distinct artifacts.

## Linkage Fields

| Field | Source | Target | Purpose |
|-------|--------|--------|---------|
| `invocation_id` | Adapter envelope | Execution result | Links result back to envelope |
| `receipt_sha256` | Execution result → tool receipt | ReceiptEnvelope evidence | Links execution result to receipt |
| `receipt_envelope_id` | ReceiptEnvelope | Execution result | Links execution result to envelope |
| `audit_event_id` | AuditEvent | Execution result | Links execution result to audit |
| `envelope_id` | ReceiptEnvelope | AuditEvent | Links audit event to envelope |
| `evidence_sha256` | AuditEvent → ReceiptEnvelope | AuditEvent | Links audit event to evidence |

## Content-Light Contract

See audit document for full Allowed/Forbidden field list.

**Principle:** Content-light means any data in a receipt, envelope, execution result, or audit event must be safe to:
1. Log to structured observability
2. Include in cross-session coordination artifacts
3. Share in derived eval datasets
4. Index and search without exposing raw content

## Schema Validation

Each adapter-level schema must validate its corresponding model's `model_dump(mode="json")` output in tests. Tool receipt schemas should validate against actual receipt model dumps, not just be registered in the schema registry.
