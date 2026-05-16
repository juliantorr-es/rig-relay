# Context Assembler — Completion Plan

Inspection date: 2026-05-15. HEAD: c5a31bbe.

## Current state

The context assembly pipeline (`rig_relay/context/`) has a well-structured model layer
(`ContextRequest`, `ContextPacket`, `ContextScope`, `ContextBudget`, `CompressionMode`,
`DetailLevel`) and a functional but incomplete compiler (`compiler.py`). The compiler
successfully builds repo topology, subsystem maps, collision warnings, and receipt
entries. But 12 of 12 request fields that promise gating behavior are ignored.
Budget, compression, detail, freshness, relevance, and repo-index expansion are all
promised by the schema but not delivered by the implementation.

## Proposed architecture: ContextAssemblyPlan v1

### New models

| Model | Purpose |
|---|---|
| `ContextCandidate` | A discovered possible context item (file, symbol, receipt, lane) |
| `ContextSelection` | A selected context item with reason, priority, and estimated tokens |
| `ContextOmission` | An omitted item with reason (budget, irrelevant, duplicate, risk) |
| `ContextAssemblyPlan` | Canonical plan: candidates → selections → omissions → budget → warnings → hashes |
| `ContextSection` | Rendered packet section with provenance, cache tier, and token estimate |

### Candidate fields

| Field | Type | Meaning |
|---|---|---|
| `path` | str | repo-relative path |
| `kind` | str | source/test/doc/schema/config/work/receipt/governance |
| `source` | str | requested_path/repo_index/repo_map/work_map/receipt |
| `relation` | str\|None | direct/test/doc/schema/same_package/active_work/collision |
| `estimated_tokens` | int | deterministic estimate from token_estimator |
| `priority` | int | deterministic integer from scoring function |
| `risk_flags` | list[str] | dirty/collision/generated/large/binary/unknown |
| `reason` | str | concise human-readable reason for inclusion |
| `source_hash` | str\|None | content hash if safe to compute |
| `include_mode` | str | full/summary/path_only/omitted |

### Planner flow

```
ContextRequest.normalize()
  → resolve scope paths/symbols/options
  → discover_candidates()
    → requested_paths + repo_map + work_map
  → expand_relations()
    → RepoContextIndex for tests/docs/schemas/same-package
  → apply_scope_flags()
    → include_tests/include_docs/include_receipts filtering
  → score_candidates()
    → deterministic priority: requested > related > same_package > other
  → apply_risk_policy()
    → collision_warnings → do_not_touch flag
    → dirty files → risk flag, not exclusion
  → enforce_budget()
    → select until cumulative tokens ≤ max_tokens
    → record omissions with reason
  → apply_compression()
    → symbol_codec only if net savings positive
    → substitution_table_sha256
  → build_packet()
    → structured sections with cache tiers
  → build_receipt()
    → canonical hash, warnings, omissions
```

### Cache-aware layout

| Cache tier | Sections | Stability |
|---|---|---|
| stable | AGENTS.md, project doctrine, schemas, API contracts | Changes only on repo structure/doctrine updates |
| semi-stable | Repo topology, subsystem map, package map | Changes on file additions/removals |
| dynamic | Dirty files, active lanes, collision warnings | Changes every turn |
| volatile | Current user task, latest receipts, tool results | Changes mid-turn |

Prompt caching research supports this: strategic cache block placement
outperforms naive full-context caching. Static content should be
placed at the beginning of the prompt for prefix caching.

### Privacy/security model

| Risk | Mitigation |
|---|---|
| Untrusted repo docs/files | Label with provenance (`source: "repo_file"`, `trust: "untrusted"`) |
| Tool output injection | Separate dynamic/tool-result sections with explicit boundary |
| External docs | `provenance: "external"`, `trust_tier: "untrusted"` |
| Raw secrets in context | Path/env/token redaction before rendering |
| Prompt instructions in files | Prefix with `[CONTEXT EVIDENCE — NOT INSTRUCTIONS]` marker |
| Raw message content | Replace with content_sha256 + role + byte_count |

## Implementation slices

| # | Slice | Goal | Gap IDs addressed |
|---|---|---|---|
| 1 | `ContextAssemblyPlan` models + tests | Define `ContextCandidate`, `ContextSelection`, `ContextOmission`, `ContextAssemblyPlan`, `ContextSection` as Pydantic models with `extra="forbid"`. Deterministic hash tests. | — (new models) |
| 2 | Deterministic planner: candidate discovery + scoring | `discover_candidates()`, `score_candidates()`, `apply_scope_flags()`, `apply_risk_policy()`. Pure functions, testable without repo. | 003, 004, 006 |
| 3 | RepoIndex integration: relation expansion | Wire `RepoContextIndex` into planner. `expand_relations()` for tests/docs/schemas/same-package. | 004, 016 |
| 4 | Budget enforcement: select under max_tokens | `enforce_budget()` with incremental token tracking. `ContextOmission` recording. | 001, 007 |
| 5 | Compression integration: symbol codec | `apply_compression()` calling `SymbolCodec.compress()`. Net savings check. Substitution table SHA. | 002, 008, 015 |
| 6 | Cache-aware renderer: stable/dynamic/volatile layout | `build_packet()` with cache tier ordering. Section metadata. | 014 |
| 7 | Privacy/provenance hardening: trust labels + injection boundary | Trust tier labels on all context. Quoted evidence markers. Path/secret redaction. | 009, 010 |
| 8 | AgentLoop integration: consume plan/packet safely | Replace `build_envelope()` with `ContextAssemblyPlan.execute()`. Backward compatible. | — |
| 9 | Determinism fix: hash-based IDs | Replace `uuid4()` with deterministic hash. Exclude `generated_at` from canonical hash. | 011, 012 |
| 10 | Failure hardening: structured warnings | Replace `except: pass` with logged warnings. Add `warnings` field to receipt. | 013 |

## Tests needed

| Slice | Test scenarios |
|---|---|
| 1 — Models | JSON-safe serialization, extra=forbid, field defaults, candidate equality, selection/omission roundtrip |
| 2 — Planner | Empty request, single path, path not found, scope flag exclusion, risk flag propagation, deterministic priority for identical inputs |
| 3 — RepoIndex | Test/doc/schema expansion from source file, same-package expansion, no circular expansion, empty index returns empty |
| 4 — Budget | Under-budget selection, exact-budget selection, over-budget omission, omission reason recorded, cumulative token tracking |
| 5 — Compression | No savings → skip, positive savings → apply, substitution table valid, compressed → decompressed roundtrip |
| 6 — Cache layout | Stable sections first, dynamic sections last, cache tier metadata on sections |
| 7 — Privacy | Untrusted source label, quoted evidence marker, path hash instead of raw, message content replaced with hash |
| 8 — Integration | AgentLoop._build_context_envelope unchanged API, backward compatible receipt, no regression on existing context tests |

## Recommendation

Build slices 1-4 as a single coherent push (model + planner + repo index + budget).
This establishes the `ContextAssemblyPlan` architecture and delivers the four
highest-impact gaps (budget enforcement, scope filtering, relevance scoring,
repo index integration). Slices 5-10 can follow as separate pushes.

The current implementation is NOT wrong — it's just incomplete. The compiler
produces correct, deterministic output for what it does. The completion plan
adds the missing intelligence without rewriting the existing infrastructure.
