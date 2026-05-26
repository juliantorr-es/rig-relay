"""Provider invocation outcome — normalized evidence of what happened during inference.

Content-light: no prompts, no generated text, no tool arguments, no secrets.
Designed for downstream routing, cost, and A2A admission consumption.
Does NOT persist data — produces a typed value only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from rig_relay.providers.models import ProviderClass


class InvocationOutcomeClass(StrEnum):
    """High-level outcome classification for an inference invocation."""

    SUCCESS = "success"
    REFUSAL = "refusal"
    SAFETY_BLOCK = "safety_block"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class InvocationRefusalClass(StrEnum):
    """Specific refusal or safety-block reason class."""

    PROVIDER_SAFETY = "provider_safety"
    PROVIDER_POLICY = "provider_policy"
    CAPABILITY_UNSUPPORTED = "capability_unsupported"
    RATE_LIMITED = "rate_limited"
    AUTH_FAILURE = "auth_failure"
    MALFORMED_REQUEST = "malformed_request"
    PROVIDER_ERROR = "provider_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


class GatewayProvenanceSource(StrEnum):
    """How downstream provider/model identity was determined."""

    RESPONSE_BODY = "response_body"
    RESPONSE_HEADER = "response_header"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


@dataclass
class GatewayProvenance:
    """Downstream provider/model identity through a routed gateway."""

    downstream_provider: str | None = None
    downstream_model: str | None = None
    provenance_source: GatewayProvenanceSource = GatewayProvenanceSource.UNAVAILABLE


@dataclass
class ProviderInvocationOutcome:
    """Normalized evidence for a single provider inference invocation.

    Content-light by construction: stores hashes, counts, and classifications
    only. Never stores prompts, generated text, raw responses, or credentials.

    Fields marked as None are unavailable or not yet verified for this provider.
    """

    schema_version: str = "rig.relay.invocation_outcome.v1"

    # Identity — requested
    requested_provider_id: str = ""
    requested_model_id: str = ""

    # Identity — actual (where observable from provider response)
    actual_provider_id: str | None = None
    actual_model_id: str | None = None

    # Classification
    provider_class: ProviderClass = ProviderClass.DIRECT_INFERENCE
    api_style: str = "openai"

    # Outcome
    outcome_class: InvocationOutcomeClass = InvocationOutcomeClass.UNKNOWN
    refusal_class: InvocationRefusalClass | None = None
    outcome_summary: str = ""

    # Execution mode
    streaming: bool = False
    latency_ms: float | None = None

    # Usage evidence (only fields returned by the actual provider response)
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None

    # Gateway provenance (unavailable unless extracted from response)
    gateway_provenance: GatewayProvenance | None = None

    # Provider-side response tracking (where safe)
    provider_response_id: str | None = None

    # Safe content hashes (never raw text)
    output_content_sha256: str | None = None

    # Content-light guarantee
    content_light: bool = True

    # Availability flags — explicit: None = not verified, True/False = known
    usage_verified: bool | None = None
    cache_read_verified: bool | None = None
    cache_creation_verified: bool | None = None
    safety_refusal_verified: bool | None = None
    actual_provider_verified: bool | None = None
    actual_model_verified: bool | None = None
    streaming_terminal_usage_verified: bool | None = None
    gateway_provenance_verified: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "requested_provider_id": self.requested_provider_id,
            "requested_model_id": self.requested_model_id,
            "actual_provider_id": self.actual_provider_id,
            "actual_model_id": self.actual_model_id,
            "provider_class": self.provider_class.value,
            "api_style": self.api_style,
            "outcome_class": self.outcome_class.value,
            "refusal_class": self.refusal_class.value if self.refusal_class else None,
            "outcome_summary": self.outcome_summary,
            "streaming": self.streaming,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "gateway_provenance": (
                {
                    "downstream_provider": self.gateway_provenance.downstream_provider,
                    "downstream_model": self.gateway_provenance.downstream_model,
                    "provenance_source": self.gateway_provenance.provenance_source.value,
                }
                if self.gateway_provenance
                else None
            ),
            "provider_response_id": self.provider_response_id,
            "output_content_sha256": self.output_content_sha256,
            "content_light": self.content_light,
            "usage_verified": self.usage_verified,
            "cache_read_verified": self.cache_read_verified,
            "cache_creation_verified": self.cache_creation_verified,
            "safety_refusal_verified": self.safety_refusal_verified,
            "actual_provider_verified": self.actual_provider_verified,
            "actual_model_verified": self.actual_model_verified,
            "streaming_terminal_usage_verified": self.streaming_terminal_usage_verified,
            "gateway_provenance_verified": self.gateway_provenance_verified,
        }
        return result


_FORBIDDEN_TOKENS: set[str] = {
    "sk-",
    "sk-ant-",
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "Bearer ",
    "x-goog-api-key",
    "api_key",
    "private_key",
}


def assert_content_light(value: dict[str, Any]) -> list[str]:
    """Scan a serialized outcome for forbidden token patterns. Returns violations."""
    serialized = str(value).lower()
    violations: list[str] = []
    for token in _FORBIDDEN_TOKENS:
        if token.lower() in serialized:
            violations.append(token)
    return violations


def build_invocation_outcome(
    *,
    requested_provider_id: str,
    requested_model_id: str,
    provider_class: ProviderClass,
    api_style: str,
    outcome_class: InvocationOutcomeClass,
    streaming: bool = False,
    refusal_class: InvocationRefusalClass | None = None,
    outcome_summary: str = "",
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    cache_creation_tokens: int | None = None,
    actual_provider_id: str | None = None,
    actual_model_id: str | None = None,
    provider_response_id: str | None = None,
    gateway_provenance: GatewayProvenance | None = None,
    usage_verified: bool | None = None,
    cache_read_verified: bool | None = None,
    cache_creation_verified: bool | None = None,
    safety_refusal_verified: bool | None = None,
    actual_provider_verified: bool | None = None,
    actual_model_verified: bool | None = None,
    streaming_terminal_usage_verified: bool | None = None,
    gateway_provenance_verified: bool | None = None,
) -> ProviderInvocationOutcome:
    """Construct a ProviderInvocationOutcome with content-light enforcement."""
    return ProviderInvocationOutcome(
        requested_provider_id=requested_provider_id,
        requested_model_id=requested_model_id,
        actual_provider_id=actual_provider_id,
        actual_model_id=actual_model_id,
        provider_class=provider_class,
        api_style=api_style,
        outcome_class=outcome_class,
        refusal_class=refusal_class,
        outcome_summary=outcome_summary,
        streaming=streaming,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        provider_response_id=provider_response_id,
        gateway_provenance=gateway_provenance,
        usage_verified=usage_verified,
        cache_read_verified=cache_read_verified,
        cache_creation_verified=cache_creation_verified,
        safety_refusal_verified=safety_refusal_verified,
        actual_provider_verified=actual_provider_verified,
        actual_model_verified=actual_model_verified,
        streaming_terminal_usage_verified=streaming_terminal_usage_verified,
        gateway_provenance_verified=gateway_provenance_verified,
    )


@dataclass
class InvocationEvidenceCapability:
    """Read-only capability summary for invocation evidence per provider.

    Describes what evidence fields a provider adapter is verified to produce.
    Distinguishes contract representability from live-emission proof.
    No network calls, no secrets, no inference, no persistence.
    """

    provider_id: str
    provider_class: ProviderClass
    api_style: str
    usage_verified: bool
    usage_streaming_final_verified: bool
    cache_read_verified: bool
    cache_creation_verified: bool
    safety_refusal_verified: bool
    actual_provider_verified: bool
    actual_model_verified: bool
    gateway_provenance_verified: bool
    response_id_verified: bool
    # P1.2 live emission flags
    live_non_streaming_outcome: bool = False
    live_streaming_outcome: bool = False
    live_provider_identity_preserved: bool = False
    live_cache_evidence_preserved: bool = False
    live_safety_classification: bool = False
    notes: list[str] = field(default_factory=list)


# Honest adapter-by-adapter evidence capability registry.
# Only marks True what is proven by boundary tests.
_ADAPTER_INVOCATION_EVIDENCE: dict[str, dict[str, Any]] = {
    "openai": {
        "usage_verified": True,
        "usage_streaming_final_verified": True,
        "cache_read_verified": False,
        "cache_creation_verified": False,
        "safety_refusal_verified": False,
        "actual_provider_verified": False,
        "actual_model_verified": True,
        "gateway_provenance_verified": False,
        "response_id_verified": True,
        "live_non_streaming_outcome": True,
        "live_streaming_outcome": True,
        "live_provider_identity_preserved": True,
        "live_cache_evidence_preserved": False,
        "live_safety_classification": False,
        "notes": [
            "live non-streaming + streaming outcome emission via OpenAIAdapter",
            "provider identity preserved from config (OpenAI/DeepSeek distinguished)",
            "model ID and response ID extracted where available",
            "cache tokens not parsed from usage response",
        ],
    },
    "anthropic": {
        "usage_verified": True,
        "usage_streaming_final_verified": True,
        "cache_read_verified": True,
        "cache_creation_verified": True,
        "safety_refusal_verified": False,
        "actual_provider_verified": False,
        "actual_model_verified": True,
        "gateway_provenance_verified": False,
        "response_id_verified": True,
        "live_non_streaming_outcome": True,
        "live_streaming_outcome": True,
        "live_provider_identity_preserved": True,
        "live_cache_evidence_preserved": True,
        "live_safety_classification": False,
        "notes": [
            "cache_read_input_tokens and cache_creation_input_tokens preserved as named fields",
            "live outcomes emitted for both non-streaming and streaming (terminal message_delta)",
            "model ID available from response",
        ],
    },
    "gemini": {
        "usage_verified": True,
        "usage_streaming_final_verified": True,
        "cache_read_verified": False,
        "cache_creation_verified": False,
        "safety_refusal_verified": True,
        "actual_provider_verified": False,
        "actual_model_verified": False,
        "gateway_provenance_verified": False,
        "response_id_verified": False,
        "live_non_streaming_outcome": True,
        "live_streaming_outcome": True,
        "live_provider_identity_preserved": True,
        "live_cache_evidence_preserved": False,
        "live_safety_classification": True,
        "notes": [
            "safety refusal detected in-band via finishReason/promptFeedback",
            "live outcomes with typed safety classification",
            "streaming terminal usage emitted when usageMetadata present in SSE event",
        ],
    },
    "openrouter": {
        "usage_verified": True,
        "usage_streaming_final_verified": True,
        "cache_read_verified": False,
        "cache_creation_verified": False,
        "safety_refusal_verified": False,
        "actual_provider_verified": False,
        "actual_model_verified": False,
        "gateway_provenance_verified": False,
        "response_id_verified": True,
        "live_non_streaming_outcome": True,
        "live_streaming_outcome": True,
        "live_provider_identity_preserved": True,
        "live_cache_evidence_preserved": False,
        "live_safety_classification": False,
        "notes": [
            "routed gateway — provider class preserved as ROUTED_GATEWAY",
            "provenance extraction from response headers (x-provider) for non-streaming",
            "streaming provenance unavailable (SSE headers not accessible)",
        ],
    },
    "deepseek": {
        "usage_verified": True,
        "usage_streaming_final_verified": True,
        "cache_read_verified": False,
        "cache_creation_verified": False,
        "safety_refusal_verified": False,
        "actual_provider_verified": False,
        "actual_model_verified": False,
        "gateway_provenance_verified": False,
        "response_id_verified": True,
        "live_non_streaming_outcome": True,
        "live_streaming_outcome": True,
        "live_provider_identity_preserved": True,
        "live_cache_evidence_preserved": False,
        "live_safety_classification": False,
        "notes": ["DeepSeek identity preserved despite OpenAI-compatible transport"],
    },
    "reasoning": {
        "usage_verified": True,
        "usage_streaming_final_verified": True,
        "cache_read_verified": False,
        "cache_creation_verified": False,
        "safety_refusal_verified": False,
        "actual_provider_verified": False,
        "actual_model_verified": True,
        "gateway_provenance_verified": False,
        "response_id_verified": True,
        "live_non_streaming_outcome": True,
        "live_streaming_outcome": True,
        "live_provider_identity_preserved": True,
        "live_cache_evidence_preserved": False,
        "live_safety_classification": False,
        "notes": [
            "ReasoningAdapter wired for live outcomes",
            "provider identity preserved from config",
        ],
    },
    "mistral": {
        "usage_verified": True,
        "usage_streaming_final_verified": True,
        "cache_read_verified": False,
        "cache_creation_verified": False,
        "safety_refusal_verified": False,
        "actual_provider_verified": False,
        "actual_model_verified": False,
        "gateway_provenance_verified": False,
        "response_id_verified": False,
        "live_non_streaming_outcome": True,
        "live_streaming_outcome": True,
        "live_provider_identity_preserved": True,
        "live_cache_evidence_preserved": False,
        "live_safety_classification": False,
        "notes": [
            "MistralBackend wired for live outcomes via SDK",
            "streaming outcomes emitted when usage data present",
        ],
    },
    "vertex-anthropic": {
        "usage_verified": True,
        "usage_streaming_final_verified": True,
        "cache_read_verified": True,
        "cache_creation_verified": True,
        "safety_refusal_verified": False,
        "actual_provider_verified": False,
        "actual_model_verified": True,
        "gateway_provenance_verified": False,
        "response_id_verified": True,
        "live_non_streaming_outcome": True,
        "live_streaming_outcome": True,
        "live_provider_identity_preserved": True,
        "live_cache_evidence_preserved": True,
        "live_safety_classification": False,
        "notes": [
            "VertexAnthropicAdapter inherits Anthropic live outcomes",
            "provider identity preserved via _last_provider_name",
        ],
    },
    "openai-responses": {
        "usage_verified": True,
        "usage_streaming_final_verified": True,
        "cache_read_verified": False,
        "cache_creation_verified": False,
        "safety_refusal_verified": False,
        "actual_provider_verified": False,
        "actual_model_verified": True,
        "gateway_provenance_verified": False,
        "response_id_verified": True,
        "live_non_streaming_outcome": True,
        "live_streaming_outcome": True,
        "live_provider_identity_preserved": True,
        "live_cache_evidence_preserved": False,
        "live_safety_classification": False,
        "notes": [
            "OpenAIResponsesAdapter wired, api_style='openai-responses'",
            "distinct from chat completions adapter",
        ],
    },
    "local_inference": {
        "usage_verified": False,
        "usage_streaming_final_verified": False,
        "cache_read_verified": False,
        "cache_creation_verified": False,
        "safety_refusal_verified": False,
        "actual_provider_verified": False,
        "actual_model_verified": False,
        "gateway_provenance_verified": False,
        "response_id_verified": False,
        "live_non_streaming_outcome": False,
        "live_streaming_outcome": False,
        "live_provider_identity_preserved": False,
        "live_cache_evidence_preserved": False,
        "live_safety_classification": False,
        "notes": ["local inference — not yet wired for live outcome emission"],
    },
}


_INVOCATION_CLASS_MAP: dict[str, ProviderClass] = {
    "openai": ProviderClass.DIRECT_INFERENCE,
    "openai-responses": ProviderClass.DIRECT_INFERENCE,
    "anthropic": ProviderClass.DIRECT_INFERENCE,
    "gemini": ProviderClass.DIRECT_INFERENCE,
    "openrouter": ProviderClass.ROUTED_GATEWAY,
    "deepseek": ProviderClass.DIRECT_INFERENCE,
    "reasoning": ProviderClass.DIRECT_INFERENCE,
    "mistral": ProviderClass.DIRECT_INFERENCE,
    "vertex-anthropic": ProviderClass.DIRECT_INFERENCE,
    "local_inference": ProviderClass.LOCAL_SERVER,
}


def invocation_evidence_capabilities() -> list[InvocationEvidenceCapability]:
    """Return invocation evidence capability summaries for all known providers.

    Read-only. No network calls. No secrets. No inference. No persistence.
    """
    result: list[InvocationEvidenceCapability] = []
    for provider_id, caps in _ADAPTER_INVOCATION_EVIDENCE.items():
        pv_class = _INVOCATION_CLASS_MAP.get(
            provider_id, ProviderClass.DIRECT_INFERENCE
        )
        api_style = _api_style_for_evidence(provider_id)
        notes_raw = caps.get("notes", [])
        notes: list[str] = notes_raw if isinstance(notes_raw, list) else []
        result.append(
            InvocationEvidenceCapability(
                provider_id=provider_id,
                provider_class=pv_class,
                api_style=api_style,
                usage_verified=bool(caps.get("usage_verified", False)),
                usage_streaming_final_verified=bool(
                    caps.get("usage_streaming_final_verified", False)
                ),
                cache_read_verified=bool(caps.get("cache_read_verified", False)),
                cache_creation_verified=bool(
                    caps.get("cache_creation_verified", False)
                ),
                safety_refusal_verified=bool(
                    caps.get("safety_refusal_verified", False)
                ),
                actual_provider_verified=bool(
                    caps.get("actual_provider_verified", False)
                ),
                actual_model_verified=bool(caps.get("actual_model_verified", False)),
                gateway_provenance_verified=bool(
                    caps.get("gateway_provenance_verified", False)
                ),
                response_id_verified=bool(caps.get("response_id_verified", False)),
                live_non_streaming_outcome=bool(
                    caps.get("live_non_streaming_outcome", False)
                ),
                live_streaming_outcome=bool(caps.get("live_streaming_outcome", False)),
                live_provider_identity_preserved=bool(
                    caps.get("live_provider_identity_preserved", False)
                ),
                live_cache_evidence_preserved=bool(
                    caps.get("live_cache_evidence_preserved", False)
                ),
                live_safety_classification=bool(
                    caps.get("live_safety_classification", False)
                ),
                notes=notes,
            )
        )
    return result


def get_invocation_evidence_capability(
    provider_id: str,
) -> InvocationEvidenceCapability | None:
    for cap in invocation_evidence_capabilities():
        if cap.provider_id == provider_id:
            return cap
    return None


def _api_style_for_evidence(provider_id: str) -> str:
    return {
        "openai": "openai",
        "anthropic": "anthropic",
        "gemini": "gemini",
        "openrouter": "openai",
        "deepseek": "openai",
        "local_inference": "openai",
    }.get(provider_id, "openai")
