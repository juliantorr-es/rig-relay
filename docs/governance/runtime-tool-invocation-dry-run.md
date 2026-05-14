# Runtime Tool Invocation Dry-Run

`RuntimeToolDryRunRunner` provides a dry-run integration layer for the `RuntimeToolInvocationAdapter`. It calls adapter prepare, validates the envelope against the runtime_tool_invocation schema, and returns a structured assessment — without executing any tool, acquiring any lease, or mutating any file.

## Purpose

Dry-run proves that:
- Context resolves into an adapter envelope
- Envelope validates against schema
- Tool-specific payload shape is structurally valid
- No real tool is executed
- No files are mutated
- No leases are acquired

## Behavior

1. **Prepare** — Calls `RuntimeToolInvocationAdapter.prepare(intent, resolution)` to produce an envelope.
2. **Classify** — Flags `would_mutate=True` for write_file and search_replace; `would_execute=False` always; `would_acquire_lease=False` always.
3. **Validate envelope** — Validates the prepared envelope against `rig.relay.runtime_tool_invocation.v1` schema via jsonschema.
4. **Validate payload** — Checks tool-specific payload shape structurally (required fields per tool).
5. **Return result** — Structured `RuntimeToolDryRunResult` with status, validity flags, and refusal/error information.

## Status Mapping

| Adapter Status | Dry-Run Status | Meaning |
|----------------|----------------|---------|
| `prepared` | `would_prepare` | Adapter prepared envelope, schema valid, payload valid |
| `blocked` | `blocked` | Context or policy blocked preparation |
| `refused` | `refused` | Tool/path/payload refused by adapter |
| (schema invalid) | `invalid` | Envelope failed schema validation or payload invalid |

## Content Boundary

- Invocation **envelopes** may contain operational tool input (file content, SEARCH/REPLACE blocks).
- **Dry-run results** must NOT store raw content — only boolean flags, paths, schema validity indicators, and structured error/refusal information.
- Do not feed raw invocation payload into ReceiptEnvelope or AuditTrailStore.

## Guarantees

- **No tools executed** — `would_execute` is always `False`.
- **No files mutated** — `would_mutate` is a classification flag, not an action. Tests verify files are unchanged after dry-run.
- **No leases acquired** — `would_acquire_lease` is always `False`.
- **Content-light** — No raw file contents, stdout, stderr, diffs, snippets, or secrets in results.

## Future

- **One-tool-at-a-time execution** — Dry-run validates adapter output; the next step is to wire one-tool-at-a-time execution through the adapter for write_file, search_replace, and validate via their hardened runtime paths.
- **Audit integration** — Dry-run results could feed into AuditTrailStore for non-repudiation of dry-run decisions.

## Related

- `rig_relay/runtime/tool_invocation_dry_run.py` — module
- `rig_relay/runtime/tool_invocation_adapter.py` — adapter
- `docs/schemas/rig.relay.runtime_tool_invocation_dry_run.v1.schema.json`
- `docs/schemas/rig.relay.runtime_tool_invocation.v1.schema.json`
- `tests/runtime/test_runtime_tool_invocation_dry_run.py`
