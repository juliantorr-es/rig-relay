"""Tests for RiggedLocalRuntime X2.1 — corrected boundary.

Tests: visible response, durable evidence, private-context policy,
tool-call parsing, chat template usage, v1 posture.
"""

from __future__ import annotations

import pytest

from rig_relay.local_inference.runtime._engine import (
    RiggedMlxEngine,
    _build_prompt_using_chat_template,
    _parse_tool_calls,
)
from rig_relay.local_inference.runtime._evidence import (
    _ledger_path,
    build_evidence_receipt,
    emit_execution_receipt,
    emit_lifecycle_event,
    emit_refusal_receipt,
)
from rig_relay.local_inference.runtime._models import (
    CapabilityPosture,
    ContextPrivacyClass,
    ExecutionStatus,
    FinishReason,
    LocalInferenceEvidenceReceipt,
    LocalInferenceResponse,
    RefusalReason,
    TaskKind,
    TaskRefusal,
    ToolCallProposal,
)
from rig_relay.local_inference.runtime._service import (
    RiggedLocalRuntime,
    get_runtime,
    reset_runtime,
)


class TestVisibleResponse:
    """Model output must be visible to the consumer, not hashed and discarded."""

    def test_local_inference_response_has_content_field(self) -> None:
        resp = LocalInferenceResponse(content="Hello, world!")
        assert resp.content == "Hello, world!"

    def test_response_carries_tool_proposals(self) -> None:
        proposals = [ToolCallProposal(call_id="c1", tool_name="test", arguments="{}")]
        resp = LocalInferenceResponse(
            content="text",
            finish_reason=FinishReason.TOOL_CALLS,
            tool_call_proposals=proposals,
        )
        assert len(resp.tool_call_proposals) == 1
        assert resp.finish_reason == FinishReason.TOOL_CALLS

    def test_response_has_evidence_receipt_id(self) -> None:
        resp = LocalInferenceResponse(content="text", evidence_receipt_id="abc")
        assert resp.evidence_receipt_id == "abc"


class TestDurableEvidence:
    """Evidence must be written to durable append-only JSONL ledgers, not discarded."""

    def test_ledger_path_exists(self) -> None:
        path = _ledger_path("runtime_execution_ledger.jsonl")
        assert path.parent.name == "evidence"
        assert path.name.endswith(".jsonl")

    def test_emit_execution_receipt_writes(self) -> None:
        receipt = LocalInferenceEvidenceReceipt(
            receipt_id="test_exec_1",
            task_id_hash="hash123",
            status=ExecutionStatus.EXECUTED,
            prompt_sha256="abc",
            output_sha256="def",
        )
        rid = emit_execution_receipt(receipt)
        assert rid == "test_exec_1"

        path = _ledger_path("runtime_execution_ledger.jsonl")
        assert path.exists()

    def test_emit_refusal_receipt_writes(self) -> None:
        refusal = TaskRefusal(
            reason=RefusalReason.RUNTIME_NOT_CONFIGURED, detail="test"
        )
        rid = emit_refusal_receipt(refusal, "hash456")
        assert rid

    def test_emit_lifecycle_event_writes(self) -> None:
        rid = emit_lifecycle_event(
            "rig.relay.runtime.model_loaded", "model_hash", {"extra": "data"}
        )
        assert rid

    def test_evidence_receipt_is_content_light(self) -> None:
        receipt = LocalInferenceEvidenceReceipt(
            receipt_id="r1", task_id_hash="h1", status=ExecutionStatus.EXECUTED
        )
        assert receipt.content_light
        assert receipt.output_sha256 == ""

    def test_build_evidence_receipt_from_response(self) -> None:
        resp = LocalInferenceResponse(
            content="Hello, world!",
            finish_reason=FinishReason.STOP,
            prompt_tokens=5,
            completion_tokens=3,
            total_tokens=8,
            latency_ms=100,
            model_id_hash="m123",
        )
        receipt = build_evidence_receipt(
            task_id_hash="hash",
            prompt_sha256="psha",
            response=resp,
            model_id_hash="m123",
            latency_ms=100,
            context_privacy_class=ContextPrivacyClass.PRIVATE_LOCAL,
        )
        assert receipt.content_light
        assert receipt.output_sha256
        assert receipt.output_length_chars == 13
        assert receipt.context_privacy_class == ContextPrivacyClass.PRIVATE_LOCAL


