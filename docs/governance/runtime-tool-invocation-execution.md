# Runtime Tool Invocation Execution

**File:** `docs/governance/runtime-tool-invocation-execution.md`

## Purpose

The execution layer bridges the runtime adapter and concrete tools (validate, search_replace, write_file, bash), providing structured, content-light execution paths that return `RuntimeToolExecutionResult` objects. Phase 3 adds `execute_runtime_exec()` as a top-level router above all four Phase 2 adapters.

## Execution Paths

### Validate (read-only) — `execute_validate()`
- Runs the `Validate` tool through the adapter
- Returns content-light `RuntimeToolExecutionResult`
- First read-only execution behind the adapter (Phase 1)
- No InvokeContext passed (read-only, no coordination needed)

### SearchReplace (mutation) — `execute_search_replace()`
- Runs the `SearchReplace` tool through its hardened interface
- Returns content-light `RuntimeToolExecutionResult`
- First mutation execution behind the adapter (Phase 1)
- **InvokeContext injected**: session_id and task_id are passed through the
  invocation path via `_build_invoke_context()`
- **CWD managed**: `_cwd_for_envelope()` temporarily sets CWD to
  `envelope.cwd` during execution, restoring the original on exit
- **Coordination enabled**: the tool's internal coordination runs using
  the injected context (session_id, task_id). Same-owner renewal succeeds.
  Reservations are released immediately after execution.

### WriteFile (mutation) — `execute_write_file()`
- Runs the `WriteFile` tool through its hardened interface (Phase 2)
- Returns content-light `RuntimeToolExecutionResult`
- **InvokeContext injected**: session_id and task_id are passed through the
  invocation path via `_build_invoke_context()`
- **CWD managed**: `_cwd_for_envelope()` temporarily sets CWD to
  `envelope.cwd` during execution, restoring the original on exit
- **Coordination enabled**: the tool's internal coordination runs using
  the injected context (session_id, task_id).
- **Dirty guard**: the tool internally handles dirty-file protection,
  protected-file permission, and expected-before-SHA256 validation.
- **Receipt**: `WriteFileReceipt` is built via `_build_write_file_receipt()`
  and converted to a `RuntimeToolInvocationReceipt` through `_attach_receipt()`.
- **Linkage**: `tool_receipt_kind='write_file'`,
  `tool_receipt_schema_version='rig.relay.write_file_receipt.v1'`,
  `changed_paths=[path]` populated on success.

### Bash (subprocess) — `execute_bash()`
- Runs the `Bash` tool through its hardened interface (Phase 2)
- Returns content-light `RuntimeToolExecutionResult`
- **InvokeContext injected**: session_id and task_id are passed through the
  invocation path via `_build_invoke_context()`
- **CWD managed**: `_cwd_for_envelope()` temporarily sets CWD to
  `envelope.cwd` during execution, restoring the original on exit
- **Timeout handled by bash tool**: the hardened `Bash._run_subprocess()` uses
  `asyncio.wait_for()` with the configured timeout; timeouts produce
  `BashResult(status="timed_out", error_kind="timeout")` which maps to
  `RuntimeToolExecutionResult(tool_status="timed_out", error_kind="timeout")`
- **Guard integration**: destructive git commands (`git restore`, `git checkout`,
  `git reset`, `git clean`, `git stash`) are refused by the dirty-file guard
  before execution, producing `BashResult(status="refused")`
- **Error handling**: non-zero exit codes raise `ToolError` (preserving existing
  hardened contract), caught by the adapter as `FAILED` with
  `error_kind="execution_error"`
- **Receipt**: `BashReceipt` is built via `_build_bash_receipt()` and converted
  to a `RuntimeToolInvocationReceipt` through `_attach_receipt()`. The receipt
  is content-light — no raw stdout/stderr, only SHA256 hashes and byte counts.
- **Linkage**: `tool_receipt_kind='bash'`,
  `tool_receipt_schema_version='rig.relay.bash_receipt.v1'`,
  `changed_paths=[]` (bash does not track file changes)

### Constraints
- **bash_legacy** — ✅ Supported (Phase 2)
- **runtime_exec** — NOT wired (deferred to Phase 2)
- No lease acquisition
- No RuntimeSupervisor integration
- No audit persistence

## Audit Persistence (Phase 3)

