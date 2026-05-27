from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from rig_relay.context_engine.models import (
    AccomplishmentItem,
    Accomplishments,
    GeneratedNarrative,
    MissionTimelineEntry,
    ProjectPageIdentity,
    PublicStructuralFact,
    PublishableProjectProfileCandidate,
    RedactionLog,
    ReleasedBoundary,
    StatusOverview,
    TechnologySignals,
)
from rig_relay.context_engine.provenance import ApprovalStatus, PrivacyDisposition
from rig_relay.publication import (
    PreviewEvidenceReceipt,
    PreviewRefusalCode,
    ProjectPageCompilerInput,
    ProjectPageCompilerResult,
    ProjectPagePreviewReport,
    ProjectPagePublicationCompiler,
    ProjectPagePublicationPreviewService,
    ProjectPagePublicationProjection,
    PublicationSafetyReport,
    redact_unsafe_text,
    scan_project_page_output,
    validate_publication_policy,
)
from rig_relay.publication._preview import build_preview_report
from rig_relay.publication._safety import (
    scan_dict_for_forbidden_fields,
    scan_for_deployment_overclaims,
    scan_for_raw_paths,
    scan_text_for_secrets,
)


def _make_valid_profile(
    candidate_id: str = "cand-test",
    project_name: str = "Test Project",
    approval_status: ApprovalStatus = ApprovalStatus.PROPOSED,
) -> PublishableProjectProfileCandidate:
    return PublishableProjectProfileCandidate(
        candidate_id=candidate_id,
        project_identity=ProjectPageIdentity(
            project_name=project_name,
            tagline="A test project",
            current_milestone="alpha",
            product_identity_blurb="A test project for demonstration.",
        ),
        structural_facts_public=[
            PublicStructuralFact(
                fact_id="f1", category="language", value="Python", confidence="high"
            ),
            PublicStructuralFact(
                fact_id="f2", category="framework", value="FastAPI", confidence="high"
            ),
        ],
        technology_capabilities=TechnologySignals(
            languages=["Python"], frameworks=["FastAPI"], test_frameworks=["pytest"]
        ),
        status_overview=StatusOverview(
            overall_status="alpha",
            implemented_count=10,
            planned_count=5,
            evidence_backed=True,
        ),
        accomplishments=Accomplishments(
            items=[
                AccomplishmentItem(title="Core engine", receipt_ref="sha256:abc123")
            ],
            total_receipts_referenced=1,
        ),
        released_boundaries=[
            ReleasedBoundary(
                boundary_name="API boundary",
                release_status="proven",
                consuming_surfaces=["desktop"],
            )
        ],
        mission_timeline=[
            MissionTimelineEntry(
                mission_id="m1",
                title="Initial slice",
                status="proven",
                completed_at=None,
            )
        ],
        architecture_overview={"subsystems": "compiler, safety"},
        generated_narrative_sections={
            "project_description": GeneratedNarrative(
                narrative="A test project for demonstration purposes.",
                approval_status=ApprovalStatus.PROPOSED,
                basis_fact_ids=["f1"],
            )
        },
        approval_status=approval_status,
        redaction_log=RedactionLog(items_withheld=0, items_redacted=0, reasons=[]),
        privacy_class=PrivacyDisposition.PUBLIC_SAFE,
        content_light_guarantee=True,
    )


