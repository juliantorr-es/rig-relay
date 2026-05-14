# Context Optimization Codecs

Policy and architecture for Rig Relay context compression codecs.

## Codec Philosophy

Context optimization in Rig uses a layered codec pipeline. Each pass is
independently configured, receipted, and evaled. Lossy codecs are gated
behind eval requirements and never applied to authoritative context by
default.

### Definitions

- **Authoritative context**: AGENTS.md rules, exact user instructions,
  code patches, test failures, security policy, schemas, command output
  needed for correctness.
- **Navigational context**: file paths, symbol names, subsystem labels,
  package/module names, repeated class/function names.
- **Semantic context**: summaries, explanations, subsystem descriptions,
  plan prose.

## Codec Registry

| Codec | Type | Reversible | Lossy | Status |
|---|---|---|---|---|
| `rig.symbol_table.v1` | Symbol replacement | Yes | No | **Implemented** |
| `rig.semantic_alias.v1` | Alias/glossary | Semi | Yes | Future |
| `rig.semantic_dense.v0` | Semantic summary | No | Yes | Future |
| `rig.semantic_zh_dense.v0` | Dense Chinese summary | No | Yes | Future |

## Codec Pipeline

```
Raw context
  → context slicer
  → symbol table pass (rig.symbol_table.v1)
  → semantic alias pass (future)
  → dense-language experiment (future, eval-gated)
  → token estimator
  → model-specific optimizer
  → reconstruction receipt
  → AgentLoop prompt
```

## Implemented: `rig.symbol_table.v1`

Deterministic reversible symbol replacement. Replaces repeated long terms
(file paths, class names, module names) with short `§`-prefixed symbols.

### Policy

- Compresses navigational context by default.
- Does NOT compress authoritative context (code fences, AGENTS.md, etc.).
- Always reversible; emits receipt with input/output/symbol-table SHA256.
- Collision detection: if text already contains `§` symbols, they are
  escaped reversibly with `\u00A7` encoding.
- Minimum candidate length: 16 characters.
- Minimum occurrences: 3.
- Maximum symbols: 256.

### Current integration slice

- `ContextCompiler.build_envelope()` compresses only navigational packs by
  default.
- `ContextEnvelopeReceipt` carries the symbol manifest plus the codec
  receipt so downstream bridges can expand aliases before tool execution.
- Tool execution must expand aliases before validation or tool dispatch.
- AGENTS.md, user prompts, transcript bodies, test contents, and exact
  command output stay uncompressed in the prompt envelope.

### Alias modes

- `§` aliases are the human-readable debug mode.
- PUA aliases are the dense runtime mode and are only valid inside compiled
  runtime envelopes.
- PUA aliases must never be written into canonical docs or passed to tools.
- Compression is safe only when the manifest proves exact reconstruction.
- If expansion cannot reconstruct the original section byte-for-byte, the
  section must be left uncompressed.

### Non-goals

- Semantic aliasing remains out of scope.
- Dense semantic summaries remain out of scope.
- Chinese or other cross-language semantic compression remains out of scope
  for authoritative context.

### Receipt fields

```json
{
  "codec_name": "rig.symbol_table.v1",
  "codec_version": "1",
  "input_sha256": "sha256:...",
  "output_sha256": "sha256:...",
  "symbol_table_sha256": "sha256:...",
  "estimated_tokens_before": 18420,
  "estimated_tokens_after": 13980,
  "replacement_count": 47,
  "reversible": true,
  "lossy": false,
  "refused_reason": null
}
```

### API

```
compress_symbols(text, config?) -> SymbolCodecResult
decompress_symbols(compressed_text, symbol_table) -> str
dry_run(text, config?) -> SymbolCodecResult
find_symbol_candidates(text, config?) -> tuple[SymbolEntry, ...]
```

## Future: `rig.semantic_alias.v1`

Semi-reversible controlled alias/glossary codec. Uses a project-specific
glossary to replace known terms with short aliases. Reversible only if
the glossary is preserved alongside the compressed text.

### Constraints

- Must be eval-gated.
- Must emit `lossy=true`.
- Must not be applied to authoritative context by default.

## Future: `rig.semantic_dense.v0` / `rig.semantic_zh_dense.v0`

Lossy semantic summary codecs. The `_zh_dense` variant uses Chinese or
other dense-language notation for semantic summaries.

### Hard rules

1. **Forbidden** for: exact instructions, code patches, security policy,
   schemas, legal text, AGENTS.md, test failure details.
2. **Allowed only** for: navigational summaries, non-authoritative
   background, subsystem descriptions.
3. Must include model-specific token/success eval before default use.
4. Must preserve an English reconstruction/summary sidecar.
5. Must emit `lossy=true`, `requires_eval=true`.
6. Automatic rollback if eval shows regression.

### Risk

Semantic drift is the primary risk. Deterministic replacement is safe
because the mapping is one-to-one and auditable. Dense-language summary
replaces meaning, not just tokens, and introduces model-dependent bias.
Empirical results vary by model — some tokenizer studies show that
non-English tokenization can introduce representational issues depending
on the model/tokenizer setup.

## Token Estimation

- **Default**: Heuristic estimator (~2–4 chars/token depending on code ratio).
- **Future**: Model-specific estimators via tiktoken adapter.
- All estimates are advisory. The receipt records `estimator_kind`
  (currently `"heuristic"`).

## Eval Gate

No lossy codec may be enabled by default without passing an A/B eval
that demonstrates:
- No regression in task success rate
- Measurable token cost reduction
- Model-specific behavior is understood
- Rollback mechanism is automated
