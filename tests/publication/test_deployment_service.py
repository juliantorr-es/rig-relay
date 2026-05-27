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
    DeploymentEvidenceLedger,
    DeploymentOutcomeReceipt,
    DeploymentPreparationResult,
    DeploymentRefusalCode,
    DeploymentStatus,
    GitHubPagesDeploymentService,
    PortfolioProjectionRejection,
    PortfolioSynthesisInput,
    PortfolioSynthesisResult,
    PortfolioSynthesisService,
    ProjectPagePublicationPreviewService,
)
from rig_relay.publication._deployment_models import _now_iso


def _make_valid_profile(
    candidate_id: str = "cand-deploy",
    project_name: str = "Deploy Test",
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED,
) -> PublishableProjectProfileCandidate:
    return PublishableProjectProfileCandidate(
        candidate_id=candidate_id,
        project_identity=ProjectPageIdentity(
            project_name=project_name,
            tagline="A deploy test project",
            current_milestone="alpha",
            product_identity_blurb="For deployment testing.",
        ),
        structural_facts_public=[
            PublicStructuralFact(
                fact_id="f1", category="language", value="Python", confidence="high"
            )
        ],
        technology_capabilities=TechnologySignals(
            languages=["Python"], frameworks=["FastAPI"], test_frameworks=["pytest"]
        ),
        status_overview=StatusOverview(
            overall_status="alpha",
            implemented_count=5,
            planned_count=3,
            evidence_backed=True,
        ),
        accomplishments=Accomplishments(
            items=[AccomplishmentItem(title="Core engine", receipt_ref="sha256:abc")],
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
        architecture_overview={"subsystems": "compiler"},
        generated_narrative_sections={
            "project_description": GeneratedNarrative(
                narrative="A test project for deployment.",
                approval_status=ApprovalStatus.APPROVED,
                basis_fact_ids=["f1"],
            )
        },
        approval_status=approval_status,
        redaction_log=RedactionLog(items_withheld=0, items_redacted=0, reasons=[]),
        privacy_class=PrivacyDisposition.PUBLIC_SAFE,
        content_light_guarantee=True,
    )


def _compile_valid_preview(
    profile: PublishableProjectProfileCandidate | None = None,
) -> object:
    """Compile a valid preview using the existing preview service + compiler."""
    import tempfile

    prof = profile or _make_valid_profile()
    service = ProjectPagePublicationPreviewService()
    output_dir = tempfile.mkdtemp()
    result = service.compile_preview(
        prof,
        publication_policy="developer_approved",
        repo_owner="test-owner",
        repo_name="test-repo",
        narrative_approvals={"project_description": "approved"},
        output_dir=Path(output_dir),
    )
    return result


# ═══════════════════════════════════════════════════════════════════════
# Deployment Models Tests
# ═══════════════════════════════════════════════════════════════════════


class TestDeploymentModels:
    def test_deployment_outcome_receipt_digest(self) -> None:
        receipt = DeploymentOutcomeReceipt(
            receipt_id="r-test",
            operation_id="op-test",
            profile_candidate_digest="sha256:abc",
            preview_evidence_digest="sha256:def",
            deployment_status=DeploymentStatus.DEPLOYED.value,
            evidence_digest="",
        )
        digest = receipt.compute_digest()
        assert digest.startswith("sha256:")
        assert receipt.evidence_digest == ""

    def test_deployment_outcome_receipt_refusal(self) -> None:
        receipt = DeploymentOutcomeReceipt(
            receipt_id="r-refused",
            operation_id="op-refuse",
            profile_candidate_digest="sha256:abc",
            preview_evidence_digest="sha256:def",
            deployment_status=DeploymentStatus.REFUSED.value,
            refusal_code=DeploymentRefusalCode.AUTHORIZATION_MISSING.value,
            refusal_reasons=["No authorization provided"],
            recovery_hint="Retry with valid authorization",
            evidence_digest="",
        )
        digest = receipt.compute_digest()
        assert digest.startswith("sha256:")
        assert receipt.refusal_code == "authorization_missing"

    def test_deployment_preparation_digest(self) -> None:
        prep = DeploymentPreparationResult(
            preparation_id="prep-1",
            operation_id="op-1",
            ready_to_deploy=True,
            compilation_valid=True,
            safety_valid=True,
            preview_evidence_valid=True,
            content_digest="sha256:content",
            pages_ready=True,
            pages_target_repo="owner/repo",
            static_content_available=True,
            static_content_digest="sha256:static",
            authorization_required=True,
        )
        digest = prep.compute_digest()
        assert digest.startswith("sha256:")
        assert prep.evidence_digest == digest

    def test_deployment_preparation_not_ready(self) -> None:
        prep = DeploymentPreparationResult(
            preparation_id="prep-2",
            operation_id="op-2",
            ready_to_deploy=False,
            compilation_valid=False,
            safety_valid=False,
            preview_evidence_valid=False,
            content_digest="",
            pages_ready=False,
            pages_target_repo="",
            static_content_available=False,
            static_content_digest="",
            authorization_required=True,
            blockers=["Compilation was not successful", "Safety scan did not pass"],
        )
        assert not prep.ready_to_deploy
        assert len(prep.blockers) == 2

    def test_deployment_status_enum_values(self) -> None:
        assert DeploymentStatus.PREPARING.value == "preparing"
        assert DeploymentStatus.DEPLOYED.value == "deployed"
        assert DeploymentStatus.REFUSED.value == "refused"
        assert DeploymentStatus.VERIFIED.value == "verified"
        assert DeploymentStatus.RECOVERY_REQUIRED.value == "recovery_required"

    def test_refusal_code_enum_values(self) -> None:
        assert (
            DeploymentRefusalCode.PREVIEW_NOT_APPROVED.value == "preview_not_approved"
        )
        assert (
            DeploymentRefusalCode.AUTHORIZATION_MISSING.value == "authorization_missing"
        )
        assert (
            DeploymentRefusalCode.REMOTE_VERIFICATION_FAILED.value
            == "remote_verification_failed"
        )


# ═══════════════════════════════════════════════════════════════════════
# Deployment Evidence Ledger Tests
# ═══════════════════════════════════════════════════════════════════════


class TestDeploymentEvidenceLedger:
    def test_append_and_count(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "deploy_evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=path)

            receipt = DeploymentOutcomeReceipt(
                receipt_id="r-1",
                operation_id="op-1",
                profile_candidate_digest="sha256:a",
                preview_evidence_digest="sha256:b",
                compilation_result_digest="sha256:c",
                deployment_status=DeploymentStatus.DEPLOYED.value,
                pages_site_url="https://owner.github.io/repo",
                pages_build_status="built",
                remote_request_sent=True,
                remote_verified=True,
                evidence_digest="",
            )
            receipt.evidence_digest = receipt.compute_digest()
            event_digest = ledger.append_event("op-1", receipt)
            assert event_digest.startswith("sha256:")
            assert ledger.count_events() == 1

    def test_dedup_same_operation(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "deploy_dedup.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=path)

            receipt = DeploymentOutcomeReceipt(
                receipt_id="r-dedup",
                operation_id="op-dedup",
                profile_candidate_digest="sha256:a",
                preview_evidence_digest="sha256:b",
                deployment_status=DeploymentStatus.DEPLOYED.value,
                evidence_digest="",
            )
            receipt.evidence_digest = receipt.compute_digest()
            first = ledger.append_event("op-dedup", receipt)
            second = ledger.append_event("op-dedup", receipt)
            assert first == second
            assert ledger.count_events() == 1

    def test_conflict_different_content(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "deploy_conflict.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=path)

            r1 = DeploymentOutcomeReceipt(
                receipt_id="r-c1",
                operation_id="op-conflict",
                profile_candidate_digest="sha256:a",
                preview_evidence_digest="sha256:b",
                deployment_status=DeploymentStatus.DEPLOYED.value,
                evidence_digest="",
            )
            r1.evidence_digest = r1.compute_digest()
            ledger.append_event("op-conflict", r1)

            r2 = DeploymentOutcomeReceipt(
                receipt_id="r-c2",
                operation_id="op-conflict",
                profile_candidate_digest="sha256:x",
                preview_evidence_digest="sha256:y",
                deployment_status=DeploymentStatus.REFUSED.value,
                evidence_digest="",
            )
            r2.evidence_digest = r2.compute_digest()
            with pytest.raises(RuntimeError, match="idempotency conflict"):
                ledger.append_event("op-conflict", r2)


# ═══════════════════════════════════════════════════════════════════════
# Deployment Service Tests
# ═══════════════════════════════════════════════════════════════════════


class TestDeploymentService:
    def test_prepare_with_valid_compilation(self) -> None:
        preview = _compile_valid_preview()
        compiler_result = preview.compiler_result
        service = GitHubPagesDeploymentService()
        prep = service.prepare_deployment(
            compiler_result,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
            preview_evidence_digest=compiler_result.preview_report.report_id,
            publication_policy="public_release",
        )
        assert prep.compilation_valid is True
        assert prep.safety_valid is True
        assert prep.authorization_required is True
        assert prep.pages_requires_configure is True
        assert prep.evidence_digest.startswith("sha256:")

    def test_prepare_refuses_failed_compilation(self) -> None:
        from rig_relay.publication._models import (
            ProjectPageCompilerResult,
            ProjectPagePreviewReport,
            ProjectPagePublicationProjection,
            PublicationSafetyReport,
        )

        service = GitHubPagesDeploymentService()
        bad_result = ProjectPageCompilerResult(
            result_id="bad-result",
            compiler_digest="sha256:bad",
            generated_at=_now_iso(),
            projection=ProjectPagePublicationProjection(
                projection_id="bad-proj",
                projection_digest="sha256:bad",
                generated_at=_now_iso(),
                project_identity={"project_name": "Bad"},
                status_overview={
                    "implemented_count": 0,
                    "planned_count": 0,
                    "overall_status": "failed",
                },
                accomplishments={},
                released_boundaries={},
                mission_timeline={},
            ),
            preview_report=ProjectPagePreviewReport(
                report_id="bad-preview",
                projection_id="bad-proj",
                generated_at=_now_iso(),
            ),
            safety_report=PublicationSafetyReport(
                passed=False, scan_id="bad-scan", scanned_at=_now_iso()
            ),
            compilation_successful=False,
            warnings=["Compilation failed"],
        )
        prep = service.prepare_deployment(
            bad_result,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
            preview_evidence_digest="sha256:bad",
            publication_policy="public_release",
        )
        assert not prep.ready_to_deploy
        assert not prep.compilation_valid
        assert not prep.safety_valid
        assert len(prep.blockers) > 0

    def test_prepare_refuses_unsafe_policy(self) -> None:
        preview = _compile_valid_preview()
        service = GitHubPagesDeploymentService()
        prep = service.prepare_deployment(
            preview.compiler_result,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
            preview_evidence_digest=preview.compiler_result.preview_report.report_id,
            publication_policy="preview_only",
        )
        assert not prep.ready_to_deploy
        assert any("preview_only" in b for b in prep.blockers)

    def test_prepare_requires_target_repo(self) -> None:
        preview = _compile_valid_preview()
        service = GitHubPagesDeploymentService()
        prep = service.prepare_deployment(
            preview.compiler_result,
            target_repo_owner="",
            target_repo_name="",
            preview_evidence_digest=preview.compiler_result.preview_report.report_id,
            publication_policy="public_release",
        )
        assert not prep.ready_to_deploy
        assert any("owner" in b.lower() for b in prep.blockers)

    def test_execute_refuses_without_authorization(self) -> None:
        preview = _compile_valid_preview()
        service = GitHubPagesDeploymentService()
        prep = service.prepare_deployment(
            preview.compiler_result,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
            preview_evidence_digest=preview.compiler_result.preview_report.report_id,
            publication_policy="public_release",
        )
        result = service.execute_deployment(
            preview.compiler_result,
            prep,
            authorization_receipt_id="",
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )
        assert result.deployment_status == DeploymentStatus.REFUSED.value
        assert result.refusal_code == DeploymentRefusalCode.AUTHORIZATION_MISSING.value

    def test_execute_refuses_not_ready_preparation(self) -> None:
        preview = _compile_valid_preview()
        service = GitHubPagesDeploymentService()
        prep = DeploymentPreparationResult(
            preparation_id="not-ready",
            operation_id="op-nr",
            ready_to_deploy=False,
            authorization_required=True,
            blockers=["Compilation was not successful"],
        )
        result = service.execute_deployment(
            preview.compiler_result,
            prep,
            authorization_receipt_id="some-auth-id",
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )
        assert result.deployment_status == DeploymentStatus.REFUSED.value
        assert result.refusal_code == DeploymentRefusalCode.COMPILATION_FAILED.value

    def test_outcome_receipt_evidence_persisted(self) -> None:
        preview = _compile_valid_preview()
        with tempfile.TemporaryDirectory() as d:
            ledger = DeploymentEvidenceLedger(ledger_path=Path(d) / "evidence.jsonl")
            service = GitHubPagesDeploymentService(ledger=ledger)
            prep = service.prepare_deployment(
                preview.compiler_result,
                target_repo_owner="test-owner",
                target_repo_name="test-repo",
                preview_evidence_digest=preview.compiler_result.preview_report.report_id,
                publication_policy="public_release",
            )
            result = service.execute_deployment(
                preview.compiler_result,
                prep,
                authorization_receipt_id="",
                target_repo_owner="test-owner",
                target_repo_name="test-repo",
            )
            assert ledger.count_events() >= 1
            assert result.evidence_digest.startswith("sha256:")

    def test_compute_recovery_state_verified(self) -> None:
        receipt = DeploymentOutcomeReceipt(
            receipt_id="r-verified",
            operation_id="op-v",
            profile_candidate_digest="sha256:a",
            preview_evidence_digest="sha256:b",
            compilation_result_digest="sha256:c",
            authorization_receipt_digest="sha256:d",
            deployment_status=DeploymentStatus.VERIFIED.value,
            pages_site_url="https://owner.github.io/repo",
            pages_build_status="built",
            remote_request_sent=True,
            remote_verified=True,
            evidence_digest="",
        )
        receipt.evidence_digest = receipt.compute_digest()
        service = GitHubPagesDeploymentService()
        recovery = service.compute_recovery_state(receipt)
        assert recovery.recoverable is True
        assert recovery.recovery_action == "verify_only"

    def test_compute_recovery_state_failed(self) -> None:
        receipt = DeploymentOutcomeReceipt(
            receipt_id="r-failed",
            operation_id="op-f",
            profile_candidate_digest="sha256:a",
            preview_evidence_digest="sha256:b",
            deployment_status=DeploymentStatus.FAILED.value,
            remote_request_sent=True,
            remote_verified=False,
            evidence_digest="",
        )
        receipt.evidence_digest = receipt.compute_digest()
        service = GitHubPagesDeploymentService()
        recovery = service.compute_recovery_state(receipt)
        assert recovery.recoverable is True
        assert recovery.recovery_action in ("retry", "reauthorize")


# ═══════════════════════════════════════════════════════════════════════
# Portfolio Synthesis Tests
# ═══════════════════════════════════════════════════════════════════════


class TestPortfolioSynthesis:
    def test_synthesize_empty_input(self) -> None:
        service = PortfolioSynthesisService()
        s_input = PortfolioSynthesisInput(
            developer_display_name="Test Dev", approved_project_records=[]
        )
        result = service.synthesize(s_input)
        assert not result.compilation_successful
        assert result.total_project_records == 0
        assert result.included_count == 0
        assert result.rejected_count == 0
        assert result.content_light_guarantee is True
        assert result.privacy_class == "public_safe"

    def test_synthesize_with_valid_records(self) -> None:
        service = PortfolioSynthesisService()
        records = [
            {
                "schema_version": "rig.relay.publication_preview_receipt.v1",
                "receipt_id": "rec-1",
                "compilation_successful": True,
                "profile_candidate_digest": "sha256:proj1",
                "safety_passed": True,
                "privacy_class": "public_safe",
                "projection": {
                    "projection_digest": "sha256:proj1-digest",
                    "publication_surface": "project_page",
                    "project_identity": {
                        "project_name": "Alpha Project",
                        "tagline": "First project",
                        "current_milestone": "beta",
                    },
                    "status_overview": {
                        "overall_status": "beta",
                        "evidence_backed": True,
                    },
                },
            },
            {
                "schema_version": "rig.relay.publication_preview_receipt.v1",
                "receipt_id": "rec-2",
                "compilation_successful": True,
                "profile_candidate_digest": "sha256:proj2",
                "safety_passed": True,
                "privacy_class": "public_safe",
                "projection": {
                    "projection_digest": "sha256:proj2-digest",
                    "publication_surface": "project_page",
                    "project_identity": {
                        "project_name": "Beta Project",
                        "tagline": "Second project",
                        "current_milestone": "alpha",
                    },
                    "status_overview": {
                        "overall_status": "alpha",
                        "evidence_backed": True,
                    },
                },
            },
        ]
        s_input = PortfolioSynthesisInput(
            developer_display_name="Test Dev",
            developer_headline="Full Stack Developer",
            developer_bio="Building things.",
            approved_project_records=records,
        )
        result = service.synthesize(s_input)
        assert result.compilation_successful is True
        assert result.total_project_records == 2
        assert result.included_count == 2
        assert result.rejected_count == 0
        assert result.ready_for_deployment is True
        assert result.portfolio_projection["publication_surface"] == "portfolio_site"
        assert len(result.portfolio_projection["project_catalogue"]) == 2

    def test_synthesize_rejects_failed_compilation(self) -> None:
        service = PortfolioSynthesisService()
        records = [
            {
                "receipt_id": "rec-failed",
                "compilation_successful": False,
                "profile_candidate_digest": "sha256:badproj",
                "safety_passed": False,
            }
        ]
        s_input = PortfolioSynthesisInput(approved_project_records=records)
        result = service.synthesize(s_input)
        assert result.compilation_successful is False
        assert result.included_count == 0
        assert result.rejected_count == 1
        assert result.rejected_records[0].rejection_reason == "compilation_failed"

    def test_synthesize_rejects_unsafe_privacy(self) -> None:
        service = PortfolioSynthesisService()
        records = [
            {
                "receipt_id": "rec-unsafe",
                "compilation_successful": True,
                "profile_candidate_digest": "sha256:unsafe",
                "safety_passed": True,
                "privacy_class": "internal_only",
                "projection": {
                    "project_identity": {"project_name": "Internal"},
                    "status_overview": {"overall_status": "internal"},
                },
            }
        ]
        s_input = PortfolioSynthesisInput(approved_project_records=records)
        result = service.synthesize(s_input)
        assert result.rejected_count == 1
        assert result.rejected_records[0].rejection_reason == "privacy_class_unsafe"

    def test_synthesize_mixed_valid_and_invalid(self) -> None:
        service = PortfolioSynthesisService()
        records: list[dict] = [
            {
                "receipt_id": "rec-valid",
                "compilation_successful": True,
                "profile_candidate_digest": "sha256:valid",
                "safety_passed": True,
                "privacy_class": "public_safe",
                "projection": {
                    "projection_digest": "sha256:valid-digest",
                    "publication_surface": "project_page",
                    "project_identity": {
                        "project_name": "Good Project",
                        "tagline": "Works",
                    },
                    "status_overview": {
                        "overall_status": "stable",
                        "evidence_backed": True,
                    },
                },
            },
            {
                "receipt_id": "rec-invalid",
                "compilation_successful": False,
                "profile_candidate_digest": "sha256:invalid",
                "safety_passed": False,
            },
        ]
        s_input = PortfolioSynthesisInput(approved_project_records=records)
        result = service.synthesize(s_input)
        assert result.included_count == 1
        assert result.rejected_count == 1
        assert result.ready_for_deployment is True

    def test_synthesize_determinism(self) -> None:
        service = PortfolioSynthesisService()
        records = [
            {
                "receipt_id": "rec-det",
                "compilation_successful": True,
                "profile_candidate_digest": "sha256:det",
                "safety_passed": True,
                "privacy_class": "public_safe",
                "projection": {
                    "projection_digest": "sha256:det-digest",
                    "publication_surface": "project_page",
                    "project_identity": {
                        "project_name": "Determinism Test",
                        "tagline": "Same every time",
                    },
                    "status_overview": {
                        "overall_status": "alpha",
                        "evidence_backed": True,
                    },
                },
            }
        ]
        s_input = PortfolioSynthesisInput(approved_project_records=records)
        r1 = service.synthesize(s_input)
        r2 = service.synthesize(s_input)
        assert r1.included_count == r2.included_count
        assert r1.content_light_guarantee == r2.content_light_guarantee

    def test_synthesize_html_output(self) -> None:
        service = PortfolioSynthesisService()
        records = [
            {
                "receipt_id": "rec-html",
                "compilation_successful": True,
                "profile_candidate_digest": "sha256:html",
                "safety_passed": True,
                "privacy_class": "public_safe",
                "projection": {
                    "projection_digest": "sha256:html-digest",
                    "publication_surface": "project_page",
                    "project_identity": {
                        "project_name": "HTML Test",
                        "tagline": "Renders HTML",
                        "current_milestone": "alpha",
                    },
                    "status_overview": {
                        "overall_status": "alpha",
                        "evidence_backed": True,
                    },
                },
            }
        ]
        s_input = PortfolioSynthesisInput(
            developer_display_name="Dev Name",
            developer_headline="Headline",
            developer_bio="Bio text",
            approved_project_records=records,
        )
        result = service.synthesize(s_input)
        assert result.portfolio_html is not None
        assert "HTML Test" in result.portfolio_html
        assert "Dev Name" in result.portfolio_html
        assert "Headline" in result.portfolio_html
        assert result.portfolio_html_digest is None

    def test_synthesize_html_bundle_output(self) -> None:
        service = PortfolioSynthesisService()
        records = [
            {
                "receipt_id": "rec-bundle",
                "compilation_successful": True,
                "profile_candidate_digest": "sha256:bundle",
                "safety_passed": True,
                "privacy_class": "public_safe",
                "projection": {
                    "projection_digest": "sha256:bundle-digest",
                    "publication_surface": "project_page",
                    "project_identity": {
                        "project_name": "Bundle Test",
                        "tagline": "Renders to disk",
                    },
                    "status_overview": {
                        "overall_status": "alpha",
                        "evidence_backed": True,
                    },
                },
            }
        ]
        s_input = PortfolioSynthesisInput(approved_project_records=records)
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "portfolio"
            result = service.synthesize(s_input, output_dir=out_dir)
            assert result.portfolio_html_digest is not None
            assert result.portfolio_bundle_path is not None
            assert Path(result.portfolio_bundle_path).exists()
            content = Path(result.portfolio_bundle_path).read_text()
            assert "Bundle Test" in content


# ═══════════════════════════════════════════════════════════════════════
# Portfolio Models Tests
# ═══════════════════════════════════════════════════════════════════════


class TestPortfolioModels:
    def test_portfolio_rejection(self) -> None:
        rejection = PortfolioProjectionRejection(
            profile_candidate_digest="sha256:abc",
            compilation_receipt_digest="sha256:def",
            rejection_reason="compilation_failed",
            rejection_detail="Compilation was not successful",
        )
        assert rejection.rejection_reason == "compilation_failed"
        assert rejection.profile_candidate_digest == "sha256:abc"

    def test_portfolio_synthesis_input(self) -> None:
        s_input = PortfolioSynthesisInput(
            developer_display_name="Dev",
            approved_project_records=[{"receipt_id": "r1"}],
        )
        assert s_input.developer_display_name == "Dev"
        assert s_input.schema_version == "rig.relay.publication_portfolio_synthesis.v1"
        assert len(s_input.approved_project_records) == 1

    def test_portfolio_synthesis_result_digest(self) -> None:
        result = PortfolioSynthesisResult(
            synthesis_id="synth-1",
            generated_at=_now_iso(),
            compilation_successful=True,
            total_project_records=3,
            included_count=2,
            rejected_count=1,
            rejected_records=[
                PortfolioProjectionRejection(
                    profile_candidate_digest="sha256:x",
                    compilation_receipt_digest="sha256:y",
                    rejection_reason="compilation_failed",
                )
            ],
            portfolio_projection={"surface": "portfolio_site"},
            portfolio_html="<html>test</html>",
            portfolio_html_digest="sha256:html",
            ready_for_deployment=True,
        )
        digest = result.compute_digest()
        assert digest.startswith("sha256:")
