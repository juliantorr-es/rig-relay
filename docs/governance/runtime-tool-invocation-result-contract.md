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
- **Contains:** Adapter status + tool receipt SHA256 + timing + linkage IDs + RuntimeToolInvocationReceipt (strict model)
- **Content-light:** YES — only IDs, statuses, hashes, timing; `RuntimeToolInvocationReceipt` has `extra="forbid"`
- **Persisted as evidence:** Via receipt envelope wrapping
- **Schema:** `rig.relay.runtime_tool_execution_result.v1` with `$ref` to `#/$defs/runtime_tool_invocation_receipt`

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

## RuntimeToolExecutionResult Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | string | yes | `"rig.relay.runtime_tool_execution_result.v1"` |
| `invocation_id` | string\|null | no | Invocation ID from the adapter envelope |
| `intent_id` | string | yes | ID from the original RuntimeToolIntent |
| `tool_name` | string | yes | Name of the executed tool |
| `status` | string | yes | `completed`, `blocked`, `refused`, or `failed` |
| `envelope_schema_valid` | boolean | no | Whether the envelope passed schema validation |
| `tool_status` | string\|null | no | Status returned by the tool |
| `tool_error_kind` | string\|null | no | Structured error kind from the tool |
| `receipt_sha256` | string\|null | no | SHA256 of tool receipt canonical JSON (`model_dump(mode="json"), sort_keys=True`) |
| `duration_ms` | number\|null | no | Adapter-level wall-clock execution time |
| `error_kind` | string\|null | no | Structured error kind for blocked/refused/failed |
| `refusal_reason` | string\|null | no | Human-readable refusal reason |
| `warnings` | string[] | no | Non-fatal warnings |
| `tool_receipt_kind` | string\|null | no | Kind of tool receipt (e.g. `validate`, `search_replace`) |
| `tool_receipt_schema_version` | string\|null | no | Schema version of the tool receipt (e.g. `rig.relay.validate_receipt.v1`) |
| `receipt_envelope_id` | string\|null | no | ReceiptEnvelope ID — initially `None`, populated by envelope builder |
| `audit_event_id` | string\|null | no | AuditEvent ID — initially `None`, populated by audit integration |
| `changed_paths` | string[] | no | Files affected by mutation tools; populated by search_replace, write_file |
| `receipt` | object\|null | no | RuntimeToolInvocationReceipt dict dump, produced alongside the result |

## Linkage Fields

| Field | Source | Target | Purpose |
|-------|--------|--------|---------|
| `invocation_id` | Adapter envelope | Execution result | Links result back to envelope |
| `receipt_sha256` | Execution result → tool receipt | ReceiptEnvelope evidence | Links execution result to receipt |
| `tool_receipt_kind` | Tool-specific (validate, search_replace) | Execution result | Identifies which receipt schema applies |
| `tool_receipt_schema_version` | Tool receipt model | Execution result | Records which schema version produced the hash |
| `receipt_envelope_id` | ReceiptEnvelope | Execution result | Links execution result to envelope |
| `audit_event_id` | AuditEvent | Execution result | Links execution result to audit |
| `changed_paths` | Mutation tool payload | Execution result | Lists files affected |
| `envelope_id` | ReceiptEnvelope | AuditEvent | Links audit event to envelope |
| `evidence_sha256` | AuditEvent → ReceiptEnvelope | AuditEvent | Links audit event to evidence |

## Content-Light Boundary Policy

### Principle

Content-light means any data in a receipt, envelope, execution result, or audit event must be safe to:
1. Log to structured observability
2. Include in cross-session coordination artifacts
3. Share in derived eval datasets
4. Index and search without exposing raw content

### Raw Payload Boundary

Local tool result models (BashResult, WriteFileResult, SearchReplaceResult, ValidateResult) **intentionally carry raw operational payloads** (stdout, stderr, content, diffs). These are used for in-process rendering and user feedback — never persisted to receipts, envelopes, execution results, projections, or telemetry.

**Allowed (raw payloads in local result models):**
- `BashResult.stdout`, `BashResult.stderr` — full command output
- `WriteFileResult.content` — file content written
- `SearchReplaceResult.content` — diff/patch output
- `SearchReplaceResult.old_text`, `SearchReplaceResult.new_text` — SEARCH/REPLACE text
- `BashResult.argv` — command arguments

**Forbidden (must never appear in content-light artifacts):**
- `stdout`, `stderr` — raw output
- `content`, `file_content`, `file_contents` — raw file content
- `old_text`, `new_text`, `old`, `new` — SEARCH/REPLACE text
- `diff`, `patch`, `snippet`, `context` — diff and snippet data
- `chunk_text` — streaming chunk data
- `command_output` — raw command output
- `raw_output`, `raw_stdout`, `raw_stderr` — raw output aliases
- `replacement`, `replacement_text` — replacement text
- `prompt`, `secret` — sensitive material
- `argv` — raw command arguments (metadata summary allowed)

### Enforcement Points

1. **`build_receipt()`** — Each tool's receipt builder explicitly excludes raw fields. This is the primary enforcement point for tool-specific receipts (BashReceipt, WriteFileReceipt, SearchReplaceReceipt, ValidateReceipt).

2. **`build_runtime_tool_invocation_receipt()`** — Copies only content-light fields from RuntimeToolExecutionResult (`invocation_id`, `intent_id`, `tool_name`, `status`, hashes, timing). Never copies stdout, stderr, content, diffs.

3. **`validate_receipt_payload()`** — Runtime policy validator (`rig_relay/evidence/tool_receipt_policy.py`) catches raw field leaks in `rig.relay.tool_receipt.captured` events. Tests in `tests/evidence/test_tool_receipt_policy.py` prove enforcement for all four tool receipts.

4. **Pydantic `extra="forbid"`** — Every receipt and execution result model has `ConfigDict(extra="forbid")`, rejecting unknown fields at the model boundary.

5. **JSON Schema `additionalProperties: false`** — Every receipt and execution result schema has `additionalProperties: false`, rejecting unknown fields at the schema boundary.

### Test Coverage

| Artifact | Content-light enforced | Tests |
|---|---|---|
| BashReceipt | `build_receipt()` + policy validator | `test_tool_receipt_policy.py` |
| WriteFileReceipt | `build_receipt()` + policy validator | `test_tool_receipt_policy.py` |
| SearchReplaceReceipt | `build_receipt()` + policy validator | `test_tool_receipt_policy.py` |
| ValidateReceipt | `build_receipt()` + policy validator | `test_tool_receipt_policy.py` |
| RuntimeToolInvocationReceipt | `extra="forbid"` + builder | `test_runtime_tool_invocation_execution.py` |
| RuntimeToolExecutionResult | `extra="forbid"` + schema | `test_runtime_tool_invocation_execution.py`

## Schema Validation

Each adapter-level schema must validate its corresponding model's `model_dump(mode="json")` output in tests. Tool receipt schemas should validate against actual receipt model dumps, not just be registered in the schema registry.
