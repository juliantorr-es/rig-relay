from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from rig_relay.publication._deployment_evidence import (
    DEPLOYMENT_LEDGER_DIR,
    DEPLOYMENT_LEDGER_FILE,
    DeploymentEvidenceLedger,
)
from rig_relay.publication._deployment_models import (
    AuthorizedPublicationTransitionPreparation,
    PublicationStatusContract,
    PublicationTransitionPhase,
    PublicationTransitionReceipt,
)
from rig_relay.publication._deployment_service import _available_actions, _phase_message

_DEFAULT_LEDGER_PATH = DEPLOYMENT_LEDGER_DIR / DEPLOYMENT_LEDGER_FILE


def _digest_sha256_raw(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"


def _compute_target_digest(owner: str, repo: str, branch: str) -> str:
    """Compute a content-light target identity digest from owner/repo/branch."""
    return _digest_sha256_raw(f"{owner}/{repo}/{branch}")


def _reconstruct_receipt(
    receipt_data: dict[str, Any],
) -> PublicationTransitionReceipt | None:
    try:
        return PublicationTransitionReceipt.model_validate(receipt_data)
    except Exception:
        return None


def _reconstruct_preparation(
    receipt: PublicationTransitionReceipt, *, target_identity_digest: str = ""
) -> AuthorizedPublicationTransitionPreparation:
    return AuthorizedPublicationTransitionPreparation(
        publication_operation_id=receipt.operation_id,
        preview_evidence_digest=receipt.preview_evidence_digest,
        preview_receipt_digest=receipt.preview_receipt_digest,
        static_bundle_digest=receipt.static_bundle_digest,
        target_repository_identity_digest=target_identity_digest,
        target_surface="project_page",
        authorization_required=True,
        preparation_digest=receipt.transition_preparation_digest,
    )


def _find_latest_receipt(
    receipts: list[dict[str, Any]], *, target_digest: str = ""
) -> dict[str, Any] | None:
    if not receipts:
        return None
    if target_digest:
        matching = [
            r for r in receipts if r.get("target_identity_digest", "") == target_digest
        ]
        if not matching:
            return None
        return max(matching, key=lambda r: r.get("deployed_at", ""))
    return max(receipts, key=lambda r: r.get("deployed_at", ""))


def build_publication_projection(
    ledger_path: str = "", *, owner: str = "", repo: str = "", branch: str = ""
) -> PublicationStatusContract:
    """Build an X0-consumable publication status projection from the evidence ledger.

    Reads the deployment evidence ledger and produces a PublicationStatusContract
    without requiring a full GitHubPagesDeploymentService instance. This is a
    read-only projection entry point that X0 can call directly.

    Content-light guarantee: no raw file contents, no secrets, no private code.
    Only status fields, digests, and the evidence ledger path are included.

    X3.8: target-scoped — filters receipts by owner/repo/branch when provided.
    """
    lp = Path(ledger_path) if ledger_path else _DEFAULT_LEDGER_PATH
    target_digest = (
        _compute_target_digest(owner, repo, branch) if owner and repo and branch else ""
    )
    repo_digest = _digest_sha256_raw(f"{owner}/{repo}") if owner and repo else ""

    ledger = DeploymentEvidenceLedger(ledger_path=lp)
    reconstruction = ledger.load_receipts(authoritative=False)
    receipts_raw = reconstruction.get("receipts", [])

    if not receipts_raw:
        empty_digest = _digest_sha256_raw(f"empty:{owner}:{repo}:{branch}")
        return PublicationStatusContract(
            publication_operation_id="",
            transition_phase=PublicationTransitionPhase.PREPARED.value,
            target_repository_digest=repo_digest,
            target_surface="project_page",
            authorization_required=True,
            authorization_status="pending",
            status_message=_phase_message(PublicationTransitionPhase.PREPARED.value),
            available_actions=_available_actions(
                PublicationTransitionPhase.PREPARED.value
            ),
            projection_digest=empty_digest,
            evidence_linkage={
                "terminal_receipt_digest": "",
                "evidence_ledger_path": str(lp),
                "projection_digest": empty_digest,
            },
        )

    latest_data = _find_latest_receipt(receipts_raw, target_digest=target_digest)
    if latest_data is None:
        no_match_digest = _digest_sha256_raw(f"no_target_match:{owner}:{repo}:{branch}")
        return PublicationStatusContract(
            publication_operation_id="",
            transition_phase=PublicationTransitionPhase.PREPARED.value
            if not target_digest
            else PublicationTransitionPhase.FAILED.value,
            target_repository_digest=repo_digest,
            target_surface="project_page",
            authorization_required=True,
            authorization_status="pending",
            status_message=_phase_message(
                PublicationTransitionPhase.PREPARED.value
                if not target_digest
                else PublicationTransitionPhase.FAILED.value
            ),
            available_actions=_available_actions(
                PublicationTransitionPhase.PREPARED.value
                if not target_digest
                else PublicationTransitionPhase.FAILED.value
            ),
            recovery_required=False,
            projection_digest=no_match_digest,
            evidence_linkage={
                "terminal_receipt_digest": "",
                "evidence_ledger_path": str(lp),
                "projection_digest": no_match_digest,
            },
        )

    receipt = _reconstruct_receipt(latest_data)
    evidence_target_digest = (
        latest_data.get("target_identity_digest", "") or repo_digest
    )
    evidence_target_surface = latest_data.get("target_surface", "project_page")

    if receipt is None:
        corrupt_digest = _digest_sha256_raw(
            f"{latest_data.get('operation_id', '')}:"
            f"{latest_data.get('transition_phase', '')}:"
            f"{latest_data.get('published_commit_sha', '')}:"
            f"{latest_data.get('build_commit_sha', '')}:"
            f"{latest_data.get('build_commit_matches_published', False)}:"
            f"{evidence_target_surface}"
        )
        return PublicationStatusContract(
            publication_operation_id=latest_data.get("operation_id", ""),
            transition_phase=latest_data.get(
                "transition_phase", PublicationTransitionPhase.FAILED.value
            ),
            target_repository_digest=evidence_target_digest,
            target_surface=evidence_target_surface,
            authorization_required=True,
            authorization_status="pending",
            pages_configured=latest_data.get("pages_created", False)
            or latest_data.get("pages_updated", False),
            content_published=latest_data.get("content_published", False),
            content_publication_mode=latest_data.get("git_publication_mode", "none"),
            published_commit_sha=latest_data.get("published_commit_sha", ""),
            build_status=latest_data.get("pages_build_status", ""),
            build_commit_sha=latest_data.get("build_commit_sha", ""),
            build_commit_matches_published=latest_data.get(
                "build_commit_matches_published", False
            ),
            published_verified=latest_data.get("remote_verified", False),
            refusal_code=latest_data.get("refusal_code"),
            recovery_required=latest_data.get("recovery_required", False),
            status_message=_phase_message(
                latest_data.get(
                    "transition_phase", PublicationTransitionPhase.FAILED.value
                )
            ),
            available_actions=_available_actions(
                latest_data.get(
                    "transition_phase", PublicationTransitionPhase.FAILED.value
                )
            ),
            terminal_receipt_digest=latest_data.get("evidence_digest", ""),
            projection_digest=corrupt_digest,
            evidence_linkage={
                "terminal_receipt_digest": latest_data.get("evidence_digest", ""),
                "evidence_ledger_path": str(lp),
                "projection_digest": corrupt_digest,
            },
        )

    prep = _reconstruct_preparation(
        receipt, target_identity_digest=evidence_target_digest
    )

    git_mode = receipt.git_publication_mode or "none"
    published_sha = receipt.published_commit_sha or ""
    build_sha = receipt.build_commit_sha or ""
    build_matches = receipt.build_commit_matches_published

    projection_digest = _digest_sha256_raw(
        f"{receipt.operation_id}:{receipt.transition_phase}:"
        f"{published_sha}:{build_sha}:{build_matches}:"
        f"{prep.target_surface}"
    )

    return PublicationStatusContract(
        publication_operation_id=receipt.operation_id,
        transition_phase=receipt.transition_phase,
        target_repository_digest=evidence_target_digest
        or prep.target_repository_identity_digest,
        target_surface=prep.target_surface,
        authorization_required=prep.authorization_required,
        authorization_status=(
            "accepted" if receipt.authorization_receipt_digest else "pending"
        ),
        pages_configured=receipt.pages_created or receipt.pages_updated,
        content_published=receipt.content_published,
        content_publication_mode=git_mode,
        published_commit_sha=published_sha,
        build_status=receipt.pages_build_status or "",
        build_commit_sha=build_sha,
        build_commit_matches_published=build_matches,
        published_verified=receipt.remote_verified,
        refusal_code=receipt.refusal_code,
        recovery_required=receipt.recovery_required,
        status_message=_phase_message(receipt.transition_phase),
        available_actions=_available_actions(receipt.transition_phase),
        projection_digest=projection_digest,
        terminal_receipt_digest=receipt.evidence_digest or "",
        evidence_linkage={
            "terminal_receipt_digest": receipt.evidence_digest or "",
            "evidence_ledger_path": str(lp),
            "projection_digest": projection_digest,
        },
    )


__all__ = ["build_publication_projection"]
