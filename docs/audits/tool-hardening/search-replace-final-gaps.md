# SearchReplace Final Gaps

## Current Hardening Status

SearchReplace is largely complete:

- structured invocation/result/receipt models: present
- `build_receipt()`: present
- schema coverage: present
- content-light validator coverage: present
- receipt index compatibility: present
- automatic receipt emission through the agent loop: present

## Remaining Gaps

1. **End-to-end agent-loop test**
   - Current evidence proves `build_receipt()` and generic receipt emission separately.
   - Missing: a full synthetic agent-loop test that exercises `_execute_tool()` end to end.

2. **Sanitizer edge cases**
   - `refusal_reason` and `warnings` are sanitized, but the current audit still flags the need for a tighter regression around any future contextual text.

3. **Structured failure completeness**
   - Some `ToolError` paths still bypass receipt emission because they are caller/setup errors rather than tool outcomes.
   - That is acceptable, but should remain explicit and tested.

4. **Status completeness**
   - Structured statuses are present, but the audit should keep checking that every intended status emits a receipt and indexes correctly.

## Evidence Standard

SearchReplace should remain the reference pattern for deterministic mutation tools:

- content-light receipts
- schema coverage
- policy validation
- receipt index compatibility
- structured refusals

## Next Step

Use SearchReplace as the baseline template for `write_file`.
