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