RuntimeToolExecutionResult outcomes are persisted as 
RuntimeAuditEvent records to an append-only JSONL store.
Each execute_*() method in RuntimeToolExecutionRunner calls
_persist_if_configured() before returning, writing a content-light
audit event. Early returns (blocked, refused, failed) are also
persisted. Persistence is best-effort: failures are silently
ignored so audit never breaks tool execution.

### RuntimeAuditEvent
- Content-light: no raw payloads, stdout, stderr, diffs, snippets, secrets
- Records: invocation_id, tool_name, status, tool_status, receipt_sha256,
  runtime_result_sha256 (SHA-256 of the execution result's canonical JSON),
  changed_paths, duration_ms, error fields, created_at
- Context propagation (Otel-inspired): mission_id, agent_id, lease_id,
  parent_event_id carried when available
- Schema: `rig.relay.runtime_audit_event.v1`

### RuntimeAuditPersistenceStore
- Append-only JSONL persistence under an injected root path
- Creates parent directories automatically
- Uses flush + fsync for best-effort durability
- Example: `RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")`

## Supervisor Projection (Phase 3)

`RuntimeSupervisorProjection` is a content-light summary derived from
`RuntimeAuditEvent` records. It is not derived from raw tool payloads.

### Projection contents
- total_invocations: total count
- status_counts: counts per status (completed, blocked, refused, failed)
- recent_invocations: most recent events (capped, sorted by created_at desc)
- changed_path_count: total changed paths across recent events
- changed_path_hashes: SHA-256 hashes of recent runtime results

Builder: `build_runtime_supervisor_projection(store_or_events)`
Schema: `rig.relay.runtime_supervisor_projection.v1`

## Context Injection

### `_build_invoke_context(envelope)`

Builds an `InvokeContext` from the invocation envelope:

| Envelope field | InvokeContext field |
|----------------|---------------------|
| `session_id` | `session_dir` (as `Path("/runtime/sessions/{session_id}")`) |
| `task_id` | `tool_call_id` |

Returns `None` when the envelope lacks `session_id` or `task_id`,
preserving backward compatibility (coordination skipped).

### `_cwd_for_envelope(envelope)`

Context manager that sets `os.chdir()` to `envelope.cwd` during tool
execution. This allows the tool's `Path.cwd()`-based checks (path
validation via `require_path_within_workdir`, coordination store
resolution via `Path.cwd() / ".build" / "rig-relay" / "coordination"`)
to operate within the correct scope.

- If `envelope.cwd` is `None`, the context manager is a no-op
- The original CWD is always restored in a `finally` block
- Tool execution (path resolution, guard checks, file mutation) happens
  within the scope of this context manager

### Receipt Model Attachment

Both `execute_validate()` and `execute_search_replace()` call
`build_runtime_tool_invocation_receipt()` after constructing the result,
storing the returned `RuntimeToolInvocationReceipt` directly in the
`receipt` field of `RuntimeToolExecutionResult`. Receipt building failures
are silently caught — `receipt` remains `None`.

The `RuntimeToolInvocationReceipt` model has `extra="forbid"` and the
execution result schema validates it through a `$ref` to
`#/$defs/runtime_tool_invocation_receipt` with `additionalProperties: false`.
This provides strict type safety at both the Python and schema level,
replacing the previous `dict[str, Any]` bridge.## Coordination Behavior

The `SearchReplace` tool internally handles coordination via
`_build_coordination_state()` and `_claim_coordination()`. When an
InvokeContext with `session_dir` and `tool_call_id` is provided:

1. **Claim task**: `store.claim_task(session_id, task_id, ...)` — reserves
   the task for the session
2. **Reserve path**: `store.reserve_paths(session_id, task_id, mode="write",
   paths=[...])` — reserves the target file path
3. **Same-owner renewal**: same `(session_id, task_id)` refreshes the claim
   without conflict
4. **Release**: reservations are released in a `finally` block after
   execution completes

The coordination store is created at
`Path.cwd() / ".build" / "rig-relay" / "coordination"`. Since the runner
sets CWD to `envelope.cwd`, the store is scoped to the worktree directory.

## CWD/Worktree Scope

Tests no longer require `monkeypatch.chdir()` for search_replace execution.
The runner's `_cwd_for_envelope()` context manager handles CWD management.

