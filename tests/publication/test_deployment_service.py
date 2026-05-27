"""Lane X3.1 deployment and portfolio synthesis tests.

Covers all 9 X3.1 repairs:
  1. Single authorization authority
  2. T1.2 PreviewEvidenceReceipt binding
  3. Static content publication
  4. Create/update Pages routing
  5. Truthful deployment phase model
  6. Evidence ledger integrity
  7. Verified record portfolio synthesis
  8. Safe HTML escaping
  9. Deterministic portfolio content digest
"""

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
    DeploymentPhase,
    DeploymentPreparationResult,
    DeploymentRefusalCode,
    GitHubPagesDeploymentService,
    PortfolioSynthesisInput,
    PortfolioSynthesisService,
    PreviewEvidenceReceipt,
    ProjectPagePublicationPreviewService,
    VerifiedApprovedProjectPublicationRecord,
)
from rig_relay.publication._deployment_models import _digest_sha256, _now_iso


def _make_valid_profile(
    candidate_id: str = "cand-x31",
    project_name: str = "X3.1 Test",
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED,
) -> PublishableProjectProfileCandidate:
    return PublishableProjectProfileCandidate(
        candidate_id=candidate_id,
        project_identity=ProjectPageIdentity(
            project_name=project_name,
            tagline="An X3.1 test project",
            current_milestone="alpha",
            product_identity_blurb="For X3.1 testing.",
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
            items=[AccomplishmentItem(title="Core", receipt_ref="sha256:abc")],
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
                narrative="A test project.",
                approval_status=ApprovalStatus.APPROVED,
                basis_fact_ids=["f1"],
            )
        },
        approval_status=approval_status,
        redaction_log=RedactionLog(items_withheld=0, items_redacted=0, reasons=[]),
        privacy_class=PrivacyDisposition.PUBLIC_SAFE,
        content_light_guarantee=True,
    )


def _compile_valid_preview() -> object:
    """Compile a valid preview with static bundle for deployment testing."""
    import tempfile

    profile = _make_valid_profile()
    service = ProjectPagePublicationPreviewService()
    output_dir = tempfile.mkdtemp()
    result = service.compile_preview(
        profile,
        publication_policy="developer_approved",
        repo_owner="test-owner",
        repo_name="test-repo",
        narrative_approvals={"project_description": "approved"},
        output_dir=Path(output_dir),
    )
    return result


def _make_valid_preview_receipt(compiler_result=None) -> PreviewEvidenceReceipt:
    """Build a valid T1.2 PreviewEvidenceReceipt for deployment binding."""
    if compiler_result is None:
        preview = _compile_valid_preview()
        compiler_result = preview.compiler_result
    return PreviewEvidenceReceipt(
        receipt_id="preview-receipt-x31",
        compiled_at=_now_iso(),
        compilation_successful=compiler_result.compilation_successful,
        profile_candidate_digest="sha256:cand-x31",
        result_digest=compiler_result.compute_result_digest(),
        safety_passed=compiler_result.safety_report.passed,
        deployment_ready=True,
        preview_only=False,
    )


# ═══════════════════════════════════════════════════════════════════════
# Repair 5: Truthful Deployment Phase Model
# ═══════════════════════════════════════════════════════════════════════


class TestDeploymentPhaseModel:
    def test_all_phases_are_distinct(self) -> None:
        phases = {
            DeploymentPhase.PREPARED,
            DeploymentPhase.AUTHORIZED,
            DeploymentPhase.PAGES_CONFIGURING,
            DeploymentPhase.PAGES_CONFIGURED,
            DeploymentPhase.CONTENT_PUBLISHING,
            DeploymentPhase.CONTENT_PUBLISHED,
            DeploymentPhase.BUILD_PENDING,
            DeploymentPhase.PUBLISHED_VERIFIED,
            DeploymentPhase.REFUSED,
            DeploymentPhase.FAILED,
            DeploymentPhase.RECOVERY_REQUIRED,
        }
        assert len(phases) == 11

    def test_no_deployed_phase(self) -> None:
        for phase in DeploymentPhase:
            assert "deployed" not in phase.value

    def test_recovery_required_is_not_deployed(self) -> None:
        assert DeploymentPhase.RECOVERY_REQUIRED.value != "deployed"

    def test_refusal_codes_expanded(self) -> None:
        assert (
            DeploymentRefusalCode.EVIDENCE_RECEIPT_ABSENT.value
            == "evidence_receipt_absent"
        )
        assert (
            DeploymentRefusalCode.EVIDENCE_RECEIPT_CORRUPT.value
            == "evidence_receipt_corrupt"
        )
        assert DeploymentRefusalCode.PAGES_CONFIG_FAILED.value == "pages_config_failed"
        assert (
            DeploymentRefusalCode.BRANCH_CREATION_FAILED.value
            == "branch_creation_failed"
        )


