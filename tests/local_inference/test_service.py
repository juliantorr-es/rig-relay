from __future__ import annotations

import hashlib

import pytest

from rig_relay.local_inference._models import (
    AssistanceExecutionStatus,
    AssistanceTask,
    AssistanceTaskKind,
    OutputDisposition,
    ProjectContextPacket,
    PublicationApplicability,
    build_rig_relay_project_packet,
)
from rig_relay.local_inference._service import (
    get_inference_service,
    reset_inference_service,
)
from rig_relay.recovery.capability_admission import (
    ConstraintCapabilityDisposition,
    EnforcementClass,
)


def _make_disposition(
    disposition_id: str = "disp_1",
    enforcement_class: EnforcementClass = EnforcementClass.NATIVE_JSON_SCHEMA,
    captured: bool = True,
    receipt_bound: bool = True,
) -> ConstraintCapabilityDisposition:
    return ConstraintCapabilityDisposition(
        disposition_id=disposition_id,
        runtime_kind="ollama",
        runtime_endpoint_hash=f"sha256:{hashlib.sha256(b'http://localhost:11434').hexdigest()}",
        model_name_hash=f"sha256:{hashlib.sha256(b'llama3.2').hexdigest()}",
        highest_enforcement_class_demonstrated=enforcement_class,
        json_schema_enforcement_demonstrated=(
            enforcement_class == EnforcementClass.NATIVE_JSON_SCHEMA
        ),
        json_object_formatting_demonstrated=(
            enforcement_class
            in {
                EnforcementClass.JSON_OBJECT_FORMATTING_ONLY,
                EnforcementClass.NATIVE_JSON_SCHEMA,
            }
        ),
        json_schema_enforcement_receipt_bound=receipt_bound,
        evidence_from_captured_local_model=captured,
        proof_event_ids=["proof_disp_1"],
        proof_run_count=1 if captured else 0,
    )


class TestLocalProjectInferenceService:
    def setup_method(self):
        reset_inference_service()
        self.service = get_inference_service()

    def test_service_is_singleton(self):
        s1 = get_inference_service()
        s2 = get_inference_service()
        assert s1 is s2

    def test_reset_creates_new_service(self):
        s1 = get_inference_service()
        reset_inference_service()
        s2 = get_inference_service()
        assert s1 is not s2

    def test_runtime_unavailable_without_config(self):
        from rig_relay.providers.local_inference.airlock import (
            is_local_inference_configured,
        )

        if is_local_inference_configured():
            pytest.skip(
                "Local inference runtime is configured — skipping unavailable test"
            )
        assert not self.service.is_runtime_available()

    def test_runtime_info_returns_unavailable(self):
        from rig_relay.providers.local_inference.airlock import (
            is_local_inference_configured,
        )

        info = self.service.get_runtime_info()
        if is_local_inference_configured():
            assert info["configured"]
        else:
            assert not info["available"]
            assert not info["configured"]

    def test_admit_task_without_dispositions(self):
        task = AssistanceTask(
            task_id="t1", task_kind=AssistanceTaskKind.PROJECT_SUMMARY
        )
        decision = self.service.admit_task(task)
        assert not decision.runtime_capable
        assert "No runtime capability dispositions registered" in decision.reason

    def test_admit_task_with_sufficient_disposition(self):
        disp = _make_disposition()
        self.service.register_disposition(disp)

        task = AssistanceTask(
            task_id="t2",
            task_kind=AssistanceTaskKind.PROJECT_SUMMARY,
            required_enforcement_class=EnforcementClass.NATIVE_JSON_SCHEMA,
        )
        decision = self.service.admit_task(task)
        assert decision.runtime_capable
        assert "satisfies required" in decision.reason

    def test_admit_task_refuses_stronger_class(self):
        disp = _make_disposition(
            enforcement_class=EnforcementClass.JSON_OBJECT_FORMATTING_ONLY,
            captured=True,
            receipt_bound=True,
        )
        self.service.register_disposition(disp)

        task = AssistanceTask(
            task_id="t3",
            task_kind=AssistanceTaskKind.PROJECT_SUMMARY,
            required_enforcement_class=EnforcementClass.NATIVE_JSON_SCHEMA,
        )
        decision = self.service.admit_task(task)
        assert not decision.runtime_capable
        assert "weaker than required" in decision.reason

    def test_admit_task_refuses_without_captured_evidence(self):
        disp = _make_disposition(captured=False)
        self.service.register_disposition(disp)

        task = AssistanceTask(
            task_id="t4",
            task_kind=AssistanceTaskKind.PROJECT_SUMMARY,
            required_enforcement_class=EnforcementClass.NATIVE_JSON_SCHEMA,
        )
        decision = self.service.admit_task(task)
        assert not decision.runtime_capable
        assert "captured local model evidence" in decision.reason

    @pytest.mark.asyncio
    async def test_execute_refuses_unsafe_packet(self):
        packet = ProjectContextPacket(packet_id="pkt_unsafe", public_safe=False).seal()
        task = AssistanceTask(
            task_id="t5", task_kind=AssistanceTaskKind.PROJECT_SUMMARY
        )

        result = await self.service.execute_task(task, packet)
        assert result.status == AssistanceExecutionStatus.REFUSED_UNSAFE_PACKET
        assert result.output_disposition == OutputDisposition.REFUSED_PUBLICATION
        assert result.draft_sha256 == ""

    @pytest.mark.asyncio
    async def test_execute_refuses_packet_digest_mismatch(self):
        packet = ProjectContextPacket(packet_id="pkt_a", public_safe=True).seal()
        task = AssistanceTask(
            task_id="t6",
            task_kind=AssistanceTaskKind.PROJECT_SUMMARY,
            context_packet_digest="sha256:" + "0" * 64,
        )

        result = await self.service.execute_task(task, packet)
        assert result.status == AssistanceExecutionStatus.REFUSED_UNSAFE_PACKET
        assert "digest mismatch" in result.refusal_reason

    @pytest.mark.asyncio
    async def test_execute_refuses_without_runtime(self):
        from rig_relay.providers.local_inference.airlock import (
            is_local_inference_configured,
        )

        packet = build_rig_relay_project_packet()
        task = AssistanceTask(
            task_id="t7", task_kind=AssistanceTaskKind.PROJECT_SUMMARY
        )

        result = await self.service.execute_task(task, packet)
        if not is_local_inference_configured():
            assert (
                result.status == AssistanceExecutionStatus.REFUSED_RUNTIME_UNAVAILABLE
            )
        else:
            assert result.status in {
                AssistanceExecutionStatus.REFUSED_RUNTIME_UNAVAILABLE,
                AssistanceExecutionStatus.REFUSED_CAPABILITY_UNPROVEN,
            }

    @pytest.mark.asyncio
    async def test_execute_refuses_without_capability(self):
        packet = build_rig_relay_project_packet()
        task = AssistanceTask(
            task_id="t8",
            task_kind=AssistanceTaskKind.PROJECT_SUMMARY,
            required_enforcement_class=EnforcementClass.NATIVE_JSON_SCHEMA,
        )

        result = await self.service.execute_task(task, packet)
        assert result.status in {
            AssistanceExecutionStatus.REFUSED_RUNTIME_UNAVAILABLE,
            AssistanceExecutionStatus.REFUSED_CAPABILITY_UNPROVEN,
        }


