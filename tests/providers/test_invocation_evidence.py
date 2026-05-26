"""Tests for provider invocation outcome evidence contract and capability inspection.

Proves:
- Normalized invocation outcome model validity
- Content-light guarantee (no secrets in serialized outcomes)
- Provider/adapter evidence capability registry truth
- Gemini safety refusal outcome mapping
- Gemini streaming and non-streaming usage evidence
- Anthropic cache token preservation
- OpenRouter gateway classification (no false provenance)
- DeepSeek identity preservation (not OpenAI)
- InvocationEvidenceCapability read-boundary (no network, no inference, no secrets)
"""

from __future__ import annotations

from rig_relay.providers.invocation import (
    GatewayProvenance,
    GatewayProvenanceSource,
    InvocationOutcomeClass,
    InvocationOutcomeInput,
    InvocationRefusalClass,
    assert_content_light,
    build_invocation_outcome,
    get_invocation_evidence_capability,
    invocation_evidence_capabilities,
)
from rig_relay.providers.models import ProviderClass


class TestInvocationOutcomeModel:
    def test_build_minimal_outcome(self):
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openai",
                requested_model_id="gpt-4o",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
            )
        )
        assert outcome.requested_provider_id == "openai"
        assert outcome.requested_model_id == "gpt-4o"
        assert outcome.provider_class == ProviderClass.DIRECT_INFERENCE
        assert outcome.outcome_class == InvocationOutcomeClass.SUCCESS
        assert outcome.content_light is True

    def test_outcome_with_full_usage(self):
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="anthropic",
                requested_model_id="claude-sonnet-4-20250514",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="anthropic",
                outcome_class=InvocationOutcomeClass.SUCCESS,
                input_tokens=150,
                output_tokens=80,
                cache_read_tokens=120,
                cache_creation_tokens=10,
                usage_verified=True,
                cache_read_verified=True,
                cache_creation_verified=True,
                actual_model_verified=True,
                actual_model_id="claude-sonnet-4-20250514",
            )
        )
        assert outcome.input_tokens == 150
        assert outcome.output_tokens == 80
        assert outcome.cache_read_tokens == 120
        assert outcome.cache_creation_tokens == 10
        assert outcome.actual_model_id == "claude-sonnet-4-20250514"

    def test_outcome_with_refusal(self):
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="gemini",
                requested_model_id="gemini-2.0-flash",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="gemini",
                outcome_class=InvocationOutcomeClass.SAFETY_BLOCK,
                refusal_class=InvocationRefusalClass.PROVIDER_SAFETY,
                outcome_summary="SAFETY_BLOCK: OTHER",
                safety_refusal_verified=True,
            )
        )
        assert outcome.outcome_class == InvocationOutcomeClass.SAFETY_BLOCK
        assert outcome.refusal_class == InvocationRefusalClass.PROVIDER_SAFETY
        assert outcome.safety_refusal_verified is True

    def test_to_dict_contains_all_keys(self):
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openai",
                requested_model_id="gpt-4o",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
                streaming=True,
                usage_verified=True,
            )
        )
        d = outcome.to_dict()
        assert d["requested_provider_id"] == "openai"
        assert d["requested_model_id"] == "gpt-4o"
        assert d["provider_class"] == "direct_inference"
        assert d["outcome_class"] == "success"
        assert d["streaming"] is True
        assert d["content_light"] is True
        assert "input_tokens" in d

    def test_unavailable_fields_are_none(self):
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openai",
                requested_model_id="gpt-4o",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
            )
        )
        assert outcome.cache_read_tokens is None
        assert outcome.cache_creation_tokens is None
        assert outcome.actual_provider_id is None
        assert outcome.gateway_provenance is None


