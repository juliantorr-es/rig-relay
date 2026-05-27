# Third-Party Notices

This project contains portions of code derived from third-party projects.

## Mistral Vibe

Rig Relay includes code derived from [mistralai/mistral-vibe](https://github.com/mistralai/mistral-vibe).

- **Upstream License**: Apache License, Version 2.0
- **Upstream Copyright**: Copyright 2025 Mistral AI

### Notices

1. Applicable upstream copyright, attribution, and license notices from the source project are preserved in the `LICENSE` file and within individual source files where present.
2. Source files may have been modified for the Rig Relay project. Modified files carry prominent notices stating that they have been changed, as required by Section 4(b) of the Apache License, Version 2.0.
3. Rig Relay is an independent derivative project and is not affiliated with, endorsed by, or sponsored by Mistral AI.

## oMLX (jundot/omlx)

Rig Relay's local inference runtime (`rig_relay/local_inference/runtime/`) incorporates architectural patterns informed by [jundot/omlx](https://github.com/jundot/omlx), an Apache-2.0 licensed local LLM inference server for macOS/Apple Silicon.

- **Upstream License**: Apache License, Version 2.0
- **Upstream Copyright**: Copyright 2025 oMLX contributors

**X2.4 Status (May 2026)**:
- KV-cache reuse now uses `mlx-lm`'s built-in `LRUPromptCache` with longest-prefix trie matching — an independently implemented mechanism. No OMLX code adapted for cache functionality.
- All adapted patterns listed below remain attribution-only (no OMLX source code copied).
- The OMLX comparative architecture audit for this lane is at `docs/json/audits/runtime_substrate/lane_x2.4_omlx_comparative_audit.v1.json`.

### Adapted Patterns

The following patterns were studied from OMLX source and adapted into original Rig Relay code (not ported). OMLX source was inspected for architecture decisions; no OMLX source code was directly copied.

| Pattern | OMLX Source | Rig Relay Adaptation |
|---------|-------------|---------------------|
| Model classification taxonomy | `model_discovery.py` (architecture-based VLM/embedding/reranker detection) | `_inventory.py`: `_classify_model_type()` architecture detection and `_models.py`: `ModelTypeClass` enum |
| Cache evidence metrics schema | `server_metrics.py` CacheRateTracker (rolling windows: 60s, 5m, 15m) | `_models.py`: `CacheEvidenceMetrics` with recent/medium/aggregate windows |
| Capability probe structure | `server.py` endpoint layout (/health, /v1/models, /v1/chat/completions, /v1/embeddings, /v1/rerank, /v1/messages, /api/status) | `_models.py`: `EnrichedRuntimeCapabilities` probe target fields |
| MLX thread safety pattern | `engine_core.py`: `_init_mlx_thread()` (thread-local Metal stream initialization) | `_engine.py`: `_ensure_mlx_initialized()` stream safety |
| LRU prompt cache with trie | `cache/prefix_cache.py` (block-hash-based prefix sharing with custom caching) | `_cache_authority.py`: `RiggedCacheAuthority` using mlx-lm's built-in `LRUPromptCache` with longest-prefix trie matching. Independently implemented — no OMLX code adapted. |

### Dependencies

Rig Relay adds the following dependencies (all permissively licensed — MIT, Apache 2.0, BSD) for MLX-backed local inference:

- `mlx` (MIT) — Apple MLX GPU framework
- `mlx-lm` (MIT) — Language model library
- `transformers` (Apache 2.0) — HuggingFace Transformers
- `tokenizers` (Apache 2.0) — Fast tokenizer
- `huggingface-hub` (Apache 2.0) — HuggingFace Hub API
- `numpy` (BSD) — Array operations
- `protobuf` (BSD-like) — Model format parsing
- `sentencepiece` (Apache 2.0) — Tokenizer

### Licensing Notes

1. OMLX's Apache 2.0 license covers its application code only. Downloaded model weights carry their own licenses (LLaMA Community, Mistral Research, DeepSeek, etc.). Rig Relay never implies OMLX's Apache license extends to model weights.
2. No OMLX source code was directly copied into Rig Relay. Adapted patterns are documented with attribution in source files.
3. Rig Relay's local inference runtime is original code — not a derivative work of OMLX.
4. Rig Relay is not affiliated with, endorsed by, or sponsored by the oMLX project or its contributors.