class TestServiceRefusals:
    def setup_method(self):
        reset_inference_service()
        self.service = get_inference_service()

    @pytest.mark.asyncio
    async def test_unsafe_packet_refused_for_public_task(self):
        packet = ProjectContextPacket(
            packet_id="pkt_unsafe", public_safe=False, project_name="Internal"
        ).seal()
        task = AssistanceTask(
            task_id="t_refuse_unsafe",
            task_kind=AssistanceTaskKind.PROJECT_SUMMARY,
            target_publication_applicability=PublicationApplicability.PROJECT_PAGE,
        )

        result = await self.service.execute_task(task, packet)
        assert result.status == AssistanceExecutionStatus.REFUSED_UNSAFE_PACKET

    @pytest.mark.asyncio
    async def test_runtime_unavailable_refusal_is_specific(self):
        from rig_relay.providers.local_inference.airlock import (
            is_local_inference_configured,
        )

        packet = build_rig_relay_project_packet()
        task = AssistanceTask(
            task_id="t_no_runtime",
            task_kind=AssistanceTaskKind.CAPABILITY_CLASSIFICATION,
        )

        result = await self.service.execute_task(task, packet)
        if not is_local_inference_configured():
            assert (
                result.status == AssistanceExecutionStatus.REFUSED_RUNTIME_UNAVAILABLE
            )
            assert "not configured" in result.refusal_reason
        else:
            assert result.status in {
                AssistanceExecutionStatus.REFUSED_RUNTIME_UNAVAILABLE,
                AssistanceExecutionStatus.REFUSED_CAPABILITY_UNPROVEN,
            }

    @pytest.mark.asyncio
    async def test_capability_unproven_has_reason(self):
        packet = build_rig_relay_project_packet()
        task = AssistanceTask(
            task_id="t_need_schema",
            task_kind=AssistanceTaskKind.CAPABILITY_CLASSIFICATION,
            required_enforcement_class=EnforcementClass.NATIVE_GRAMMAR_GBNF,
        )

        result = await self.service.execute_task(task, packet)
        assert result.status in {
            AssistanceExecutionStatus.REFUSED_RUNTIME_UNAVAILABLE,
            AssistanceExecutionStatus.REFUSED_CAPABILITY_UNPROVEN,
        }


class TestServiceState:
    def setup_method(self):
        reset_inference_service()
        self.service = get_inference_service()

    def test_register_disposition_adds_to_admission(self):
        disp = _make_disposition()
        self.service.register_disposition(disp)
        dispositions = self.service._admission_service.list_dispositions()
        assert len(dispositions) == 1
        assert dispositions[0].disposition_id == "disp_1"

    def test_multiple_dispositions(self):
        self.service.register_disposition(_make_disposition("a"))
        self.service.register_disposition(_make_disposition("b"))
        dispositions = self.service._admission_service.list_dispositions()
        assert len(dispositions) == 2

    def test_list_results_initially_empty(self):
        assert self.service.list_results() == []

    def test_get_result_returns_none_for_unknown(self):
        assert self.service.get_result("nonexistent") is None

    def test_get_draft_returns_none_for_unknown(self):
        assert self.service.get_draft("sha256:ff" + "0" * 62) is None

    def test_clear_drafts(self):
        import hashlib

        key = f"sha256:{hashlib.sha256(b'draft').hexdigest()}"
        self.service._drafts[key] = "test draft"
        self.service.clear_drafts()
        assert not self.service._drafts