class TestPrivateContextPolicy:
    """Local runtime must allow private repo content, not just public-safe."""

    def test_admits_private_local_context(self) -> None:
        rt = RiggedLocalRuntime()
        admission = rt.admit_task(
            TaskKind.CHAT, context_privacy_class=ContextPrivacyClass.PRIVATE_LOCAL
        )
        if rt.is_configured:
            assert admission.admitted
            assert admission.privacy_approved

    def test_admits_public_safe_context(self) -> None:
        rt = RiggedLocalRuntime()
        admission = rt.admit_task(
            TaskKind.CHAT, context_privacy_class=ContextPrivacyClass.PUBLIC_SAFE
        )
        if rt.is_configured:
            assert admission.admitted
            assert admission.privacy_approved

    def test_refuses_secret_bearing_context(self) -> None:
        rt = RiggedLocalRuntime()
        admission = rt.admit_task(
            TaskKind.CHAT, context_privacy_class=ContextPrivacyClass.SECRET_BEARING
        )
        if rt.is_configured:
            assert not admission.admitted
            assert admission.refusal_reason == RefusalReason.CONTEXT_BLOCKED_BY_POLICY

    def test_context_privacy_class_is_recorded(self) -> None:
        rt = RiggedLocalRuntime()
        admission = rt.admit_task(
            TaskKind.CHAT, context_privacy_class=ContextPrivacyClass.PRIVATE_LOCAL
        )
        assert admission.context_privacy_class == ContextPrivacyClass.PRIVATE_LOCAL


class TestToolCallParsing:
    """Tool-call output must be parsed, not hardcoded False."""

    def test_parses_json_tool_block(self) -> None:
        text = '```json\n{"name": "read_file", "arguments": {"path": "x.py"}}\n```'
        proposals = _parse_tool_calls(text)
        assert len(proposals) >= 1
        assert proposals[0].tool_name == "read_file"

    def test_parses_function_call_tag(self) -> None:
        text = '<function_call>\n{"name": "search", "arguments": {"query": "test"}}\n</function_call>'
        proposals = _parse_tool_calls(text)
        assert len(proposals) >= 1
        assert proposals[0].tool_name == "search"

    def test_no_tool_calls_in_plain_text(self) -> None:
        proposals = _parse_tool_calls("Just a normal response.")
        assert len(proposals) == 0

    def test_tool_call_proposal_model(self) -> None:
        proposal = ToolCallProposal(
            call_id="c1", tool_name="test", arguments="{}", rationale="need this"
        )
        assert proposal.tool_name == "test"
        assert proposal.call_id

    def test_multi_tool_calls_parsed(self) -> None:
        text = (
            '```json\n{"name": "tool1", "arguments": {}}\n```\n'
            '```json\n{"name": "tool2", "arguments": {}}\n```'
        )
        proposals = _parse_tool_calls(text)
        assert len(proposals) >= 2


class TestChatTemplate:
    """Prompt formatting must use the tokenizer's chat template."""

    def test_build_prompt_fallback_plain_text(self) -> None:
        messages = [{"role": "user", "content": "Hello"}]
        result = _build_prompt_using_chat_template(messages, object())
        assert "Hello" in result

    def test_build_prompt_with_system_message(self) -> None:
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        result = _build_prompt_using_chat_template(messages, object())
        assert "helpful" in result
        assert "Hi" in result