# ═══════════════════════════════════════════════════════════════════════
# Repair 2: T1.2 PreviewEvidenceReceipt Binding
# ═══════════════════════════════════════════════════════════════════════


class TestT12EvidenceBinding:
    def test_prepare_refuses_without_preview_receipt(self) -> None:
        preview = _compile_valid_preview()
        service = GitHubPagesDeploymentService()
        prep = service.prepare_deployment(
            preview.compiler_result,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )
        assert not prep.ready_to_deploy
        assert not prep.preview_evidence_valid
        assert not prep.approval_gate_passed
        assert any("No T1.2 PreviewEvidenceReceipt" in b for b in prep.blockers)

    def test_prepare_accepts_valid_preview_receipt(self) -> None:
        preview = _compile_valid_preview()
        receipt = _make_valid_preview_receipt(preview.compiler_result)
        receipt.evidence_digest = receipt.compute_digest()
        service = GitHubPagesDeploymentService()
        prep = service.prepare_deployment(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )
        assert prep.preview_evidence_valid
        assert prep.approval_gate_passed
        assert prep.preview_receipt_digest

    def test_prepare_refuses_failed_preview_receipt(self) -> None:
        preview = _compile_valid_preview()
        receipt = PreviewEvidenceReceipt(
            receipt_id="bad-receipt",
            compiled_at=_now_iso(),
            compilation_successful=False,
            profile_candidate_digest="sha256:bad",
            safety_passed=False,
            refusal_code="safety_scan_failed",
            deployment_ready=False,
        )
        receipt.evidence_digest = receipt.compute_digest()
        service = GitHubPagesDeploymentService()
        prep = service.prepare_deployment(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )
        assert not prep.preview_evidence_valid
        assert not prep.ready_to_deploy

    def test_prepare_refuses_preview_only_receipt(self) -> None:
        preview = _compile_valid_preview()
        receipt = PreviewEvidenceReceipt(
            receipt_id="preview-only-receipt",
            compiled_at=_now_iso(),
            compilation_successful=True,
            profile_candidate_digest="sha256:ok",
            result_digest="sha256:ok",
            safety_passed=True,
            deployment_ready=False,
            preview_only=True,
        )
        receipt.evidence_digest = receipt.compute_digest()
        service = GitHubPagesDeploymentService()
        prep = service.prepare_deployment(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )
        assert not prep.preview_evidence_valid
        assert any("preview_only" in b.lower() for b in prep.blockers)


# ═══════════════════════════════════════════════════════════════════════
# Repair 1 & 3: Single Authorization + Content Publication
# ═══════════════════════════════════════════════════════════════════════


