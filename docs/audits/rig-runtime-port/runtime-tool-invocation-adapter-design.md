# Runtime Tool Invocation Adapter Design

**Status: Phase 1 implemented** — adapter models, schema, and 38 tests complete.

## Design Summary

The adapter is the missing bridge between `RuntimeContextResolution` and actual tool/runtime invocation envelopes.

Its job is to keep coordination identifiers, dirty policy, and path scope in the runtime control plane instead of making the agent manually repair them at call time.

## Input

- High-level intent
- `RuntimeContextResolution`
- tool name
- requested paths and payload
- optional mutation/validation policy hints

## Output

- structured tool invocation envelope, or
- structured blocked/refused result

## Canonical Behavior

1. Resolve context first.
2. Refuse if the context is blocked or unresolved.
3. Normalize paths against repo/worktree scope.
4. Inject canonical IDs from the resolved context.
5. Apply tool-specific policy.
6. Bind receipt/audit metadata for later evidence collection.

## Tool-Specific Mapping

### WriteFile

- Use the resolved worktree path if present.
- Require `expected_before_sha256` for protected overwrites.
- Preserve create vs overwrite semantics.
- Refuse unsupported mutation locations instead of silently falling back.

### SearchReplace

- Use the resolved worktree or repo scope.
- Require expected hash for protected files.
- Keep block safety and reservation logic intact.
- Prefer a structured refusal over a generic tool error.

### Validate

- Choose a validate profile from the intent and scope.
- Keep checks read-only unless a profile explicitly permits mutation.
- Use dirty policy as an input, not a per-agent guess.

### Bash / Runtime Execution

- Prefer `ExecutionRequest` and `ExecutionLease`.
- Route governed execution through lease and supervisor plumbing.
- Raw bash remains a compatibility fallback, not the default control path.

## Refusal Taxonomy

- `context_unresolved`
- `session_required`
- `task_required`
- `worktree_required`
- `unsafe_path`
- `dirty_policy_failed`
- `lease_conflict`
- `path_reserved`
- `expected_hash_missing`
- `unsupported_tool`
- `unsupported_mutation_location`

## Dependencies

- `rig_relay.runtime.context`
- `rig_relay.runtime.context_resolver`
- `rig_relay.coordination.store`
- `rig_relay.coordination.worktree_manager`
- `rig_relay.coordination.execution_lease`
- `rig_relay.runtime.execution_request`
- `rig_relay.runtime.supervisor`
- `rig_relay.governance.governance_engine`
- `rig_relay.evidence.receipt_index`
- `rig_relay.evidence.receipt_envelope`
- `rig_relay.evidence.audit_trail`

## Dry-Run Integration

The `RuntimeToolDryRunRunner` provides a dry-run assessment layer:

1. Calls `RuntimeToolInvocationAdapter.prepare()` to produce an envelope.
2. Validates the envelope against `rig.relay.runtime_tool_invocation.v1` schema.
3. Validates tool-specific payload shape structurally (required fields per tool).
4. Returns `RuntimeToolDryRunResult` — always `would_execute=False`,
   `would_acquire_lease=False`, never stores raw payload content.

Dry-run proves the adapter output is schema-valid and structurally valid without
executing tools, acquiring leases, or mutating files.

See `docs/governance/runtime-tool-invocation-dry-run.md`.

## Future Schemas

Proposed later:

- `rig.relay.runtime_tool_invocation.v1` (implemented)
- `rig.relay.runtime_tool_invocation_result.v1`
- `rig.relay.runtime_tool_invocation_receipt.v1`
- `rig.relay.runtime_tool_invocation_dry_run.v1` (implemented)

These should remain content-light and should not carry raw prompts, raw stdout/stderr, raw diffs, or file bodies.

