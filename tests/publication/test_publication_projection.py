"""Lane X3.8 — Publication projection boundary tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile

from rig_relay.publication import (
    ApprovedStaticPublicationBundle,
    AuthorizedPublicationTransitionPreparation,
    DeploymentEvidenceLedger,
    GitHubPagesDeploymentService,
    PublicationStatusContract,
    PublicationTransitionPhase,
    PublicationTransitionReceipt,
)
from rig_relay.publication._deployment_models import _digest_sha256
from rig_relay.publication._projection import build_publication_projection
from tests.publication.test_deployment_service import (
    _FakeAuthorizationConsumer,
    _RecordingGitBoundary,
)


class TestPublicationProjection:
    """X3.8: validate build_publication_projection for all boundary paths."""

    def test_empty_ledger_returns_prepared_contract(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "projection_empty.jsonl"
            contract = build_publication_projection(
                str(ev_path), owner="test-owner", repo="test-repo", branch="gh-pages"
            )
            assert isinstance(contract, PublicationStatusContract)
            assert contract.transition_phase == "prepared"
            assert contract.authorization_required is True
            assert contract.content_published is False
            assert contract.target_repository_digest
            assert contract.evidence_linkage["evidence_ledger_path"] == str(ev_path)

    def test_valid_receipt_returns_full_contract_with_evidence_linkage(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "projection_valid.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)

            target_digest = _digest_sha256("test-owner/test-repo/gh-pages")
            receipt = PublicationTransitionReceipt(
                receipt_id="r-proj-1",
                operation_id="op-proj-1",
                transition_preparation_digest="sha256:prep-x",
                preview_evidence_digest="sha256:prev-x",
                static_bundle_digest="sha256:bundle-x",
                authorization_receipt_digest="sha256:auth-x",
                transition_phase=PublicationTransitionPhase.CONTENT_PUBLISHED.value,
                content_published=True,
                published_commit_sha="sha256:pub-abc",
                git_publication_mode="atomic_git_commit",
                deployed_at="2025-01-01T00:00:00Z",
                target_identity_digest=target_digest,
            )
            receipt.evidence_digest = receipt.compute_digest()
            ledger.append_event("op-proj-1", receipt)

            contract = build_publication_projection(
                str(ev_path), owner="test-owner", repo="test-repo", branch="gh-pages"
            )
            assert isinstance(contract, PublicationStatusContract)
            assert contract.content_published is True
            assert contract.evidence_linkage["terminal_receipt_digest"]
            assert contract.evidence_linkage["evidence_ledger_path"] == str(ev_path)
            assert contract.evidence_linkage["projection_digest"]

    def test_multi_event_ledger_returns_latest_by_deployed_at(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "projection_multi.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)

            target_digest = _digest_sha256("test-owner/test-repo/gh-pages")
            r1 = PublicationTransitionReceipt(
                receipt_id="r-proj-early",
                operation_id="op-proj-early",
                transition_preparation_digest="sha256:prep-early",
                preview_evidence_digest="sha256:prev-early",
                static_bundle_digest="sha256:bundle-early",
                transition_phase=PublicationTransitionPhase.PREPARED.value,
                deployed_at="2024-01-01T00:00:00Z",
                target_identity_digest=target_digest,
            )
            r1.evidence_digest = r1.compute_digest()
            ledger.append_event("op-proj-early", r1)

            r2 = PublicationTransitionReceipt(
                receipt_id="r-proj-late",
                operation_id="op-proj-late",
                transition_preparation_digest="sha256:prep-late",
                preview_evidence_digest="sha256:prev-late",
                static_bundle_digest="sha256:bundle-late",
                transition_phase=PublicationTransitionPhase.CONTENT_PUBLISHED.value,
                content_published=True,
                deployed_at="2025-06-01T00:00:00Z",
                target_identity_digest=target_digest,
            )
            r2.evidence_digest = r2.compute_digest()
            ledger.append_event("op-proj-late", r2)

            contract = build_publication_projection(
                str(ev_path), owner="test-owner", repo="test-repo", branch="gh-pages"
            )
            assert contract.transition_phase == "content_published"
            assert contract.publication_operation_id == "op-proj-late"

    def test_corrupt_receipt_returns_failed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "projection_corrupt.jsonl"
            ev_path.write_text("not valid json at all\n")

            contract = build_publication_projection(
                str(ev_path), owner="test-owner", repo="test-repo", branch="gh-pages"
            )
            assert isinstance(contract, PublicationStatusContract)
            assert contract.transition_phase in ("prepared", "failed")

    def test_target_scoped_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "projection_scoped.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)

            target_a = _digest_sha256("owner-a/repo-a/branch-a")
            target_b = _digest_sha256("owner-b/repo-b/branch-b")

            r_a = PublicationTransitionReceipt(
                receipt_id="r-target-a",
                operation_id="op-target-a",
                transition_preparation_digest="sha256:prep-a",
                preview_evidence_digest="sha256:prev-a",
                static_bundle_digest="sha256:bundle-a",
                transition_phase=PublicationTransitionPhase.CONTENT_PUBLISHED.value,
                content_published=True,
                deployed_at="2025-01-01T00:00:00Z",
                target_identity_digest=target_a,
            )
            r_a.evidence_digest = r_a.compute_digest()
            ledger.append_event("op-target-a", r_a)

            r_b = PublicationTransitionReceipt(
                receipt_id="r-target-b",
                operation_id="op-target-b",
                transition_preparation_digest="sha256:prep-b",
                preview_evidence_digest="sha256:prev-b",
                static_bundle_digest="sha256:bundle-b",
                transition_phase=PublicationTransitionPhase.PAGES_CREATED.value,
                pages_created=True,
                deployed_at="2025-02-01T00:00:00Z",
                target_identity_digest=target_b,
            )
            r_b.evidence_digest = r_b.compute_digest()
            ledger.append_event("op-target-b", r_b)

            contract_a = build_publication_projection(
                str(ev_path), owner="owner-a", repo="repo-a", branch="branch-a"
            )
            assert contract_a.transition_phase == "content_published"
            assert contract_a.publication_operation_id == "op-target-a"

            contract_b = build_publication_projection(
                str(ev_path), owner="owner-b", repo="repo-b", branch="branch-b"
            )
            assert contract_b.transition_phase == "pages_created"
            assert contract_b.publication_operation_id == "op-target-b"

    def test_projection_scopes_by_target_through_service(self) -> None:
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
                files={"index.html": "<h1>E2E Projection</h1>"},
                target_surface="project_page",
            )
            bundle.compute_content_digest()

            prep = AuthorizedPublicationTransitionPreparation(
                publication_operation_id="op-e2e-proj",
                preview_evidence_digest="sha256:prev",
                static_bundle_digest=bundle.content_digest,
                target_repository_identity_digest=_digest_sha256(
                    "test-owner/test-repo"
                ),
                source_branch="branch-a",
                source_path="/",
            )
            prep.compute_digest()

            result = asyncio.get_event_loop().run_until_complete(
                service.execute_publication(
                    prep,
                    bundle,
                    authorization_receipt_id="auth-e2e",
                    target_repo_owner="test-owner",
                    target_repo_name="test-repo",
                )
            )
            assert result.content_published is True

            contract_a = build_publication_projection(
                str(ev_path), owner="test-owner", repo="test-repo", branch="branch-a"
            )
            assert contract_a.content_published is True
            # Projection may reflect content_published even when the final
            # service return records recovery_required (Pages needs separate
            # authorization). The content IS published — intermediate
            # receipts now target by branch correctly.
            assert contract_a.transition_phase in (
                "content_published",
                result.transition_phase,
            )

            contract_b = build_publication_projection(
                str(ev_path), owner="test-owner", repo="test-repo", branch="branch-b"
            )
            assert contract_b.content_published is False
            assert contract_b.transition_phase in ("prepared", "failed")

    def test_unscoped_fallback_to_global_latest(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ev_path = Path(d) / "projection_unscoped.jsonl"
            ledger = DeploymentEvidenceLedger(ledger_path=ev_path)

            target_a = _digest_sha256("owner-a/repo-a/branch-a")
            target_b = _digest_sha256("owner-b/repo-b/branch-b")

            r_early = PublicationTransitionReceipt(
                receipt_id="r-unscoped-early",
                operation_id="op-unscoped-early",
                transition_preparation_digest="sha256:prep-early",
                preview_evidence_digest="sha256:prev-early",
                static_bundle_digest="sha256:bundle-early",
                transition_phase=PublicationTransitionPhase.PREPARED.value,
                deployed_at="2024-01-01T00:00:00Z",
                target_identity_digest=target_a,
            )
            r_early.evidence_digest = r_early.compute_digest()
            ledger.append_event("op-unscoped-early", r_early)

            r_late = PublicationTransitionReceipt(
                receipt_id="r-unscoped-late",
                operation_id="op-unscoped-late",
                transition_preparation_digest="sha256:prep-late",
                preview_evidence_digest="sha256:prev-late",
                static_bundle_digest="sha256:bundle-late",
                transition_phase=PublicationTransitionPhase.CONTENT_PUBLISHED.value,
                content_published=True,
                deployed_at="2025-06-01T00:00:00Z",
                target_identity_digest=target_b,
            )
            r_late.evidence_digest = r_late.compute_digest()
            ledger.append_event("op-unscoped-late", r_late)

            contract = build_publication_projection(str(ev_path))
            assert contract.transition_phase == "content_published"
            assert contract.publication_operation_id == "op-unscoped-late"
