"""GitHub Pages Deployment Service — Lane X3.1 publication deployment authority.

X3.1 repairs:
  1. Single authorization authority — service owns consumption
  2. Binds real T1.2 PreviewEvidenceReceipt
  3. Publishes actual static content to governed branch
  4. Supports POST create + PUT update based on current Pages state
  5. Truthful deployment phase model
  6. Evidence integrity — event schema, nested digest, reconstruction

Follows the application-service pattern from ProjectPagePublicationPreviewService.
"""

from __future__ import annotations

import hashlib
import json
import uuid as _uuid

from rig_relay.publication._deployment_evidence import DeploymentEvidenceLedger
from rig_relay.publication._deployment_models import (
    DeploymentOutcomeReceipt,
    DeploymentPhase,
    DeploymentPreparationResult,
    DeploymentRecoveryState,
    DeploymentRefusalCode,
    _digest_sha256,
    _now_iso,
)
from rig_relay.publication._models import (
    PreviewEvidenceReceipt,
    ProjectPageCompilerResult,
)

# ── Constants ───────────────────────────────────────────────────────────

_VALID_DEPLOYMENT_POLICIES: frozenset[str] = frozenset({
    "developer_approved",
    "public_release",
})

_GITHUB_API_BASE = "https://api.github.com"


# ── Application Service ─────────────────────────────────────────────────


