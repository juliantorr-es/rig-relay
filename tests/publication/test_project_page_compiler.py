from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from rig_relay.publication import (
    ProjectPageCompilerInput,
    ProjectPageCompilerResult,
    ProjectPagePreviewReport,
    ProjectPagePublicationCompiler,
    ProjectPagePublicationProjection,
    PublicationSafetyReport,
    redact_unsafe_text,
    scan_project_page_output,
    validate_publication_policy,
)
from rig_relay.publication._safety import (
    scan_for_raw_paths,
    scan_text_for_secrets,
    scan_dict_for_forbidden_fields,
)
from rig_relay.publication._preview import build_preview_report


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
            released_boundaries={"boundaries": []},
            mission_timeline={"entries": []},
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
            released_boundaries={"boundaries": []},
            mission_timeline={"entries": []},
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
        assert projection.project_identity["tagline"] == "A test project"
        assert projection.status_overview["overall_status"] == "alpha"
        assert projection.status_overview["evidence_backed"] is True
        assert projection.accomplishments["get_item_list"][0]["title"] == "Core engine"
        assert len(projection.released_boundaries["get_boundary_list"]) == 1
        assert len(projection.mission_timeline["get_entry_list"]) == 1
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
                    },
                    {
                        "fact_id": "f2",
                        "category": "test_framework",
                        "value": "pytest",
                        "confidence": "high",
                    },
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
                        },
                        {"title": "Safety enforcement", "receipt_ref": "sha256:ghi789"},
                    ],
                    "total_receipts_referenced": 2,
                },
                "released_boundaries": [
                    {
                        "boundary_name": "L0 context assembly",
                        "release_status": "proven",
                        "consuming_surfaces": ["publication"],
                    },
                    {
                        "boundary_name": "R0 project page",
                        "release_status": "proven",
                        "consuming_surfaces": ["frontend"],
                    },
                ],
                "mission_timeline": [
                    {
                        "mission_id": "lane-l0",
                        "title": "Context Assembly",
                        "status": "proven",
                        "completed_at": "2026-05-20T00:00:00Z",
                    },
                    {
                        "mission_id": "lane-r0",
                        "title": "Project Page Compiler",
                        "status": "proven",
                        "completed_at": "2026-05-26T00:00:00Z",
                    },
                ],
                "architecture_overview": {
                    "subsystems": "compiler, safety, preview, templates",
                    "protocol_surfaces": "publication_projection.v1",
                },
                "generated_narrative_sections": {
                    "project_description": {
                        "narrative": "This project compiles public-safe project pages from evidence-backed profile candidates.",
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
                "suggested_next_action": "Configure GitHub Pages when ready",
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
            assert "Testing the full pipeline" in html_content
            assert "PREVIEW ONLY" in html_content
            assert "proposed" in html_content.lower()
            assert "Project page compiler" in html_content
            assert "project_page.css" in html_content

            nojekyll = output_dir / ".nojekyll"
            assert nojekyll.exists()

            css_file = output_dir / "project_page.css"
            assert css_file.exists()

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
        assert result.preview_report is not None

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
        assert report.proposed_content.requires_developer_review


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
            released_boundaries={"boundaries": []},
            mission_timeline={"entries": []},
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
            released_boundaries={"boundaries": []},
            mission_timeline={"entries": []},
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
            released_boundaries={"boundaries": []},
            mission_timeline={"entries": []},
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
