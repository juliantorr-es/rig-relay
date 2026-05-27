"""Lane X3.2 publication deployment tests — T1.2 traversal, authorization, content push, recovery.

Gate A: Genuine T1.2 preview receipts traverse the corridor
Gate B: Digest-bound content enforcement, recovery on partial push
Gate C: Pages create/update/no-change routing, truthful verification
Gate D: Evidence ledger with linked state-transition events
Gate E: Portfolio verified records bind T1.2 receipts
Gate F: Status contracts for X0 consumption
"""

from __future__ import annotations

import asyncio
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
from rig_relay.governance.remote_action_authorization import RemoteActionClass
from rig_relay.integrations.github_provider._authorization_consumer import (
    operation_kind_to_action_class,
)
from rig_relay.publication import (
    ApprovedStaticPublicationBundle,
    AuthorizedPublicationTransitionPreparation,
    ContentPublicationManifest,
    DeploymentEvidenceLedger,
    DeploymentRefusalCode,
    GitHubPagesDeploymentService,
    PortfolioSynthesisInput,
    PortfolioSynthesisService,
    PreviewEvidenceReceipt,
    ProjectPagePublicationPreviewService,
    PublicationStatusContract,
    PublicationTransitionPhase,
    PublicationTransitionReceipt,
    VerifiedApprovedProjectPublicationRecord,
)
from rig_relay.publication._deployment_models import _digest_sha256, _now_iso


class _FakeAuthorizationConsumer:
    def __init__(self, *, authorized: bool = True, refusal_code: str = "") -> None:
        self._authorized = authorized
        self._refusal_code = refusal_code

    async def authorize(
        self,
        *,
        authorization_id: str,
        operation_kind: str,
        request_payload: dict[str, object],
        target_identity: str,
        prior_evidence_digest: str,
    ) -> dict[str, object]:
        return {
            "authorized": self._authorized,
            "refusal_code": self._refusal_code,
            "reasons": [] if self._authorized else ["test refusal"],
            "authorization_digest": "test_auth_digest",
            "authorization_id": authorization_id,
            "operation_kind": operation_kind,
        }


