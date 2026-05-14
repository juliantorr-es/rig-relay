# Tool Hardening Roadmap Audit

## Scope

Audit of the remaining hardening surface for mutation tools, read-only inspection tools, and orchestration tools. This is design-only; no implementations changed.

## Executive Summary

The repo has already crossed the threshold on the highest-risk mutation surfaces:

- `bash` has a deterministic envelope, receipt model, and receipt policy validation.
- `search_replace` has a structured result model, receipt model, schema coverage, and automatic receipt emission.
- `validate` has a read-only stage 1 profile runner and a content-light receipt path.
- a generic receipt index now exists, which means future tools should target the same emission and indexing contract instead of inventing custom logs.

The remaining risk is not "general shell usage." The remaining risk is the set of mutation and inspection surfaces that still leak raw content, depend on implicit state, or lack consistent receipts.

## Hardening Status Summary

### SearchReplace

Current status:

- structured invocation model: complete
- structured result model: complete
- structured receipt model: complete
- `build_receipt()`: complete
- schema coverage: complete
- actual result schema validation tests: complete
- actual receipt schema validation tests: complete
- generic receipt emission compatibility: complete
- content-light policy validation coverage: complete
- receipt index compatibility: complete
- end-to-end agent-loop receipt emission test: partial
- path safety: complete
- outside-workspace refusal: complete
- binary/content policy: partial
- before/after file hashes: complete
- before/after byte counts: complete
- atomic write behavior: not_applicable
- structured statuses for success/no_match/ambiguous_match/count_mismatch/refused/internal_error: partial
- warning/refusal sanitizer: partial
- legacy `ToolError` bypasses: partial
- tests for every status: partial
- docs/audit coverage: complete

Key remaining gap:

- full agent-loop integration test for receipt emission
- sanitizer path still needs tighter guarantees for warnings/refusal text
- caller errors still bypass receipts by design

### WriteFile

Current status:

- structured invocation model: complete
- structured result model: partial
- structured receipt model: missing
- `build_receipt()`: missing
- schema coverage: missing
- actual result schema validation tests: missing
- actual receipt schema validation tests: missing
- generic receipt emission compatibility: missing
- content-light policy validation coverage: missing
- receipt index compatibility: missing
- path safety: complete
- outside-workspace refusal: complete
- binary/content policy: partial
- before/after file hashes: partial
- before/after byte counts: partial
- created vs overwritten status: complete
- atomic write behavior: partial
- file permission preservation: unknown
- newline/encoding policy: partial
- structured statuses for success/refused/internal_error/etc.: partial
- tests for creating a new file: likely present, but receipt-level evidence not yet complete
- tests for overwriting an existing file: likely present, but receipt-level evidence not yet complete
- tests for refusing unsafe paths: likely present
- tests for binary or invalid content handling: partial
- tests proving receipts omit raw file contents: missing
- docs/audit coverage: missing or incomplete

Key conclusion:

- `write_file` still needs the same evidence standard as `search_replace`.
- it should be the next high-risk mutation closure after `search_replace`.

### Read-Only Inspection Tools

Inventory:

- `read_file`
- `grep`
- likely `webfetch`/`websearch`-style inspection helpers where used interactively

Observed behavior:

- `read_file` has path safety, byte caps, and truncation flags, but no receipt model.
- `grep` has truncation behavior and parsed matches, but no unified receipt model.
- both expose raw content in results by design, which makes receipts and structured hashes important if promoted into `validate`-style surfaces.

Call volume / failure rate from tool-usage analysis:

- `read_file`: 3,970 calls, 14 failures
- `grep`: 1,243 calls, 4 failures

Read-only hardening priority:

1. `read_file`
2. `grep`
3. related search/list helpers

### Orchestration Tools

Inventory:

- `coordination`
- `checkpoint`
- `validate`
- `session_lifecycle`
- `receipt_index`
- lane / worktree / promotion / handoff scripts

Current role:

- these tools coordinate state transitions, claims, leases, promotion, and evidence indexing.
- they should not become ad hoc mutation channels.

Observed posture:

- `coordination` and `checkpoint` are mutation surfaces with some evidence emission.
- `validate` is becoming the read-only gate that orchestration should trust before promotion.
- `receipt_index` is read-only and should remain evidence-only.

Recommended ordering:

1. finish mutation tool hardening first
2. then harden read-only inspection tools
3. then harden orchestration surfaces

## Shared Hardening Matrix

Legend:

- `complete`
- `partial`
- `missing`
- `not_applicable`
- `unknown`

| Surface | structured args | structured result | structured receipt | schema coverage | actual schema tests | receipt emission | receipt policy validation | receipt index compatibility | path safety | mutation safety | atomicity | output caps/truncation | binary/content policy | timeout | refusal taxonomy | legacy exception bypasses | focused tests | CI coverage | docs/audit coverage |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `search_replace` | complete | complete | complete | complete | complete | complete | complete | complete | complete | complete | partial | complete | partial | partial | partial | partial | complete | partial | complete |
| `write_file` | complete | partial | missing | missing | missing | missing | missing | missing | complete | partial | partial | partial | partial | partial | partial | partial | partial | partial | missing |
| `read_file` | complete | partial | missing | missing | missing | missing | missing | missing | complete | not_applicable | not_applicable | complete | partial | partial | partial | partial | partial | partial | missing |
| `grep` | complete | partial | missing | missing | missing | missing | missing | missing | complete | not_applicable | not_applicable | complete | partial | partial | partial | partial | partial | partial | missing |
| `coordination` | complete | partial | missing | missing | missing | partial | missing | missing | partial | partial | partial | partial | unknown | partial | partial | partial | partial | partial | missing |
| `checkpoint` | complete | partial | partial | partial | partial | partial | partial | partial | partial | partial | partial | partial | partial | partial | partial | partial | partial | partial | partial |
| `validate` | complete | complete | complete | complete | complete | complete | complete | complete | complete | not_applicable | not_applicable | complete | partial | partial | complete | complete | complete | complete | complete |