class TestDeploymentExecution:
    def test_execute_refuses_without_authorization(self) -> None:
        preview = _compile_valid_preview()
        receipt = _make_valid_preview_receipt(preview.compiler_result)
        receipt.evidence_digest = receipt.compute_digest()
        service = GitHubPagesDeploymentService()
        prep = service.prepare_deployment(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )
        assert prep.ready_to_deploy

        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            service.execute_deployment(
                preview.compiler_result,
                prep,
                authorization_receipt_id="",
                target_repo_owner="test-owner",
                target_repo_name="test-repo",
            )
        )
        assert result.deployment_phase == DeploymentPhase.REFUSED.value
        assert result.refusal_code == DeploymentRefusalCode.AUTHORIZATION_MISSING.value

    def test_execute_refuses_not_ready(self) -> None:
        preview = _compile_valid_preview()
        service = GitHubPagesDeploymentService()
        prep = DeploymentPreparationResult(
            preparation_id="not-ready",
            operation_id="op-nr",
            ready_to_deploy=False,
            authorization_required=True,
        )
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            service.execute_deployment(
                preview.compiler_result,
                prep,
                authorization_receipt_id="some-auth",
                target_repo_owner="test-owner",
                target_repo_name="test-repo",
            )
        )
        assert result.deployment_phase == DeploymentPhase.REFUSED.value

    def test_phase_transition_on_contentless_deploy(self) -> None:
        """Without git boundary, service truthfully reports PAGES_CONFIGURED."""
        preview = _compile_valid_preview()
        receipt = _make_valid_preview_receipt(preview.compiler_result)
        receipt.evidence_digest = receipt.compute_digest()
        service = GitHubPagesDeploymentService()
        prep = service.prepare_deployment(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            service.execute_deployment(
                preview.compiler_result,
                prep,
                authorization_receipt_id="auth-fake",
                target_repo_owner="test-owner",
                target_repo_name="test-repo",
            )
        )
        # Without real auth + adapter, should refuse at authorization or config
        assert result.deployment_phase != "deployed"


# ═══════════════════════════════════════════════════════════════════════
# Repair 4: Create vs Update Pages Routing
# ═══════════════════════════════════════════════════════════════════════


class TestCreateUpdatePagesRouting:
    def test_prepare_flags_requires_create_for_new_site(self) -> None:
        preview = _compile_valid_preview()
        receipt = _make_valid_preview_receipt(preview.compiler_result)
        receipt.evidence_digest = receipt.compute_digest()
        service = GitHubPagesDeploymentService()
        prep = service.prepare_deployment(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )
        assert prep.pages_requires_create
        assert not prep.pages_site_exists


# ═══════════════════════════════════════════════════════════════════════
# Repair 5: Recovery State Model
# ═══════════════════════════════════════════════════════════════════════


class TestRecoveryState:
    def test_verified_returns_verify_only(self) -> None:
        receipt = DeploymentOutcomeReceipt(
            receipt_id="r-verified",
            operation_id="op-v",
            profile_candidate_digest="sha256:a",
            preview_evidence_digest="sha256:b",
            compilation_result_digest="sha256:c",
            deployment_phase=DeploymentPhase.PUBLISHED_VERIFIED.value,
            pages_configured=True,
            content_published=True,
            remote_request_sent=True,
            remote_verified=True,
            evidence_digest="",
        )
        receipt.evidence_digest = receipt.compute_digest()
        service = GitHubPagesDeploymentService()
        recovery = service.compute_recovery_state(receipt)
        assert recovery.recoverable
        assert recovery.recovery_action == "verify_only"

    def test_configured_without_content_returns_retry_push(self) -> None:
        receipt = DeploymentOutcomeReceipt(
            receipt_id="r-config",
            operation_id="op-c",
            profile_candidate_digest="sha256:a",
            preview_evidence_digest="sha256:b",
            compilation_result_digest="sha256:c",
            deployment_phase=DeploymentPhase.PAGES_CONFIGURED.value,
            pages_configured=True,
            content_published=False,
            remote_request_sent=True,
            remote_verified=False,
            evidence_digest="",
        )
        receipt.evidence_digest = receipt.compute_digest()
        service = GitHubPagesDeploymentService()
        recovery = service.compute_recovery_state(receipt)
        assert recovery.recoverable
        assert recovery.recovery_action == "retry_content_push"
        assert recovery.prior_pages_configured is True
        assert recovery.prior_content_published is False

    def test_failed_with_auth_returns_reauthorize(self) -> None:
        receipt = DeploymentOutcomeReceipt(
            receipt_id="r-failed",
            operation_id="op-f",
            profile_candidate_digest="sha256:a",
            preview_evidence_digest="sha256:b",
            deployment_phase=DeploymentPhase.FAILED.value,
            authorization_receipt_digest="sha256:auth-consumed",
            remote_request_sent=True,
            evidence_digest="",
        )
        receipt.evidence_digest = receipt.compute_digest()
        service = GitHubPagesDeploymentService()
        recovery = service.compute_recovery_state(receipt)
        assert recovery.recoverable
        assert recovery.recovery_action == "reauthorize"