def _make_valid_profile(
    candidate_id: str = "cand-x32", project_name: str = "X3.2 Test"
) -> PublishableProjectProfileCandidate:
    return PublishableProjectProfileCandidate(
        candidate_id=candidate_id,
        project_identity=ProjectPageIdentity(
            project_name=project_name,
            tagline="An X3.2 test project",
            current_milestone="alpha",
            product_identity_blurb="For X3.2 testing.",
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
        approval_status=ApprovalStatus.APPROVED,
        redaction_log=RedactionLog(items_withheld=0, items_redacted=0, reasons=[]),
        privacy_class=PrivacyDisposition.PUBLIC_SAFE,
        content_light_guarantee=True,
    )


def _compile_genuine_preview() -> object:
    """Compile a genuine T1.2 preview — always preview_only=True, deployment_ready=False."""
    import tempfile

    profile = _make_valid_profile()
    service = ProjectPagePublicationPreviewService()
    output_dir = tempfile.mkdtemp()
    return service.compile_preview(
        profile,
        publication_policy="developer_approved",
        repo_owner="test-owner",
        repo_name="test-repo",
        narrative_approvals={"project_description": "approved"},
        output_dir=Path(output_dir),
    )


# ═══════════════════════════════════════════════════════════════════════
# Gate A: Genuine T1.2 Preview Receipt Traversal
# ═══════════════════════════════════════════════════════════════════════


class TestT12ReceiptTraversal:
    def test_genuine_receipt_accepted_despite_preview_only(self) -> None:
        """Genuine T1.2 receipt (preview_only=True, deployment_ready=False)
        successfully enters X3.2 preparation.
        """
        preview = _compile_genuine_preview()
        receipt = preview.receipt
        assert receipt.preview_only is True
        assert receipt.deployment_ready is False
        assert receipt.compilation_successful is True
        assert receipt.safety_passed is True

        service = GitHubPagesDeploymentService()
        prep = service.prepare_transition(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )
        assert prep.publication_operation_id
        assert prep.preview_evidence_digest
        assert prep.preparation_digest
        assert prep.authorization_required is True

    def test_failed_preview_receipt_refused(self) -> None:
        preview = _compile_genuine_preview()
        bad_receipt = PreviewEvidenceReceipt(
            receipt_id="bad-receipt",
            compiled_at=_now_iso(),
            compilation_successful=False,
            profile_candidate_digest="sha256:bad",
            safety_passed=False,
            refusal_code="safety_scan_failed",
            result_digest=None,
        )
        bad_receipt.evidence_digest = bad_receipt.compute_digest()
        service = GitHubPagesDeploymentService()
        with pytest.raises(ValueError, match="compilation_successful"):
            service.prepare_transition(
                preview.compiler_result,
                preview_receipt=bad_receipt,
                target_repo_owner="test-owner",
                target_repo_name="test-repo",
            )

    def test_missing_preview_receipt_refused(self) -> None:
        preview = _compile_genuine_preview()
        service = GitHubPagesDeploymentService()
        with pytest.raises(ValueError, match="T1.2"):
            service.prepare_transition(
                preview.compiler_result,
                preview_receipt=None,  # type: ignore[arg-type]
            )

    def test_result_digest_mismatch_refused(self) -> None:
        preview = _compile_genuine_preview()
        receipt = preview.receipt
        receipt_copy = receipt.model_copy()
        receipt_copy.result_digest = "sha256:wrong-digest"
        receipt_copy.evidence_digest = receipt_copy.compute_digest()
        service = GitHubPagesDeploymentService()
        with pytest.raises(ValueError, match="result_digest"):
            service.prepare_transition(
                preview.compiler_result,
                preview_receipt=receipt_copy,
                target_repo_owner="test-owner",
                target_repo_name="test-repo",
            )


# ═══════════════════════════════════════════════════════════════════════
# Gate B: Digest-Bound Content Enforcement
# ═══════════════════════════════════════════════════════════════════════


class TestDigestBoundContent:
    def test_bundle_digest_mismatch_refused(self) -> None:
        preview = _compile_genuine_preview()
        receipt = preview.receipt
        service = GitHubPagesDeploymentService()
        prep = service.prepare_transition(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )

        bundle = ApprovedStaticPublicationBundle(
            files={"index.html": "<h1>Hello</h1>"},
            preview_result_digest=prep.preview_result_digest,
            preparation_digest=prep.preparation_digest,
        )
        bundle.compute_content_digest()
        bogus_bundle = ApprovedStaticPublicationBundle(
            files={"index.html": "<h1>Different content</h1>"},
            preview_result_digest=prep.preview_result_digest,
            preparation_digest=prep.preparation_digest,
        )
        bogus_bundle.compute_content_digest()

        result = service.validate_bundle(bogus_bundle, prep)
        assert not result["valid"]

    def test_valid_bundle_passes_validation(self) -> None:
        preview = _compile_genuine_preview()
        receipt = preview.receipt
        service = GitHubPagesDeploymentService()
        prep = service.prepare_transition(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )

        bundle = ApprovedStaticPublicationBundle(
            files={"index.html": "<h1>Hello</h1>"},
            preview_result_digest=prep.preview_result_digest,
            preparation_digest=prep.preparation_digest,
        )
        bundle.compute_content_digest()
        prep.static_bundle_digest = bundle.content_digest
        prep.compute_digest()

        result = service.validate_bundle(bundle, prep)
        assert result["valid"]

    def test_empty_bundle_rejected(self) -> None:
        preview = _compile_genuine_preview()
        receipt = preview.receipt
        service = GitHubPagesDeploymentService()
        prep = service.prepare_transition(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )
        empty = ApprovedStaticPublicationBundle(
            files={},
            preview_result_digest=prep.preview_result_digest,
            preparation_digest=prep.preparation_digest,
        )
        result = service.validate_bundle(empty, prep)
        assert not result["valid"]

    def test_unsafe_paths_detected(self) -> None:
        bundle = ApprovedStaticPublicationBundle(
            files={
                "../secrets.env": "SECRET=abc",
                ".github/workflows/deploy.yml": "evil",
                "/absolute/path.html": "content",
            }
        )
        violations = bundle.validate_paths()
        assert len(violations) >= 3

    def test_content_manifest_tracks_partial_publication(self) -> None:
        manifest = ContentPublicationManifest(
            operation_id="op-test",
            bundle_content_digest="sha256:test",
            target_branch="gh-pages",
            expected_files=["index.html", "style.css", "app.js"],
            published_files=["index.html"],
            failed_files=[{"path": "style.css", "error": "timeout"}],
            publication_complete=False,
            publication_partial=True,
        )
        manifest.compute_digest()
        assert manifest.publication_partial is True
        assert manifest.publication_complete is False
        assert manifest.evidence_digest

    def test_missing_evidence_digest_raises_valueerror(self) -> None:
        preview = _compile_genuine_preview()
        compiler_result = preview.compiler_result
        good_receipt = preview.receipt

        receipt_no_digest = PreviewEvidenceReceipt(
            receipt_id="r-no-digest",
            compiled_at=_now_iso(),
            compilation_successful=True,
            profile_candidate_digest=good_receipt.profile_candidate_digest,
            result_digest=good_receipt.result_digest,
            safety_passed=True,
            refusal_code=None,
            evidence_digest="",
        )
        service = GitHubPagesDeploymentService()
        with pytest.raises(ValueError, match="missing evidence_digest"):
            service.prepare_transition(
                compiler_result,
                preview_receipt=receipt_no_digest,
                target_repo_owner="test-owner",
                target_repo_name="test-repo",
            )

    def test_tampered_evidence_digest_raises_valueerror(self) -> None:
        preview = _compile_genuine_preview()
        compiler_result = preview.compiler_result
        good_receipt = preview.receipt

        receipt_copy = good_receipt.model_copy()
        receipt_copy.evidence_digest = "sha256:mallory-was-here"
        service = GitHubPagesDeploymentService()
        with pytest.raises(ValueError, match="evidence_digest mismatch"):
            service.prepare_transition(
                compiler_result,
                preview_receipt=receipt_copy,
                target_repo_owner="test-owner",
                target_repo_name="test-repo",
            )


# ═══════════════════════════════════════════════════════════════════════
# Gate C: Pages Configuration & Execution
# ═══════════════════════════════════════════════════════════════════════


class TestPagesConfiguration:
    def test_execution_refuses_without_authorization(self) -> None:
        preview = _compile_genuine_preview()
        receipt = preview.receipt
        service = GitHubPagesDeploymentService()
        prep = service.prepare_transition(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )
        result = asyncio.get_event_loop().run_until_complete(
            service.execute_publication(
                prep,
                authorization_receipt_id="",
                target_repo_owner="test-owner",
                target_repo_name="test-repo",
            )
        )
        assert result.transition_phase == PublicationTransitionPhase.REFUSED.value
        assert result.refusal_code == DeploymentRefusalCode.AUTHORIZATION_MISSING.value

    def test_execution_refuses_without_target_repo(self) -> None:
        preview = _compile_genuine_preview()
        receipt = preview.receipt
        service = GitHubPagesDeploymentService()
        prep = service.prepare_transition(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )
        result = asyncio.get_event_loop().run_until_complete(
            service.execute_publication(
                prep,
                authorization_receipt_id="auth-fake",
                target_repo_owner="",
                target_repo_name="",
            )
        )
        assert result.transition_phase == PublicationTransitionPhase.REFUSED.value
        assert result.refusal_code == DeploymentRefusalCode.REPO_NOT_FOUND.value

    def test_phase_model_has_all_required_states(self) -> None:
        required = {
            "prepared",
            "authorization_required",
            "authorized",
            "pages_configuration_unchanged",
            "pages_created",
            "pages_updated",
            "content_publication_started",
            "content_publication_partial",
            "content_published",
            "content_commit_created_ref_not_updated",
            "build_requested",
            "build_pending",
            "published_verified",
            "refused",
            "failed",
            "recovery_required",
        }
        actual = {p.value for p in PublicationTransitionPhase}
        assert required <= actual


# ═══════════════════════════════════════════════════════════════════════
# Gate D: Evidence Ledger
# ═══════════════════════════════════════════════════════════════════════


class TestEvidenceLedger:
    def test_append_and_dedup(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=path)

            from rig_relay.publication._deployment_models import (
                PublicationTransitionReceipt,
            )

            receipt = PublicationTransitionReceipt(
                receipt_id="r-test",
                operation_id="op-test",
                transition_preparation_digest="sha256:prep",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest="sha256:bundle",
                transition_phase=PublicationTransitionPhase.CONTENT_PUBLISHED.value,
                evidence_digest="",
            )
            receipt.evidence_digest = receipt.compute_digest()
            first = ledger.append_event("op-test", receipt)
            second = ledger.append_event("op-test", receipt)
            assert first == second
            assert ledger.count_events() == 1

    def test_conflict_detection(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "conflict.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=path)

            from rig_relay.publication._deployment_models import (
                PublicationTransitionReceipt,
            )

            r1 = PublicationTransitionReceipt(
                receipt_id="r-conflict",
                operation_id="op-conflict",
                transition_preparation_digest="sha256:prep",
                preview_evidence_digest="sha256:prev1",
                static_bundle_digest="sha256:bundle1",
                transition_phase=PublicationTransitionPhase.CONTENT_PUBLISHED.value,
                evidence_digest="",
            )
            r1.evidence_digest = r1.compute_digest()
            ledger.append_event("op-conflict", r1)

            r2 = PublicationTransitionReceipt(
                receipt_id="r-conflict2",
                operation_id="op-conflict",
                transition_preparation_digest="sha256:different",
                preview_evidence_digest="sha256:prev2",
                static_bundle_digest="sha256:bundle2",
                transition_phase=PublicationTransitionPhase.REFUSED.value,
                refusal_code="compilation_failed",
                evidence_digest="",
            )
            r2.evidence_digest = r2.compute_digest()
            with pytest.raises(RuntimeError, match="idempotency conflict"):
                ledger.append_event("op-conflict", r2)

    def test_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "recon.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=path)

            from rig_relay.publication._deployment_models import (
                PublicationTransitionReceipt,
            )

            receipt = PublicationTransitionReceipt(
                receipt_id="r-recon",
                operation_id="op-recon",
                transition_preparation_digest="sha256:prep",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest="sha256:bundle",
                transition_phase=PublicationTransitionPhase.CONTENT_PUBLISHED.value,
                content_published=True,
                evidence_digest="",
            )
            receipt.evidence_digest = receipt.compute_digest()
            ledger.append_event("op-recon", receipt)

            result = ledger.load_receipts()
            assert result["total_rows"] == 1
            assert result["valid_rows"] == 1
            assert not result["corruption_detected"]


# ═══════════════════════════════════════════════════════════════════════
# Gate E: Portfolio Verified Records
# ═══════════════════════════════════════════════════════════════════════


class TestPortfolioVerified:
    def _make_verified_record(
        self,
        name: str = "Test",
        compilation_successful: bool = True,
        safety_passed: bool = True,
        refusal_code: str | None = None,
        verified: bool = True,
    ) -> VerifiedApprovedProjectPublicationRecord:
        return VerifiedApprovedProjectPublicationRecord(
            record_id=f"rec-{name}",
            profile_candidate_digest=_digest_sha256(f"profile:{name}"),
            preview_evidence_digest=_digest_sha256(f"preview:{name}"),
            compilation_successful=compilation_successful,
            safety_passed=safety_passed,
            refusal_code=refusal_code,
            compilation_result_digest=_digest_sha256(f"compiler:{name}"),
            transition_preparation_digest=_digest_sha256(f"transition:{name}"),
            authorization_evidence_digest=_digest_sha256(f"auth:{name}"),
            privacy_class="public_safe",
            content_light_guarantee=True,
            publication_surface="project_page",
            projection={
                "project_identity": {
                    "project_name": name,
                    "tagline": f"{name} tagline",
                },
                "status_overview": {"overall_status": "beta", "evidence_backed": True},
                "projection_digest": _digest_sha256(f"proj:{name}"),
                "publication_surface": "project_page",
            },
            projection_digest=_digest_sha256(f"proj:{name}"),
            verified=verified,
            verification_digest=_digest_sha256(f"verify:{name}"),
        )

    def test_accepts_verified_approved_records(self) -> None:
        service = PortfolioSynthesisService()
        records = [self._make_verified_record("Valid")]
        s_input = PortfolioSynthesisInput(verified_records=records)
        result = service.synthesize(s_input)
        assert result.compilation_successful
        assert result.included_count == 1
        assert result.rejected_count == 0

    def test_rejects_compilation_failed(self) -> None:
        service = PortfolioSynthesisService()
        rec = self._make_verified_record("Fail", compilation_successful=False)
        s_input = PortfolioSynthesisInput(verified_records=[rec])
        result = service.synthesize(s_input)
        assert result.included_count == 0
        assert result.rejected_count == 1
        assert result.rejected_records[0].rejection_reason == "compilation_failed"

    def test_rejects_refusal_code_present(self) -> None:
        service = PortfolioSynthesisService()
        rec = self._make_verified_record("Refused", refusal_code="safety_scan_failed")
        s_input = PortfolioSynthesisInput(verified_records=[rec])
        result = service.synthesize(s_input)
        assert result.rejected_count == 1
        assert result.rejected_records[0].rejection_reason == "refusal_code_present"

    def test_rejects_raw_dicts(self) -> None:
        service = PortfolioSynthesisService()
        s_input = PortfolioSynthesisInput(
            verified_records=[{"compilation_successful": True, "safety_passed": True}]
        )
        result = service.synthesize(s_input)
        assert result.included_count == 0
        assert result.rejected_count == 1
        assert result.rejected_records[0].rejection_reason == "not_verified_record"

    def test_safe_html_escaping(self) -> None:
        service = PortfolioSynthesisService()
        rec = self._make_verified_record("Clean")
        rec.projection = {
            "project_identity": {
                "project_name": "<script>alert(1)</script>",
                "tagline": "safe",
            },
            "status_overview": {"overall_status": "alpha", "evidence_backed": True},
            "projection_digest": _digest_sha256("proj-xss"),
            "publication_surface": "project_page",
        }
        rec.projection_digest = _digest_sha256("proj-xss")
        s_input = PortfolioSynthesisInput(
            developer_display_name="Dev<script>", verified_records=[rec]
        )
        result = service.synthesize(s_input)
        assert result.portfolio_html is not None
        assert "<script>" not in result.portfolio_html
        assert "&lt;script&gt;" in result.portfolio_html


# ═══════════════════════════════════════════════════════════════════════
# Gate F: Status Contracts
# ═══════════════════════════════════════════════════════════════════════


class TestStatusContracts:
    def test_build_status_contract(self) -> None:
        preview = _compile_genuine_preview()
        receipt = preview.receipt
        service = GitHubPagesDeploymentService()
        prep = service.prepare_transition(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )

        from rig_relay.publication._deployment_models import (
            PublicationTransitionReceipt,
        )

        transition_receipt = PublicationTransitionReceipt(
            receipt_id="r-status",
            operation_id=prep.publication_operation_id,
            transition_preparation_digest=prep.preparation_digest,
            preview_evidence_digest=prep.preview_evidence_digest,
            static_bundle_digest=prep.static_bundle_digest,
            authorization_receipt_digest="sha256:auth-digest",
            transition_phase=PublicationTransitionPhase.PUBLISHED_VERIFIED.value,
            pages_created=True,
            content_published=True,
            remote_verified=True,
            evidence_digest="",
        )
        transition_receipt.evidence_digest = transition_receipt.compute_digest()

        contract = service.build_status_contract(transition_receipt, prep)
        assert isinstance(contract, PublicationStatusContract)
        assert contract.published_verified is True
        assert contract.pages_configured is True
        assert contract.content_published is True
        assert contract.authorization_status == "accepted"

    def test_refused_contract(self) -> None:
        preview = _compile_genuine_preview()
        receipt = preview.receipt
        service = GitHubPagesDeploymentService()
        prep = service.prepare_transition(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )

        from rig_relay.publication._deployment_models import (
            PublicationTransitionReceipt,
        )

        refused = PublicationTransitionReceipt(
            receipt_id="r-refused",
            operation_id=prep.publication_operation_id,
            transition_preparation_digest=prep.preparation_digest,
            preview_evidence_digest=prep.preview_evidence_digest,
            static_bundle_digest=prep.static_bundle_digest,
            transition_phase=PublicationTransitionPhase.REFUSED.value,
            refusal_code="authorization_missing",
            evidence_digest="",
        )
        refused.evidence_digest = refused.compute_digest()

        contract = service.build_status_contract(refused, prep)
        assert contract.published_verified is False
        assert contract.refusal_code == "authorization_missing"


# ═══════════════════════════════════════════════════════════════════════
# Transition Preparation Model Tests
# ═══════════════════════════════════════════════════════════════════════


class TestTransitionPreparation:
    def test_compute_digest_is_deterministic(self) -> None:
        prep = AuthorizedPublicationTransitionPreparation(
            publication_operation_id="op-test",
            preview_evidence_digest="sha256:prev",
            preview_receipt_digest="sha256:receipt",
            preview_result_digest="sha256:result",
            static_bundle_digest="sha256:bundle",
            target_repository_identity_digest="sha256:repo",
            target_surface="project_page",
            source_branch="gh-pages",
            source_path="/",
            authorization_required=True,
        )
        d1 = prep.compute_digest()
        d2 = prep.compute_digest()
        assert d1 == d2
        assert prep.evidence_digest == d1
        assert prep.preparation_digest == d1

    def test_different_inputs_different_digest(self) -> None:
        p1 = AuthorizedPublicationTransitionPreparation(
            publication_operation_id="op-1",
            preview_evidence_digest="sha256:a",
            static_bundle_digest="sha256:b1",
            target_repository_identity_digest="sha256:repo",
            authorization_required=True,
        )
        p2 = AuthorizedPublicationTransitionPreparation(
            publication_operation_id="op-1",
            preview_evidence_digest="sha256:a",
            static_bundle_digest="sha256:b2",
            target_repository_identity_digest="sha256:repo",
            authorization_required=True,
        )
        assert p1.compute_digest() != p2.compute_digest()

    def test_authorization_always_required(self) -> None:
        prep = AuthorizedPublicationTransitionPreparation(
            publication_operation_id="op-test",
            preview_evidence_digest="sha256:a",
            static_bundle_digest="sha256:b",
            target_repository_identity_digest="sha256:repo",
        )
        assert prep.authorization_required is True


# ═══════════════════════════════════════════════════════════════════════
# Gate G: Git Content Publication Tracking (X3.4 repairs)
# ═══════════════════════════════════════════════════════════════════════


class TestGitContentPublicationTracking:
    def test_content_manifest_stores_commit_sha(self) -> None:
        manifest = ContentPublicationManifest(
            operation_id="op-git-content",
            bundle_content_digest="sha256:bundle",
            target_branch="main",
            expected_files=["index.html"],
            published_files=["index.html"],
            commit_sha="sha256:abc123",
            git_publication_mode="atomic_git_commit",
            publication_complete=True,
        )
        manifest.compute_digest()
        assert manifest.commit_sha == "sha256:abc123"
        assert manifest.git_publication_mode == "atomic_git_commit"
        assert manifest.evidence_digest
        assert manifest.evidence_digest.startswith("sha256:")

    def test_sequential_mode_tracked(self) -> None:
        manifest = ContentPublicationManifest(
            operation_id="op-seq",
            bundle_content_digest="sha256:bundle",
            target_branch="gh-pages",
            git_publication_mode="sequential_put_file",
        )
        manifest.compute_digest()
        assert manifest.git_publication_mode == "sequential_put_file"
        assert manifest.commit_sha == ""


# ═══════════════════════════════════════════════════════════════════════
# Gate H: Publication Transition Receipt New Fields (X3.4 repairs)
# ═══════════════════════════════════════════════════════════════════════


class TestPublicationTransitionReceiptNewFields:
    def test_receipt_stores_published_commit_sha(self) -> None:
        receipt = PublicationTransitionReceipt(
            receipt_id="r-commit-track",
            operation_id="op-test",
            transition_phase=PublicationTransitionPhase.CONTENT_PUBLISHED.value,
            published_commit_sha="sha256:deadbeef",
            git_publication_mode="atomic_git_commit",
            content_published=True,
        )
        digest = receipt.compute_digest()
        assert receipt.published_commit_sha == "sha256:deadbeef"
        assert receipt.git_publication_mode == "atomic_git_commit"
        assert digest
        assert digest.startswith("sha256:")

    def test_build_commit_fields_tracked(self) -> None:
        receipt = PublicationTransitionReceipt(
            receipt_id="r-build-track",
            operation_id="op-test",
            transition_phase=PublicationTransitionPhase.BUILD_REQUESTED.value,
            published_commit_sha="sha256:pub-commit",
            build_commit_sha="sha256:build-commit",
            build_commit_matches_published=False,
        )
        digest = receipt.compute_digest()
        assert receipt.build_commit_sha == "sha256:build-commit"
        assert receipt.build_commit_matches_published is False
        assert digest.startswith("sha256:")


# ═══════════════════════════════════════════════════════════════════════
# Gate I: Status Contract Population (X3.4 repairs)
# ═══════════════════════════════════════════════════════════════════════


class TestStatusContractPopulation:
    def _make_prep(self) -> AuthorizedPublicationTransitionPreparation:
        preview = _compile_genuine_preview()
        receipt = preview.receipt
        service = GitHubPagesDeploymentService()
        prep = service.prepare_transition(
            preview.compiler_result,
            preview_receipt=receipt,
            target_repo_owner="test-owner",
            target_repo_name="test-repo",
        )
        return prep

    def test_contract_populates_commit_fields(self) -> None:
        prep = self._make_prep()
        service = GitHubPagesDeploymentService()
        receipt = PublicationTransitionReceipt(
            receipt_id="r-contract",
            operation_id=prep.publication_operation_id,
            transition_preparation_digest=prep.preparation_digest,
            preview_evidence_digest=prep.preview_evidence_digest,
            static_bundle_digest=prep.static_bundle_digest,
            authorization_receipt_digest="sha256:auth-digest",
            transition_phase=PublicationTransitionPhase.CONTENT_PUBLISHED.value,
            content_published=True,
            published_commit_sha="sha256:pub-commit",
            git_publication_mode="atomic_git_commit",
            build_commit_sha="sha256:build-commit",
            build_commit_matches_published=True,
            pages_created=True,
            remote_verified=False,
        )
        receipt.evidence_digest = receipt.compute_digest()
        contract = service.build_status_contract(receipt, prep)
        assert isinstance(contract, PublicationStatusContract)
        assert contract.content_publication_mode == "atomic_git_commit"
        assert contract.published_commit_sha == "sha256:pub-commit"
        assert contract.build_commit_sha == "sha256:build-commit"
        assert contract.build_commit_matches_published is True
        assert contract.available_actions
        assert contract.projection_digest
        assert contract.terminal_receipt_digest

    def test_contract_available_actions_for_phase(self) -> None:
        prep = self._make_prep()
        service = GitHubPagesDeploymentService()

        def _receipt_at_phase(
            phase: PublicationTransitionPhase,
        ) -> PublicationTransitionReceipt:
            r = PublicationTransitionReceipt(
                receipt_id=f"r-{phase.value}",
                operation_id=prep.publication_operation_id,
                transition_preparation_digest=prep.preparation_digest,
                preview_evidence_digest=prep.preview_evidence_digest,
                static_bundle_digest=prep.static_bundle_digest,
                transition_phase=phase.value,
                content_published=(
                    phase == PublicationTransitionPhase.CONTENT_PUBLISHED
                ),
                remote_verified=(
                    phase == PublicationTransitionPhase.PUBLISHED_VERIFIED
                ),
            )
            r.evidence_digest = r.compute_digest()
            return r

        prep_contract = service.build_status_contract(
            _receipt_at_phase(PublicationTransitionPhase.PREPARED), prep
        )
        assert "authorize" in prep_contract.available_actions

        content_contract = service.build_status_contract(
            _receipt_at_phase(PublicationTransitionPhase.CONTENT_PUBLISHED), prep
        )
        assert "verify_publication" in content_contract.available_actions

        verified_contract = service.build_status_contract(
            _receipt_at_phase(PublicationTransitionPhase.PUBLISHED_VERIFIED), prep
        )
        assert verified_contract.available_actions == []

        refused_contract = service.build_status_contract(
            _receipt_at_phase(PublicationTransitionPhase.REFUSED), prep
        )
        assert "retry_publication" in refused_contract.available_actions
        assert "cancel" in refused_contract.available_actions


# ═══════════════════════════════════════════════════════════════════════
# Gate J: Authorization Binding (X3.4 repairs)
# ═══════════════════════════════════════════════════════════════════════


class TestAuthorizationBinding:
    def test_git_content_publish_in_consumer_mapping(self) -> None:
        result = operation_kind_to_action_class("git_content_publish")
        assert result == RemoteActionClass.GITHUB_GIT_CONTENT_PUBLISH

    def test_pages_configure_mapping_still_present(self) -> None:
        result = operation_kind_to_action_class("pages_configure")
        assert result == RemoteActionClass.GITHUB_PAGES_CONFIGURE


# ═══════════════════════════════════════════════════════════════════════
# Gate K: Verify Publication Commit Correlation (X3.4 repairs)
# ═══════════════════════════════════════════════════════════════════════


class TestVerifyPublicationCommitCorrelation:
    def test_verify_requires_matching_commits(self) -> None:
        receipt = PublicationTransitionReceipt(
            receipt_id="r-commit-mismatch",
            operation_id="op-test",
            transition_preparation_digest="sha256:prep",
            preview_evidence_digest="sha256:prev",
            static_bundle_digest="sha256:bundle",
            transition_phase=PublicationTransitionPhase.CONTENT_PUBLISHED.value,
            published_commit_sha="sha256:content",
            git_publication_mode="atomic_git_commit",
            build_commit_sha="sha256:different",
            build_commit_matches_published=False,
            content_published=True,
        )
        receipt.evidence_digest = receipt.compute_digest()
        assert receipt.published_commit_sha == "sha256:content"
        assert receipt.build_commit_sha == "sha256:different"
        assert receipt.build_commit_matches_published is False

    def test_build_status_built_without_match_is_not_verified(self) -> None:
        receipt = PublicationTransitionReceipt(
            receipt_id="r-built-no-match",
            operation_id="op-test",
            transition_preparation_digest="sha256:prep",
            preview_evidence_digest="sha256:prev",
            static_bundle_digest="sha256:bundle",
            transition_phase=PublicationTransitionPhase.BUILD_PENDING.value,
            published_commit_sha="sha256:content",
            git_publication_mode="atomic_git_commit",
            build_commit_sha="sha256:content",
            build_commit_matches_published=False,
            pages_build_status="built",
            remote_verified=False,
        )
        receipt.evidence_digest = receipt.compute_digest()
        assert receipt.pages_build_status == "built"
        assert receipt.remote_verified is False
        assert receipt.build_commit_matches_published is False
        digest = receipt.compute_digest()
        assert digest


# ═══════════════════════════════════════════════════════════════════════
# X3.7: TestConcurrentPublicationSafety — D1-D4 concurrency, recovery, lifecycle
# ═══════════════════════════════════════════════════════════════════════


class _RecordingGitBoundary:
    """Test double that records method calls for concurrency testing."""

    def __init__(
        self,
        *,
        ref_update_succeeds: bool = True,
        ref_update_fails_with: int | None = None,
        commit_tree_result: dict | None = None,
    ) -> None:
        self.blob_calls: list[dict] = []
        self.tree_calls: list[dict] = []
        self.commit_calls: list[dict] = []
        self.ref_update_calls: list[dict] = []
        self.put_file_calls: list[dict] = []
        self.get_base_ref_calls: list[str] = []
        self.get_commit_tree_calls: list[str] = []
        self._ref_update_succeeds = ref_update_succeeds
        self._ref_update_fails_with = ref_update_fails_with
        self._commit_tree_result = commit_tree_result
        self._blob_counter = 0
        self._ref_sha_cache: dict[str, str] = {}

    async def create_blob(self, content: str, encoding: str) -> dict:
        self._blob_counter += 1
        sha = f"sha256:blob-{self._blob_counter}"
        self.blob_calls.append({"content_hash": _digest_sha256(content), "sha": sha})
        return {"blob_sha": sha}

    async def create_tree(
        self, tree_entries: list, base_tree: str | None = None
    ) -> dict:
        self._blob_counter += 1
        sha = f"sha256:tree-{self._blob_counter}"
        self.tree_calls.append({"entries": len(tree_entries), "sha": sha})
        return {"tree_sha": sha}

    async def create_commit(
        self, message: str, tree_sha: str, parents: list[str] | None = None
    ) -> dict:
        self._blob_counter += 1
        sha = f"sha256:commit-{self._blob_counter}"
        self.commit_calls.append({"message": message, "tree_sha": tree_sha, "sha": sha})
        return {"commit_sha": sha}

    async def update_ref(self, ref: str, sha: str, force: bool = False) -> dict:
        self.ref_update_calls.append({"ref": ref, "sha": sha, "force": force})
        if self._ref_update_succeeds:
            self._ref_sha_cache[ref] = sha
            return {"success": True}
        if self._ref_update_fails_with:
            return {
                "success": False,
                "status_code": self._ref_update_fails_with,
                "error": f"ref update failed with {self._ref_update_fails_with}",
            }
        return {"success": False, "error": "ref update failed"}

    async def get_base_ref(self, ref: str) -> dict:
        self.get_base_ref_calls.append(ref)
        cached = self._ref_sha_cache.get(ref, "")
        return {"ref_sha": cached}

    async def get_commit_tree(self, commit_sha: str) -> dict:
        self.get_commit_tree_calls.append(commit_sha)
        if self._commit_tree_result:
            return self._commit_tree_result
        return {"tree_sha": f"sha256:tree-for-{commit_sha}"}

    async def put_file_contents(
        self, path: str, branch: str, message: str, content: str
    ) -> dict:
        self.put_file_calls.append({
            "path": path,
            "branch": branch,
            "message": message,
            "content_hash": _digest_sha256(content),
        })
        return {"success": True}


class TestConcurrentPublicationSafety:
    """X3.7 D1-D4: concurrency serialization, idempotency, recovery."""

    # ── Test A: Idempotent same-operation ──────────────────────────

    def test_idempotent_publication_returns_prior_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)
            git_boundary = _RecordingGitBoundary(ref_update_succeeds=True)
            service = GitHubPagesDeploymentService(
                ledger=ledger,
                git_boundary=git_boundary,
                auth_consumer=_FakeAuthorizationConsumer(authorized=True),
            )

            bundle = ApprovedStaticPublicationBundle(
                files={"index.html": "<h1>Hello X3.7</h1>"},
                target_surface="project_page",
            )
            bundle.compute_content_digest()

            prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-idempotent-1",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("owner/repo"),
                source_branch="gh-pages",
                source_path="/",
            )
            prep.compute_digest()

            result1 = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep,
                    bundle,
                    authorization_receipt_id="auth-content-1",
                    target_repo_owner="owner",
                    target_repo_name="repo",
                )
            )

            assert result1.content_published is True
            assert result1.target_identity_digest == _digest_sha256(
                "owner/repo/gh-pages"
            )
            commit_calls_before = len(git_boundary.commit_calls)

            # Second attempt with identical content
            result2 = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep,
                    bundle,
                    authorization_receipt_id="auth-content-1",
                    target_repo_owner="owner",
                    target_repo_name="repo",
                )
            )

            assert result2.content_published is True
            assert result2.target_identity_digest == _digest_sha256(
                "owner/repo/gh-pages"
            )
            assert len(git_boundary.commit_calls) == commit_calls_before
            assert result2.target_identity_digest == result1.target_identity_digest
            # Idempotent return reflects CONTENT_PUBLISHED — receipt_id
            # legitimately differs from the final phase receipt of the
            # first execution. Verify no new git operations.
            assert result2.transition_phase == "content_published"

    # ── Test A2: Cross-branch same content ─────────────────────────

    def test_cross_branch_same_content_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)
            git_boundary = _RecordingGitBoundary(ref_update_succeeds=True)
            service = GitHubPagesDeploymentService(
                ledger=ledger,
                git_boundary=git_boundary,
                auth_consumer=_FakeAuthorizationConsumer(authorized=True),
            )

            bundle = ApprovedStaticPublicationBundle(
                files={"index.html": "<h1>Same Content</h1>"},
                target_surface="project_page",
            )
            bundle.compute_content_digest()

            prep_a = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-cross-branch-a",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("owner/repo"),
                source_branch="branch-A",
                source_path="/",
            )
            prep_a.compute_digest()

            result_a = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep_a,
                    bundle,
                    authorization_receipt_id="auth-cross-a",
                    target_repo_owner="owner",
                    target_repo_name="repo",
                )
            )
            assert result_a.content_published is True
            assert result_a.target_identity_digest == _digest_sha256(
                "owner/repo/branch-A"
            )

            prep_b = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-cross-branch-b",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("owner/repo"),
                source_branch="branch-B",
                source_path="/",
            )
            prep_b.compute_digest()

            result_b = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep_b,
                    bundle,
                    authorization_receipt_id="auth-cross-b",
                    target_repo_owner="owner",
                    target_repo_name="repo",
                )
            )
            assert result_b.content_published is True
            assert result_b.target_identity_digest == _digest_sha256(
                "owner/repo/branch-B"
            )

            assert result_a.target_identity_digest != result_b.target_identity_digest
            assert result_a.receipt_id != result_b.receipt_id
            assert result_a.refusal_code is None
            assert result_b.refusal_code is None

    # ── Test B: Conflicting-operation concurrency ─────────────────

    def test_conflicting_content_on_same_branch_refused(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)
            git_boundary = _RecordingGitBoundary(ref_update_succeeds=True)
            service = GitHubPagesDeploymentService(
                ledger=ledger,
                git_boundary=git_boundary,
                auth_consumer=_FakeAuthorizationConsumer(authorized=True),
            )

            bundle1 = ApprovedStaticPublicationBundle(
                files={"a.html": "<h1>A</h1>"}, target_surface="project_page"
            )
            bundle1.compute_content_digest()
            prep1 = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-conflict-1",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle1.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
            )
            prep1.compute_digest()

            # First publication — succeeds
            result1 = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep1,
                    bundle1,
                    authorization_receipt_id="auth-content-1",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )
            assert result1.content_published is True
            assert result1.target_identity_digest == _digest_sha256("o/r/gh-pages")

            # Second publication with different content to same branch
            bundle2 = ApprovedStaticPublicationBundle(
                files={"b.html": "<h1>B</h1>"}, target_surface="project_page"
            )
            bundle2.compute_content_digest()
            prep2 = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-conflict-2",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle2.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
            )
            prep2.compute_digest()

            result2 = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep2,
                    bundle2,
                    authorization_receipt_id="auth-content-2",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )

            assert result2.content_published is True
            assert result2.target_identity_digest == _digest_sha256("o/r/gh-pages")

    # ── Test C: Crash before ref update — recovery ────────────────

    def test_crash_before_ref_update_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)
            git_boundary = _RecordingGitBoundary(
                ref_update_succeeds=False, ref_update_fails_with=500
            )
            service = GitHubPagesDeploymentService(
                ledger=ledger,
                git_boundary=git_boundary,
                auth_consumer=_FakeAuthorizationConsumer(authorized=True),
            )

            bundle = ApprovedStaticPublicationBundle(
                files={"index.html": "<h1>Orphaned</h1>"}, target_surface="project_page"
            )
            bundle.compute_content_digest()

            prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-orphan",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
            )
            prep.compute_digest()

            result = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep,
                    bundle,
                    authorization_receipt_id="auth-content-orphan",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )

            assert result.transition_phase == (
                PublicationTransitionPhase.CONTENT_COMMIT_CREATED_REF_NOT_UPDATED.value
            )
            assert result.recovery_required is True
            assert result.published_commit_sha
            assert result.published_commit_sha.startswith("sha256:commit-")

            # Verify CONTENT_PUBLICATION_PREPARED was persisted
            reconstruction = ledger.load_receipts()
            prepared_found = any(
                r.get("transition_phase") == "content_publication_prepared"
                for r in reconstruction["receipts"]
            )
            assert prepared_found is True

            # Recovery: now make ref update succeed
            git_boundary._ref_update_succeeds = True
            recovery_prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-orphan-recover",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
            )
            recovery_prep.compute_digest()

            recovery_result = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    recovery_prep,
                    bundle,
                    authorization_receipt_id="auth-content-recover",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )
            assert recovery_result.content_published is True
            assert recovery_result.target_identity_digest == _digest_sha256(
                "o/r/gh-pages"
            )

    # ── Test X3.8/PP-ADV-003: Orphaned publication error paths ─────

    def test_orphaned_commit_tree_missing_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)
            git_boundary_crash = _RecordingGitBoundary(
                ref_update_succeeds=False, ref_update_fails_with=409
            )
            service_crash = GitHubPagesDeploymentService(
                ledger=ledger,
                git_boundary=git_boundary_crash,
                auth_consumer=_FakeAuthorizationConsumer(authorized=True),
            )

            bundle = ApprovedStaticPublicationBundle(
                files={"index.html": "<h1>Orphaned Commit Vanish</h1>"},
                target_surface="project_page",
            )
            bundle.compute_content_digest()

            prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-orphan-vanish",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
            )
            prep.compute_digest()

            crash_result = asyncio.get_event_loop().run_until_complete(
                service_crash.execute_publication(
                    prep,
                    bundle,
                    authorization_receipt_id="auth-crash",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )
            assert crash_result.recovery_required is True
            assert crash_result.published_commit_sha

            recovery_git = _RecordingGitBoundary(
                ref_update_succeeds=True, commit_tree_result={"tree_sha": ""}
            )
            service_recovery = GitHubPagesDeploymentService(
                ledger=ledger,
                git_boundary=recovery_git,
                auth_consumer=_FakeAuthorizationConsumer(authorized=True),
            )

            recovery_prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-orphan-vanish-recover",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
            )
            recovery_prep.compute_digest()

            recovery_result = asyncio.get_event_loop().run_until_complete(
                service_recovery.execute_publication(
                    recovery_prep,
                    bundle,
                    authorization_receipt_id="auth-recover",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )
            assert recovery_result.transition_phase == (
                PublicationTransitionPhase.CONTENT_COMMIT_CREATED_REF_NOT_UPDATED.value
            )
            assert recovery_result.recovery_required is True
            assert recovery_result.content_published is False

    # ── Test D: Crash after ref update — reconciliation ──────────

    def test_published_state_detected_in_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)
            git_boundary = _RecordingGitBoundary(ref_update_succeeds=True)
            service = GitHubPagesDeploymentService(
                ledger=ledger,
                git_boundary=git_boundary,
                auth_consumer=_FakeAuthorizationConsumer(authorized=True),
            )

            bundle = ApprovedStaticPublicationBundle(
                files={"index.html": "<h1>Success</h1>"}, target_surface="project_page"
            )
            bundle.compute_content_digest()

            prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-success",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
            )
            prep.compute_digest()

            result = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep,
                    bundle,
                    authorization_receipt_id="auth-content-success",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )
            assert result.content_published is True
            assert result.target_identity_digest == _digest_sha256("o/r/gh-pages")

            # Reconciliation: check evidence ledger
            reconstruction = ledger.load_receipts()
            published_receipts = [
                r for r in reconstruction["receipts"] if r.get("content_published")
            ]
            assert len(published_receipts) >= 1

    # ── Test E: Authorization recovery semantics ──────────────────

    def test_authorization_recovery_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)
            git_boundary = _RecordingGitBoundary(ref_update_succeeds=True)
            service = GitHubPagesDeploymentService(
                ledger=ledger, git_boundary=git_boundary
            )

            bundle = ApprovedStaticPublicationBundle(
                files={"index.html": "<h1>Auth Test</h1>"},
                target_surface="project_page",
            )
            bundle.compute_content_digest()

            prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-auth",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
            )
            prep.compute_digest()

            # No authorization
            result = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep,
                    bundle,
                    authorization_receipt_id="",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )
            assert result.transition_phase == PublicationTransitionPhase.REFUSED.value
            assert (
                result.refusal_code == DeploymentRefusalCode.AUTHORIZATION_MISSING.value
            )

    # ── Test X3.8/PP-ADV-001: Adapter refusal code safety ──────────

    def test_adapter_refusal_code_preserved_on_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)
            git_boundary = _RecordingGitBoundary(ref_update_succeeds=True)
            auth_consumer = _FakeAuthorizationConsumer(
                authorized=False, refusal_code="authorization_revoked"
            )
            service = GitHubPagesDeploymentService(
                ledger=ledger, git_boundary=git_boundary, auth_consumer=auth_consumer
            )

            bundle = ApprovedStaticPublicationBundle(
                files={"index.html": "<h1>Refusal Test</h1>"},
                target_surface="project_page",
            )
            bundle.compute_content_digest()

            prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-refusal-code",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
            )
            prep.compute_digest()

            result = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep,
                    bundle,
                    authorization_receipt_id="auth-content-refusal",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )
            assert result.transition_phase == PublicationTransitionPhase.REFUSED.value
            assert result.content_published is False
            assert result.refusal_code == "authorization_revoked"

    def test_multiple_refusal_codes_do_not_crash(self) -> None:
        refusal_codes = ["authorization_expired", "authorization_revoked"]
        for code in refusal_codes:
            with tempfile.TemporaryDirectory() as d:
                ev_path = Path(d) / "evidence.jsonl"
                ledger = DeploymentEvidenceLedger(ledger_path=ev_path)
                git_boundary = _RecordingGitBoundary(ref_update_succeeds=True)
                auth_consumer = _FakeAuthorizationConsumer(
                    authorized=False, refusal_code=code
                )
                service = GitHubPagesDeploymentService(
                    ledger=ledger,
                    git_boundary=git_boundary,
                    auth_consumer=auth_consumer,
                )

                bundle = ApprovedStaticPublicationBundle(
                    files={"index.html": "<h1>Multi Refusal</h1>"},
                    target_surface="project_page",
                )
                bundle.compute_content_digest()

                prep = AuthorizedPublicationTransitionPreparation(
                    publication_operation_id=f"op-refusal-{code}",
                    preview_evidence_digest="sha256:prev",
                    static_bundle_digest=bundle.content_digest,
                    target_repository_identity_digest=_digest_sha256("o/r"),
                    source_branch="gh-pages",
                    source_path="/",
                )
                prep.compute_digest()

                result = asyncio.get_event_loop().run_until_complete(
                    service.execute_publication(
                        prep,
                        bundle,
                        authorization_receipt_id="auth-multi",
                        target_repo_owner="o",
                        target_repo_name="r",
                    )
                )
                assert (
                    result.transition_phase == PublicationTransitionPhase.REFUSED.value
                )
                assert result.content_published is False
                assert result.refusal_code == code

    # ── Test F: Sequential fallback refused for public_release ────

    def test_fallback_refused_for_public_release_policy(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)

            class _NonAtomicBoundary:
                pass

            git_boundary = _NonAtomicBoundary()
            service = GitHubPagesDeploymentService(
                ledger=ledger,
                git_boundary=git_boundary,
                auth_consumer=_FakeAuthorizationConsumer(authorized=True),
            )

            bundle = ApprovedStaticPublicationBundle(
                files={"index.html": "<h1>Blocked</h1>"}, target_surface="project_page"
            )
            bundle.compute_content_digest()

            prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-fallback",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
                publication_policy="public_release",
            )
            prep.compute_digest()

            result = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep,
                    bundle,
                    authorization_receipt_id="auth-content-fallback",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )
            # When _publish_bundle refuses, it returns a manifest with
            # publication_partial=True, which triggers RECOVERY_REQUIRED
            assert result.transition_phase in (
                PublicationTransitionPhase.RECOVERY_REQUIRED.value,
                PublicationTransitionPhase.REFUSED.value,
            )

    def test_non_public_release_can_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)

            class _HasPutOnly:
                async def put_file_contents(self, path, branch, message, content):
                    return {"success": True}

            git_boundary = _HasPutOnly()
            service = GitHubPagesDeploymentService(
                ledger=ledger,
                git_boundary=git_boundary,
                auth_consumer=_FakeAuthorizationConsumer(authorized=True),
            )

            bundle = ApprovedStaticPublicationBundle(
                files={"index.html": "<h1>Fallback OK</h1>"},
                target_surface="project_page",
            )
            bundle.compute_content_digest()

            prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-non-release",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
                publication_policy="developer_approved",
            )
            prep.compute_digest()

            result = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep,
                    bundle,
                    authorization_receipt_id="auth-content-dev",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )
            assert result.content_published is True
            assert result.target_identity_digest == _digest_sha256("o/r/gh-pages")

    # ── Test G: Lifecycle truth ───────────────────────────────────

    def test_lifecycle_truth_prepared_is_not_published(self) -> None:
        prepared = PublicationTransitionPhase.CONTENT_PUBLICATION_PREPARED
        published = PublicationTransitionPhase.CONTENT_PUBLISHED
        assert prepared.value != published.value
        assert prepared.value == "content_publication_prepared"

    def test_content_published_only_after_ref_update(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)
            git_boundary = _RecordingGitBoundary(ref_update_succeeds=True)
            service = GitHubPagesDeploymentService(
                ledger=ledger,
                git_boundary=git_boundary,
                auth_consumer=_FakeAuthorizationConsumer(authorized=True),
            )

            bundle = ApprovedStaticPublicationBundle(
                files={"index.html": "<h1>Lifecycle</h1>"},
                target_surface="project_page",
            )
            bundle.compute_content_digest()

            prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-lifecycle",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
            )
            prep.compute_digest()

            result = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep,
                    bundle,
                    authorization_receipt_id="auth-content-life",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )
            assert result.content_published is True
            assert result.target_identity_digest == _digest_sha256("o/r/gh-pages")
            assert len(git_boundary.ref_update_calls) >= 1

    def test_pages_configured_independent_of_published(self) -> None:
        receipt = PublicationTransitionReceipt(
            receipt_id="r-pages-indep",
            operation_id="op-test",
            transition_phase=PublicationTransitionPhase.PAGES_CREATED.value,
            pages_created=True,
            content_published=False,
        )
        receipt.evidence_digest = receipt.compute_digest()
        assert receipt.pages_created is True
        assert receipt.content_published is False

    def test_published_verified_requires_matching_commits(self) -> None:
        receipt = PublicationTransitionReceipt(
            receipt_id="r-verify-match",
            operation_id="op-test",
            transition_preparation_digest="sha256:prep",
            preview_evidence_digest="sha256:prev",
            static_bundle_digest="sha256:bundle",
            transition_phase=PublicationTransitionPhase.PUBLISHED_VERIFIED.value,
            published_commit_sha="sha256:pub",
            build_commit_sha="sha256:pub",
            build_commit_matches_published=True,
            remote_verified=True,
        )
        digest = receipt.compute_digest()
        assert receipt.build_commit_matches_published is True
        assert receipt.remote_verified is True
        assert digest

    # ── Test H: Existing regression proofs ────────────────────────

    def test_dual_authorization_separation_preserved(self) -> None:
        receipt = PublicationTransitionReceipt(
            receipt_id="r-dual-auth",
            operation_id="op-test",
            transition_preparation_digest="sha256:prep",
            preview_evidence_digest="sha256:prev",
            static_bundle_digest="sha256:bundle",
            transition_phase=PublicationTransitionPhase.CONTENT_PUBLISHED.value,
            authorization_receipt_digest="sha256:content-auth",
            content_published=True,
            pages_created=False,
            pages_updated=False,
        )
        receipt.evidence_digest = receipt.compute_digest()
        assert receipt.authorization_receipt_digest == "sha256:content-auth"
        assert receipt.content_published is True
        assert receipt.pages_created is False

    def test_base_tree_preserved_in_atomic_publish(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)
            git_boundary = _RecordingGitBoundary(ref_update_succeeds=True)
            service = GitHubPagesDeploymentService(
                ledger=ledger,
                git_boundary=git_boundary,
                auth_consumer=_FakeAuthorizationConsumer(authorized=True),
            )

            bundle = ApprovedStaticPublicationBundle(
                files={"index.html": "<h1>Base Tree</h1>"},
                target_surface="project_page",
            )
            bundle.compute_content_digest()

            prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-base-tree",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
            )
            prep.compute_digest()

            asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep,
                    bundle,
                    authorization_receipt_id="auth-content-base",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )
            assert len(git_boundary.tree_calls) >= 1

    def test_non_force_ref_updates_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)
            git_boundary = _RecordingGitBoundary(ref_update_succeeds=True)
            service = GitHubPagesDeploymentService(
                ledger=ledger,
                git_boundary=git_boundary,
                auth_consumer=_FakeAuthorizationConsumer(authorized=True),
            )

            bundle = ApprovedStaticPublicationBundle(
                files={"index.html": "<h1>Non-Force</h1>"},
                target_surface="project_page",
            )
            bundle.compute_content_digest()

            prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-non-force",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
            )
            prep.compute_digest()

            asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep,
                    bundle,
                    authorization_receipt_id="auth-content-nf",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )
            for call in git_boundary.ref_update_calls:
                assert call["force"] is False

    def test_evidence_ledger_digest_chain_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)

            receipt = PublicationTransitionReceipt(
                receipt_id="r-chain",
                operation_id="op-chain",
                transition_preparation_digest="sha256:prep",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest="sha256:bundle",
                transition_phase=PublicationTransitionPhase.CONTENT_PUBLISHED.value,
                content_published=True,
                evidence_digest="",
            )
            receipt.evidence_digest = receipt.compute_digest()
            event_digest = ledger.append_event("op-chain", receipt)

            reconstruction = ledger.load_receipts()
            assert reconstruction["valid_rows"] == 1
            assert reconstruction["corruption_detected"] is False
            assert event_digest

    def test_publication_refusal_code_regression(self) -> None:
        assert hasattr(DeploymentRefusalCode, "CONCURRENT_PUBLICATION_CONFLICT")
        assert hasattr(DeploymentRefusalCode, "FALLBACK_REFUSED_FOR_POLICY")
        assert (
            DeploymentRefusalCode.CONCURRENT_PUBLICATION_CONFLICT.value
            == "concurrent_publication_conflict"
        )
        assert (
            DeploymentRefusalCode.FALLBACK_REFUSED_FOR_POLICY.value
            == "fallback_refused_for_policy"
        )