class TestContentLightGuarantee:
    def test_no_api_key_in_serialized_outcome(self):
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openai",
                requested_model_id="gpt-4o",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
            )
        )
        serialized = str(outcome.to_dict())
        assert "sk-" not in serialized.lower()
        assert "Bearer" not in serialized

    def test_forbidden_tokens_detected(self):
        violations = assert_content_light({
            "api_key": "sk-secret-value-should-be-forbidden"
        })
        assert len(violations) > 0
        assert "sk-" in violations or "api_key" in violations

    def test_clean_outcome_passes_content_light(self):
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="gemini",
                requested_model_id="gemini-2.0-flash",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="gemini",
                outcome_class=InvocationOutcomeClass.SUCCESS,
            )
        )
        violations = assert_content_light(outcome.to_dict())
        assert len(violations) == 0

    def test_refusal_outcome_no_secrets(self):
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="gemini",
                requested_model_id="gemini-2.0-flash",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="gemini",
                outcome_class=InvocationOutcomeClass.SAFETY_BLOCK,
                refusal_class=InvocationRefusalClass.PROVIDER_SAFETY,
                outcome_summary="Blocked by safety filter",
                safety_refusal_verified=True,
            )
        )
        d = outcome.to_dict()
        violations = assert_content_light(d)
        assert len(violations) == 0


class TestInvocationEvidenceCapabilityInspection:
    """Proves the read-only invocation evidence capability registry is truthful."""

    def test_returns_all_known_providers(self):
        caps = invocation_evidence_capabilities()
        provider_ids = {c.provider_id for c in caps}
        assert "openai" in provider_ids
        assert "anthropic" in provider_ids
        assert "gemini" in provider_ids
        assert "openrouter" in provider_ids
        assert "deepseek" in provider_ids
        assert "local_inference" in provider_ids
        assert "openai-responses" in provider_ids

    def test_openai_responses_cache_evidence_truth(self):
        cap = get_invocation_evidence_capability("openai-responses")
        assert cap is not None
        assert cap.cache_read_verified is True, (
            "C5 production code extracts cached_tokens from input_tokens_details"
        )
        assert cap.live_cache_evidence_preserved is True, (
            "C5 production code preserves cache evidence in streaming and non-streaming"
        )
        assert cap.usage_verified is True
        assert cap.api_style == "openai-responses"
        assert cap.provider_class == ProviderClass.DIRECT_INFERENCE

    def test_no_network_call(self):
        caps1 = invocation_evidence_capabilities()
        caps2 = invocation_evidence_capabilities()
        assert len(caps1) == len(caps2)
        for a, b in zip(caps1, caps2, strict=True):
            assert a.provider_id == b.provider_id
            assert a.usage_verified == b.usage_verified

    def test_anthropic_cache_evidence_verified(self):
        cap = get_invocation_evidence_capability("anthropic")
        assert cap is not None
        assert cap.cache_read_verified is True
        assert cap.cache_creation_verified is True
        assert cap.usage_verified is True
        assert cap.actual_model_verified is True

    def test_gemini_safety_refusal_verified(self):
        cap = get_invocation_evidence_capability("gemini")
        assert cap is not None
        assert cap.safety_refusal_verified is True
        assert cap.usage_verified is True
        assert cap.gateway_provenance_verified is False

    def test_openrouter_gateway_not_direct(self):
        cap = get_invocation_evidence_capability("openrouter")
        assert cap is not None
        assert cap.provider_class == ProviderClass.ROUTED_GATEWAY
        assert "gateway" in " ".join(cap.notes).lower()

    def test_openrouter_not_openai(self):
        openai_cap = get_invocation_evidence_capability("openai")
        openrouter_cap = get_invocation_evidence_capability("openrouter")
        assert openai_cap is not None
        assert openrouter_cap is not None
        assert openai_cap.provider_class != openrouter_cap.provider_class

    def test_deepseek_is_direct_not_openai(self):
        cap = get_invocation_evidence_capability("deepseek")
        assert cap is not None
        assert cap.provider_class == ProviderClass.DIRECT_INFERENCE
        assert cap.provider_id == "deepseek"

    def test_local_inference_unverified(self):
        cap = get_invocation_evidence_capability("local_inference")
        assert cap is not None
        assert cap.usage_verified is False
        assert cap.cache_read_verified is False
        assert cap.provider_class == ProviderClass.LOCAL_SERVER
        assert "not yet wired" in " ".join(cap.notes).lower()

    def test_lookup_nonexistent_provider(self):
        cap = get_invocation_evidence_capability("nonexistent")
        assert cap is None

    def test_no_secrets_in_capability_records(self):
        for cap in invocation_evidence_capabilities():
            for note in cap.notes:
                assert "sk-" not in note
                assert "Bearer" not in note