If `monkeypatch.chdir()` is still used in a test, it overrides the runner's
CWD setting. This is acceptable for tests intentionally testing CWD
behavior but is not required for normal operation.

## Receipt Hashing

- Receipts are built from tool results via the tool's `build_receipt()` method
- The receipt is serialized to canonical JSON (`sort_keys=True`) and SHA-256 hashed
- Receipt building failures are silently caught — `receipt_sha256` remains `None`

## Status Mapping

| Tool (any) status | Execution result status | Notes |
|-------------------|------------------------|-------|
| `success` / `passed` / `failed` | `COMPLETED` | Tool ran to completion |
| `skipped` / `timed_out` | `COMPLETED` | Timeout captured via `tool_status` and `error_kind` |
| `refused` / `blocked` | `REFUSED` | Guard or adapter refusal |
| bash `failure` (non-zero exit) | `FAILED` | `ToolError` raised by hardened bash contract, caught as `execution_error` |
| bash `refused` (guard) | `REFUSED` | Destructive git commands blocked by dirty-file guard |

Adapter-level `BLOCKED` → `BLOCKED`. Adapter-level `REFUSED` → `REFUSED`.

## Linkage Field Population

The `RuntimeToolExecutionResult` model carries linkage fields that bridge
the execution result to tool receipts, receipt envelopes, and audit events:

| Field | Validate | SearchReplace | Bash | Description |
|-------|----------|---------------|------|-------------|
| `tool_receipt_kind` | `"validate"` | `"search_replace"` | `"bash"` | Identifies which receipt schema applies |
| `tool_receipt_schema_version` | From `ValidateReceipt.schema_version` | From `SearchReplaceReceipt.schema_version` | From `BashReceipt.schema_version` | Records which schema version produced the receipt hash |
| `changed_paths` | `[]` (empty) | `[file_path]` | `[]` (bash does not track file changes) | Files affected by mutation tools |
| `receipt` | `RuntimeToolInvocationReceipt` | `RuntimeToolInvocationReceipt` | `RuntimeToolInvocationReceipt` | Produced by `build_runtime_tool_invocation_receipt()` and stored directly as the Pydantic model |
| `invocation_id` | From envelope | From envelope | From envelope | Links result back to invocation |
| `receipt_envelope_id` | `None` (Phase 2) | `None` (Phase 2) | `None` (Phase 2) | Populated by envelope builder |
| `audit_event_id` | `None` (Phase 2) | `None` (Phase 2) | `None` (Phase 2) | Populated by audit integration |

The `receipt` field stores a `RuntimeToolInvocationReceipt` Pydantic model
(not a dict). The model has `extra="forbid"` and the execution result
schema references it via `$ref` to `#/$defs/runtime_tool_invocation_receipt`
with `additionalProperties: false`. This guarantees content-light conformance
at both the type and schema level — no dicts, no raw content, no arbitrary
properties.

## Raw Payload Boundary

WriteFileResult has a `content: str` field that contains the raw file
content. This field is explicitly governed:

- **Local operational payload only** — used by the agent loop for display
  and verification during the same session
- **Not emitted in receipt** — `WriteFileReceipt` has no `content` field;
  `build_receipt()` never copies it
- **Not emitted in runtime execution result** — `RuntimeToolExecutionResult`
  has no `content` field; write_file is not wired into the runner
- **Not emitted in telemetry/projections** — tool output artifacts and
  observability events use only SHA256 hashes and metadata

BashResult has `stdout: str` and `stderr: str` fields that contain raw
command output. These fields are explicitly governed:

- **Local operational payload only** — used by the agent loop for display
  and verification during the same session
- **Not emitted in receipt** — `BashReceipt` has no `stdout`/`stderr` fields;
  `build_receipt()` computes SHA256 hashes and byte counts instead
- **Not emitted in runtime execution result** — `RuntimeToolExecutionResult`
  has no `stdout`/`stderr` fields; the content-light contract is enforced
  by `ConfigDict(extra="forbid")` on all models and `additionalProperties: false`
  on all schemas
- **Not emitted in telemetry/projections** — only hashes and metadata

This boundary is enforced by the receipt schema
(`rig.relay.write_file_receipt.v1`, `additionalProperties: false`) and
the execution result schema
(`rig.relay.runtime_tool_execution_result.v1`, `additionalProperties: false`).