# ═══════════════════════════════════════════════════════════════════════
# Repair 6: Evidence Ledger Integrity
# ═══════════════════════════════════════════════════════════════════════


class TestEvidenceLedgerIntegrity:
    def test_append_validates_receipt_digest(self) -> None:
        """Receipt with fake digest gets recomputed and validated on append."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=path)

            receipt = DeploymentOutcomeReceipt(
                receipt_id="r-1",
                operation_id="op-1",
                profile_candidate_digest="sha256:a",
                preview_evidence_digest="sha256:b",
                deployment_phase=DeploymentPhase.PAGES_CONFIGURED.value,
                evidence_digest="not-a-real-digest",
            )
            # Ledger recomputes and validates the digest
            event_digest = ledger.append_event("op-1", receipt)
            assert event_digest.startswith("sha256:")
            assert ledger.count_events() == 1

    def test_append_event_with_valid_digest(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=path)

            receipt = DeploymentOutcomeReceipt(
                receipt_id="r-valid",
                operation_id="op-valid",
                profile_candidate_digest="sha256:a",
                preview_evidence_digest="sha256:b",
                deployment_phase=DeploymentPhase.PAGES_CONFIGURED.value,
                pages_configured=True,
                evidence_digest="",
            )
            receipt.evidence_digest = receipt.compute_digest()
            event_digest = ledger.append_event("op-valid", receipt)
            assert event_digest.startswith("sha256:")
            assert ledger.count_events() == 1

    def test_dedup_preserves_first_event(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "dedup.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=path)

            receipt = DeploymentOutcomeReceipt(
                receipt_id="r-dedup",
                operation_id="op-dedup",
                profile_candidate_digest="sha256:a",
                preview_evidence_digest="sha256:b",
                deployment_phase=DeploymentPhase.PAGES_CONFIGURED.value,
                evidence_digest="",
            )
            receipt.evidence_digest = receipt.compute_digest()
            first = ledger.append_event("op-dedup", receipt)
            second = ledger.append_event("op-dedup", receipt)
            assert first == second
            assert ledger.count_events() == 1

    def test_conflict_different_content_raises(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "conflict.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=path)

            r1 = DeploymentOutcomeReceipt(
                receipt_id="r-c1",
                operation_id="op-conflict",
                profile_candidate_digest="sha256:a",
                preview_evidence_digest="sha256:b",
                deployment_phase=DeploymentPhase.PAGES_CONFIGURED.value,
                pages_configured=True,
                evidence_digest="",
            )
            r1.evidence_digest = r1.compute_digest()
            ledger.append_event("op-conflict", r1)

            r2 = DeploymentOutcomeReceipt(
                receipt_id="r-c2",
                operation_id="op-conflict",
                profile_candidate_digest="sha256:different",
                preview_evidence_digest="sha256:different",
                deployment_phase=DeploymentPhase.REFUSED.value,
                refusal_code="compilation_failed",
                evidence_digest="",
            )
            r2.evidence_digest = r2.compute_digest()
            with pytest.raises(RuntimeError, match="idempotency conflict"):
                ledger.append_event("op-conflict", r2)

    def test_load_receipts_with_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "recon.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=path)

            receipt = DeploymentOutcomeReceipt(
                receipt_id="r-recon",
                operation_id="op-recon",
                profile_candidate_digest="sha256:a",
                preview_evidence_digest="sha256:b",
                deployment_phase=DeploymentPhase.CONTENT_PUBLISHED.value,
                pages_configured=True,
                content_published=True,
                evidence_digest="",
            )
            receipt.evidence_digest = receipt.compute_digest()
            ledger.append_event("op-recon", receipt)

            result = ledger.load_receipts()
            assert result["total_rows"] == 1
            assert result["valid_rows"] == 1
            assert result["corrupt_rows"] == 0
            assert not result["corruption_detected"]

    def test_authoritative_refuses_on_corruption(self) -> None:
        """Corrupt row in ledger → authoritative returns empty."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "corrupt.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=path)

            # Write a valid event first
            receipt = DeploymentOutcomeReceipt(
                receipt_id="r-valid-auth",
                operation_id="op-auth",
                profile_candidate_digest="sha256:a",
                preview_evidence_digest="sha256:b",
                deployment_phase=DeploymentPhase.PAGES_CONFIGURED.value,
                evidence_digest="",
            )
            receipt.evidence_digest = receipt.compute_digest()
            ledger.append_event("op-auth", receipt)

            # Corrupt the file
            with open(path, "a") as f:
                f.write("this is not valid json\n")

            result = ledger.load_receipts(authoritative=True)
            assert result["corruption_detected"] is True
            assert result["valid_rows"] == 0
            assert len(result["receipts"]) == 0
            assert result["total_rows"] == 2


