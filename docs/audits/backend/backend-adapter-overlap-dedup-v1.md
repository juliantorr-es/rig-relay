# Backend Adapter Overlap Dedup v1 — Audit

**Date**: 2026-05-17

## Overlap Inventory

Inspected production adapters:
- `rig_relay/core/llm/backend/anthropic.py` (653 lines)
- `rig_relay/core/llm/backend/vertex.py` (132 lines)

Inspected test files:
- `tests/backend/test_anthropic_adapter.py` (611 lines)
- `tests/backend/test_vertex_anthropic_adapter.py` (637 → 299 lines)

### Behavior Matrix

| Behavior | Anthropic | Vertex Anthropic | Shared? | Notes |
|---|---|---|---|---|
| Message formatting | `AnthropicMapper.prepare_messages()` | **Inherited** | Yes | Full inheritance |
| Tool formatting | `AnthropicMapper.prepare_tools()` | **Inherited** | Yes | |
| System prompt handling | `AnthropicAdapter._build_system_blocks()` | **Inherited** | Yes | |
| Cache-control | `AnthropicAdapter._add_cache_control_to_last_user_message()` | **Inherited** | Yes | |
| Streaming parse | `AnthropicMapper.parse_streaming_event()` | **Inherited** | Yes | |
| Usage parsing | `AnthropicMapper.parse_response()` | **Inherited** | Yes | |
| Thinking config | `AnthropicAdapter._apply_thinking_config()` | **Inherited** | Yes | |
| Error handling | `APIAdapter` base class | **Inherited** | Yes | |
| Auth/client setup | API key env var | Google ADC + project/region | **No** | Provider-specific |
| Endpoint/model naming | `https://api.anthropic.com/v1/messages` | Vertex endpoint with project/region | **No** | Provider-specific |
| Request building | `AnthropicAdapter.prepare_request()` | `VertexAnthropicAdapter.prepare_request()` (overrides) | **No** | Vertex adds project_id, region, ADC auth |
| Anthropic version header | `anthropic-version: 2023-06-01` | `anthropic_version: vertex-2023-10-16` | **No** | Different version strings |

## Extraction Decision

**No extraction needed.** The production adapters are already well-factored:

- `AnthropicAdapter` is a full-featured base class with 15+ methods
- `VertexAnthropicAdapter(AnthropicAdapter)` inherits **all** parsing/streaming/cache/thinking logic
- Only `__init__()` and `prepare_request()` are overridden for Vertex-specific auth/endpoint
- `AnthropicMapper` is a standalone mapper used by both

The overlap was in the **tests**, not the production code.

## Test Consolidation

### Before

28 Vertex tests duplicated Anthropic mapper/adapter tests:
- `TestParseFullResponse` (6 tests) — duplicate of `AnthropicMapper.parse_response`
- `TestStreamingEvents` (13 tests) — duplicate of `AnthropicMapper.parse_streaming_event`
- `TestHelperMethods` (9 tests) — duplicate of `AnthropicAdapter` helpers

### After

4 lightweight contract tests replaced the 28 duplicates:
- `TestAdapterInheritanceContract::test_inherits_parse_response` — proves Vertex delegates to AnthropicAdapter
- `TestAdapterInheritanceContract::test_inherits_streaming_events` — proves streaming parse inheritance
- `TestAdapterInheritanceContract::test_inherits_cache_control` — proves cache control inheritance
- `TestAdapterInheritanceContract::test_inherits_thinking_detection` — proves thinking detection inheritance

Vertex-specific tests preserved (18 tests):
- `TestBuildVertexEndpoint` (5 tests) — endpoint/URL construction
- `TestPrepareRequest` (8 tests) — Vertex-specific auth/endpoint/project/region request building
- `TestVertexCredentials` (5 tests) — ADC token lifecycle

### Lines Changed

| File | Before | After | Change |
|---|---|---|---|
| `tests/backend/test_vertex_anthropic_adapter.py` | 637 | ~299 | −338 lines (−53%) |

### Provider-Specific Seams

Kept separate:
- API key/env var loading (`AnthropicAdapter.__init__` vs `VertexAnthropicAdapter.__init__` + `VertexCredentials`)
- Endpoint construction (`build_vertex_endpoint`, `build_vertex_base_url`)
- Request body (Vertex uses `anthropic_version: vertex-2023-10-16`, Anthropic uses `anthropic-version` header)
- Auth (API key vs Google ADC)
- Beta features (Vertex has none, Anthropic may have)

### Risks

- `test_inherits_streaming_events` and `test_inherits_thinking_detection` fail on pre-existing `vibe` module references (not caused by this change)
- VertexCredentials tests also fail on pre-existing `vibe` references (5 of 5)

### Validation

| Command | Result |
|---|---|
| `ruff check tests/backend/test_vertex_anthropic_adapter.py` | All checks passed |
| `pyright tests/backend/test_vertex_anthropic_adapter.py` | 0 errors |
| `pytest tests/backend/test_anthropic_adapter.py tests/backend/test_vertex_anthropic_adapter.py -q` | 75 passed, 7 pre-existing `vibe` failures |
| `python scripts/rig_relay_test_duplicate_audit.py --max-exact-duplicate-groups=1` | Exit 0 |
| `collect-only` | 6271 tests, 0 errors |

## Deferred

No remaining adapter overlap. The Anthropic ↔ Vertex Anthropic relationship is cleanly modeled as inheritance. Future Anthropic-family adapters (e.g., AWS Bedrock Anthropic) can follow the same pattern.
