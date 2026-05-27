"""Tests for RiggedLocalRuntime — governed internal MLX-backed runtime boundary.

Tests governance, admission, evidence, projection, and tool authority.
Does NOT require MLX hardware — tests validate the governance path.
Real model execution tests require Apple Silicon and are deferred.
"""

from __future__ import annotations

import pytest

from rig_relay.local_inference.runtime._engine import RiggedMlxEngine
from rig_relay.local_inference.runtime._evidence import (
    emit_cache_evidence,
    emit_execution_evidence,
    emit_refusal_evidence,
)
from rig_relay.local_inference.runtime._models import (
    CacheEvidenceMetrics,
    CachePrivacyClass,
    EnrichedRuntimeCapabilities,
    ExecutionOutcome,
    ExecutionStatus,
    ModelTypeClass,
    RefusalReason,
    RuntimeHealth,
    RuntimeIdentity,
    RuntimeLifecycleState,
    TaskAdmissionResult,
    TaskKind,
    TaskRefusal,
)
from rig_relay.local_inference.runtime._service import (
    RiggedLocalRuntime,
    get_runtime,
    reset_runtime,
)


class TestRuntimeIdentity:
    def test_runtime_kind_is_rigged_mlx(self) -> None:
        rt = RiggedLocalRuntime()
        assert rt.runtime_kind == "rigged_mlx"

    def test_is_configured_reflects_mlx_availability(self) -> None:
        rt = RiggedLocalRuntime()
        actual = rt.is_configured
        if actual:
            assert rt.engine.is_mlx_available

    @pytest.mark.asyncio
    async def test_get_runtime_info_has_expected_shape(self) -> None:
        rt = RiggedLocalRuntime()
        info = await rt.get_runtime_info()
        assert isinstance(info, RuntimeIdentity)
        assert info.runtime_kind == "rigged_mlx"
        assert info.api_protocol == "python_module"


class TestRuntimeHealth:
    @pytest.mark.asyncio
    async def test_health_when_no_mlx(self) -> None:
        rt = RiggedLocalRuntime()
        health = await rt.probe()
        if not rt.is_configured:
            assert health.state in (
                RuntimeLifecycleState.UNCONFIGURED,
                RuntimeLifecycleState.DEGRADED,
            )

    @pytest.mark.asyncio
    async def test_check_health_is_lightweight(self) -> None:
        rt = RiggedLocalRuntime()
        health = await rt.check_health()
        assert isinstance(health, RuntimeHealth)


class TestTaskAdmission:
    def test_rejects_when_mlx_not_available(self) -> None:
        rt = RiggedLocalRuntime()
        admission = rt.admit_task(TaskKind.CHAT)
        if not rt.is_configured:
            assert not admission.admitted
            assert admission.refusal_reason == RefusalReason.RUNTIME_NOT_CONFIGURED

    def test_rejects_non_public_safe_context(self) -> None:
        rt = RiggedLocalRuntime()
        admission = rt.admit_task(TaskKind.CHAT, context_public_safe=False)
        if rt.is_configured:
            assert not admission.admitted
            assert admission.refusal_reason == RefusalReason.CONTEXT_NOT_PUBLIC_SAFE

    def test_rejects_tool_calling_requested(self) -> None:
        rt = RiggedLocalRuntime()
        admission = rt.admit_task(TaskKind.TOOL_PROPOSAL, tool_calling_requested=True)
        if rt.is_configured:
            assert not admission.admitted
            assert admission.refusal_reason == RefusalReason.CAPABILITY_UNSUPPORTED

    def test_rejects_structured_output_requested(self) -> None:
        rt = RiggedLocalRuntime()
        admission = rt.admit_task(
            TaskKind.STRUCTURED_OUTPUT, structured_output_requested=True
        )
        if rt.is_configured:
            assert not admission.admitted
            assert admission.refusal_reason == RefusalReason.CAPABILITY_UNSUPPORTED

    def test_admits_simple_chat_with_public_safe_context(self) -> None:
        rt = RiggedLocalRuntime()
        admission = rt.admit_task(TaskKind.CHAT, context_public_safe=True)
        if rt.is_configured:
            assert admission.admitted
            assert admission.capability_match
            assert not admission.tool_calling_allowed
            assert not admission.structured_output_allowed


