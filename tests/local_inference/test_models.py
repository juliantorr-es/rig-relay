from __future__ import annotations

from rig_relay.local_inference._models import (
    AssistanceExecutionStatus,
    AssistanceResult,
    AssistanceTask,
    AssistanceTaskKind,
    OutputDisposition,
    ProjectContextPacket,
    PublicationApplicability,
    build_rig_relay_project_packet,
)
from rig_relay.recovery.capability_admission import EnforcementClass


class TestProjectContextPacket:
    def test_build_and_seal(self):
        packet = ProjectContextPacket(
            packet_id="pkt_test",
            project_name="Test App",
            project_summary="A test application",
            technology_keywords=["python"],
            public_safe=True,
        ).seal()

        assert packet.packet_digest.startswith("sha256:")
        assert len(packet.packet_digest) == 71

    def test_is_public_safe(self):
        packet = ProjectContextPacket(packet_id="pkt_test", public_safe=True).seal()
        assert packet.is_public_safe()

    def test_not_safe_when_flagged(self):
        packet = ProjectContextPacket(packet_id="pkt_test", public_safe=False).seal()
        assert not packet.is_public_safe()

    def test_not_safe_when_no_digest(self):
        packet = ProjectContextPacket(packet_id="pkt_test", public_safe=True)
        assert not packet.is_public_safe()

    def test_digest_deterministic(self):
        p1 = ProjectContextPacket(packet_id="pkt_det", project_name="X").seal()
        p2 = ProjectContextPacket(packet_id="pkt_det", project_name="X").seal()
        assert p1.packet_digest == p2.packet_digest

    def test_digest_changes_with_content(self):
        p1 = ProjectContextPacket(packet_id="pkt_x", project_name="A").seal()
        p2 = ProjectContextPacket(packet_id="pkt_x", project_name="B").seal()
        assert p1.packet_digest != p2.packet_digest

    def test_build_context_renders_fields(self):
        packet = ProjectContextPacket(
            packet_id="pkt_ctx",
            project_name="Rig Relay",
            project_summary="A governed desktop app",
            technology_keywords=["Python", "asyncio"],
            package_dependency_summary="pydantic, httpx",
            component_architecture_summary="core, desktop, providers",
            current_milestone="M0",
        ).seal()

        ctx = packet.build_prompt_context()
        assert "Rig Relay" in ctx
        assert "governed desktop app" in ctx
        assert "Python" in ctx
        assert "asyncio" in ctx
        assert "pydantic" in ctx
        assert "core, desktop, providers" in ctx
        assert "M0" in ctx

    def test_build_context_empty_fields_omitted(self):
        packet = ProjectContextPacket(
            packet_id="pkt_empty", project_name="Minimal"
        ).seal()
        ctx = packet.build_prompt_context()
        assert ctx == "Project: Minimal"

    def test_fixture_is_valid(self):
        packet = build_rig_relay_project_packet()
        assert packet.is_public_safe()
        assert packet.provenance == "m0_synthetic_fixture"
        assert "Rig Relay" in packet.project_name

    def test_serialization_roundtrip(self):
        packet = build_rig_relay_project_packet()
        data = packet.model_dump(mode="json")
        reloaded = ProjectContextPacket.model_validate(data)
        assert reloaded.packet_id == packet.packet_id
        assert reloaded.packet_digest == packet.packet_digest