class TestV1Posture:
    """OMLX-class capabilities must not be labeled post-v1."""

    def test_capability_posture_enum(self) -> None:
        assert CapabilityPosture.SUPPORTED == "supported"
        assert (
            CapabilityPosture.V1_REQUIRED_PENDING
            == "v1_required_pending_implementation"
        )
        assert CapabilityPosture.DEFERRED == "deferred"

    def test_embeddings_labeled_v1_required(self) -> None:
        rt = RiggedLocalRuntime()
        caps = rt.get_capabilities()
        assert caps.embeddings != "unsupported"
        assert caps.embeddings != "deferred"
        assert (
            caps.embeddings == CapabilityPosture.V1_REQUIRED_PENDING
            or caps.embeddings == "supported"
        )

    def test_vision_labeled_v1_required(self) -> None:
        rt = RiggedLocalRuntime()
        caps = rt.get_capabilities()
        assert caps.vision != "unsupported"
        assert (
            caps.vision == CapabilityPosture.V1_REQUIRED_PENDING
            or caps.vision == "supported"
        )

    def test_reranking_labeled_v1_required(self) -> None:
        rt = RiggedLocalRuntime()
        caps = rt.get_capabilities()
        assert caps.reranking != "unsupported"
        assert (
            caps.reranking == CapabilityPosture.V1_REQUIRED_PENDING
            or caps.reranking == "supported"
        )


class TestProjection:
    def test_projection_has_privacy_section(self) -> None:
        rt = RiggedLocalRuntime()
        proj = rt.build_projection()
        assert "privacy" in proj
        assert (
            proj["privacy"]["private_local_context"] == "allowed (local-only retention)"
        )

    def test_projection_has_evidence_ledgers_section(self) -> None:
        rt = RiggedLocalRuntime()
        proj = rt.build_projection()
        assert "evidence_ledgers" in proj
        assert "execution" in proj["evidence_ledgers"]

    def test_projection_capabilities_use_correct_posture(self) -> None:
        rt = RiggedLocalRuntime()
        proj = rt.build_projection()
        caps = proj["capabilities"]
        assert caps["text_generation"] == CapabilityPosture.SUPPORTED
        assert caps["embeddings"] == CapabilityPosture.V1_REQUIRED_PENDING


class TestExecutionFlow:
    @pytest.mark.asyncio
    async def test_refuses_when_no_model_loaded(self) -> None:
        rt = RiggedLocalRuntime()
        result = await rt.execute(
            messages=[{"role": "user", "content": "Hello"}],
            context_privacy_class=ContextPrivacyClass.PRIVATE_LOCAL,
        )
        if rt.is_configured:
            assert not result.executed
            assert result.refusal is not None

    @pytest.mark.asyncio
    async def test_private_context_admitted(self) -> None:
        rt = RiggedLocalRuntime()
        result = await rt.execute(
            messages=[{"role": "user", "content": "Hello"}],
            context_privacy_class=ContextPrivacyClass.PRIVATE_LOCAL,
        )
        if rt.is_configured:
            assert result.admission.privacy_approved or not result.admission.admitted

    @pytest.mark.asyncio
    async def test_secret_bearing_context_refused(self) -> None:
        rt = RiggedLocalRuntime()
        result = await rt.execute(
            messages=[{"role": "user", "content": "Hello"}],
            context_privacy_class=ContextPrivacyClass.SECRET_BEARING,
        )
        if rt.is_configured:
            assert result.status == ExecutionStatus.REFUSED


class TestServiceSingleton:
    def test_get_runtime_returns_same_instance(self) -> None:
        reset_runtime()
        r1 = get_runtime()
        r2 = get_runtime()
        assert r1 is r2

    def test_reset_runtime_creates_new_instance(self) -> None:
        reset_runtime()
        r1 = get_runtime()
        reset_runtime()
        r2 = get_runtime()
        assert r1 is not r2


class TestEngine:
    def test_engine_has_visible_response_methods(self) -> None:
        engine = RiggedMlxEngine()
        assert hasattr(engine, "load_model")
        assert hasattr(engine, "unload_model")
        assert hasattr(engine, "generate")
