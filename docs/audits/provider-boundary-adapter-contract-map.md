# Audit: Provider Boundary and Adapter Contract Map
Status: Draft
Date: 2026-05-13
Branch: main
HEAD: 24c990e011375078a04cb4a5534d114f98c064ed
Scope: Read-only audit
Owner area: provider

## Executive Summary
Rig Relay's provider layer is currently a mix of generic OpenAI-style adapters and specialized backends (Mistral, Anthropic). While structural boundaries exist in `vibe/core/llm/backend/`, provider-specific leakage persists in the core `AgentLoop` and telemetry layers, particularly regarding "Mistral-vibe" legacy naming and specialized usage headers.

## Provider Boundary Inventory
| Component | Status | Assumptions |
| :--- | :--- | :--- |
| **Backend Factory** | Partially Isolated | Uses `Backend` enum to switch; hardcoded to internal adapters. |
| **Mistral Backend** | Highly Specific | Uses `mistralai` SDK directly; expects specific header/error shapes. |
| **Generic OpenAI** | Reusable | Standard OpenAI payload shape; supports custom `api_base`. |
| **Vertex AI** | Specific | Handles Google-specific auth and Anthropic payload translation. |

## Provider-Specific Leakage List
1.  **Vibe Legacy Naming**: Environment variables and config keys often reference "Mistral" or "Vibe" (e.g., `is_active_model_mistral`).
2.  **Telemetry Headers**: Telemetry events often assume Mistral-specific correlation IDs or headers.
3.  **Compaction Defaults**: Default compaction models are hardcoded to Mistral models in some skills/configs.
4.  **Auth Logic**: `TelemetryClient` contains Mistral-specific API key resolution logic.

## Generic Relay vs Provider Adapter Responsibilities
| Responsibility | Generic Relay (Core) | Provider Adapter |
| :--- | :--- | :--- |
| **Context Assembly** | Canonical block building. | N/A |
| **Payload Formatting** | N/A | Convert blocks to provider-native JSON. |
| **Streaming** | Event loop orchestration. | Parse chunked byte streams into `Event` objects. |
| **Usage Tracking** | Aggregate tokens/chars. | Extract usage metrics from raw response. |

## Adapter Contract Proposal
Implement a strict `ProviderAdapterPort`:
- `async def chat(request: PreparedRequest) -> LLMResult`
- `async def stream_chat(request: PreparedRequest) -> AsyncGenerator[LLMEvent, None]`
- `def format_messages(messages: list[LLMMessage]) -> Any`

## Recommended Refactor Backlog
1.  **Mission: Decouple Telemetry Auth**: Move Mistral-specific telemetry key resolution to a provider-agnostic auth manager.
2.  **Mission: Naming Normalization**: Replace `is_active_model_mistral` with `get_active_provider_capabilities()`.
3.  **Mission: Plugin-based Backends**: Allow dynamic registration of new provider backends to remove hardcoded switches in `BackendFactory`.