class TestAssistanceTask:
    def test_default_enforcement_class(self):
        task = AssistanceTask(
            task_id="t1", task_kind=AssistanceTaskKind.PROJECT_SUMMARY
        )
        assert (
            task.required_enforcement_class
            == EnforcementClass.JSON_OBJECT_FORMATTING_ONLY
        )

    def test_custom_enforcement_class(self):
        task = AssistanceTask(
            task_id="t2",
            task_kind=AssistanceTaskKind.PROJECT_SUMMARY,
            required_enforcement_class=EnforcementClass.NATIVE_JSON_SCHEMA,
        )
        assert task.required_enforcement_class == EnforcementClass.NATIVE_JSON_SCHEMA

    def test_task_digest_deterministic(self):
        t1 = AssistanceTask(
            task_id="t_digest", task_kind=AssistanceTaskKind.PROJECT_SUMMARY
        )
        t2 = AssistanceTask(
            task_id="t_digest", task_kind=AssistanceTaskKind.PROJECT_SUMMARY
        )
        assert t1.compute_task_digest() == t2.compute_task_digest()

    def test_task_digest_changes_with_params(self):
        t1 = AssistanceTask(
            task_id="t_digest", task_kind=AssistanceTaskKind.PROJECT_SUMMARY
        )
        t2 = AssistanceTask(
            task_id="t_digest", task_kind=AssistanceTaskKind.PAGE_SECTION_ORDERING
        )
        assert t1.compute_task_digest() != t2.compute_task_digest()

    def test_default_publication_internal(self):
        task = AssistanceTask(
            task_id="t3", task_kind=AssistanceTaskKind.MISSING_MATERIAL_CHECKLIST
        )
        assert (
            task.target_publication_applicability
            == PublicationApplicability.INTERNAL_ONLY
        )


class TestAssistanceResult:
    def build_result(self, **overrides):
        defaults = {
            "result_id": "res_1",
            "task_id": "t1",
            "status": AssistanceExecutionStatus.EXECUTED,
            "required_enforcement_class": EnforcementClass.NATIVE_JSON_SCHEMA,
            "enforcement_class_used": EnforcementClass.NATIVE_JSON_SCHEMA,
            "output_disposition": OutputDisposition.DRAFT_REQUIRES_REVIEW,
            "publication_applicability": PublicationApplicability.PROJECT_PAGE,
            "draft_sha256": "sha256:" + "a" * 64,
            "draft_byte_count": 100,
            "context_packet_digest": "sha256:" + "b" * 64,
        }
        defaults.update(overrides)
        return AssistanceResult(**defaults)

    def test_content_light_always_true(self):
        result = self.build_result()
        assert result.content_light

    def test_result_digest_deterministic(self):
        r1 = self.build_result()
        r2 = self.build_result()
        assert r1.compute_result_digest() == r2.compute_result_digest()

    def test_result_digest_excludes_timestamps(self):
        r1 = self.build_result(result_id="res_same")
        import time

        time.sleep(0.001)
        r2 = self.build_result(result_id="res_same")
        r2.created_at = r1.created_at
        r2.draft_sha256 = r1.draft_sha256
        r2.context_packet_digest = r1.context_packet_digest
        assert r1.compute_result_digest() == r2.compute_result_digest()

    def test_refusal_has_no_draft(self):
        result = self.build_result(
            status=AssistanceExecutionStatus.REFUSED_RUNTIME_UNAVAILABLE,
            draft_sha256="",
            draft_byte_count=0,
        )
        assert result.draft_sha256 == ""
        assert result.refusal_reason == ""

    def test_serialization_roundtrip(self):
        result = self.build_result()
        data = result.model_dump(mode="json")
        reloaded = AssistanceResult.model_validate(data)
        assert reloaded.result_id == result.result_id
        assert reloaded.status == result.status


class TestEnums:
    def test_task_kinds(self):
        kinds = list(AssistanceTaskKind)
        assert len(kinds) == 4
        assert AssistanceTaskKind.PROJECT_SUMMARY in kinds

    def test_execution_statuses(self):
        statuses = list(AssistanceExecutionStatus)
        assert AssistanceExecutionStatus.EXECUTED in statuses
        assert AssistanceExecutionStatus.REFUSED_RUNTIME_UNAVAILABLE in statuses

    def test_output_dispositions(self):
        assert OutputDisposition.DRAFT_REQUIRES_REVIEW.value == "draft_requires_review"
        assert OutputDisposition.NO_OUTPUT_PRODUCED.value == "no_output_produced"

    def test_publication_applicabilities(self):
        apps = list(PublicationApplicability)
        assert PublicationApplicability.PROJECT_PAGE in apps
        assert PublicationApplicability.NONE in apps