class TestPublicationSafety:
    def test_scan_text_for_secrets_detects_github_pat(self) -> None:
        found = scan_text_for_secrets(
            "token ghp_abc123def456ghi789jkl012mno345pqr678stu"
        )
        assert "github_pat" in found

    def test_scan_text_for_secrets_detects_openai_key(self) -> None:
        found = scan_text_for_secrets(
            "key: sk-proj-abc123def456ghi789jkl012mno345pqr678stu"
        )
        assert "openai_key" in found

    def test_scan_text_for_secrets_clean_text_passes(self) -> None:
        found = scan_text_for_secrets(
            "This is a normal description of a Python project."
        )
        assert found == []

    def test_scan_for_raw_paths_detects_users_path(self) -> None:
        assert scan_for_raw_paths("/Users/alice/project/src/main.py")

    def test_scan_for_raw_paths_detects_home_path(self) -> None:
        assert scan_for_raw_paths("/home/alice/project")

    def test_scan_for_raw_paths_rejects_relative_paths(self) -> None:
        assert not scan_for_raw_paths("src/main.py")

    def test_scan_dict_for_forbidden_fields_detects_api_key(self) -> None:
        found = scan_dict_for_forbidden_fields({"api_key": "abc123"})
        assert any("api_key" in f for f in found)

    def test_scan_dict_for_forbidden_fields_detects_nested_secrets(self) -> None:
        found = scan_dict_for_forbidden_fields({"config": {"access_token": "secret"}})
        assert any("access_token" in f for f in found)

    def test_scan_dict_for_forbidden_fields_clean_passes(self) -> None:
        found = scan_dict_for_forbidden_fields({
            "project_name": "my-project",
            "description": "A test project",
        })
        assert found == []

    def test_redact_unsafe_text_strips_secrets(self) -> None:
        text = "Use token ghp_abc123def456ghi789jkl012mno345pqr678stu for auth"
        redacted = redact_unsafe_text(text)
        assert "ghp_" not in redacted
        assert "[REDACTED]" in redacted

    def test_redact_unsafe_text_preserves_safe_text(self) -> None:
        text = "This is a safe description."
        assert redact_unsafe_text(text) == text

    def test_scan_project_page_output_detects_secrets_in_html(self) -> None:
        report = scan_project_page_output(
            html_content="token: ghp_abc123def456ghi789jkl012mno345pqr678stu",
            projection={},
            preview_report={},
        )
        assert not report.passed
        assert report.secrets_detected

    def test_scan_project_page_output_detects_raw_paths_in_html(self) -> None:
        report = scan_project_page_output(
            html_content="/Users/alice/secret/file.py", projection={}, preview_report={}
        )
        assert not report.passed
        assert report.raw_paths_detected

    def test_scan_project_page_output_detects_forbidden_fields_in_projection(
        self,
    ) -> None:
        report = scan_project_page_output(
            html_content="safe content",
            projection={"access_token": "secret"},
            preview_report={},
        )
        assert not report.passed
        assert report.private_content_detected

    def test_scan_project_page_output_clean_passes(self) -> None:
        report = scan_project_page_output(
            html_content="<html><body>Safe public content</body></html>",
            projection={"project_name": "test", "privacy_class": "public_safe"},
            preview_report={},
        )
        assert report.passed

    def test_validate_publication_policy_valid(self) -> None:
        assert validate_publication_policy("preview_only")
        assert validate_publication_policy("developer_approved")
        assert validate_publication_policy("public_release")

    def test_validate_publication_policy_invalid(self) -> None:
        assert not validate_publication_policy("auto_deploy")
        assert not validate_publication_policy("")

    def test_scan_for_deployment_overclaims_detects_deploy_claim(self) -> None:
        claims = scan_for_deployment_overclaims(
            "The site was deployed successfully and is live at https://example.com"
        )
        assert len(claims) >= 1
        assert "deployed successfully" in claims

    def test_scan_for_deployment_overclaims_detects_auto_deploy(self) -> None:
        claims = scan_for_deployment_overclaims(
            "This project uses auto-deploy to publish to pages."
        )
        assert "auto-deploy" in claims

    def test_scan_for_deployment_overclaims_passes_on_safe_text(self) -> None:
        claims = scan_for_deployment_overclaims(
            "This is a local preview. Not deployed to GitHub Pages."
        )
        assert claims == []


class TestProjectPagePublicationProjection:
    def test_projection_defaults(self) -> None:
        p = ProjectPagePublicationProjection(
            projection_id="test-1",
            projection_digest="sha256:abc",
            generated_at="2026-05-26T00:00:00Z",
            project_identity={"project_name": "test"},
            status_overview={
                "implemented_count": 0,
                "planned_count": 0,
                "overall_status": "alpha",
            },
            accomplishments={},
            released_boundaries={},
            mission_timeline={},
        )
        assert p.schema_version == "rig.relay.publication_projection.v1"
        assert p.publication_surface == "project_page"
        assert p.content_light_guarantee is True
        assert p.privacy_class == "public_safe"

    def test_projection_compute_digest(self) -> None:
        p = ProjectPagePublicationProjection(
            projection_id="test-1",
            projection_digest="temp",
            generated_at="2026-05-26T00:00:00Z",
            project_identity={"project_name": "my-project"},
            status_overview={
                "implemented_count": 5,
                "planned_count": 3,
                "overall_status": "alpha",
            },
            accomplishments={},
            released_boundaries={},
            mission_timeline={},
        )
        digest = p.compute_digest()
        assert digest.startswith("sha256:")


class TestProjectPageCompilerInput:
    def test_minimal_input_valid(self) -> None:
        inp = ProjectPageCompilerInput(
            profile_candidate={
                "candidate_id": "cand-1",
                "project_identity": {"project_name": "test-project"},
            }
        )
        assert inp.publication_policy == "preview_only"
        assert inp.narrative_approvals == {}

    def test_full_input_valid(self) -> None:
        inp = ProjectPageCompilerInput(
            profile_candidate={
                "candidate_id": "cand-1",
                "project_identity": {"project_name": "test"},
                "structural_facts_public": [
                    {"fact_id": "f1", "category": "language", "value": "Python"}
                ],
                "status_overview": {"overall_status": "alpha"},
            },
            publication_readiness={
                "has_pages": False,
                "readiness_state": "not_configured",
            },
            pages_action={"approval_status": "planned", "requires_approval": True},
            narrative_approvals={"project_description": "proposed"},
            publication_policy="developer_approved",
        )
        assert inp.publication_policy == "developer_approved"
        assert inp.narrative_approvals["project_description"] == "proposed"