## Content-Light Contract

The `RuntimeToolExecutionResult` model contains no raw file contents,
stdout, stderr, diffs, snippets, or secrets. Only status indicators,
hashes, timing, and structured error/refusal information.

## Usage

```python
from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolIntent, RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import RuntimeToolExecutionRunner

ctx = RuntimeContext(
    session_id="sess-001",
    task_id="task-001",
    worktree_path="/tmp/worktree",
    repo_root="/tmp/repo",
)
resolution = RuntimeContextResolution(status="resolved", context=ctx)

# Validate execution (no InvokeContext)
v_intent = RuntimeToolIntent(
    intent_id="intent-001",
    tool_name=RuntimeToolName.VALIDATE,
    payload={"profile": "quick"},
)
runner = RuntimeToolExecutionRunner()
v_result = await runner.execute_validate(v_intent, resolution)

# SearchReplace execution (InvokeContext injected, CWD managed)
sr_intent = RuntimeToolIntent(
    intent_id="intent-002",
    tool_name=RuntimeToolName.SEARCH_REPLACE,
    payload={
        "file_path": "src/main.py",
        "content": "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE",
    },
)
sr_result = await runner.execute_search_replace(sr_intent, resolution)

# Bash execution
b_intent = RuntimeToolIntent(
    intent_id="intent-003",
    tool_name=RuntimeToolName.BASH_LEGACY,
    payload={"command": "echo hello", "legacy_fallback_allowed": True},
)
b_result = await runner.execute_bash(b_intent, resolution)
```

## Implementation Status

| Feature | Status | Notes |
|---------|--------|-------|
| `execute_validate()` | ✅ Implemented | Read-only, runs Validate tool |
| `execute_search_replace()` | ✅ Implemented | Mutation, runs SearchReplace through hardened interface |
| Context injection (InvokeContext) | ✅ Implemented | session_id, task_id passed to tool |
| CWD management | ✅ Implemented | `_cwd_for_envelope()` context manager |
| Coordination via injected context | ✅ Implemented | Same-owner renewal, released after execution |
| Adapter prepare → blocked → refused | ✅ Implemented | Both paths handle BLOCKED and REFUSED envelopes |
| Envelope schema validation | ✅ Implemented | Draft7 validation against runtime_tool_invocation schema |
| Receipt hashing | ✅ Implemented | SHA-256 of canonical JSON receipt |
| Linkage fields (validate) | ✅ Implemented | `tool_receipt_kind`, `tool_receipt_schema_version` populated |
| Linkage fields (search_replace) | ✅ Implemented | `tool_receipt_kind`, `tool_receipt_schema_version`, `changed_paths` populated |
| Receipt model attachment | ✅ Implemented | `build_runtime_tool_invocation_receipt()` stores model directly as `RuntimeToolInvocationReceipt` |
| Schema validation (no workarounds) | ✅ Implemented | Tests validate full model dumps without `exclude_none` |
| Content-light results | ✅ Implemented | No raw content in result model |
| Schema validation of result | ✅ Implemented | Against `rig.relay.runtime_tool_execution_result.v1` |
| `execute_write_file()` | ✅ Implemented | Mutation, runs WriteFile through hardened interface |
| `execute_bash()` | ✅ Implemented | Subprocess, runs Bash through hardened interface with timeout/refusal/error handling |
| Lease acquisition | ❌ Deferred | Phase 2 |
| RuntimeSupervisor integration | ❌ Deferred | Phase 2 |
| Audit persistence | ❌ Deferred | Phase 2 |

## Dependencies

- `RuntimeToolInvocationAdapter` — translates intent + context to envelope
- `RuntimeToolInvocationEnvelope` — carries session_id, task_id, cwd, payload
- `InvokeContext` (`vibe.core.tools.base`) — passed to SearchReplace tool
- `Validate` tool (`vibe/core/tools/builtins/validate.py`) — actual validation logic
- `SearchReplace` tool (`vibe/core/tools/builtins/search_replace.py`) — actual search/replace logic
- `Bash` tool (`vibe/core/tools/builtins/bash.py`) — actual command execution with timeout/refusal/error handling (`vibe/core/tools/builtins/search_replace.py`) — actual search/replace logic
- `jsonschema` — envelope schema validation
- Schema: `rig.relay.runtime_tool_execution_result.v1`