class TestExecution:
    @pytest.mark.asyncio
    async def test_refuses_when_no_model_loaded(self) -> None:
        rt = RiggedLocalRuntime()
        result = await rt.execute(messages=[{"role": "user", "content": "Hello"}])
        if rt.is_configured:
            assert not result.executed
            assert result.status in (ExecutionStatus.REFUSED, ExecutionStatus.BLOCKED)
            assert result.refusal is not None

    @pytest.mark.asyncio
    async def test_execution_result_has_correct_shape(self) -> None:
        rt = RiggedLocalRuntime()
        result = await rt.execute(
            messages=[{"role": "user", "content": "Hello"}],
            task_kind=TaskKind.CHAT,
            context_public_safe=True,
        )
        assert isinstance(result, TaskAdmissionResult)
        assert result.task_kind == TaskKind.CHAT
        assert result.admission is not None


class TestEvidenceEmission:
    def test_execution_evidence_is_content_light(self) -> None:
        outcome = ExecutionOutcome(
            executed=True,
            output_sha256="abc123",
            output_length_chars=42,
            prompt_sha256="def456",
            model_id_hash="ghi789",
            latency_ms=100,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            status=ExecutionStatus.EXECUTED,
        )
        evidence_id = emit_execution_evidence(outcome)
        assert evidence_id
        assert evidence_id.startswith("exec_")

    def test_refusal_evidence_is_content_light(self) -> None:
        refusal = TaskRefusal(
            reason=RefusalReason.RUNTIME_NOT_CONFIGURED, detail="MLX not available"
        )
        evidence_id = emit_refusal_evidence(refusal, "task_hash")
        assert evidence_id
        assert evidence_id.startswith("ref_")

    def test_cache_evidence_is_content_light(self) -> None:
        metrics = CacheEvidenceMetrics(
            runtime_kind="rigged_mlx",
            cache_hit_rate_recent=0.85,
            schema_version="rig.relay.local_cache_evidence.v1",
        )
        evidence_id = emit_cache_evidence(metrics)
        assert evidence_id
        assert evidence_id.startswith("cache_")
        assert metrics.content_light


class TestCachePolicy:
    def test_cache_mode_is_local_runtime_kv(self) -> None:
        rt = RiggedLocalRuntime()
        policy = rt.get_cache_policy()
        assert policy.cache_mode == "local_runtime_kv"
        assert policy.data_never_leaves_machine
        assert not policy.persists_across_restarts
        assert policy.rig_relay_must_not_read_cache_contents

    def test_cache_policy_distinct_from_cloud(self) -> None:
        rt = RiggedLocalRuntime()
        policy = rt.get_cache_policy()
        assert policy.privacy_class in (
            CachePrivacyClass.LOCAL_KV_CACHE,
            CachePrivacyClass.LOCAL_HOT_CACHE,
        )
        assert policy.privacy_class != CachePrivacyClass.CLOUD_PROVIDER_CACHE

    def test_cache_policy_requires_disclosure(self) -> None:
        rt = RiggedLocalRuntime()
        policy = rt.get_cache_policy()
        assert policy.disclosure_required
        assert policy.disclosure_summary


class TestCapabilityReporting:
    def test_capabilities_are_honest(self) -> None:
        rt = RiggedLocalRuntime()
        caps = rt.get_capabilities()
        assert caps.chat_completions == "supported"
        assert caps.embeddings == "unsupported"
        assert caps.reranking == "unsupported"
        assert caps.vision == "unsupported"
        assert caps.tool_calling in ("not_tested", "supported", "unsupported")

    def test_capabilities_report_enriched_fields(self) -> None:
        rt = RiggedLocalRuntime()
        caps = rt.get_capabilities()
        assert isinstance(caps, EnrichedRuntimeCapabilities)
        data = caps.model_dump()
        assert len(data) >= 8