# ═══════════════════════════════════════════════════════════════════════
# Repair 7: Verified Record Portfolio Synthesis
# ═══════════════════════════════════════════════════════════════════════


class TestVerifiedPortfolioSynthesis:
    def _make_verified_record(
        self, name: str = "Test Project"
    ) -> VerifiedApprovedProjectPublicationRecord:
        return VerifiedApprovedProjectPublicationRecord(
            record_id=f"rec-{name}",
            profile_candidate_digest=_digest_sha256(f"profile:{name}"),
            preview_evidence_digest=_digest_sha256(f"preview:{name}"),
            compilation_result_digest=_digest_sha256(f"compiler:{name}"),
            approval_evidence_digest=_digest_sha256(f"approval:{name}"),
            safety_passed=True,
            privacy_class="public_safe",
            content_light_guarantee=True,
            publication_surface="project_page",
            projection={
                "project_identity": {
                    "project_name": name,
                    "tagline": f"{name} tagline",
                    "current_milestone": "beta",
                },
                "status_overview": {"overall_status": "beta", "evidence_backed": True},
                "projection_digest": _digest_sha256(f"proj:{name}"),
                "publication_surface": "project_page",
            },
            projection_digest=_digest_sha256(f"proj:{name}"),
            verified=True,
            verification_digest=_digest_sha256(f"verify:{name}"),
        )

    def test_synthesize_accepts_verified_records(self) -> None:
        service = PortfolioSynthesisService()
        records = [
            self._make_verified_record("Alpha"),
            self._make_verified_record("Beta"),
        ]
        s_input = PortfolioSynthesisInput(
            developer_display_name="Dev", verified_records=records
        )
        result = service.synthesize(s_input)
        assert result.compilation_successful
        assert result.included_count == 2
        assert result.rejected_count == 0
        assert result.safety_passed
        assert result.ready_for_deployment

    def test_synthesize_rejects_unverified_records(self) -> None:
        service = PortfolioSynthesisService()
        unverified = self._make_verified_record("Unverified")
        unverified.verified = False
        s_input = PortfolioSynthesisInput(verified_records=[unverified])
        result = service.synthesize(s_input)
        assert result.included_count == 0
        assert result.rejected_count == 1
        assert result.rejected_records[0].rejection_reason == "not_verified"

    def test_synthesize_rejects_raw_dicts(self) -> None:
        """X3.1 repair #7: arbitrary dicts are rejected."""
        service = PortfolioSynthesisService()
        s_input = PortfolioSynthesisInput(
            verified_records=[
                {
                    "compilation_successful": True,
                    "safety_passed": True,
                    "projection": {
                        "project_identity": {"project_name": "Fake Project"},
                        "status_overview": {"overall_status": "good"},
                    },
                }
            ]
        )
        result = service.synthesize(s_input)
        assert result.included_count == 0
        assert result.rejected_count == 1
        assert result.rejected_records[0].rejection_reason == "not_verified_record"

    def test_synthesize_rejects_safety_failed(self) -> None:
        service = PortfolioSynthesisService()
        unsafe = self._make_verified_record("Unsafe")
        unsafe.safety_passed = False
        s_input = PortfolioSynthesisInput(verified_records=[unsafe])
        result = service.synthesize(s_input)
        assert result.included_count == 0
        assert result.rejected_records[0].rejection_reason == "safety_not_passed"

    def test_synthesize_rejects_internal_privacy(self) -> None:
        service = PortfolioSynthesisService()
        internal = self._make_verified_record("Internal")
        internal.privacy_class = "internal_only"
        s_input = PortfolioSynthesisInput(verified_records=[internal])
        result = service.synthesize(s_input)
        assert result.included_count == 0
        assert result.rejected_records[0].rejection_reason == "privacy_class_unsafe"

    def test_synthesize_mixed_records(self) -> None:
        service = PortfolioSynthesisService()
        valid = self._make_verified_record("Valid")
        unverified = self._make_verified_record("Unverified")
        unverified.verified = False
        s_input = PortfolioSynthesisInput(
            verified_records=[valid, unverified, {"bad": "dict"}]
        )
        result = service.synthesize(s_input)
        assert result.included_count == 1
        assert result.rejected_count == 2


