# Runtime Tool Invocation Adapter

`RuntimeToolInvocationAdapter` is the relay-native boundary that turns a resolved runtime context into a safe tool or runtime invocation envelope.

## Purpose

Agents should not carry fragile coordination identifiers through each tool call. The adapter consumes a high-level intent plus `RuntimeContextResolution`, then derives the canonical metadata needed for a tool invocation.

## Responsibilities

- Accept a high-level intent, a `RuntimeContextResolution`, a tool name, and the requested path/payload inputs.
- Refuse unresolved, unsafe, or policy-incompatible invocations before they reach a tool.
- Inject canonical `session_id`, `task_id`, `lane_id`, and worktree metadata from the resolved context.
- Apply dirty policy and coordination policy consistently.
- Build the correct invocation envelope for each tool family.
- Bind receipt and audit metadata at the adapter boundary, not in the agent prompt.

## Tool Families

### `write_file`

- Resolve the target path inside the resolved repo/worktree scope.
- Require `expected_before_sha256` when overwriting a dirty-at-start file.
- Preserve overwrite/create-parent policy from the tool contract.
- Prefer the resolved worktree path when the context requires isolation.

### `search_replace`

- Resolve the target path inside the resolved repo/worktree scope.
- Carry `expected_before_sha256` for protected files.
- Preserve patch-block safety and refusal handling.
- Feed the same canonical session/task metadata used for coordination claims.

### `validate`

- Select a validation profile from the context and intent.
- Scope checks to the resolved repo/worktree.
- Use the dirty policy from the resolved context to decide whether validation is allowed to inspect or mutate anything.
- Prefer `worktree-readiness` style checks when a worktree is required.

### `bash` and runtime execution

- Prefer `ExecutionRequest` + `ExecutionLease` + `RuntimeSupervisor`.
- Treat raw bash as legacy fallback only when a governed runtime path is unavailable.
- Map requested capabilities into governance decisions before lease acquisition.

## Blocking / Refusal Taxonomy

The adapter should return structured blocked or refused results for:

- unresolved context
- unsafe path
- missing worktree when required
- dirty policy failure
- active lease conflict
- coordination path already reserved
- missing expected hash
- unsupported tool
- unsupported mutation location
- invalid payload
- session required
- task required

## Metadata Injection

The adapter owns canonical injection for:

- `session_id`
- `task_id`
- `lane_id`
- `workspace_id`
- `worktree_path`
- `repo_root`
- `cwd`

Those values should come from the resolved context, not from ad hoc agent-provided fields.

## Implementation

Phase 1 implementation is complete. See
[docs/governance/runtime-tool-invocation-adapter-implementation.md](runtime-tool-invocation-adapter-implementation.md)
for details.

Source: `rig_relay/runtime/tool_invocation_adapter.py`
Schema: `docs/schemas/rig.relay.runtime_tool_invocation.v1.schema.json`
Tests: `tests/runtime/test_runtime_tool_invocation_adapter.py`

## Dry-Run Integration

The `RuntimeToolDryRunRunner` provides a dry-run layer that validates adapter
output without executing tools, acquiring leases, or mutating files.

- Calls `RuntimeToolInvocationAdapter.prepare()` and validates the envelope.
- Returns `RuntimeToolDryRunResult` with status, schema validity, tool-specific
  payload validity, and refusal/error information.
- `would_execute` is always `False` — this is a dry run.
- `would_mutate` is a classification flag for write_file/search_replace, not an
  action. See `docs/governance/runtime-tool-invocation-dry-run.md`.
- Content-light: dry-run results never store raw invocation payloads.

## Future Shape

Later implementation can split into smaller adapters per surface if needed, but the semantic contract stays the same: intent plus resolved context becomes a safe invocation envelope, or a structured refusal.