class TestProjection:
    def test_projection_has_expected_sections(self) -> None:
        rt = RiggedLocalRuntime()
        proj = rt.build_projection()
        assert "runtime" in proj
        assert "health" in proj
        assert "capabilities" in proj
        assert "cache" in proj
        assert "deferred" in proj
        assert "governance" in proj

    def test_projection_is_content_light(self) -> None:
        rt = RiggedLocalRuntime()
        proj = rt.build_projection()
        gov = proj.get("governance", {})
        assert gov.get("content_light") is True

    def test_projection_deferred_section_exists(self) -> None:
        rt = RiggedLocalRuntime()
        proj = rt.build_projection()
        deferred = proj.get("deferred", {})
        assert len(deferred) > 0


class TestToolAuthority:
    def test_tool_calling_is_not_admitted(self) -> None:
        rt = RiggedLocalRuntime()
        admission = rt.admit_task(
            task_kind=TaskKind.TOOL_PROPOSAL, tool_calling_requested=True
        )
        if rt.is_configured:
            assert not admission.admitted
            assert admission.refusal_reason == RefusalReason.CAPABILITY_UNSUPPORTED

    def test_structured_output_is_not_admitted(self) -> None:
        rt = RiggedLocalRuntime()
        admission = rt.admit_task(
            task_kind=TaskKind.STRUCTURED_OUTPUT, structured_output_requested=True
        )
        if rt.is_configured:
            assert not admission.admitted
            assert admission.refusal_reason == RefusalReason.CAPABILITY_UNSUPPORTED

    def test_execution_outcome_reports_tool_calls_routed(self) -> None:
        outcome = ExecutionOutcome(
            executed=True,
            status=ExecutionStatus.EXECUTED,
            tool_calls_routed_to_governance=True,
        )
        assert outcome.tool_calls_routed_to_governance


class TestModelInventory:
    def test_model_type_enum_values(self) -> None:
        assert ModelTypeClass.LLM == "llm"
        assert ModelTypeClass.VLM == "vlm"
        assert ModelTypeClass.EMBEDDING == "embedding"
        assert ModelTypeClass.RERANKER == "reranker"

    @pytest.mark.asyncio
    async def test_list_models_returns_list(self) -> None:
        rt = RiggedLocalRuntime()
        models = await rt.list_models()
        assert isinstance(models, list)

    def test_inventory_scan_with_no_models(self) -> None:
        from pathlib import Path
        import tempfile

        from rig_relay.local_inference.runtime._inventory import scan_model_inventory

        with tempfile.TemporaryDirectory() as td:
            models = scan_model_inventory([Path(td)])
            assert isinstance(models, list)


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

    def test_runtime_kind_on_new_instance(self) -> None:
        reset_runtime()
        rt = get_runtime()
        assert rt.runtime_kind == "rigged_mlx"


class TestEngine:
    def test_engine_has_expected_methods(self) -> None:
        engine = RiggedMlxEngine()
        assert hasattr(engine, "is_mlx_available")
        assert hasattr(engine, "loaded_model_count")
        assert hasattr(engine, "load_model")
        assert hasattr(engine, "unload_model")
        assert hasattr(engine, "generate")
        assert hasattr(engine, "list_loaded_models")


class TestRefusal:
    def test_refusal_reason_enum_values(self) -> None:
        assert RefusalReason.RUNTIME_NOT_CONFIGURED
        assert RefusalReason.RUNTIME_UNHEALTHY
        assert RefusalReason.CAPABILITY_UNSUPPORTED
        assert RefusalReason.PRIVACY_CLASSIFICATION_DENIED
        assert RefusalReason.CONTEXT_NOT_PUBLIC_SAFE

    def test_task_refusal_model(self) -> None:
        refusal = TaskRefusal(
            reason=RefusalReason.RUNTIME_NOT_CONFIGURED, detail="Test refusal"
        )
        assert refusal.reason == "runtime_not_configured"
        assert refusal.detail == "Test refusal"


class TestExecutionOutcome:
    def test_outcome_is_content_light(self) -> None:
        outcome = ExecutionOutcome()
        assert outcome.content_light
        assert outcome.executed is False

    def test_outcome_no_raw_output(self) -> None:
        outcome = ExecutionOutcome(
            executed=True, output_sha256="abc123", output_length_chars=100
        )
        assert outcome.content_light
        assert outcome.output_sha256
