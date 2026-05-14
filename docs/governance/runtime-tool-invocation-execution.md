# Runtime Tool Invocation Validate Execution

**File:** `docs/governance/runtime-tool-invocation-execution.md`

## Purpose

The execution layer bridges the runtime adapter and concrete tools (validate, search_replace), providing structured, content-light execution paths that return `RuntimeToolExecutionResult` objects.

## Execution Paths

### Validate (read-only)
- Runs the `Validate` tool through the adapter
- Returns content-light result with `tool_receipt_kind="validate"`

### SearchReplace (mutation)
- Runs the `SearchReplace` tool through its hardened interface
- Returns content-light result with `changed_paths` and `tool_receipt_kind="search_replace"`

### No lease acquisition, no RuntimeSupervisor integration, no audit persistence

## Key Design Decisions

### Tool construction
- Tool instances are created per-invocation with tool-specific config and `BaseToolState()`
- The `run()` method is an `AsyncGenerator` — the final yielded value is the tool result
- `build_receipt()` is a synchronous instance method

### Receipt hashing
- Receipts are built from tool results via the tool's `build_receipt()` method
- The receipt is serialized to canonical JSON (`sort_keys=True`) and SHA-256 hashed
- Receipt building failures are silently caught — `receipt_sha256` remains `None`

### Linkage fields (added in P3b)
`RuntimeToolExecutionResult` now includes:
- `tool_receipt_kind` — discriminator for the receipt type (e.g. "validate", "search_replace")
- `tool_receipt_schema_version` — schema version of the underlying tool receipt
- `receipt_envelope_id` — future: links to a `ReceiptEnvelope` when one is built
- `audit_event_id` — future: links to an `AuditEvent` when one is created
- `changed_paths` — files affected by mutation tools (empty for validate)

These are linkage fields only — they do not contain tool-specific payload data.

### Status mapping

| Tool status (validate) | Adapter status |
|------------------------|----------------|
| `passed` | `COMPLETED` |
| `failed` | `COMPLETED` |
| `skipped` | `COMPLETED` |
| `timed_out` | `COMPLETED` |
| `refused` | `REFUSED` |
| `blocked` | `REFUSED` |

Adapter-level `BLOCKED` → `BLOCKED`. Adapter-level `REFUSED` → `REFUSED`.

### Content-light contract
The `RuntimeToolExecutionResult` model contains no raw file contents, stdout, stderr, diffs, snippets, or secrets. Only status indicators, hashes, timing, and structured error/refusal information.

## RuntimeToolInvocationReceipt

The `RuntimeToolInvocationReceipt` model (in `tool_invocation_receipt.py`) bridges the execution result to the evidence layer. It is built via `build_runtime_tool_invocation_receipt(result)` which copies content-light fields and adds a timestamp.

This is NOT a tool receipt (those are tool-specific, e.g. `ValidateReceipt`).  
This is NOT a `ReceiptEnvelope` (those have actor/subject/decision/evidence wrappers).  
This is an adapter-level content-light receipt that links the execution result → tool receipt → envelope → audit event.

## Dependencies

- `RuntimeToolInvocationAdapter` — translates intent + context to envelope
- `Validate` tool / `SearchReplace` tool — actual tool logic
- `jsonschema` — envelope schema validation
- Schemas: `rig.relay.runtime_tool_execution_result.v1`, `rig.relay.runtime_tool_invocation_receipt.v1`
