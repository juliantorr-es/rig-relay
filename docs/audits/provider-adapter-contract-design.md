# Audit: Provider Adapter Contract Design
Status: Draft
Date: 2026-05-13
Branch: main
HEAD: e389b446706173ebc5950931994ba4cdb6a7d9f4
Scope: Read-only design audit
Owner area: provider

## Executive Summary
Rig Relay must maintain provider neutrality to ensure evidence reliability. Currently, Mistral-specific assumptions leak into the core. This design proposes a strict `ProviderAdapterPort` that handles the mapping between generic Relay intents and provider-specific stochastic behaviors.

## Current Boundary Map
- **Relay Core**: Handles turn logic, tool orchestration, context assembly, and evidence writing.
- **Backend Implementations**: (Mistral, OpenAI, Anthropic, Vertex) - Currently handle both HTTP transport and payload mapping.

## Leakage Inventory
- **Usage Metrics**: Mistral-specific headers are sometimes parsed outside the adapter.
- **Error Types**: Core loop sometimes checks for `MistralError`.
- **Cached Tokens**: The concept of "cached tokens" is currently modeled closely to Mistral's implementation.

## Proposed Adapter Interface
```python
class ProviderAdapter(Protocol):
    def to_provider_request(self, messages: list[LLMMessage], tools: list[Tool]) -> dict:
        """Map generic messages to provider JSON."""

    def from_provider_response(self, raw_json: dict) -> LLMChunk:
        """Map provider JSON to generic chunk with normalized usage."""

    def extract_receipt_metadata(self, response_headers: dict) -> dict:
        """Extract evidence-grade metadata (correlation IDs, server timing)."""
```

## Normalized Event Model
- All backends must return a `LLMUsage` object with:
    - `prompt_tokens`
    - `completion_tokens`
    - `total_tokens`
    - `cache_creation_input_tokens` (optional)
    - `cache_read_input_tokens` (optional)

## Testing Strategy
- **FakeProvider**: A test double that implements the adapter and returns deterministic, reproducible responses for evidence smoke tests.
- **Adapter Unit Tests**: Each adapter must have a suite that transforms a canonical `LLMMessage` list into its provider's expected JSON and back.

## Future Implementation Slices
1.  **Slice 1**: Abstract `Usage` extraction into the adapter.
2.  **Slice 2**: Move HTTP headers extraction (for receipt links) into the adapter.
3.  **Slice 3**: Formalize the `ProviderAdapter` Protocol and migrate Mistral as the first "clean" adapter.