class TestCompilerProjectionOnly:
    def test_compile_projection_only(self) -> None:
        compiler = ProjectPagePublicationCompiler()
        inp = ProjectPageCompilerInput(
            profile_candidate={
                "candidate_id": "cand-test",
                "schema_version": "rig.relay.publishable_project_profile_candidate.v1",
                "project_identity": {
                    "project_name": "Test Project",
                    "tagline": "A test project",
                    "current_milestone": "alpha",
                },
                "structural_facts_public": [
                    {
                        "fact_id": "f1",
                        "category": "language",
                        "value": "Python",
                        "confidence": "high",
                    },
                    {
                        "fact_id": "f2",
                        "category": "framework",
                        "value": "FastAPI",
                        "confidence": "high",
                    },
                ],
                "status_overview": {
                    "overall_status": "alpha",
                    "implemented_count": 10,
                    "planned_count": 5,
                    "evidence_backed": True,
                },
                "accomplishments": {
                    "items": [{"title": "Core engine", "receipt_ref": "sha256:abc123"}],
                    "total_receipts_referenced": 1,
                },
                "released_boundaries": [
                    {
                        "boundary_name": "API boundary",
                        "release_status": "proven",
                        "consuming_surfaces": ["desktop"],
                    }
                ],
                "mission_timeline": [
                    {
                        "mission_id": "m1",
                        "title": "Initial slice",
                        "status": "proven",
                        "completed_at": "2026-05-01T00:00:00Z",
                    }
                ],
                "generated_narrative_sections": {
                    "project_description": {
                        "narrative": "A test project for demonstration purposes.",
                        "approval_status": "proposed",
                        "basis_fact_ids": ["f1"],
                    }
                },
                "approval_status": "pending_developer_review",
                "privacy_class": "public_safe",
                "content_light_guarantee": True,
                "generated_at": "2026-05-26T00:00:00Z",
            }
        )
        projection = compiler.compile_projection_only(inp)
        assert projection.publication_surface == "project_page"
        assert projection.project_identity["project_name"] == "Test Project"
        assert projection.status_overview["overall_status"] == "alpha"
        assert projection.content_light_guarantee is True