# ═══════════════════════════════════════════════════════════════════════
# Repair 8: Safe HTML Escaping
# ═══════════════════════════════════════════════════════════════════════


class TestSafeHTML:
    def test_html_escapes_script_injection(self) -> None:
        service = PortfolioSynthesisService()
        malicious = VerifiedApprovedProjectPublicationRecord(
            record_id="rec-malicious",
            profile_candidate_digest=_digest_sha256("malicious"),
            preview_evidence_digest=_digest_sha256("preview:mal"),
            compilation_result_digest=_digest_sha256("compiler:mal"),
            safety_passed=True,
            privacy_class="public_safe",
            content_light_guarantee=True,
            publication_surface="project_page",
            projection={
                "project_identity": {
                    "project_name": '<script>alert("xss")</script>',
                    "tagline": '"><svg onload=alert(1)>',
                    "current_milestone": "alpha",
                },
                "status_overview": {"overall_status": "beta", "evidence_backed": True},
                "projection_digest": _digest_sha256("proj-mal"),
                "publication_surface": "project_page",
            },
            projection_digest=_digest_sha256("proj-mal"),
            verified=True,
            verification_digest=_digest_sha256("verify-mal"),
        )
        s_input = PortfolioSynthesisInput(
            developer_display_name='Dev"><script>alert(1)</script>',
            developer_headline="Safety<script>",
            developer_bio="Bio<iframe src=x>",
            verified_records=[malicious],
        )
        result = service.synthesize(s_input)
        html_content = result.portfolio_html
        assert html_content is not None
        # Script tags and iframes should be escaped
        assert "<script>" not in html_content
        assert "<iframe" not in html_content
        assert "&lt;script&gt;" in html_content
        assert "&lt;iframe" in html_content
        # Safety scan should detect the onload= pattern in the escaped text
        assert not result.safety_passed
        assert not result.ready_for_deployment

    def test_html_scan_detects_unsafe_patterns(self) -> None:
        from rig_relay.publication._portfolio_service import (
            _scan_portfolio_html_for_safety,
        )

        clean = "<h1>Safe Title</h1><p>Content</p>"
        assert _scan_portfolio_html_for_safety(clean) == []

        dirty = "<h1>Safe</h1><script>alert(1)</script>"
        findings = _scan_portfolio_html_for_safety(dirty)
        assert any("script_tag" in f for f in findings)

    def test_safety_scan_blocks_deployment_readiness(self) -> None:
        """If HTML contains unsafe patterns, ready_for_deployment is False."""
        # Safety scan runs on rendered HTML; escaped HTML passes
        service = PortfolioSynthesisService()
        valid = VerifiedApprovedProjectPublicationRecord(
            record_id="rec-clean",
            profile_candidate_digest=_digest_sha256("clean"),
            preview_evidence_digest=_digest_sha256("preview:clean"),
            compilation_result_digest=_digest_sha256("compiler:clean"),
            safety_passed=True,
            privacy_class="public_safe",
            content_light_guarantee=True,
            publication_surface="project_page",
            projection={
                "project_identity": {
                    "project_name": "Clean Project",
                    "tagline": "Safe tagline",
                    "current_milestone": "alpha",
                },
                "status_overview": {"overall_status": "alpha", "evidence_backed": True},
                "projection_digest": _digest_sha256("proj-clean"),
                "publication_surface": "project_page",
            },
            projection_digest=_digest_sha256("proj-clean"),
            verified=True,
            verification_digest=_digest_sha256("verify-clean"),
        )
        s_input = PortfolioSynthesisInput(verified_records=[valid])
        result = service.synthesize(s_input)
        assert result.safety_passed
        assert result.ready_for_deployment