## Roadmap

### Stage 0 - This Audit Only

Goal:

- capture the remaining surface gaps without changing implementations.

Files likely affected:

- docs only

Tests needed:

- JSONL parseability for the gap inventory

Risks:

- overfitting to current hardening state

Exit criteria:

- roadmap accepted as the next hardening plan

### Stage 1 - SearchReplace Final Closure

Goal:

- close the last search_replace gaps.

Files likely affected:

- `vibe/core/tools/builtins/search_replace.py`
- `tests/tools/test_tool_receipt_emission.py`
- `tests/tools/test_hardened_tools.py`
- `tests/evidence/test_tool_receipt_policy.py`
- `tests/evidence/test_receipt_index.py`

Tests needed:

- end-to-end agent-loop receipt emission test
- actual result schema validation tests
- actual receipt schema validation tests
- sanitizer regression tests
- receipt index compatibility test

Validation commands:

- `uv run pytest tests/tools/test_tool_receipt_emission.py`
- `uv run pytest tests/evidence/test_tool_receipt_policy.py`
- `uv run pytest tests/evidence/test_receipt_index.py`

Risks:

- sanitizer regressions
- receipt bypass in structured failure paths

Exit criteria:

- structured failures all emit content-light receipts
- no avoidable raw-content leaks remain

### Stage 2 - WriteFile Deterministic Envelope

Goal:

- bring write_file to the same evidence standard as search_replace.

Files likely affected:

- `vibe/core/tools/builtins/write_file.py`
- `tests/tools/test_write_file*`
- `tests/evidence/test_tool_receipt_policy.py`
- `tests/evidence/test_receipt_index.py`

Tests needed:

- create new file
- overwrite existing file
- refuse unsafe paths
- binary / invalid content handling
- before / after hash verification
- byte-count verification
- content-light result model validation

Validation commands:

- `uv run pytest tests/tools/test_write_file*`
- `uv run pytest tests/evidence/test_receipt_index.py`

Risks:

- write path mutation without adequate evidence
- accidental raw-content leakage

Exit criteria:

- structured results with before/after hashes and byte counts
- refusal and overwrite semantics are explicit

### Stage 3 - WriteFile Receipt Emission and Policy Validation

Goal:

- add receipt emission and policy coverage to write_file.

Files likely affected:

- `vibe/core/tools/builtins/write_file.py`
- `docs/schemas/*write_file*`
- `tests/tools/test_tool_receipt_emission.py`
- `tests/evidence/test_tool_receipt_policy.py`
- `tests/evidence/test_receipt_index.py`

Tests needed:

- receipt builder test
- content-light receipt test
- receipt policy validator test
- receipt index support test

Validation commands:

- `uv run pytest tests/tools/test_tool_receipt_emission.py`
- `uv run pytest tests/evidence/test_tool_receipt_policy.py`
- `uv run pytest tests/evidence/test_receipt_index.py`

Risks:

- raw file content in receipt fields

Exit criteria:

- write_file receipts are content-light and indexed

### Stage 4 - Shared Mutation Tool Test Matrix

Goal:

- reuse common assertions across search_replace and write_file.

Files likely affected:

- shared test helpers
- mutation tool tests

Tests needed:

- path safety
- refusal taxonomy
- receipt policy
- hash and byte counts
- atomicity

Validation commands:

- tool-specific pytest targets

Risks:

- over-generalizing tool-specific semantics

Exit criteria:

- mutation tools share a consistent evidence bar

### Stage 5 - Read-Only Inspection Tool Hardening

Goal:

- give read-only tools structured outputs, truncation flags, and content-light receipts where feasible.

Files likely affected:

- `vibe/core/tools/builtins/read_file.py`
- `vibe/core/tools/builtins/grep.py`
- related inspection tools
- schemas and receipt policy tests

Tests needed:

- output cap enforcement
- binary handling
- hash and byte metadata
- path safety
- receipt omission of raw content

Validation commands:

- focused read-only tool tests

Risks:

- privacy leakage through large outputs
- accidental over-truncation

Exit criteria:

- inspection tools become bounded and measurable

### Stage 6 - Orchestration Hardening Prerequisites

Goal:

- constrain orchestration tools to hardened mutation and validation surfaces.

Files likely affected:

- `rig_relay/coordination/*`
- `vibe/core/tools/builtins/coordination.py`
- session lifecycle tools
- checkpoint helpers
- validate integration

Tests needed:

- dirty workspace respect
- lease / handoff integrity
- evidence emission

Validation commands:

- coordination / checkpoint / validate-focused tests

Risks:

- new ad hoc mutation channels

Exit criteria:

- orchestration depends on hardened mutation and validation primitives

### Stage 7 - Fleet / Delegate / Aggregate Patching Readiness

Goal:

- make fleet and delegate tooling rely on validated lanes and receipts.

Files likely affected:

- lane / worktree / fleet / promotion code
- validate integration
- receipt index and evidence consumers

Tests needed:

- lane readiness
- promotion gate
- evidence lineage

Validation commands:

- promotion / readiness tests

Risks:

- promotion based on incomplete evidence

Exit criteria:

- promotion uses validate and receipts as gate inputs
