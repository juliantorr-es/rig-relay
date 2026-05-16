# ContextAssemblyPlan Contract Spine v1

**Date**: 2026-05-18
**Schema**: `rig.context_assembly_plan.v1`

## Purpose

Provide the contract spine for context assembly planning so downstream lanes (discovery, scoring, budget, rendering, compression, provenance) can plug in without inventing ad hoc dictionaries.

## Models

### ContextCandidate

A discovered possible context item. Deterministic `candidate_id` derived from `path|kind|source|relation`. Carries `estimated_tokens`, `priority`, `risk_flags`, `trust_tier`, `cache_tier`. No raw content fields.

### ContextSelection

A candidate selected for inclusion. Links to `candidate_id`, specifies `selected_tokens`, `include_mode` (full/summary/path_only/hash_only), `selection_reason`, and target `section_name`.

### ContextOmission

A candidate omitted from the packet. Links to `candidate_id`, specifies `omission_reason` (budget_exceeded/disabled_by_scope/duplicate/risk_policy/unavailable/unsupported/not_relevant).

### ContextBudgetLedger

Token budget accounting: requested, used, remaining, selection overhead, compression ratio.

### ContextAssemblyPlan

Full plan with `candidates`, `selections`, `omissions`, `budget`, `warnings`, `deterministic_inputs`. Carries `plan_sha256` and `selection_sha256` for content-addressed identity.

## Hash Model

- `plan_sha256`: `sha256:<64 hex>` over all stable fields (excludes `plan_sha256`, `selection_sha256`, `generated_at`)
- `selection_sha256`: `sha256:<64 hex>` over selections only
- Candidate IDs: `sha256:<hex>` truncated to 20 chars, derived from `path|kind|source|relation`
- `plan_id`: first 24 chars of `plan_sha256`

## Cache Tiers

| Tier | Meaning |
|---|---|
| `stable` | Static across many turns (committed files, schemas) |
| `semi_stable` | Changes infrequently (work map, config) |
| `dynamic` | Changes per turn (tool outputs, recent messages) |
| `volatile` | Must be recomputed every time |

## Trust Tiers

| Tier | Meaning |
|---|---|
| `first_party` | Rig Relay internal (doctrine, governance) |
| `repo_content` | User's repository files |
| `tool_output` | Tool result content |
| `external` | External provider/model output |
| `untrusted` | Unknown origin, treat with caution |

## Privacy Model

No raw content fields: `content`, `raw_text`, `stdout`, `stderr`, `env`, `cwd`, `token`, `output`, `file_contents`, `snippet`, `prompt` are excluded from all assembly plan models. Candidates are evidence/provenance descriptors, not content buckets.

## Tests

`tests/context/test_context_assembly_plan.py` — 19 tests covering:
- Candidate/selection/omission/plan rejects extra fields (4 tests)
- Candidate ID determinism and uniqueness (3 tests)
- Negative tokens rejected (2 tests)
- Plan hash determinism and generated_at exclusion (2 tests)
- Selection hash determinism (1 test)
- JSON roundtrip (1 test)
- Plan ID derivation (1 test)
- No raw content fields on candidate/plan (2 tests)
- Canonical hash stability (1 test)
- Budget ledger negative validation (1 test)

## Next Lanes

- **Planner**: populate candidates from repo map, repo index, work map, recent messages
- **Scorer**: compute priority from relation/trust/cache tiers
- **Budget enforcer**: select candidates up to token budget, record omissions
- **Renderer**: produce ContextRenderedSection from selections
- **Provenance**: use plan_sha256 and selection_sha256 for cache invalidation
