# Tool Hardening Priority

## `bash` ✅ COMPLETED
- Risk tier: `3`
- Observed usage: `5023` calls
- Failure count: `337`
- Guardrails: schema validation, max output size, timeout, structured refusal, content-light summaries, per-stream byte caps, content-light receipts, explicit cwd, structured timeout result
- Tests: 58 tests total (10 base + 23 hardening + 25 permission/denylist)
- Deterministic envelope: **implemented** (BashResult with status/duration_ms/truncation_flags/error_kind, BashReceipt with SHA256 hashes, JSON schemas for invocation/result/receipt)
- Schemas: `docs/schemas/rig.relay.bash_invocation.v1.schema.json`, `rig.relay.bash_result.v1.schema.json`, `rig.relay.bash_receipt.v1.schema.json`
- Docs: `docs/audits/tool-hardening/bash-deterministic-envelope.md`

## `search_replace`
- Risk tier: `1`
- Observed usage: `2057` calls
- Failure count: `217`
- Guardrails: schema validation, max output size, timeout, structured refusal, content-light summaries
- Tests: malformed input, refusal path, truncation, protected content redaction
- Deterministic Rig-managed tool: maybe
- Receipt envelope: **implemented** (SearchReplaceReceipt with SHA256 before/after hashes, block counts, byte counts, error classification)
- Receipt index: **implemented** (indexed by `rig_relay.evidence.receipt_index`)
- Schemas: `docs/schemas/rig.relay.search_replace_invocation.v1.schema.json`, `rig.relay.search_replace_receipt.v1.schema.json`, `rig.relay.tool_receipt_index.v1.schema.json`

## `write_file`
- Risk tier: `2`
- Observed usage: `943` calls
- Failure count: `39`
- Guardrails: schema validation, max output size, timeout, structured refusal, content-light summaries
- Tests: malformed input, refusal path, truncation, protected content redaction
- Deterministic Rig-managed tool: maybe

## `coordination`
- Risk tier: `0`
- Observed usage: `260` calls
- Failure count: `28`
- Guardrails: schema validation, max output size, timeout, structured refusal, content-light summaries
- Tests: malformed input, refusal path, truncation, protected content redaction
- Deterministic Rig-managed tool: maybe

## `read_file`
- Risk tier: `1`
- Observed usage: `3970` calls
- Failure count: `14`
- Guardrails: schema validation, max output size, timeout, structured refusal, content-light summaries
- Tests: malformed input, refusal path, truncation, protected content redaction
- Deterministic Rig-managed tool: maybe

## `grep`
- Risk tier: `0`
- Observed usage: `1243` calls
- Failure count: `4`
- Guardrails: schema validation, max output size, timeout, structured refusal, content-light summaries
- Tests: malformed input, refusal path, truncation, protected content redaction
- Deterministic Rig-managed tool: maybe

## `web_fetch`
- Risk tier: `0`
- Observed usage: `40` calls
- Failure count: `4`
- Guardrails: schema validation, max output size, timeout, structured refusal, content-light summaries
- Tests: malformed input, refusal path, truncation, protected content redaction
- Deterministic Rig-managed tool: maybe

## `task`
- Risk tier: `0`
- Observed usage: `15` calls
- Failure count: `2`
- Guardrails: schema validation, max output size, timeout, structured refusal, content-light summaries
- Tests: malformed input, refusal path, truncation, protected content redaction
- Deterministic Rig-managed tool: maybe

## `validate` ✅ COMPLETED (Stage 1 + Stage 2)
- Risk tier: `0`
- Observed usage: `0` calls
- Failure count: `0`
- Guardrails: schema validation, max output size, timeout, structured refusal, content-light results, content-light summaries, content-light receipts
- Tests: 48 tests (37 Stage 1 profile + 11 Stage 2 receipt)
- Deterministic Rig-managed tool: profile-based, read-only by default
- Receipt envelope: **implemented** (ValidateReceipt with ValidateCheckReceipt per-check hashes and byte counts)
- Receipt index: **implemented** (indexed by `rig_relay.evidence.receipt_index`)
- Schemas: `docs/schemas/rig.relay.validate_invocation.v1.schema.json`, `rig.relay.validate_result.v1.schema.json`, `rig.relay.validate_receipt.v1.schema.json`

## Receipt Index ✅ COMPLETED
- Module: `rig_relay.evidence.receipt_index`
- Model: `ToolReceiptIndexRecord` (content-light, extra="forbid")
- Builder: `build_receipt_index()` reads session observability JSONL
- Summary: `summarize_receipt_index()` with counts by tool/status, mutation/refusal/timeout tracking
- Content-light validation: `validate_index_content_light()` checks for forbidden raw fields
- CLI: `scripts/rig_relay_receipt_index.py` (read-only, JSON or --summary output, --validate mode)
- Schema: `docs/schemas/rig.relay.tool_receipt_index.v1.schema.json` (additionalProperties: false)
- Tests: 37 tests covering builder, summary, error handling, script, content-light validation, validate receipt indexing
- Supported tools: `bash`, `search_replace`, `validate`
