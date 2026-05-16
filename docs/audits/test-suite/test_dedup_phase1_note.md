# Test Deduplication Phase 1 — Doctrine Note

**Date**: 2026-05-16

## Rule

When tests share the same **target module** and **assertion shape**, prefer a **named case table** (`pytest.mark.parametrize` or dataclass table) over separate test functions, unless separate functions encode materially different setup, contract, or regression history.

## Phase 1 Actions

### Exact body duplicate resolved

- `tests/evidence/test_audit_trail.py::test_schema_has_no_forbidden_raw_fields`
- `tests/evidence/test_receipt_envelope.py::test_schema_has_no_forbidden_raw_fields`

**Resolution**: Extracted shared `check_schema_for_forbidden_fields()` helper into `tests/evidence/_helpers.py`. Both tests now call the shared helper. Bodies remain structurally identical by design (same assertion pattern, different schema fixtures).

### Guardrail added

`scripts/rig_relay_test_duplicate_audit.py` supports:
- `--fail-on-exact-duplicates` — exits 1 if any exact body duplicates found
- `--max-exact-duplicate-groups=N` — exits 1 if exact groups exceed N

Current baseline: 1 exact duplicate group (acceptable — shared helper pattern).

### Audit results post-Phase 1

| Metric | Count |
|---|---|
| Scanned | 5,966 |
| Exact body groups | 1 (shared helper, by design) |
| Normalized AST groups | 35 |
| Assert shape groups | 618 |

### Assert shape groups

The 618 assert-shape groups represent tests with similar assertion counts/patterns across different domains. Most are within-file test methods in the same class. These are not true duplicates — they test different behaviors on the same model. Parametrization would require case-by-case analysis.

### Future dedup targets

| Priority | Group | Notes |
|---|---|---|
| P1 | Normalized AST groups (35) | Within-file structural duplicates — best targets for parametrization |
| P2 | Backend adapter duplicates | test_anthropic_adapter ↔ test_vertex_anthropic_adapter structural overlap |
| P3 | ACP tool get_name duplicates | 4 files with identical `test_get_name` — cross-file parametrization deferred |