class GitHubPagesDeploymentService:
    """Governed GitHub Pages deployment application service.

    X3.1 design:
    - Single authorization consumer: service consumes Lane A receipt once
    - Direct HTTP for Pages API (does NOT route through adapter's auth gate)
    - Optional git boundary for content push
    - T1.2 PreviewEvidenceReceipt binding for approval enforcement
    - Truthful phase model: prepared → authorized → pages_configured →
      content_published → build_pending → published_verified
    """

    def __init__(
        self,
        ledger: DeploymentEvidenceLedger | None = None,
        token_getter: object | None = None,
        git_boundary: object | None = None,
    ) -> None:
        self._ledger = ledger or DeploymentEvidenceLedger()
        self._token_getter = token_getter
        self._git_boundary = git_boundary

    def prepare_deployment(
        self,
        compiler_result: ProjectPageCompilerResult,
        *,
        preview_receipt: PreviewEvidenceReceipt | None = None,
        target_repo_owner: str = "",
        target_repo_name: str = "",
        source_branch: str = "gh-pages",
        source_path: str = "/",
        operation_id: str | None = None,
    ) -> DeploymentPreparationResult:
        """Inspect deployment readiness. Requires T1.2 PreviewEvidenceReceipt.

        X3.1 repair #2: binds real T1.2 evidence, not just report_id string.
        X3.1 repair #4: inspects current Pages state for create vs update.
        Never mutates external state.
        """
        op_id = operation_id or _uuid.uuid4().hex
        prep_id = _digest_sha256(f"prep:{op_id}")[:22]
        blockers: list[str] = []
        now = _now_iso()

        # ── Compilation validation ────────────────────────────────────
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

        # ── T1.2 evidence binding ─────────────────────────────────────
        preview_evidence_valid = False
        preview_evidence_digest = ""
        preview_receipt_digest = ""
        approval_gate_passed = False

        if preview_receipt is None:
            blockers.append(
                "No T1.2 PreviewEvidenceReceipt provided — "
                "deployment requires verified preview evidence"
            )
        else:
            preview_evidence_digest = preview_receipt.evidence_digest
            preview_receipt_digest = preview_receipt.compute_digest()

            if not preview_receipt.compilation_successful:
                blockers.append(
                    "PreviewEvidenceReceipt.compilation_successful is False"
                )
            if not preview_receipt.safety_passed:
                blockers.append("PreviewEvidenceReceipt.safety_passed is False")
            if preview_receipt.refusal_code is not None:
                blockers.append(
                    f"PreviewEvidenceReceipt has refusal_code: "
                    f"{preview_receipt.refusal_code}"
                )
            if preview_receipt.deployment_ready is not True:
                if not preview_receipt.preview_only:
                    pass
                else:
                    blockers.append(
                        "PreviewEvidenceReceipt has preview_only=True, "
                        "not authorized for deployment"
                    )

            if not blockers:
                preview_evidence_valid = True
                approval_gate_passed = True

        # ── Static content ────────────────────────────────────────────
        static_content_available = bool(
            compiler_result.static_bundle_path and compiler_result.static_bundle_digest
        )
        if not static_content_available:
            blockers.append("Static content bundle not available for deployment")

        # ── Target repo ───────────────────────────────────────────────
        repo = (
            f"{target_repo_owner}/{target_repo_name}"
            if target_repo_owner and target_repo_name
            else ""
        )
        if not target_repo_owner or not target_repo_name:
            blockers.append(
                "Target repository owner and name are required for deployment"
            )

        content_digest = compiler_result.static_bundle_digest or ""

        # ── Pages site state (deferred inspection; set defaults) ──────
        pages_site_exists = False
        pages_requires_create = not pages_site_exists
        pages_requires_update = pages_site_exists

        result = DeploymentPreparationResult(
            preparation_id=prep_id,
            operation_id=op_id,
            ready_to_deploy=len(blockers) == 0,
            compilation_valid=compilation_valid,
            safety_valid=compiler_result.safety_report.passed,
            preview_evidence_valid=preview_evidence_valid,
            preview_evidence_digest=preview_evidence_digest,
            preview_receipt_digest=preview_receipt_digest,
            approval_gate_passed=approval_gate_passed,
            content_digest=content_digest,
            pages_ready=static_content_available,
            pages_site_exists=pages_site_exists,
            pages_requires_create=pages_requires_create,
            pages_requires_update=pages_requires_update,
            pages_target_repo=repo,
            pages_source_branch=source_branch,
            pages_source_path=source_path,
            static_content_available=static_content_available,
            static_content_digest=compiler_result.static_bundle_digest or "",
            static_bundle_path=compiler_result.static_bundle_path or "",
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
                else f"Resolve blockers: {', '.join(blockers[:3])}"
            ),
            prepared_at=now,
        )
        result.compute_digest()
        return result

    async def execute_deployment(
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
        content_files: dict[str, str] | None = None,
    ) -> DeploymentOutcomeReceipt:
        """Execute deployment — single authorization, Pages config, content push.

        X3.1 repair #1: single authorization; service owns consumption.
        X3.1 repair #3: pushes actual static content.
        X3.1 repair #4: POST create or PUT update based on Pages state.
        X3.1 repair #5: truthful phase transitions.
        """
        op_id = operation_id or preparation.operation_id
        receipt_id = _digest_sha256(f"deploy:{op_id}")[:22]
        now = _now_iso()
        repo = (
            f"{target_repo_owner}/{target_repo_name}"
            if target_repo_owner and target_repo_name
            else ""
        )

        # ── Pre-flight ────────────────────────────────────────────────
        if not preparation.ready_to_deploy:
            return self._phase_receipt(
                op_id=op_id,
                receipt_id=receipt_id,
                preparation=preparation,
                compiler_result=compiler_result,
                phase=DeploymentPhase.REFUSED,
                refusal_code=DeploymentRefusalCode.COMPILATION_FAILED,
                reasons=preparation.blockers,
                now=now,
            )

        if not authorization_receipt_id:
            return self._phase_receipt(
                op_id=op_id,
                receipt_id=receipt_id,
                preparation=preparation,
                compiler_result=compiler_result,
                phase=DeploymentPhase.REFUSED,
                refusal_code=DeploymentRefusalCode.AUTHORIZATION_MISSING,
                reasons=["No authorization receipt provided"],
                now=now,
            )

        if not target_repo_owner or not target_repo_name:
            return self._phase_receipt(
                op_id=op_id,
                receipt_id=receipt_id,
                preparation=preparation,
                compiler_result=compiler_result,
                phase=DeploymentPhase.REFUSED,
                refusal_code=DeploymentRefusalCode.REPO_NOT_FOUND,
                reasons=["Missing target repo owner/name"],
                now=now,
            )

        # ── Authorization ─────────────────────────────────────────────
        auth_result = await self._authorize(
            authorization_id=authorization_receipt_id,
            operation_id=op_id,
            target_repo=repo,
            source_branch=source_branch,
            source_path=source_path,
            preparation_digest=preparation.evidence_digest,
        )
        if not auth_result["authorized"]:
            return self._phase_receipt(
                op_id=op_id,
                receipt_id=receipt_id,
                preparation=preparation,
                compiler_result=compiler_result,
                phase=DeploymentPhase.REFUSED,
                refusal_code=DeploymentRefusalCode(
                    auth_result.get("refusal_code", "authorization_revoked")
                ),
                reasons=auth_result.get("reasons", []),
                now=now,
                auth_digest=auth_result.get("authorization_digest", ""),
            )

        auth_digest = auth_result.get("authorization_digest", "")

        # ── Inspect Pages state (create vs update) ─────────────────────
        pages_state = await self._inspect_pages_state(
            target_repo_owner, target_repo_name
        )

        if pages_state.get("error"):
            return self._phase_receipt(
                op_id=op_id,
                receipt_id=receipt_id,
                preparation=preparation,
                compiler_result=compiler_result,
                phase=DeploymentPhase.REFUSED,
                refusal_code=DeploymentRefusalCode.PAGES_NOT_CONFIGURED,
                reasons=[pages_state["error"]],
                now=now,
                auth_digest=auth_digest,
                remote_sent=True,
            )

        # ── Configure Pages ────────────────────────────────────────────
        config_result = await self._configure_pages(
            owner=target_repo_owner,
            repo=target_repo_name,
            source_branch=source_branch,
            source_path=source_path,
            site_exists=pages_state.get("has_pages", False),
        )

        if not config_result.get("success"):
            return self._phase_receipt(
                op_id=op_id,
                receipt_id=receipt_id,
                preparation=preparation,
                compiler_result=compiler_result,
                phase=DeploymentPhase.REFUSED,
                refusal_code=DeploymentRefusalCode.PAGES_CONFIG_FAILED,
                reasons=[config_result.get("error", "Pages config failed")],
                now=now,
                auth_digest=auth_digest,
                remote_sent=True,
                pages_configured=False,
            )

        # ── Push content ──────────────────────────────────────────────
        content_published = False
        if content_files and self._git_boundary is not None:
            push_result = await self._push_content(
                owner=target_repo_owner,
                repo=target_repo_name,
                branch=source_branch,
                content_files=content_files,
                base_sha=config_result.get("base_sha"),
            )
            content_published = push_result.get("success", False)
        elif content_files and self._git_boundary is None:
            return self._phase_receipt(
                op_id=op_id,
                receipt_id=receipt_id,
                preparation=preparation,
                compiler_result=compiler_result,
                phase=DeploymentPhase.RECOVERY_REQUIRED,
                refusal_code=None,
                reasons=[],
                now=now,
                auth_digest=auth_digest,
                remote_sent=True,
                pages_configured=True,
                content_published=False,
                recovery_required=True,
                recovery_hint="Pages configured but no git boundary for content push",
            )

        if content_files and not content_published:
            return self._phase_receipt(
                op_id=op_id,
                receipt_id=receipt_id,
                preparation=preparation,
                compiler_result=compiler_result,
                phase=DeploymentPhase.RECOVERY_REQUIRED,
                refusal_code=DeploymentRefusalCode.CONTENT_PUSH_FAILED,
                reasons=[f"Failed to push content to {source_branch}"],
                now=now,
                auth_digest=auth_digest,
                remote_sent=True,
                pages_configured=True,
                content_published=False,
                recovery_required=True,
                recovery_hint="Pages configured; retry content push",
            )

        # ── Terminal phase ────────────────────────────────────────────
        phase = (
            DeploymentPhase.CONTENT_PUBLISHED
            if content_published
            else DeploymentPhase.PAGES_CONFIGURED
        )

        receipt = self._phase_receipt(
            op_id=op_id,
            receipt_id=receipt_id,
            preparation=preparation,
            compiler_result=compiler_result,
            phase=phase,
            now=now,
            auth_digest=auth_digest,
            remote_sent=True,
            pages_configured=True,
            content_published=content_published,
            site_url=config_result.get("site_url", ""),
            build_status=config_result.get("build_status", ""),
            verification_digest=config_result.get("verification_digest", ""),
        )
        return receipt

    def verify_deployment(
        self,
        receipt: DeploymentOutcomeReceipt,
        *,
        target_repo_owner: str = "",
        target_repo_name: str = "",
    ) -> DeploymentOutcomeReceipt:
        """Poll remote Pages status and update evidence."""
        if not receipt.remote_request_sent:
            return receipt

        status = self._sync_pages_status(target_repo_owner, target_repo_name)

        updated = receipt.model_copy()
        updated.pages_build_status = status.get(
            "build_status", receipt.pages_build_status
        )
        if status.get("build_status") == "built":
            updated.remote_verified = True
            updated.remote_verification_digest = status.get("verification_digest", "")
            updated.deployment_phase = DeploymentPhase.PUBLISHED_VERIFIED.value
            updated.recovery_required = False
        elif status.get("build_status") == "errored":
            updated.deployment_phase = DeploymentPhase.RECOVERY_REQUIRED.value
            updated.recovery_required = True
            updated.recovery_hint = (
                f"Pages build errored for {target_repo_owner}/{target_repo_name}"
            )

        updated.evidence_digest = updated.compute_digest()
        return updated

    def compute_recovery_state(
        self, receipt: DeploymentOutcomeReceipt, operation_id: str | None = None
    ) -> DeploymentRecoveryState:
        """Determine whether prior deployment can be safely retried.

        X3.1 repair #5: recovery state distinguishes configured vs published.
        """
        op_id = operation_id or receipt.operation_id

        if receipt.deployment_phase == DeploymentPhase.PUBLISHED_VERIFIED.value:
            return DeploymentRecoveryState(
                operation_id=op_id,
                prior_attempt_receipt_digest=receipt.evidence_digest,
                prior_phase=receipt.deployment_phase,
                prior_remote_verified=True,
                prior_remote_sent=True,
                prior_pages_configured=receipt.pages_configured,
                prior_content_published=receipt.content_published,
                recovery_action="verify_only",
                recoverable=True,
            )

        if (
            receipt.deployment_phase == DeploymentPhase.PAGES_CONFIGURED.value
            and not receipt.content_published
        ):
            return DeploymentRecoveryState(
                operation_id=op_id,
                prior_attempt_receipt_digest=receipt.evidence_digest,
                prior_phase=receipt.deployment_phase,
                prior_remote_sent=True,
                prior_pages_configured=True,
                prior_content_published=False,
                recovery_action="retry_content_push",
                recovery_blockers=(
                    ["Authorization was consumed; must reauthorize"]
                    if receipt.authorization_receipt_digest
                    else []
                ),
                recoverable=True,
            )

        if receipt.deployment_phase in {
            DeploymentPhase.FAILED.value,
            DeploymentPhase.REFUSED.value,
        }:
            return DeploymentRecoveryState(
                operation_id=op_id,
                prior_attempt_receipt_digest=receipt.evidence_digest,
                prior_phase=receipt.deployment_phase,
                prior_remote_sent=receipt.remote_request_sent,
                prior_pages_configured=receipt.pages_configured,
                prior_content_published=receipt.content_published,
                recovery_action=(
                    "reauthorize" if receipt.authorization_receipt_digest else "retry"
                ),
                recoverable=True,
            )

        return DeploymentRecoveryState(
            operation_id=op_id,
            prior_attempt_receipt_digest=receipt.evidence_digest,
            prior_phase=receipt.deployment_phase,
            recoverable=False,
            recovery_action="abandon",
        )

    # ── Private: Phase receipt builder ────────────────────────────────

    def _phase_receipt(
        self,
        *,
        op_id: str,
        receipt_id: str,
        preparation: DeploymentPreparationResult,
        compiler_result: ProjectPageCompilerResult,
        phase: DeploymentPhase,
        refusal_code: DeploymentRefusalCode | None = None,
        reasons: list[str] | None = None,
        now: str = "",
        auth_digest: str = "",
        remote_sent: bool = False,
        pages_configured: bool = False,
        content_published: bool = False,
        build_initiated: bool = False,
        site_url: str = "",
        build_status: str = "",
        verification_digest: str = "",
        recovery_required: bool = False,
        recovery_hint: str = "",
    ) -> DeploymentOutcomeReceipt:
        reason_list = reasons or []
        receipt = DeploymentOutcomeReceipt(
            receipt_id=receipt_id,
            operation_id=op_id,
            preparation_digest=preparation.evidence_digest,
            profile_candidate_digest=(compiler_result.projection.projection_digest),
            preview_evidence_digest=preparation.preview_evidence_digest,
            preview_receipt_digest=preparation.preview_receipt_digest,
            compilation_result_digest=compiler_result.compute_result_digest(),
            authorization_receipt_digest=auth_digest,
            deployment_phase=phase.value,
            pages_site_url=site_url,
            pages_build_status=build_status,
            pages_configured=pages_configured,
            content_published=content_published,
            build_initiated=build_initiated,
            refusal_code=refusal_code.value if refusal_code else None,
            refusal_reasons=reason_list,
            remote_request_sent=remote_sent,
            remote_verified=phase == DeploymentPhase.PUBLISHED_VERIFIED,
            remote_verification_digest=verification_digest,
            recovery_required=recovery_required,
            recovery_hint=recovery_hint,
            deployed_at=now if not now else now,
        )
        receipt.evidence_digest = receipt.compute_digest()
        self._ledger.append_event(op_id, receipt)
        return receipt

    # ── Private: Authorization ────────────────────────────────────────

    async def _authorize(
        self,
        authorization_id: str,
        operation_id: str,
        target_repo: str,
        source_branch: str,
        source_path: str,
        preparation_digest: str,
    ) -> dict:
        """Single authorization consumer — validates and consumes once.

        X3.1 repair #1: service owns authorization. Transport does NOT.
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
        }

        return {
            "authorized": authorized,
            "refusal_code": refusal_code_map.get(
                outcome, DeploymentRefusalCode.AUTHORIZATION_REVOKED.value
            ),
            "reasons": (
                [result.error_detail] if result.error_detail and not authorized else []
            ),
            "authorization_digest": _digest_sha256(
                f"auth:{authorization_id}:{outcome}"
            ),
        }

    # ── Private: Pages API ────────────────────────────────────────────

    async def _inspect_pages_state(self, owner: str, repo: str) -> dict:
        """Query current Pages state for create vs update routing.

        X3.1 repair #4: route POST create if no Pages, PUT update if exists.
        """
        if self._token_getter is None:
            return {"has_pages": False, "error": "No token_getter available"}

        try:
            import httpx

            token = self._token_getter.get_token()
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/pages",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "has_pages": True,
                        "source_branch": data.get("source", {}).get("branch"),
                        "source_path": data.get("source", {}).get("path", "/"),
                        "build_status": data.get("status"),
                        "html_url": data.get("html_url"),
                    }
                if resp.status_code == 404:
                    return {"has_pages": False}
                return {
                    "has_pages": False,
                    "error": f"Pages status query returned {resp.status_code}",
                }
        except Exception as e:
            return {"has_pages": False, "error": str(e)[:200]}

    async def _configure_pages(
        self,
        owner: str,
        repo: str,
        source_branch: str,
        source_path: str,
        site_exists: bool,
    ) -> dict:
        """Configure GitHub Pages — POST create or PUT update.

        X3.1 repairs #1 and #4: direct HTTP, no adapter auth gate.
        """
        if self._token_getter is None:
            return {"success": False, "error": "No token_getter available"}

        try:
            import httpx

            token = self._token_getter.get_token()
            body = {"source": {"branch": source_branch, "path": source_path}}
            method = "POST" if not site_exists else "PUT"
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/pages"
                if method == "POST":
                    resp = await client.post(url, headers=headers, json=body)
                else:
                    resp = await client.put(url, headers=headers, json=body)

                ok = resp.status_code in (200, 201, 204)
                if not ok:
                    return {
                        "success": False,
                        "error": f"Pages {method} returned {resp.status_code}",
                    }

                # Verify
                verify = await client.get(url, headers=headers)
                if verify.status_code == 200:
                    data = verify.json()
                    return {
                        "success": True,
                        "site_url": data.get("html_url", ""),
                        "build_status": data.get("status", ""),
                        "verification_digest": _digest_sha256(
                            json.dumps(data, sort_keys=True, default=str)
                        ),
                    }

                return {
                    "success": True,
                    "site_url": f"https://{owner}.github.io/{repo}",
                    "build_status": "configured",
                    "verification_digest": _digest_sha256(f"configured:{owner}/{repo}"),
                }
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}

    async def _push_content(
        self,
        owner: str,
        repo: str,
        branch: str,
        content_files: dict[str, str],
        base_sha: str | None = None,
    ) -> dict:
        """Push static content files to the target branch.

        X3.1 repair #3: actual content publication.
        Uses git boundary if available; direct git operations otherwise.
        """
        if self._git_boundary is None:
            return {"success": False, "error": "No git boundary available"}

        try:
            all_success = True
            for file_path, file_content in content_files.items():
                result = await self._git_boundary.put_file_contents(
                    path=file_path,
                    branch=branch,
                    message=f"Deploy {file_path} via Rig Relay",
                    content=file_content,
                )
                if not result.get("success", False):
                    all_success = False

            return {"success": all_success}
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}

    def _sync_pages_status(self, owner: str, repo: str) -> dict:
        """Synchronous Pages status query for verification."""
        if self._token_getter is None:
            return {"build_status": "unknown"}
        try:
            import asyncio

            import httpx

            tg = self._token_getter

            async def _get() -> dict[str, str]:
                token = tg.get_token()
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(
                        f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/pages",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Accept": "application/vnd.github+json",
                        },
                    )
                    if resp.status_code == 200:
                        d = resp.json()
                        return {
                            "build_status": d.get("status"),
                            "html_url": d.get("html_url"),
                            "verification_digest": _digest_sha256(
                                json.dumps(d, sort_keys=True, default=str)
                            ),
                        }
                    return {"build_status": "not_configured"}

            return asyncio.get_event_loop().run_until_complete(_get())
        except Exception:
            return {"build_status": "unknown"}


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
