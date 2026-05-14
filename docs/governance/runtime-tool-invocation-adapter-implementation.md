# Runtime Tool Invocation Adapter — Implementation

## Status

**Implemented (Phase 1, 2026-05).** Source: `rig_relay/runtime/tool_invocation_adapter.py`.

## Scope

This document covers the first implementation of the `RuntimeToolInvocationAdapter`.
It converts a `RuntimeToolIntent` + `RuntimeContextResolution` into a safe
`RuntimeToolInvocationEnvelope` or a structured refusal. The adapter does NOT
execute tools, mutate files, acquire leases, or persist envelopes.

## Supported Tools

| Tool Name | Status | Behavior |
|-----------|--------|----------|
| `write_file` | Implemented | Prepares write_file envelopes with path/content validation, expected hash enforcement for protected overwrites, and worktree-aware cwd |
| `search_replace` | Implemented | Prepares search_replace envelopes with file_path/content validation, canonical metadata injection |
| `validate` | Implemented | Prepares validate envelopes with profile/paths/dirty_policy injection from context |
| `runtime_exec` | Implemented | Builds ExecutionRequest-shaped payload, validates via model construction, never acquires lease or executes |
| `bash_legacy` | Implemented | Refused by default unless `legacy_fallback_allowed=True` |

## Refusal Taxonomy

| Error Kind | Trigger |
|------------|---------|
| `context_unresolved` | Resolution status is `blocked` or `refused`, or context is None |
| `worktree_required` | `require_worktree=True` but no `worktree_path` in context |
| `unsafe_path` | Requested path is outside repo_root or worktree scope |
| `unsupported_mutation_location` | Mutation tool without worktree and `allow_main_repo_mutation=False` |
| `expected_hash_missing` | `allow_overwrite_protected=True` without `expected_before_sha256` |
| `invalid_payload` | Missing required payload fields (path, content, argv, file_path) |
| `unsupported_tool` | Unrecognized tool name (or bash_legacy without explicit opt-in) |

## Enums

### RuntimeToolName
`write_file`, `search_replace`, `validate`, `runtime_exec`, `bash_legacy`

### RuntimeToolInvocationStatus
`prepared`, `blocked`, `refused`

### RuntimeToolInvocationErrorKind
`context_unresolved`, `session_required`, `task_required`, `worktree_required`,
`unsafe_path`, `dirty_policy_failed`, `lease_conflict`, `path_reserved`,
`expected_hash_missing`, `unsupported_tool`, `unsupported_mutation_location`,
`invalid_payload`

## Models

### RuntimeToolIntent
- `intent_id`: str (required)
- `tool_name`: RuntimeToolName (required)
- `payload`: dict[str, Any] (default {})
- `requested_paths`: list[str] (default [])
- `require_worktree`: bool (default False)
- `allow_main_repo_mutation`: bool (default False)

### RuntimeToolInvocationEnvelope
- `schema_version`: str (const `rig.relay.runtime_tool_invocation.v1`)
- `invocation_id`: str (required)
- `intent_id`: str (required)
- `tool_name`: RuntimeToolName (required)
- `status`: RuntimeToolInvocationStatus (required)
- `session_id`, `task_id`, `lane_id`, `workspace_id`: optional str
- `worktree_path`, `repo_root`, `cwd`: optional str
- `payload`: dict[str, Any]
- `requested_paths`: list[str]
- `error_kind`, `refusal_reason`: optional

All models use `extra="forbid"` and stable StrEnum serialization.

## Adapter: `prepare()` Method

Signature:
```python
def prepare(
    self,
    intent: RuntimeToolIntent,
    resolution: RuntimeContextResolution,
) -> RuntimeToolInvocationEnvelope
```

Behavior:
1. If resolution is blocked/refused → BLOCKED with CONTEXT_UNRESOLVED
2. If context is None → BLOCKED with CONTEXT_UNRESOLVED
3. If require_worktree and no worktree_path → BLOCKED with WORKTREE_REQUIRED
4. Resolve cwd: worktree_path → repo_root → None
5. If mutation tool and no worktree without allow_main_repo_mutation → REFUSED with UNSUPPORTED_MUTATION_LOCATION
6. Validate paths against repo/worktree scope → REFUSED with UNSAFE_PATH
7. Delegate to tool-specific handler

## Tool-Specific Behavior

### write_file
- Requires `path` and `content` in payload
- If `allow_overwrite_protected=True` without `expected_before_sha256` → REFUSED with EXPECTED_HASH_MISSING
- Uses worktree cwd when available

### search_replace
- Requires `file_path` (or `file`) in payload
- Preserves canonical session/task metadata
- Refuses mutation into main repo without `allow_main_repo_mutation=True`

### validate
- Defaults profile to `"quick"` if not specified
- Injects `workspace_root` from cwd if not set
- Injects `paths` from intent's requested_paths if not set
- Injects `expected_dirty_policy` from context if not set

### runtime_exec
- Requires `argv` as non-empty list of strings
- Validates payload shape by constructing an `ExecutionRequest` model (no persistence)
- Puts ExecutionRequest fields flat in the payload (not nested under `_execution_request`)
- Does NOT acquire lease or execute

### bash_legacy
- Refused by default unless `legacy_fallback_allowed=True` in payload
- When allowed, requires `command` in payload

## Raw Payload vs Receipt Boundary

Invocation envelopes carry operational input payloads that the tool needs to
execute (file content, SEARCH/REPLACE blocks, argv). These are NOT content-light.
Receipts, audit events, and projection integrity assessments derived from these
envelopes MUST be content-light — they must not carry raw payloads.

## Schema

Schema file: `docs/schemas/rig.relay.runtime_tool_invocation.v1.schema.json`

- Draft 7
- `additionalProperties: false` at all levels
- Nullable fields for optional metadata
- Enum validation for tool names, statuses, error kinds
- Schema version constant: `rig.relay.runtime_tool_invocation.v1`

## Cross-References

- **Dry-run runner**: `rig_relay/runtime/tool_invocation_dry_run.py` — validates
  adapter envelopes without executing tools. See
  [runtime-tool-invocation-dry-run.md](runtime-tool-invocation-dry-run.md).

## Deferred Features

| Feature | Phase | Reason |
|---------|-------|--------|
| Result/receipt schemas | Phase 2 | Content-light receipt delivery after tool execution |
| Lease acquisition | Phase 2 | Requires ExecutionLease integration |
| Supervisor dispatch | Phase 2 | Requires RuntimeSupervisor integration |
| Audit trail persistence | Phase 3 | Requires AuditTrailStore integration |
| Result validation | Phase 2 | Schema-driven result contract after execution |