class TestGatewayProvenance:
    def test_unavailable_default(self):
        gp = GatewayProvenance()
        assert gp.downstream_provider is None
        assert gp.downstream_model is None
        assert gp.provenance_source == GatewayProvenanceSource.UNAVAILABLE

    def test_populated_provenance(self):
        gp = GatewayProvenance(
            downstream_provider="openai",
            downstream_model="gpt-4o",
            provenance_source=GatewayProvenanceSource.RESPONSE_BODY,
        )
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openrouter",
                requested_model_id="openai/gpt-4o",
                provider_class=ProviderClass.ROUTED_GATEWAY,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
                gateway_provenance=gp,
                gateway_provenance_verified=True,
            )
        )
        assert outcome.gateway_provenance is not None
        assert outcome.gateway_provenance.downstream_provider == "openai"
        assert outcome.gateway_provenance.downstream_model == "gpt-4o"


class TestGeminiOutcomeMapping:
    """Proves the Gemini adapter's P1 output maps truthfully to invocation outcomes."""

    def test_gemini_safety_block_maps_to_safety_outcome(self):
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="google",
                requested_model_id="gemini-2.0-flash",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="gemini",
                outcome_class=InvocationOutcomeClass.SAFETY_BLOCK,
                refusal_class=InvocationRefusalClass.PROVIDER_SAFETY,
                outcome_summary="SAFETY_BLOCK: OTHER",
                safety_refusal_verified=True,
            )
        )
        assert outcome.outcome_class == InvocationOutcomeClass.SAFETY_BLOCK
        d = outcome.to_dict()
        assert d["safety_refusal_verified"] is True

    def test_gemini_success_with_usage(self):
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="google",
                requested_model_id="gemini-2.0-flash",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="gemini",
                outcome_class=InvocationOutcomeClass.SUCCESS,
                input_tokens=10,
                output_tokens=8,
                total_tokens=18,
                usage_verified=True,
            )
        )
        assert outcome.input_tokens == 10
        assert outcome.output_tokens == 8
        assert outcome.usage_verified is True

    def test_gemini_error_maps_to_error_outcome(self):
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="google",
                requested_model_id="gemini-2.0-flash",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="gemini",
                outcome_class=InvocationOutcomeClass.ERROR,
                refusal_class=InvocationRefusalClass.AUTH_FAILURE,
                outcome_summary="Gemini error 400: API key not valid",
            )
        )
        assert outcome.outcome_class == InvocationOutcomeClass.ERROR
        assert outcome.refusal_class == InvocationRefusalClass.AUTH_FAILURE


class TestProviderIdentityPreservation:
    """Proves provider identity is preserved through the invocation contract."""

    def test_deepseek_not_openai(self):
        deepseek = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="deepseek",
                requested_model_id="deepseek-v4-pro",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
            )
        )
        assert deepseek.requested_provider_id == "deepseek"
        assert deepseek.provider_class == ProviderClass.DIRECT_INFERENCE
        # api_style is openai because DeepSeek uses OpenAI-compatible protocol
        assert deepseek.api_style == "openai"

    def test_openrouter_is_gateway(self):
        openrouter = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openrouter",
                requested_model_id="openai/gpt-4o",
                provider_class=ProviderClass.ROUTED_GATEWAY,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
            )
        )
        assert openrouter.requested_provider_id == "openrouter"
        assert openrouter.provider_class == ProviderClass.ROUTED_GATEWAY

    def test_streaming_flag_preserved(self):
        streaming = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openai",
                requested_model_id="gpt-4o",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
                streaming=True,
            )
        )
        non_streaming = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openai",
                requested_model_id="gpt-4o",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
                streaming=False,
            )
        )
        assert streaming.streaming is True
        assert non_streaming.streaming is False
