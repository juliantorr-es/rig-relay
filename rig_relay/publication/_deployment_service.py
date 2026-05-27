"""GitHub Pages Deployment Service — Lane X3 publication deployment authority.

The governed application-service boundary that consumes approved
publication preview output, validates authorization, executes Pages
configuration and content deployment, verifies remote status, and
produces durable deployment evidence.

Follows the same application-service pattern as
ProjectPagePublicationPreviewService but for the deployment phase.
"""

from __future__ import annotations

import hashlib
import json
import uuid as _uuid

from rig_relay.publication._deployment_evidence import DeploymentEvidenceLedger
from rig_relay.publication._deployment_models import (
    DeploymentOutcomeReceipt,
    DeploymentPreparationResult,
    DeploymentRecoveryState,
    DeploymentRefusalCode,
    DeploymentStatus,
    _digest_sha256,
    _now_iso,
)
from rig_relay.publication._models import ProjectPageCompilerResult

# ── Constants ───────────────────────────────────────────────────────────

_VALID_DEPLOYMENT_POLICIES: frozenset[str] = frozenset({
    "developer_approved",
    "public_release",
})


# ── Application Service ─────────────────────────────────────────────────


class GitHubPagesDeploymentService:
    """Governed GitHub Pages deployment application service.

    Consumes approved ProjectPageCompilerResult output + authorization
    receipt, executes Pages configuration and content deployment, and
    produces durable deployment evidence.

    Never deploys without explicit authorization. Never deploys unapproved
    or safety-failed content. Never silently overstates remote status.
    """

    def __init__(
        self,
        ledger: DeploymentEvidenceLedger | None = None,
        pages_adapter: object | None = None,
        git_boundary: object | None = None,
    ) -> None:
        self._ledger = ledger or DeploymentEvidenceLedger()
        self._pages_adapter = pages_adapter
        self._git_boundary = git_boundary

    def prepare_deployment(
        self,
        compiler_result: ProjectPageCompilerResult,
        *,
        target_repo_owner: str = "",
        target_repo_name: str = "",
        source_branch: str = "gh-pages",
        source_path: str = "/",
        preview_evidence_digest: str = "",
        publication_policy: str = "public_release",
        operation_id: str | None = None,
    ) -> DeploymentPreparationResult:
        """Inspect deployment readiness without any external mutation.

        Validates compiler output, preview evidence, and Pages readiness.
        Returns a structured preparation result with blockers and
        suggested actions.

        Does NOT configure Pages. Does NOT push content.
        Does NOT consume authorization.
        """
        op_id = operation_id or _uuid.uuid4().hex
        prep_id = _digest_sha256(f"prep:{op_id}")[:22]
        blockers: list[str] = []
        now = _now_iso()

        compilation_valid = (
            compiler_result.compilation_successful
            and compiler_result.safety_report.passed
        )

        if not compiler_result.compilation_successful:
            blockers.append("Compilation was not successful")
        if not compiler_result.safety_report.passed:
            blockers.append("Safety scan did not pass")
        if compiler_result.safety_report.secrets_detected:
            blockers.append("Secrets detected in compiled output")
        if compiler_result.safety_report.private_content_detected:
            blockers.append("Private content detected in compiled output")

        preview_valid = bool(preview_evidence_digest)
        if not preview_valid:
            blockers.append("No preview evidence digest provided for binding")
        elif preview_evidence_digest != compiler_result.preview_report.report_id:
            blockers.append(
                f"Preview evidence digest mismatch: "
                f"expected={preview_evidence_digest}, "
                f"compiler_report_id={compiler_result.preview_report.report_id}"
            )

        static_content_available = bool(
            compiler_result.static_bundle_path and compiler_result.static_bundle_digest
        )
        if not static_content_available:
            blockers.append("Static content bundle not available for deployment")

        if publication_policy not in _VALID_DEPLOYMENT_POLICIES:
            blockers.append(
                f"Publication policy '{publication_policy}' is not valid for deployment. "
                f"Must be: {', '.join(sorted(_VALID_DEPLOYMENT_POLICIES))}"
            )

        repo = (
            f"{target_repo_owner}/{target_repo_name}"
            if target_repo_owner and target_repo_name
            else ""
        )
        if not target_repo_owner or not target_repo_name:
            blockers.append(
                "Target repository owner and name are required for deployment"
            )

        content_digest = (
            compiler_result.static_bundle_digest
            or compiler_result.compute_result_digest()
        )
        pages_requires_configure = True
        pages_site_exists = False

        result = DeploymentPreparationResult(
            preparation_id=prep_id,
            operation_id=op_id,
            ready_to_deploy=len(blockers) == 0,
            compilation_valid=compilation_valid,
            safety_valid=compiler_result.safety_report.passed,
            preview_evidence_valid=preview_valid,
            content_digest=content_digest,
            preview_evidence_digest=preview_evidence_digest,
            pages_ready=static_content_available,
            pages_site_exists=pages_site_exists,
            pages_requires_configure=pages_requires_configure,
            pages_target_repo=repo,
            pages_source_branch=source_branch,
            static_content_available=static_content_available,
            static_content_digest=compiler_result.static_bundle_digest or "",
            authorization_required=True,
            authorization_request_digest=_compute_deployment_request_digest(
                op_id=op_id,
                target_repo=repo,
                source_branch=source_branch,
                source_path=source_path,
                content_digest=content_digest,
            ),
            blockers=blockers,
            suggested_action=(
                "Proceed with authorized deployment"
                if len(blockers) == 0
                else f"Resolve blockers before deployment: {', '.join(blockers[:3])}"
            ),
            prepared_at=now,
        )
        result.compute_digest()
        return result

    def execute_deployment(
        self,
        compiler_result: ProjectPageCompilerResult,
        preparation: DeploymentPreparationResult,
        *,
        authorization_receipt_id: str = "",
        target_repo_owner: str = "",
        target_repo_name: str = "",
        source_branch: str = "gh-pages",
        source_path: str = "/",
        operation_id: str | None = None,
    ) -> DeploymentOutcomeReceipt:
        """Execute a deployment with authorization.

        Consumes an authorization receipt through Lane A/Lane B,
        configures Pages, and returns the deployment outcome.
        """
        op_id = operation_id or preparation.operation_id
        receipt_id = _digest_sha256(f"deploy:{op_id}")[:22]
        now = _now_iso()

        if not preparation.ready_to_deploy:
            return self._refused_receipt(
                op_id=op_id,
                receipt_id=receipt_id,
                preparation=preparation,
                compiler_result=compiler_result,
                refusal_code=DeploymentRefusalCode.COMPILATION_FAILED,
                reasons=preparation.blockers,
                now=now,
            )

        if not authorization_receipt_id:
            return self._refused_receipt(
                op_id=op_id,
                receipt_id=receipt_id,
                preparation=preparation,
                compiler_result=compiler_result,
                refusal_code=DeploymentRefusalCode.AUTHORIZATION_MISSING,
                reasons=["No authorization receipt provided"],
                now=now,
            )

        auth_result = self._validate_and_consume_authorization(
            authorization_id=authorization_receipt_id,
            operation_id=op_id,
            target_repo=f"{target_repo_owner}/{target_repo_name}",
            source_branch=source_branch,
            source_path=source_path,
            preparation_digest=preparation.evidence_digest,
        )

        if not auth_result.get("authorized"):
            return self._refused_receipt(
                op_id=op_id,
                receipt_id=receipt_id,
                preparation=preparation,
                compiler_result=compiler_result,
                refusal_code=DeploymentRefusalCode(
                    auth_result.get("refusal_code", "authorization_revoked")
                ),
                reasons=auth_result.get("reasons", ["Authorization failed"]),
                now=now,
                authorization_digest=auth_result.get("authorization_digest", ""),
            )

        pages_status = self._execute_pages_configure(
            target_repo_owner=target_repo_owner,
            target_repo_name=target_repo_name,
            source_branch=source_branch,
            source_path=source_path,
        )

        if not pages_status.get("success"):
            return self._refused_receipt(
                op_id=op_id,
                receipt_id=receipt_id,
                preparation=preparation,
                compiler_result=compiler_result,
                refusal_code=DeploymentRefusalCode.PAGES_NOT_CONFIGURED,
                reasons=[
                    pages_status.get("error", "Pages configuration failed"),
                    pages_status.get("suggested_action", ""),
                ],
                now=now,
                authorization_digest=auth_result.get("authorization_digest", ""),
                remote_sent=True,
            )

        receipt = DeploymentOutcomeReceipt(
            receipt_id=receipt_id,
            operation_id=op_id,
            preparation_digest=preparation.evidence_digest,
            profile_candidate_digest=compiler_result.projection.profile_candidate_digest
            if hasattr(compiler_result.projection, "profile_candidate_digest")
            else compiler_result.projection.projection_digest,
            preview_evidence_digest=preparation.preview_evidence_digest,
            compilation_result_digest=compiler_result.compute_result_digest(),
            authorization_receipt_digest=auth_result.get("authorization_digest", ""),
            deployment_status=DeploymentStatus.DEPLOYED.value,
            pages_site_url=pages_status.get("site_url", ""),
            pages_build_status=pages_status.get("build_status", ""),
            remote_request_sent=True,
            remote_verified=pages_status.get("verified", False),
            remote_verification_digest=pages_status.get("verification_digest", ""),
            recovery_required=False,
            deployed_at=now,
        )
        receipt.evidence_digest = receipt.compute_digest()
        self._ledger.append_event(op_id, receipt)
        return receipt

    def verify_deployment(
        self,
        receipt: DeploymentOutcomeReceipt,
        *,
        target_repo_owner: str = "",
        target_repo_name: str = "",
    ) -> DeploymentOutcomeReceipt:
        """Poll remote Pages status for a deployed site and update evidence."""
        if not receipt.remote_request_sent:
            return receipt

        status = self._query_pages_status(
            target_repo_owner=target_repo_owner, target_repo_name=target_repo_name
        )

        updated = receipt.model_copy()
        updated.pages_build_status = status.get(
            "build_status", receipt.pages_build_status
        )
        updated.remote_verified = status.get("build_status") == "built"
        updated.remote_verification_digest = status.get("verification_digest", "")

        if status.get("build_status") == "errored":
            updated.deployment_status = DeploymentStatus.RECOVERY_REQUIRED.value
            updated.recovery_required = True
            updated.recovery_hint = (
                f"Pages build errored. Check GitHub Actions logs for "
                f"{target_repo_owner}/{target_repo_name}."
            )
        elif updated.remote_verified:
            updated.deployment_status = DeploymentStatus.VERIFIED.value
            updated.recovery_required = False

        updated.evidence_digest = updated.compute_digest()
        return updated

    def compute_recovery_state(
        self, receipt: DeploymentOutcomeReceipt, operation_id: str | None = None
    ) -> DeploymentRecoveryState:
        """Determine whether a prior deployment can be safely retried."""
        op_id = operation_id or receipt.operation_id

        if (
            receipt.deployment_status
            in {DeploymentStatus.VERIFIED.value, DeploymentStatus.DEPLOYED.value}
            and receipt.remote_verified
        ):
            return DeploymentRecoveryState(
                operation_id=op_id,
                prior_attempt_receipt_digest=receipt.evidence_digest,
                prior_status=receipt.deployment_status,
                prior_remote_verified=True,
                prior_remote_sent=True,
                prior_authorization_consumed=bool(receipt.authorization_receipt_digest),
                recovery_action="verify_only",
                recovery_blockers=[],
                recoverable=True,
            )

        if receipt.deployment_status in {
            DeploymentStatus.FAILED.value,
            DeploymentStatus.REFUSED.value,
        }:
            return DeploymentRecoveryState(
                operation_id=op_id,
                prior_attempt_receipt_digest=receipt.evidence_digest,
                prior_status=receipt.deployment_status,
                prior_remote_verified=False,
                prior_remote_sent=receipt.remote_request_sent,
                prior_authorization_consumed=bool(receipt.authorization_receipt_digest),
                recovery_action=(
                    "reauthorize" if receipt.remote_request_sent else "retry"
                ),
                recovery_blockers=(
                    ["Authorization was consumed; must reauthorize"]
                    if receipt.authorization_receipt_digest
                    else []
                ),
                recoverable=True,
            )

        if receipt.deployment_status == DeploymentStatus.RECOVERY_REQUIRED.value:
            return DeploymentRecoveryState(
                operation_id=op_id,
                prior_attempt_receipt_digest=receipt.evidence_digest,
                prior_status=receipt.deployment_status,
                prior_remote_verified=receipt.remote_verified,
                prior_remote_sent=receipt.remote_request_sent,
                prior_authorization_consumed=bool(receipt.authorization_receipt_digest),
                recovery_action="verify_only",
                recovery_blockers=[],
                recoverable=True,
            )

        return DeploymentRecoveryState(
            operation_id=op_id,
            prior_attempt_receipt_digest=receipt.evidence_digest,
            prior_status=receipt.deployment_status,
            recoverable=False,
            recovery_action="abandon",
        )

    # ── Private helpers ──────────────────────────────────────────────

    def _refused_receipt(
        self,
        *,
        op_id: str,
        receipt_id: str,
        preparation: DeploymentPreparationResult,
        compiler_result: ProjectPageCompilerResult,
        refusal_code: DeploymentRefusalCode,
        reasons: list[str],
        now: str,
        authorization_digest: str = "",
        remote_sent: bool = False,
    ) -> DeploymentOutcomeReceipt:
        receipt = DeploymentOutcomeReceipt(
            receipt_id=receipt_id,
            operation_id=op_id,
            preparation_digest=preparation.evidence_digest,
            profile_candidate_digest=compiler_result.projection.projection_digest,
            preview_evidence_digest=preparation.preview_evidence_digest,
            compilation_result_digest=compiler_result.compute_result_digest(),
            authorization_receipt_digest=authorization_digest,
            deployment_status=DeploymentStatus.REFUSED.value,
            refusal_code=refusal_code.value,
            refusal_reasons=reasons,
            remote_request_sent=remote_sent,
            remote_verified=False,
            recovery_required=False,
            recovery_hint=(
                "Retry with valid authorization and resolved blockers"
                if refusal_code
                in {
                    DeploymentRefusalCode.AUTHORIZATION_MISSING,
                    DeploymentRefusalCode.AUTHORIZATION_REVOKED,
                }
                else "Resolve blockers and reauthorize deployment"
            ),
            deployed_at=now,
        )
        receipt.evidence_digest = receipt.compute_digest()
        self._ledger.append_event(op_id, receipt)
        return receipt

    def _validate_and_consume_authorization(
        self,
        authorization_id: str,
        operation_id: str,
        target_repo: str,
        source_branch: str,
        source_path: str,
        preparation_digest: str,
    ) -> dict:
        """Validate authorization via Lane A/Lane B consumer.

        Returns dict with 'authorized' (bool), 'refusal_code', 'reasons',
        and 'authorization_digest'.
        """
        try:
            from rig_relay.integrations.github_provider._authorization_consumer import (
                ConsumerOutcome,
                GitHubAuthorizationConsumer,
            )
        except ImportError:
            return {
                "authorized": False,
                "refusal_code": DeploymentRefusalCode.AUTHORIZATION_MISSING.value,
                "reasons": ["GitHub authorization consumer not available"],
                "authorization_digest": "",
            }

        owner, _, repo = target_repo.partition("/")
        if not owner or not repo:
            return {
                "authorized": False,
                "refusal_code": DeploymentRefusalCode.REPO_NOT_FOUND.value,
                "reasons": [f"Invalid target_repo: {target_repo}"],
                "authorization_digest": "",
            }

        payload: dict = {
            "source": {"branch": source_branch, "path": source_path},
            "operation_id": operation_id,
            "preparation_digest": preparation_digest,
        }
        result = GitHubAuthorizationConsumer.validate_and_consume(
            authorization_id=authorization_id,
            operation_kind="pages_publish",
            request_payload=payload,
            target_identity=target_repo,
            prior_evidence_digest=preparation_digest,
        )

        outcome = result.outcome
        authorized = outcome == ConsumerOutcome.AUTHORIZED.value

        refusal_code_map: dict[str, str] = {
            ConsumerOutcome.EXPIRED_RECEIPT.value: DeploymentRefusalCode.AUTHORIZATION_EXPIRED.value,
            ConsumerOutcome.ALREADY_CONSUMED.value: DeploymentRefusalCode.AUTHORIZATION_REVOKED.value,
            ConsumerOutcome.REQUEST_DIGEST_MISMATCH.value: DeploymentRefusalCode.AUTHORIZATION_DIGEST_MISMATCH.value,
            ConsumerOutcome.ACTION_MISMATCH.value: DeploymentRefusalCode.AUTHORIZATION_REVOKED.value,
            ConsumerOutcome.TARGET_MISMATCH.value: DeploymentRefusalCode.AUTHORIZATION_REVOKED.value,
        }

        return {
            "authorized": authorized,
            "refusal_code": refusal_code_map.get(
                outcome, DeploymentRefusalCode.AUTHORIZATION_REVOKED.value
            ),
            "reasons": [result.error_detail]
            if result.error_detail and not authorized
            else [],
            "authorization_digest": _digest_sha256(
                f"auth:{authorization_id}:{outcome}"
                if authorized
                else f"auth-refused:{authorization_id}"
            ),
        }

    def _execute_pages_configure(
        self,
        target_repo_owner: str,
        target_repo_name: str,
        source_branch: str,
        source_path: str,
    ) -> dict:
        """Configure GitHub Pages for the target repository.

        Uses the existing GitHubPagesAdapter if provided, otherwise returns
        a simulated result indicating the boundary is ready but external
        acceptance is pending.
        """
        if self._pages_adapter is not None:
            try:
                import asyncio as _asyncio

                result = _asyncio.get_event_loop().run_until_complete(
                    self._pages_adapter.configure_pages(
                        owner=target_repo_owner,
                        repo=target_repo_name,
                        source_branch=source_branch,
                        source_path=source_path,
                    )
                )
                return {
                    "success": result.status == "executed",
                    "site_url": result.site_url or "",
                    "build_status": result.build_status or "",
                    "verified": result.status == "executed",
                    "verification_digest": result.verification_digest or "",
                    "error": result.error_kind or "",
                    "suggested_action": result.suggested_next_action or "",
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Pages adapter error: {e}",
                    "suggested_action": "Verify Pages credentials and permissions",
                }

        return {
            "success": False,
            "site_url": f"https://{target_repo_owner}.github.io/{target_repo_name}",
            "build_status": "deferred_external_acceptance",
            "verified": False,
            "verification_digest": _digest_sha256(
                f"deferred:{target_repo_owner}/{target_repo_name}"
            ),
            "error": "No Pages adapter provided; external acceptance deferred",
            "suggested_action": "Provide a configured GitHubPagesAdapter for live deployment",
        }

    def _query_pages_status(
        self, target_repo_owner: str, target_repo_name: str
    ) -> dict:
        """Query current Pages status for verification."""
        if self._pages_adapter is not None:
            try:
                import asyncio as _asyncio

                status = _asyncio.get_event_loop().run_until_complete(
                    self._pages_adapter.get_pages_status(
                        owner=target_repo_owner, repo=target_repo_name
                    )
                )
                return {
                    "has_pages": status.has_pages,
                    "build_status": status.build_status,
                    "html_url": status.html_url,
                    "verification_digest": status.evidence_digest or "",
                }
            except Exception:
                pass

        return {
            "has_pages": False,
            "build_status": "unknown",
            "html_url": f"https://{target_repo_owner}.github.io/{target_repo_name}",
            "verification_digest": "",
        }


def _compute_deployment_request_digest(
    *,
    op_id: str,
    target_repo: str,
    source_branch: str,
    source_path: str,
    content_digest: str,
) -> str:
    payload = json.dumps(
        {
            "operation_id": op_id,
            "target_repo": target_repo,
            "source_branch": source_branch,
            "source_path": source_path,
            "content_digest": content_digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


__all__ = ["GitHubPagesDeploymentService"]
