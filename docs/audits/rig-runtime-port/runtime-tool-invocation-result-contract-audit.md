# Runtime Tool Invocation Result Contract Audit

**Audit date:** 2026-05-17
**Auditor:** Rig Relay agent (Mission 15 — Schema Audit)
**Files audited:** adapter, execution runner, dry-run runner, all tool result/receipt schemas, receipt envelope, audit trail
**Status:** Findings documented, decisions recorded, future schema proposed

---

## 1. Data Flow Summary

```
RuntimeToolIntent
  │
  ▼
RuntimeToolInvocationEnvelope     ← schema: runtime_tool_invocation.v1
  │                                     (contains tool input payload — NOT content-light)
  ▼
Tool.run() → Tool Result          ← schema: validate_result.v1 / search_replace_result.v1
  │                                     (full operational output — NOT content-light)
  ▼
Tool.build_receipt() → Receipt    ← schema: validate_receipt.v1 / search_replace_receipt.v1
  │                                     (content-light: hashes, counts, statuses)
  ▼
RuntimeToolExecutionResult        ← schema: runtime_tool_execution_result.v1
  │                                     (thin adapter-level wrapper + receipt hash)
  ▼
ReceiptEnvelope                   ← schema: receipt_envelope.v1
  │                                     (canonical wrapper: actor, subject, decision, evidence)
  ▼
AuditEvent                        ← schema: audit_event.v1
                                          (append-only trail, references envelope by ID)
```

## 2. Layer Definitions

### Invocation payload (in `RuntimeToolInvocationEnvelope.payload`)
- **Contains:** Tool input — file content for write_file, SEARCH/REPLACE blocks for search_replace, argv for runtime_exec, profile/paths for validate
- **Content-light?** NO — operational input needed by the tool
- **Who creates:** `RuntimeToolInvocationAdapter.prepare()`
- **Schema:** `runtime_tool_invocation.v1`

### Tool result (e.g. `ValidateResult`, `SearchReplaceResult`)
- **Contains:** Full operational output — stdout/stderr, check details, file content after edit, per-check results
- **Content-light?** NO — contains operational output for rendering/feedback
- **Who creates:** Tool's `run()` method
- **Schemas:** `validate_result.v1`, `search_replace_result.v1`, `bash_result.v1`

### Tool receipt (e.g. `ValidateReceipt`, `SearchReplaceReceipt`)
- **Contains:** Content-light view — SHA256 hashes, byte counts, statuses, blocker summaries, changed paths
- **Content-light?** YES — no raw stdout, stderr, file content, diffs
- **Who creates:** Tool's `build_receipt()` method
- **Schemas:** `validate_receipt.v1`, `search_replace_receipt.v1`, `write_file_receipt.v1`, `bash_receipt.v1`

### RuntimeToolExecutionResult (adapter-level wrapper)
- **Contains:** Adapter status + tool receipt SHA256 + timing + error info
- **Content-light?** YES — only IDs, statuses, hashes, timing
- **Who creates:** `RuntimeToolExecutionRunner.execute_validate()`
- **Schema:** `runtime_tool_execution_result.v1`

### Runtime Tool Invocation Receipt (proposed — adapter-level content-light receipt)
- **Contains:** Links adapter status → tool receipt → receipt envelope
- **Content-light?** YES — all linkage, no tool-specific payload
- **Who creates:** Adapter execution layer (future)
- **Schema:** `runtime_tool_invocation_receipt.v1` (proposed, not yet implemented)

### ReceiptEnvelope (canonical wrapper)
- **Contains:** Actor/subject/decision/evidence wrapping any receipt
- **Content-light?** YES — only IDs, hashes, schema versions
- **Who creates:** `build_receipt_envelope()` helper
- **Schema:** `receipt_envelope.v1`

### AuditEvent (append-only trail entry)
- **Contains:** References a ReceiptEnvelope by ID or embeds one
- **Content-light?** YES — only IDs, action/decision kinds, references
- **Who creates:** `AuditTrailStore.append_audit_event()`
- **Schema:** `audit_event.v1`

## 3. Contract Gaps in RuntimeToolExecutionResult

