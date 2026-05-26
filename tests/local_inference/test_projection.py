from __future__ import annotations

from rig_relay.local_inference._models import (
    AssistanceExecutionStatus,
    AssistanceResult,
    AssistanceTaskKind,
    OutputDisposition,
    PublicationApplicability,
)
from rig_relay.local_inference._projection import build_assistance_projection
from rig_relay.local_inference._service import (
    get_inference_service,
    reset_inference_service,
)
from rig_relay.recovery.capability_admission import EnforcementClass


class TestAssistanceProjection:
    def setup_method(self):
        reset_inference_service()
        self.service = get_inference_service()

    def test_projection_without_runtime_shows_unavailable(self):
        from rig_relay.providers.local_inference.airlock import (
            is_local_inference_configured,
        )

        proj = build_assistance_projection(self.service)
        if not is_local_inference_configured():
            assert not proj["local_runtime"]["available"]
            assert not proj["local_runtime"]["configured"]
        else:
            assert proj["local_runtime"]["configured"]
        assert (
            "configure_local_runtime" in proj["next_actions"]
            or proj["local_runtime"]["configured"]
        )
        assert not proj["approval_needed"]
        assert proj["content_light"]
        assert not proj["raw_drafts_exposed"]

    def test_projection_has_all_required_fields(self):
        proj = build_assistance_projection(self.service)
        required = [
            "schema_version",
            "projection_id",
            "created_at",
            "local_runtime",
            "task_suitability",
            "assistance_results",
            "approval_needed",
            "drafts_awaiting_review",
            "refusal_count",
            "next_actions",
            "content_light",
            "raw_drafts_exposed",
        ]
        for field in required:
            assert field in proj, f"Missing required field: {field}"

    def test_task_suitability_maps_all_kinds(self):
        proj = build_assistance_projection(self.service)
        tasks = proj["task_suitability"]["tasks"]
        for kind in AssistanceTaskKind:
            assert kind.value in tasks

    def test_task_suitability_false_without_runtime(self):
        from rig_relay.providers.local_inference.airlock import (
            is_local_inference_configured,
        )

        proj = build_assistance_projection(self.service)
        tasks = proj["task_suitability"]["tasks"]
        if not is_local_inference_configured():
            for task_info in tasks.values():
                assert not task_info["suitable"]
        else:
            for task_info in tasks.values():
                assert (
                    task_info["suitable"]
                    == proj["task_suitability"]["runtime_available"]
                )

    def test_projection_digest_present(self):
        proj = build_assistance_projection(self.service)
        assert proj["projection_digest"].startswith("sha256:")

    def test_projection_digest_deterministic_from_same_state(self):
        p1 = build_assistance_projection(self.service, projection_id="fixed_id")
        p2 = build_assistance_projection(self.service, projection_id="fixed_id")
        assert p1["projection_digest"] == p2["projection_digest"]

    def test_no_results_no_approval_needed(self):
        proj = build_assistance_projection(self.service)
        assert not proj["approval_needed"]
        assert proj["drafts_awaiting_review"] == 0
        assert proj["refusal_count"] == 0

    def test_results_summary_empty_lists(self):
        proj = build_assistance_projection(self.service)
        results = proj["assistance_results"]
        assert results["total_results"] == 0
        assert results["drafts"] == []
        assert results["refusals"] == []

    def test_projection_with_refusal_adds_to_summary(self):
        self.service._results["ref_1"] = AssistanceResult(
            result_id="ref_1",
            task_id="t1",
            status=AssistanceExecutionStatus.REFUSED_RUNTIME_UNAVAILABLE,
            required_enforcement_class=EnforcementClass.JSON_OBJECT_FORMATTING_ONLY,
            enforcement_class_used=EnforcementClass.UNSUPPORTED,
            output_disposition=OutputDisposition.REFUSED_PUBLICATION,
            publication_applicability=PublicationApplicability.NONE,
            refusal_reason="No runtime",
            refusal_code="runtime_unavailable",
        )

        proj = build_assistance_projection(self.service)
        assert proj["refusal_count"] == 1
        assert len(proj["refusal_explanations"]) == 1
        results = proj["assistance_results"]
        assert results["total_results"] == 1
        assert results["total_refused"] == 1
        assert results["total_executed"] == 0

    def test_projection_with_draft_adds_approval(self):
        key = f"sha256:{'a' * 64}"
        self.service._drafts[key] = "draft content"
        self.service._results["res_1"] = AssistanceResult(
            result_id="res_1",
            task_id="t1",
            status=AssistanceExecutionStatus.EXECUTED,
            required_enforcement_class=EnforcementClass.NATIVE_JSON_SCHEMA,
            enforcement_class_used=EnforcementClass.NATIVE_JSON_SCHEMA,
            output_disposition=OutputDisposition.DRAFT_REQUIRES_REVIEW,
            publication_applicability=PublicationApplicability.PROJECT_PAGE,
            draft_sha256=key,
            draft_byte_count=100,
        )

        proj = build_assistance_projection(self.service)
        assert proj["approval_needed"]
        assert proj["drafts_awaiting_review"] == 1
        results = proj["assistance_results"]
        assert results["total_executed"] == 1
        draft = results["drafts"][0]
        assert draft["draft_sha256"] == key
        assert draft["requires_approval"]


class TestTaskSuitabilityMapping:
    def setup_method(self):
        reset_inference_service()
        self.service = get_inference_service()

    def test_project_summary_requires_json_object(self):
        proj = build_assistance_projection(self.service)
        task_info = proj["task_suitability"]["tasks"]["project_summary"]
        assert task_info["publication_applicability"] == "project_page"
        assert "json_object_formatting_only" in task_info["enforcement_class_required"]

    def test_capability_classification_targets_portfolio(self):
        proj = build_assistance_projection(self.service)
        task_info = proj["task_suitability"]["tasks"]["capability_classification"]
        assert task_info["publication_applicability"] == "portfolio"

    def test_missing_material_checklist_is_internal_only(self):
        proj = build_assistance_projection(self.service)
        task_info = proj["task_suitability"]["tasks"]["missing_material_checklist"]
        assert task_info["publication_applicability"] == "internal_only"