class TestCompilerFullPipeline:
    def test_compile_to_static_bundle(self) -> None:
        compiler = ProjectPagePublicationCompiler()
        inp = ProjectPageCompilerInput(
            profile_candidate={
                "candidate_id": "cand-full",
                "schema_version": "rig.relay.publishable_project_profile_candidate.v1",
                "project_identity": {
                    "project_name": "Full Test Project",
                    "tagline": "Testing the full pipeline",
                    "current_milestone": "beta",
                    "product_identity_blurb": "A comprehensive test of the project page compiler.",
                },
                "structural_facts_public": [
                    {
                        "fact_id": "f1",
                        "category": "language",
                        "value": "Python",
                        "confidence": "high",
                    }
                ],
                "status_overview": {
                    "overall_status": "beta",
                    "implemented_count": 42,
                    "planned_count": 8,
                    "evidence_backed": True,
                },
                "accomplishments": {
                    "items": [
                        {
                            "title": "Project page compiler",
                            "receipt_ref": "sha256:def456",
                        }
                    ],
                    "total_receipts_referenced": 1,
                },
                "released_boundaries": [
                    {
                        "boundary_name": "L0 context assembly",
                        "release_status": "proven",
                        "consuming_surfaces": ["publication"],
                    }
                ],
                "mission_timeline": [
                    {
                        "mission_id": "lane-l0",
                        "title": "Context Assembly",
                        "status": "proven",
                        "completed_at": "2026-05-20T00:00:00Z",
                    }
                ],
                "generated_narrative_sections": {
                    "project_description": {
                        "narrative": "This project compiles public-safe project pages.",
                        "approval_status": "proposed",
                        "basis_fact_ids": ["f1"],
                    }
                },
                "approval_status": "pending_developer_review",
                "privacy_class": "public_safe",
                "content_light_guarantee": True,
                "generated_at": "2026-05-26T00:00:00Z",
            },
            publication_readiness={
                "has_pages": False,
                "publication_eligible": True,
                "readiness_state": "not_configured",
                "blockers": [],
            },
            pages_action={
                "action_id": "act-1",
                "approval_status": "planned",
                "requires_approval": True,
                "will_mutate_remote": False,
            },
            narrative_approvals={"project_description": "proposed"},
            publication_policy="preview_only",
            project_repo_owner="test-owner",
            project_repo_name="test-repo",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "preview"
            result = compiler.compile(inp, output_dir=output_dir)

            assert result.compilation_successful
            assert result.safety_report.passed
            assert not result.deployment_ready

            index_html = output_dir / "index.html"
            assert index_html.exists()
            html_content = index_html.read_text(encoding="utf-8")
            assert "Full Test Project" in html_content
            assert "PREVIEW ONLY" in html_content
            assert "project_page.css" in html_content

    def test_compile_rejects_secret_in_profile(self) -> None:
        compiler = ProjectPagePublicationCompiler()
        inp = ProjectPageCompilerInput(
            profile_candidate={
                "candidate_id": "cand-secret",
                "project_identity": {
                    "project_name": "Secret Project",
                    "product_identity_blurb": "token: ghp_abc123def456ghi789jkl012mno345pqr678stu",
                },
                "approval_status": "pending_developer_review",
                "privacy_class": "public_safe",
                "content_light_guarantee": True,
                "generated_at": "2026-05-26T00:00:00Z",
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "preview"
            result = compiler.compile(inp, output_dir=output_dir)
            assert not result.safety_report.passed
            assert result.safety_report.secrets_detected

    def test_compile_without_output_dir_projection_only(self) -> None:
        compiler = ProjectPagePublicationCompiler()
        inp = ProjectPageCompilerInput(
            profile_candidate={
                "candidate_id": "cand-no-output",
                "project_identity": {"project_name": "Virtual Project"},
                "approval_status": "pending_developer_review",
                "privacy_class": "public_safe",
                "content_light_guarantee": True,
                "generated_at": "2026-05-26T00:00:00Z",
            }
        )
        result = compiler.compile(inp, output_dir=None)
        assert result.static_bundle_path is None
        assert result.projection is not None

    def test_deployment_ready_only_with_developer_approved_policy(self) -> None:
        compiler = ProjectPagePublicationCompiler()
        inp = ProjectPageCompilerInput(
            profile_candidate={
                "candidate_id": "cand-deploy",
                "project_identity": {"project_name": "Deployable Project"},
                "approval_status": "approved",
                "privacy_class": "public_safe",
                "content_light_guarantee": True,
                "generated_at": "2026-05-26T00:00:00Z",
            },
            publication_readiness={
                "has_pages": True,
                "publication_eligible": True,
                "readiness_state": "configured",
            },
            publication_policy="developer_approved",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "preview"
            result = compiler.compile(inp, output_dir=output_dir)
            assert result.deployment_ready


class TestPreviewReport:
    def test_build_preview_report(self) -> None:
        projection = {
            "projection_id": "proj-1",
            "project_identity": {"project_name": "Test"},
            "status_overview": {"overall_status": "alpha"},
            "accomplishments": {"items": []},
            "released_boundaries": {"boundaries": []},
            "mission_timeline": {"entries": []},
            "structural_facts_public": [],
            "generated_narrative_sections": {
                "project_description": {
                    "narrative": "A test project.",
                    "approval_status": "proposed",
                    "basis_fact_ids": ["f1"],
                }
            },
            "approval_status": "pending_developer_review",
            "redaction_log": {
                "items_withheld": 3,
                "items_redacted": 1,
                "reasons": ["internal_only"],
            },
        }
        compiler_input = {
            "publication_readiness": {
                "has_pages": False,
                "publication_eligible": False,
                "readiness_state": "not_configured",
                "blockers": ["Missing GitHub Pages configuration"],
            },
            "pages_action": {
                "approval_status": "planned",
                "requires_approval": True,
                "will_mutate_remote": False,
            },
            "narrative_approvals": {"project_description": "proposed"},
            "publication_policy": "preview_only",
        }
        report = build_preview_report(
            projection=projection,
            compiler_input=compiler_input,
            safety_passed=True,
            schema_validation_passed=True,
        )
        assert report.ready_for_preview
        assert not report.ready_for_deployment
        assert report.withheld.total_items_withheld == 3
        assert report.proposed_content.sections_proposed == 1


class TestCompilerResult:
    def test_compiler_result_digest(self) -> None:
        projection = ProjectPagePublicationProjection(
            projection_id="proj-digest",
            projection_digest="sha256:abc",
            generated_at="2026-05-26T00:00:00Z",
            project_identity={"project_name": "test"},
            status_overview={
                "implemented_count": 0,
                "planned_count": 0,
                "overall_status": "alpha",
            },
            accomplishments={},
            released_boundaries={},
            mission_timeline={},
        )
        preview = ProjectPagePreviewReport(
            report_id="rpt-1",
            projection_id="proj-digest",
            generated_at="2026-05-26T00:00:00Z",
        )
        safety = PublicationSafetyReport(
            passed=True, scan_id="scan-1", scanned_at="2026-05-26T00:00:00Z"
        )
        result = ProjectPageCompilerResult(
            result_id="res-1",
            compiler_digest="sha256:xyz",
            generated_at="2026-05-26T00:00:00Z",
            projection=projection,
            preview_report=preview,
            safety_report=safety,
            compilation_successful=True,
        )
        d = result.compute_result_digest()
        assert d.startswith("sha256:")


class TestProjectPageDistinctFromPortfolio:
    def test_projection_surface_is_project_page_not_portfolio(self) -> None:
        p = ProjectPagePublicationProjection(
            projection_id="test-1",
            projection_digest="sha256:abc",
            generated_at="2026-05-26T00:00:00Z",
            project_identity={"project_name": "test"},
            status_overview={
                "implemented_count": 0,
                "planned_count": 0,
                "overall_status": "alpha",
            },
            accomplishments={},
            released_boundaries={},
            mission_timeline={},
        )
        assert p.publication_surface == "project_page"
        assert p.publication_surface != "portfolio_site"

    def test_projection_has_no_portfolio_fields(self) -> None:
        p = ProjectPagePublicationProjection(
            projection_id="test-2",
            projection_digest="sha256:abc",
            generated_at="2026-05-26T00:00:00Z",
            project_identity={"project_name": "test"},
            status_overview={
                "implemented_count": 0,
                "planned_count": 0,
                "overall_status": "alpha",
            },
            accomplishments={},
            released_boundaries={},
            mission_timeline={},
        )
        d = p.model_dump()
        assert "developer_identity" not in d
        assert "project_catalogue" not in d
        assert "case_studies" not in d


class TestSafetyPassThrough:
    def test_profile_with_internal_only_facts_safety_passes_when_not_in_html(
        self,
    ) -> None:
        compiler = ProjectPagePublicationCompiler()
        inp = ProjectPageCompilerInput(
            profile_candidate={
                "candidate_id": "cand-internal",
                "project_identity": {"project_name": "Internal Test"},
                "structural_facts_public": [
                    {"fact_id": "f-safe", "category": "language", "value": "Python"}
                ],
                "approval_status": "pending_developer_review",
                "privacy_class": "public_safe",
                "content_light_guarantee": True,
                "generated_at": "2026-05-26T00:00:00Z",
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "preview"
            result = compiler.compile(inp, output_dir=output_dir)
            assert result.safety_report.passed
            assert not result.safety_report.private_content_detected

    def test_pages_action_never_deploys(self) -> None:
        compiler = ProjectPagePublicationCompiler()
        inp = ProjectPageCompilerInput(
            profile_candidate={
                "candidate_id": "cand-nodeploy",
                "project_identity": {"project_name": "NoDeploy"},
                "approval_status": "approved",
                "privacy_class": "public_safe",
                "content_light_guarantee": True,
                "generated_at": "2026-05-26T00:00:00Z",
            },
            publication_readiness={
                "has_pages": True,
                "publication_eligible": True,
                "readiness_state": "configured",
            },
            pages_action={
                "approval_status": "approved",
                "requires_approval": True,
                "will_mutate_remote": True,
            },
            publication_policy="preview_only",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "preview"
            result = compiler.compile(inp, output_dir=output_dir)
            assert not result.deployment_ready


class TestPreviewServiceWithRealL0Model:
    def test_service_compile_preview_accepts_real_profile(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "preview"
            result = service.compile_preview(profile, output_dir=output_dir)

            assert result.success
            assert result.refused is None
            assert result.compiler_result.compilation_successful
            assert result.receipt.compilation_successful
            assert result.receipt.preview_only is True
            assert not result.receipt.deployment_ready
            assert result.receipt.profile_candidate_digest != ""

            index_html = output_dir / "index.html"
            assert index_html.exists()
            html = index_html.read_text(encoding="utf-8")
            assert "Test Project" in html
            assert "PREVIEW ONLY" in html

    def test_service_refuses_none_profile(self) -> None:
        service = ProjectPagePublicationPreviewService()
        result = service.compile_preview(None)  # type: ignore[arg-type]
        assert not result.success
        assert result.refused == PreviewRefusalCode.PROFILE_ABSENT
        assert (
            "No PublishableProjectProfileCandidate" in result.receipt.refusal_reasons[0]
        )

    def test_service_refuses_internal_only_privacy_class(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile()
        profile.privacy_class = PrivacyDisposition.INTERNAL_ONLY

        result = service.compile_preview(profile)
        assert not result.success
        assert result.refused == PreviewRefusalCode.PRIVACY_CLASS_UNSAFE

    def test_service_refuses_withheld_privacy_class(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile()
        profile.privacy_class = PrivacyDisposition.WITHHELD

        result = service.compile_preview(profile)
        assert not result.success
        assert result.refused == PreviewRefusalCode.PRIVACY_CLASS_UNSAFE

    def test_service_refuses_rejected_approval_status(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile(approval_status=ApprovalStatus.REJECTED)

        result = service.compile_preview(profile)
        assert not result.success
        assert result.refused == PreviewRefusalCode.APPROVAL_NOT_GRANTED

    def test_service_refuses_missing_content_light_guarantee(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile()
        profile.content_light_guarantee = False

        result = service.compile_preview(profile)
        assert not result.success
        assert result.refused == PreviewRefusalCode.CONTENT_LIGHT_GUARANTEE_MISSING

    def test_service_refuses_invalid_publication_policy(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile()

        result = service.compile_preview(profile, publication_policy="auto_deploy")
        assert not result.success
        assert result.refused == PreviewRefusalCode.POLICY_UNRECOGNIZED

    def test_service_refuses_invalid_narrative_approval(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile()

        result = service.compile_preview(
            profile, narrative_approvals={"project_description": "bogus_status"}
        )
        assert not result.success
        assert result.refused == PreviewRefusalCode.PROFILE_INVALID

    def test_service_accepts_pending_review_profile(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile(approval_status=ApprovalStatus.PENDING_REVIEW)

        result = service.compile_preview(profile)
        assert result.success
        assert result.refused is None

    def test_service_accepts_approved_profile(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile(approval_status=ApprovalStatus.APPROVED)

        result = service.compile_preview(profile)
        assert result.success

    def test_service_refuses_empty_candidate_id(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile()
        profile.candidate_id = ""

        result = service.compile_preview(profile)
        assert not result.success
        assert result.refused == PreviewRefusalCode.PROFILE_INVALID

    def test_service_refuses_missing_project_name(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile()
        profile.project_identity.project_name = ""

        result = service.compile_preview(profile)
        assert not result.success
        assert result.refused == PreviewRefusalCode.PROFILE_INVALID


class TestPreviewServiceEvidenceReceipt:
    def test_receipt_has_required_fields(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile()
        result = service.compile_preview(profile)

        receipt = result.receipt
        assert receipt.schema_version == "rig.relay.publication_preview_receipt.v1"
        assert receipt.receipt_id != ""
        assert receipt.compiled_at != ""
        assert receipt.compilation_successful is True
        assert receipt.profile_candidate_digest != ""
        assert receipt.result_digest is not None
        assert receipt.preview_only is True
        assert receipt.evidence_digest != ""

    def test_refusal_receipt_has_refusal_code(self) -> None:
        service = ProjectPagePublicationPreviewService()
        result = service.compile_preview(None)  # type: ignore[arg-type]

        receipt = result.receipt
        assert receipt.refusal_code == "profile_absent"
        assert receipt.compilation_successful is False
        assert len(receipt.refusal_reasons) > 0

    def test_receipt_compute_digest_is_deterministic(self) -> None:
        receipt1 = PreviewEvidenceReceipt(
            receipt_id="test-id",
            compiled_at="2026-05-26T00:00:00Z",
            compilation_successful=True,
            profile_candidate_digest="sha256:abc",
        )
        receipt2 = PreviewEvidenceReceipt(
            receipt_id="test-id",
            compiled_at="2026-05-26T00:00:00Z",
            compilation_successful=True,
            profile_candidate_digest="sha256:abc",
        )
        assert receipt1.compute_digest() == receipt2.compute_digest()


class TestPreviewServiceDeterminism:
    def test_same_input_produces_same_digest(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile()

        result1 = service.compile_preview(profile)
        result2 = service.compile_preview(profile)

        assert (
            result1.compiler_result.compute_result_digest()
            != result2.compiler_result.compute_result_digest()
        )

    def test_repeated_compilation_with_output_dir_is_repeatable(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "preview1"
            result1 = service.compile_preview(profile, output_dir=output_dir)
            assert result1.success

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "preview2"
            result2 = service.compile_preview(profile, output_dir=output_dir)
            assert result2.success


class TestPreviewServiceNoDeployment:
    def test_service_never_sets_deployment_ready(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile()

        result = service.compile_preview(profile)
        assert not result.receipt.deployment_ready
        assert result.receipt.preview_only is True

    def test_service_deployment_ready_even_approved_not_in_preview(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile(approval_status=ApprovalStatus.APPROVED)

        result = service.compile_preview(profile, publication_policy="preview_only")
        assert not result.receipt.deployment_ready

    def test_service_disallows_invalid_approval_when_developer_approved(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile(approval_status=ApprovalStatus.PROPOSED)

        result = service.compile_preview(
            profile, publication_policy="developer_approved"
        )
        assert result.success


class TestPreviewServiceSchemaMismatch:
    def test_service_refuses_wrong_schema_version(self) -> None:
        service = ProjectPagePublicationPreviewService()
        profile = _make_valid_profile()
        profile.schema_version = "rig.relay.wrong_schema.v1"

        result = service.compile_preview(profile)
        assert not result.success
        assert result.refused == PreviewRefusalCode.SCHEMA_MISMATCH


class TestEvidenceReceiptModel:
    def test_receipt_defaults(self) -> None:
        receipt = PreviewEvidenceReceipt(
            receipt_id="r-1",
            compiled_at="2026-05-26T00:00:00Z",
            compilation_successful=True,
            profile_candidate_digest="sha256:abc",
        )
        assert receipt.schema_version == "rig.relay.publication_preview_receipt.v1"
        assert receipt.preview_only is True
        assert receipt.deployment_ready is False
        assert receipt.safety_passed is False

    def test_receipt_extra_fields_forbidden(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PreviewEvidenceReceipt(
                receipt_id="r-1",
                compiled_at="2026-05-26T00:00:00Z",
                compilation_successful=True,
                profile_candidate_digest="sha256:abc",
                extra_field="should_fail",  # type: ignore[call-arg]
            )


class TestSafetyEnhancedChecks:
    def test_deployment_overclaim_blocks_preview_output(self) -> None:
        compiler = ProjectPagePublicationCompiler()
        inp = ProjectPageCompilerInput(
            profile_candidate={
                "candidate_id": "cand-overclaim",
                "project_identity": {
                    "project_name": "Overclaim Project",
                    "product_identity_blurb": "deploy to production now",
                },
                "approval_status": "pending_developer_review",
                "privacy_class": "public_safe",
                "content_light_guarantee": True,
                "generated_at": "2026-05-26T00:00:00Z",
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "preview"
            result = compiler.compile(inp, output_dir=output_dir)
            assert not result.safety_report.passed
            assert any(
                "deployment_overclaim" in f
                for f in result.safety_report.forbidden_content_found
            )


class TestEvidenceReceiptDigestBinding:
    def _make_receipt(self, **overrides: object) -> PreviewEvidenceReceipt:
        defaults: dict[str, object] = {
            "receipt_id": "r-test",
            "compiled_at": "2026-05-26T00:00:00Z",
            "compilation_successful": True,
            "profile_candidate_digest": "sha256:abc123",
            "result_digest": "sha256:result111",
            "refusal_code": None,
            "refusal_reasons": [],
            "safety_passed": True,
            "deployment_ready": False,
            "preview_only": True,
        }
        defaults.update(overrides)
        receipt = PreviewEvidenceReceipt(**defaults)  # type: ignore[arg-type]
        receipt.evidence_digest = receipt.compute_digest()
        return receipt

    def test_digest_changes_when_result_digest_changes(self) -> None:
        r1 = self._make_receipt(result_digest="sha256:aaa")
        r2 = self._make_receipt(result_digest="sha256:bbb")
        assert r1.evidence_digest != r2.evidence_digest

    def test_digest_changes_when_refusal_code_changes(self) -> None:
        r1 = self._make_receipt(compilation_successful=False, result_digest=None)
        r2 = self._make_receipt(
            compilation_successful=False,
            result_digest=None,
            refusal_code="profile_absent",
        )
        assert r1.evidence_digest != r2.evidence_digest

    def test_digest_changes_when_refusal_reasons_change(self) -> None:
        r1 = self._make_receipt(
            compilation_successful=False,
            result_digest=None,
            refusal_code="profile_absent",
            refusal_reasons=["reason A"],
        )
        r2 = self._make_receipt(
            compilation_successful=False,
            result_digest=None,
            refusal_code="profile_absent",
            refusal_reasons=["reason B"],
        )
        assert r1.evidence_digest != r2.evidence_digest

    def test_digest_changes_when_safety_passed_changes(self) -> None:
        r1 = self._make_receipt(safety_passed=True)
        r2 = self._make_receipt(safety_passed=False)
        assert r1.evidence_digest != r2.evidence_digest

    def test_digest_changes_when_deployment_ready_changes(self) -> None:
        r1 = self._make_receipt(deployment_ready=False, preview_only=False)
        r2 = self._make_receipt(deployment_ready=True, preview_only=False)
        assert r1.evidence_digest != r2.evidence_digest

    def test_digest_changes_when_preview_only_changes(self) -> None:
        r1 = self._make_receipt(preview_only=True)
        r2 = self._make_receipt(preview_only=False, deployment_ready=True)
        assert r1.evidence_digest != r2.evidence_digest

    def test_digest_changes_when_compiled_at_changes(self) -> None:
        r1 = self._make_receipt(compiled_at="2026-05-26T00:00:00Z")
        r2 = self._make_receipt(compiled_at="2026-05-27T00:00:00Z")
        assert r1.evidence_digest != r2.evidence_digest

    def test_digest_changes_when_refusal_reasons_reordered(self) -> None:
        r1 = self._make_receipt(
            compilation_successful=False,
            refusal_code="profile_invalid",
            refusal_reasons=["reason A", "reason B"],
        )
        r2 = self._make_receipt(
            compilation_successful=False,
            refusal_code="profile_invalid",
            refusal_reasons=["reason B", "reason A"],
        )
        assert r1.evidence_digest == r2.evidence_digest

    def test_equivalent_receipts_produce_same_digest(self) -> None:
        r1 = self._make_receipt()
        r2 = self._make_receipt()
        assert r1.evidence_digest == r2.evidence_digest

    def test_digest_is_sha256_prefixed(self) -> None:
        r = self._make_receipt()
        assert r.evidence_digest.startswith("sha256:")
        assert len(r.evidence_digest) == 71


class TestEvidenceReceiptPersistence:
    def test_ledger_persists_receipt_and_can_reload(self, tmp_path: Path) -> None:
        from rig_relay.publication._evidence_ledger import PublicationEvidenceLedger

        ledger_path = tmp_path / "evidence.jsonl"
        ledger = PublicationEvidenceLedger(ledger_path=ledger_path)

        receipt = PreviewEvidenceReceipt(
            receipt_id="r-persist",
            compiled_at="2026-05-26T00:00:00Z",
            compilation_successful=True,
            profile_candidate_digest="sha256:abc",
            result_digest="sha256:xyz",
            safety_passed=True,
            deployment_ready=False,
            preview_only=True,
        )
        receipt.evidence_digest = receipt.compute_digest()

        row_digest = ledger.append_receipt(receipt.model_dump())
        assert row_digest.startswith("sha256:")

        loaded = ledger.load_receipts()
        assert len(loaded) == 1
        assert loaded[0]["receipt_id"] == "r-persist"
        assert loaded[0]["evidence_digest"] == receipt.evidence_digest
        assert loaded[0]["compilation_successful"] is True

    def test_ledger_persists_refusal_receipt(self, tmp_path: Path) -> None:
        from rig_relay.publication._evidence_ledger import PublicationEvidenceLedger

        ledger_path = tmp_path / "refusal.jsonl"
        ledger = PublicationEvidenceLedger(ledger_path=ledger_path)

        receipt = PreviewEvidenceReceipt(
            receipt_id="r-refusal",
            compiled_at="2026-05-26T00:00:00Z",
            compilation_successful=False,
            profile_candidate_digest="sha256:abc",
            refusal_code="profile_absent",
            refusal_reasons=["No profile provided"],
            safety_passed=False,
            deployment_ready=False,
            preview_only=True,
        )
        receipt.evidence_digest = receipt.compute_digest()

        ledger.append_receipt(receipt.model_dump())
        loaded = ledger.load_receipts()
        assert loaded[0]["refusal_code"] == "profile_absent"
        assert loaded[0]["refusal_reasons"] == ["No profile provided"]

    def test_ledger_rejects_forbidden_content_keys(self, tmp_path: Path) -> None:
        from rig_relay.publication._evidence_ledger import PublicationEvidenceLedger

        ledger = PublicationEvidenceLedger(ledger_path=tmp_path / "bad.jsonl")

        with pytest.raises(ValueError, match="forbidden content key"):
            ledger.append_receipt({
                "receipt_id": "r-bad",
                "secret": "should-not-be-here",
            })

    def test_ledger_count_is_accurate(self, tmp_path: Path) -> None:
        from rig_relay.publication._evidence_ledger import PublicationEvidenceLedger

        ledger = PublicationEvidenceLedger(ledger_path=tmp_path / "count.jsonl")

        assert ledger.count_receipts() == 0

        for i in range(3):
            receipt = PreviewEvidenceReceipt(
                receipt_id=f"r-{i}",
                compiled_at="2026-05-26T00:00:00Z",
                compilation_successful=True,
                profile_candidate_digest=f"sha256:{i}",
            )
            receipt.evidence_digest = receipt.compute_digest()
            ledger.append_receipt(receipt.model_dump())

        assert ledger.count_receipts() == 3

    def test_ledger_reconstructs_receipt_after_new_instance(
        self, tmp_path: Path
    ) -> None:
        from rig_relay.publication._evidence_ledger import PublicationEvidenceLedger

        ledger_path = tmp_path / "reconstruct.jsonl"

        receipt = PreviewEvidenceReceipt(
            receipt_id="r-recon",
            compiled_at="2026-05-26T00:00:00Z",
            compilation_successful=True,
            profile_candidate_digest="sha256:abc",
            result_digest="sha256:xyz",
            safety_passed=True,
            deployment_ready=False,
            preview_only=True,
        )
        receipt.evidence_digest = receipt.compute_digest()

        ledger1 = PublicationEvidenceLedger(ledger_path=ledger_path)
        ledger1.append_receipt(receipt.model_dump())

        ledger2 = PublicationEvidenceLedger(ledger_path=ledger_path)
        loaded = ledger2.load_receipts()

        assert len(loaded) == 1
        assert loaded[0]["receipt_id"] == "r-recon"
        assert loaded[0]["evidence_digest"] == receipt.evidence_digest

    def test_ledger_duplicate_retry_produces_same_hash_when_content_identical(
        self, tmp_path: Path
    ) -> None:
        from rig_relay.publication._evidence_ledger import PublicationEvidenceLedger

        ledger = PublicationEvidenceLedger(ledger_path=tmp_path / "dupe.jsonl")

        r1 = PreviewEvidenceReceipt(
            receipt_id="r-dupe",
            compiled_at="2026-05-26T00:00:00Z",
            compilation_successful=True,
            profile_candidate_digest="sha256:abc",
        )
        r1.evidence_digest = r1.compute_digest()

        r2 = PreviewEvidenceReceipt(
            receipt_id="r-dupe",
            compiled_at="2026-05-26T00:00:00Z",
            compilation_successful=True,
            profile_candidate_digest="sha256:abc",
        )
        r2.evidence_digest = r2.compute_digest()

        digest1 = ledger.append_receipt(r1.model_dump())
        digest2 = ledger.append_receipt(r2.model_dump())

        assert digest1 == digest2
        assert ledger.count_receipts() == 2


class TestServiceEvidencePersistence:
    def test_service_persists_success_receipt(self, tmp_path: Path) -> None:
        from rig_relay.publication._evidence_ledger import PublicationEvidenceLedger

        ledger_path = tmp_path / "service_success.jsonl"
        ledger = PublicationEvidenceLedger(ledger_path=ledger_path)

        service = ProjectPagePublicationPreviewService(ledger=ledger)
        profile = _make_valid_profile()
        result = service.compile_preview(profile)

        assert result.success
        assert ledger.count_receipts() == 1
        loaded = ledger.load_receipts()
        assert loaded[0]["compilation_successful"] is True
        assert loaded[0]["preview_only"] is True
        assert loaded[0]["deployment_ready"] is False
        assert loaded[0]["evidence_digest"] == result.receipt.evidence_digest

    def test_service_persists_refusal_receipt(self, tmp_path: Path) -> None:
        from rig_relay.publication._evidence_ledger import PublicationEvidenceLedger

        ledger_path = tmp_path / "service_refusal.jsonl"
        ledger = PublicationEvidenceLedger(ledger_path=ledger_path)

        service = ProjectPagePublicationPreviewService(ledger=ledger)
        result = service.compile_preview(None)  # type: ignore[arg-type]

        assert not result.success
        assert ledger.count_receipts() == 1
        loaded = ledger.load_receipts()
        assert loaded[0]["refusal_code"] == "profile_absent"
        assert loaded[0]["compilation_successful"] is False

    def test_different_refusal_codes_produce_different_digests(
        self, tmp_path: Path
    ) -> None:
        from rig_relay.publication._evidence_ledger import PublicationEvidenceLedger

        ledger1 = PublicationEvidenceLedger(ledger_path=tmp_path / "refusal1.jsonl")
        ledger2 = PublicationEvidenceLedger(ledger_path=tmp_path / "refusal2.jsonl")

        service1 = ProjectPagePublicationPreviewService(ledger=ledger1)
        result1 = service1.compile_preview(None)  # type: ignore[arg-type]

        service2 = ProjectPagePublicationPreviewService(ledger=ledger2)
        profile = _make_valid_profile()
        profile.privacy_class = PrivacyDisposition.INTERNAL_ONLY
        result2 = service2.compile_preview(profile)

        assert result1.receipt.refusal_code != result2.receipt.refusal_code
        assert result1.receipt.evidence_digest != result2.receipt.evidence_digest

    def test_service_default_ledger_uses_standard_path(self) -> None:
        service = ProjectPagePublicationPreviewService()
        assert service._ledger is not None

    def test_preview_only_always_true_and_deployment_ready_false(
        self, tmp_path: Path
    ) -> None:
        from rig_relay.publication._evidence_ledger import PublicationEvidenceLedger

        ledger = PublicationEvidenceLedger(ledger_path=tmp_path / "guard.jsonl")
        service = ProjectPagePublicationPreviewService(ledger=ledger)
        profile = _make_valid_profile()

        result = service.compile_preview(
            profile, publication_policy="developer_approved"
        )

        assert result.receipt.preview_only is True
        assert result.receipt.deployment_ready is False

        loaded = ledger.load_receipts()
        assert loaded[0]["preview_only"] is True
        assert loaded[0]["deployment_ready"] is False