### Gap 1: No `tool_receipt_kind`
When multiple tool types are wired, the consumer cannot tell which receipt schema applies without inspecting the raw hash.

**Recommendation:** Add `tool_receipt_kind: str | None` — values like `"validate_receipt.v1"`, `"search_replace_receipt.v1"`, `"write_file_receipt.v1"`.

### Gap 2: No `tool_receipt_schema_version`
If the underlying receipt schema evolves (e.g. validate_receipt.v2), the execution result doesn't record which version produced the hash.

**Recommendation:** Add `tool_receipt_schema_version: str | None` — e.g. `"rig.relay.validate_receipt.v1"`.

### Gap 3: No `envelope_id` linkage to ReceiptEnvelope
The execution result has `invocation_id` (= intent_id = envelope.invocation_id), but no field linking to the `ReceiptEnvelope.envelope_id`.

**Recommendation:** Add `receipt_envelope_id: str | None`.

### Gap 4: No `audit_event_id` linkage
If an audit event is created for the execution, there's no back-link from the execution result.

**Recommendation:** Add `audit_event_id: str | None` (populated by audit integration layer, not runner).

### Gap 5: `receipt_sha256` semantics ambiguous
Currently hashes the tool receipt's canonical JSON (`model_dump(mode="json"), sort_keys=True`). This is correct but undocumented.

**Recommendation:** Document that `receipt_sha256` = SHA256 of tool receipt canonical JSON. The ReceiptEnvelope computes its own hash of the receipt payload independently.

### Gap 6: No `changed_paths` for mutation tools
When mutation tools execute, the adapter wrapper has no way to surface which files were changed without resorting to the full tool receipt.

**Recommendation:** Add `changed_paths: list[str] = Field(default_factory=list)` — already content-light (just path names).

### Gap 7: `duration_ms` only from execution start
Currently measures from `execute_validate()` start to end. Does not capture tool-level duration separately.

**Recommendation:** Keep as-is. Tool duration is in the tool receipt. This is adapter-level wall clock.

## 4. Proposed: `runtime_tool_invocation_receipt.v1`

A new schema that defines the adapter-level content-light receipt bridging `RuntimeToolExecutionResult` → tool receipt → `ReceiptEnvelope`.

**Rationale:** Without this schema, every tool execution path must independently decide what to put in the ReceiptEnvelope evidence. A standard adapter-level receipt schema provides:
- Deterministic structure for all tool types
- Clear content-light contract
- Known linkage fields for audit and governance

**Proposed fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | string | yes | `"rig.relay.runtime_tool_invocation_receipt.v1"` |
| `invocation_id` | string | yes | From envelope |
| `intent_id` | string | yes | From original intent |
| `tool_name` | string | yes | From envelope |
| `adapter_status` | string | yes | `"completed"` `"blocked"` `"refused"` `"failed"` |
| `tool_status` | string | no | Tool-level outcome string |
| `tool_error_kind` | string | no | Structured error kind |
| `tool_receipt_kind` | string | no | e.g. `"validate_receipt.v1"` |
| `tool_receipt_schema_version` | string | no | e.g. `"rig.relay.validate_receipt.v1"` |
| `receipt_sha256` | string | no | SHA256 of tool receipt canonical JSON |
| `envelope_id` | string | no | ReceiptEnvelope ID when one is built |
| `audit_event_id` | string | no | AuditEvent ID when one is created |
| `changed_paths` | string[] | no | Files affected by mutation tools |
| `duration_ms` | number | no | Adapter-level wall clock |
| `created_at` | string | no | ISO 8601 timestamp |
| `warnings` | string[] | no | Non-fatal warnings |