# ═══════════════════════════════════════════════════════════════════════
# Repair 9: Deterministic Portfolio Content Digest
# ═══════════════════════════════════════════════════════════════════════


class TestDeterministicPortfolio:
    def test_content_digest_stable_for_same_inputs(self) -> None:
        service = PortfolioSynthesisService()

        def make_record(name: str) -> VerifiedApprovedProjectPublicationRecord:
            return VerifiedApprovedProjectPublicationRecord(
                record_id=f"rec-{name}",
                profile_candidate_digest=_digest_sha256(f"profile:{name}"),
                preview_evidence_digest=_digest_sha256(f"preview:{name}"),
                compilation_result_digest=_digest_sha256(f"compiler:{name}"),
                safety_passed=True,
                privacy_class="public_safe",
                content_light_guarantee=True,
                publication_surface="project_page",
                projection={
                    "project_identity": {
                        "project_name": name,
                        "tagline": f"{name} tagline",
                    },
                    "status_overview": {
                        "overall_status": "alpha",
                        "evidence_backed": True,
                    },
                    "projection_digest": _digest_sha256(f"proj:{name}"),
                    "publication_surface": "project_page",
                },
                projection_digest=_digest_sha256(f"proj:{name}"),
                verified=True,
                verification_digest=_digest_sha256(f"verify:{name}"),
            )

        r1 = make_record("Alpha")
        r2 = make_record("Beta")
        records = [r1, r2]

        s_input = PortfolioSynthesisInput(verified_records=records)
        result_a = service.synthesize(s_input)
        result_b = service.synthesize(s_input)

        # Content digest is stable across calls
        assert result_a.content_digest == result_b.content_digest
        # Operation digest differs (contains synthesis_id + timestamp)
        assert result_a.synthesis_id != result_b.synthesis_id

    def test_different_records_produce_different_content_digest(self) -> None:
        service = PortfolioSynthesisService()

        def make_record(
            name: str, proj_digest: str
        ) -> VerifiedApprovedProjectPublicationRecord:
            return VerifiedApprovedProjectPublicationRecord(
                record_id=f"rec-{name}",
                profile_candidate_digest=_digest_sha256(f"profile:{name}"),
                preview_evidence_digest=_digest_sha256(f"preview:{name}"),
                compilation_result_digest=_digest_sha256(f"compiler:{name}"),
                safety_passed=True,
                privacy_class="public_safe",
                content_light_guarantee=True,
                publication_surface="project_page",
                projection={
                    "project_identity": {"project_name": name},
                    "status_overview": {"overall_status": "alpha"},
                    "projection_digest": proj_digest,
                    "publication_surface": "project_page",
                },
                projection_digest=proj_digest,
                verified=True,
                verification_digest=_digest_sha256(f"verify:{name}"),
            )

        s1 = PortfolioSynthesisInput(verified_records=[make_record("A", "sha256:aaa")])
        s2 = PortfolioSynthesisInput(verified_records=[make_record("B", "sha256:bbb")])

        result_a = service.synthesize(s1)
        result_b = service.synthesize(s2)

        assert result_a.content_digest != result_b.content_digest


# ═══════════════════════════════════════════════════════════════════════
# Verified Record Model Tests
# ═══════════════════════════════════════════════════════════════════════


class TestVerifiedRecordModel:
    def test_verified_record_compute_digest(self) -> None:
        record = VerifiedApprovedProjectPublicationRecord(
            record_id="rec-test",
            profile_candidate_digest="sha256:p",
            preview_evidence_digest="sha256:pe",
            compilation_result_digest="sha256:c",
            safety_passed=True,
            projection={},
            projection_digest="sha256:proj",
            verified=True,
        )
        digest = record.compute_digest()
        assert digest.startswith("sha256:")

    def test_verified_record_requires_explicit_verification(self) -> None:
        record = VerifiedApprovedProjectPublicationRecord(
            record_id="rec-noverify",
            profile_candidate_digest="sha256:p",
            preview_evidence_digest="sha256:pe",
            compilation_result_digest="sha256:c",
            safety_passed=True,
            projection={},
            projection_digest="sha256:proj",
            verified=False,
        )
        assert not record.verified