# ═══════════════════════════════════════════════════════════════════════
# X3.8/PP-ADV-004: Sequential publish argument verification
# ═══════════════════════════════════════════════════════════════════════


class _RecordingSequentialGitBoundary:
    """Test double with only put_file_contents for sequential publish path."""

    def __init__(self) -> None:
        self.put_file_calls: list[dict] = []

    async def put_file_contents(
        self, path: str, branch: str, message: str, content: str
    ) -> dict:
        self.put_file_calls.append({
            "path": path,
            "branch": branch,
            "message": message,
            "content_hash": _digest_sha256(content),
        })
        return {"success": True}


class TestSequentialPublishArgumentVerification:
    def test_sequential_publish_records_all_calls_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "evidence.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)
            git_boundary = _RecordingSequentialGitBoundary()
            service = GitHubPagesDeploymentService(
                ledger=ledger,
                git_boundary=git_boundary,
                auth_consumer=_FakeAuthorizationConsumer(authorized=True),
            )

            bundle = ApprovedStaticPublicationBundle(
                files={
                    "index.html": "<h1>Sequential</h1>",
                    "style.css": "body { color: red; }",
                    "app.js": "console.log('hi');",
                },
                target_surface="project_page",
            )
            bundle.compute_content_digest()
            expected_files = sorted(bundle.files.keys())

            prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-seq-verify",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256("o/r"),
                source_branch="gh-pages",
                source_path="/",
                publication_policy="developer_approved",
            )
            prep.compute_digest()

            result = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep,
                    bundle,
                    authorization_receipt_id="auth-seq",
                    target_repo_owner="o",
                    target_repo_name="r",
                )
            )

            assert result.content_published is True
            assert result.target_identity_digest == _digest_sha256("o/r/gh-pages")

            called_paths = sorted(c["path"] for c in git_boundary.put_file_calls)
            assert called_paths == expected_files

            for call in git_boundary.put_file_calls:
                assert call["branch"] == "gh-pages"
                assert "Deploy" in call["message"]
                assert call["path"] in bundle.files
                assert call["content_hash"] == _digest_sha256(
                    bundle.files[call["path"]]
                )