**Not included:**
- Tool-specific payload fields (content, path, argv, SEARCH/REPLACE blocks)
- Raw output (stdout, stderr, diffs)
- Full tool receipt data (that's what `receipt_sha256` references)

## 5. Content-Light Policy

### Allowed fields across all layers

| Category | Examples |
|----------|----------|
| Identifiers | `schema_version`, `invocation_id`, `intent_id`, `envelope_id`, `event_id`, `check_id`, `workspace_id`, `session_id`, `task_id`, `lane_id` |
| Status strings | `status`, `tool_status`, `adapter_status` |
| Error info | `error_kind`, `tool_error_kind`, `refusal_reason`, `failure_kind` |
| Timing | `duration_ms` |
| Byte counts | `stdout_bytes`, `stderr_bytes`, `before_bytes`, `after_bytes`, `bytes_written` |
| Hashes | `stdout_sha256`, `stderr_sha256`, `receipt_sha256`, `before_sha256`, `after_sha256`, `evidence_sha256`, `status_porcelain_sha256` |
| Schema versions | `tool_receipt_schema_version`, `schema_version` fields |
| Linkage IDs | `envelope_id`, `audit_event_id`, `receipt_envelope_id`, `governance_decision_id` |
| Path names | `changed_files`, `affected_paths`, `dirty_paths`, `changed_paths`, `requested_paths` |
| Counters | `command_count`, `passed_count`, `failed_count`, `skipped_count`, `blocks_applied`, `lines_changed`, `replacements`, `dirty_count` |
| Flags | `stdout_truncated`, `stderr_truncated`, `file_existed`, `created_file`, `overwrote_existing_file`, `envelope_schema_valid` |
| Meta | `profile`, `scope`, `command_kind`, `command_fingerprint`, `blocker_summary`, `warnings` |

### Forbidden fields (must never appear in execution results, receipts, receipt envelopes, or audit events)

| Category | Examples |
|----------|----------|
| Raw stdout/stderr | `stdout`, `stderr` content strings |
| File content | `content` in search_replace_result, write_file content |
| Diffs/patches | `diff`, `patch`, `chunk_text`, `old_text`, `new_text` |
| Prompts | Any prompt text sent to LLMs |
| Secrets | API keys, tokens, credentials, auth headers |
| Unbounded output | Any field that could contain arbitrary-length command output |
| Parsed summaries | `parsed_summary` in tool results (OK in full tool result, forbidden in receipt/envelope) |
| Git porcelain | Raw `git status` output (forbidden in receipts; `status_porcelain_sha256` is allowed) |

## 6. Schema Validation Coverage

| Schema | Validates model_dump? | Test file |
|--------|----------------------|-----------|
| `runtime_tool_invocation.v1` | Yes (adapter test) | `test_runtime_tool_invocation_adapter.py` |
| `runtime_tool_invocation_dry_run.v1` | Yes (dry-run test) | `test_runtime_tool_invocation_dry_run.py` |
| `runtime_tool_execution_result.v1` | Yes (execution test) | `test_runtime_tool_invocation_execution.py` |
| `receipt_envelope.v1` | Yes (evidence test) | `test_receipt_envelope.py` |
| `audit_event.v1` | Yes (evidence test) | `test_audit_trail.py` |
| `validate_receipt.v1` | Partial (schema registry only) | `test_tool_schema_contracts.py` |
| `search_replace_receipt.v1` | Partial (schema registry only) | `test_tool_schema_contracts.py` |
| `write_file_receipt.v1` | Partial (schema registry only) | `test_tool_schema_contracts.py` |
| `bash_receipt.v1` | Partial (schema registry only) | `test_tool_schema_contracts.py` |

**Gap:** Tool receipt schemas are registered in `test_tool_schema_contracts.py` but are not validated against actual model dumps. Only the adapter-level schemas validate live model serialization.

## 7. Recommended Implementation Slice

**Slice: "Runtime Tool Invocation Receipt"**
- Add `tool_receipt_kind`, `tool_receipt_schema_version`, `receipt_envelope_id`, `audit_event_id`, `changed_paths` to `RuntimeToolExecutionResult`
- Create `docs/schemas/rig.relay.runtime_tool_invocation_receipt.v1.schema.json`
- Update `runtime_tool_execution_result.v1.schema.json` with new optional fields
- Update `test_tool_schema_contracts.py` to validate tool receipt model dumps against schemas
- Wire `RuntimeToolExecutionRunner` to populate new fields per tool type
- Wire audit integration to populate `audit_event_id`
