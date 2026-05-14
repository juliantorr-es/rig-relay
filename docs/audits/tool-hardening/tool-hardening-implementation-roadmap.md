# Tool Hardening Implementation Roadmap

## Summary

Recommended order:

1. SearchReplace final closure
2. WriteFile deterministic envelope
3. WriteFile receipt emission and policy validation
4. Shared mutation tool test matrix
5. Read-only inspection tool hardening
6. Orchestration hardening prerequisites
7. Fleet / delegate / aggregate patching readiness

## Stage 1 - SearchReplace Final Closure

Goal:

- remove the last avoidable SearchReplace evidence gaps.

Files likely affected:

- `vibe/core/tools/builtins/search_replace.py`
- `tests/tools/test_tool_receipt_emission.py`
- `tests/evidence/test_tool_receipt_policy.py`
- `tests/evidence/test_receipt_index.py`

Tests needed:

- full agent-loop receipt emission
- schema validation against actual results/receipts
- sanitizer regression
- status coverage

Validation commands:

- `uv run pytest tests/tools/test_tool_receipt_emission.py`
- `uv run pytest tests/evidence/test_tool_receipt_policy.py`

Risks:

- contextual text leaking back into receipts

Exit criteria:

- all SearchReplace paths emit content-light receipts where appropriate

## Stage 2 - WriteFile Deterministic Envelope

Goal:

- make write_file structurally equivalent to search_replace in evidence quality.

Files likely affected:

- `vibe/core/tools/builtins/write_file.py`
- `docs/schemas/*write_file*`
- `tests/tools/test_write_file*`

Tests needed:

- create vs overwrite
- refusal paths
- hash and byte accounting
- atomic write evidence

Validation commands:

- `uv run pytest tests/tools/test_write_file*`

Risks:

- raw content leakage
- write-path ambiguity

Exit criteria:

- structured result with hashes, bytes, and statuses

## Stage 3 - WriteFile Receipt Emission and Policy Validation

Goal:

- add receipt/model/schema/policy coverage for write_file.

Files likely affected:

- `vibe/core/tools/builtins/write_file.py`
- `docs/schemas/rig.relay.write_file_*`
- `tests/evidence/test_tool_receipt_policy.py`
- `tests/evidence/test_receipt_index.py`

Tests needed:

- receipt schema validation
- receipt policy validation
- receipt index compatibility

Validation commands:

- `uv run pytest tests/evidence/test_receipt_index.py`

Risks:

- receipt can accidentally contain raw file text

Exit criteria:

- write_file receipts are content-light and indexable

## Stage 4 - Shared Mutation Tool Test Matrix

Goal:

- share core assertions across mutation tools.

Files likely affected:

- mutation tool tests
- shared helpers

Tests needed:

- path safety
- refusal taxonomy
- byte accounting
- hash accounting
- receipt policy

Risks:

- over-broad abstractions hiding tool-specific semantics

Exit criteria:

- mutation tools share a consistent evidence bar

## Stage 5 - Read-Only Inspection Tool Hardening

Goal:

- constrain content-heavy read surfaces.

Files likely affected:

- `vibe/core/tools/builtins/read_file.py`
- `vibe/core/tools/builtins/grep.py`
- related inspection helpers

Tests needed:

- output caps
- truncation flags
- path refusals
- binary handling

Risks:

- prompt bloat
- privacy leakage

Exit criteria:

- read-only tools are bounded and measurable

## Stage 6 - Orchestration Hardening Prerequisites

Goal:

- ensure orchestration depends on hardened mutation and validation surfaces.

Files likely affected:

- `vibe/core/tools/builtins/coordination.py`
- `vibe/core/tools/builtins/checkpoint.py`
- `vibe/core/tools/builtins/session_lifecycle.py`
- `vibe/core/tools/builtins/validate.py`

Tests needed:

- dirty workspace respect
- receipt lineage
- promotion gate behavior

Risks:

- orchestration becoming a bypass channel

Exit criteria:

- orchestration only routes through hardened surfaces

## Stage 7 - Fleet / Delegate / Aggregate Patching Readiness

Goal:

- enable safe promotion and delegation.

Files likely affected:

- fleet / delegate / promotion code
- lane metadata
- validate consumers

Tests needed:

- lane eligibility
- promotion gate
- evidence indexing

Risks:

- promotion on incomplete evidence

Exit criteria:

- promotion and delegation depend on validate plus receipts
