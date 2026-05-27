"""GitHub Pages Deployment Service — Lane X3.2 publication deployment authority.

X3.2 architecture (Gates A-D):
  Gate A: Accepts genuine T1.2 preview receipts (preview_only=True).
          Creates AuthorizedPublicationTransitionPreparation as the bridge.
  Gate B: Enforces digest-bound static content through
          ApprovedStaticPublicationBundle. Records ContentPublicationManifest.
          Refuses content substitution. Recovery on partial push.
  Gate C: Single authorization owner. Create/update/no-change Pages routing.
          Full truthful phase model: prepared → authorized → pages_* →
          content_* → build_* → published_verified.
  Gate D: Linked state-transition events in evidence ledger.
          Verification transitions durably appended.
"""

from __future__ import annotations

import json
import uuid as _uuid

from rig_relay.publication._deployment_evidence import DeploymentEvidenceLedger
from rig_relay.publication._deployment_models import (
    ApprovedStaticPublicationBundle,
    AuthorizedPublicationTransitionPreparation,
    ContentPublicationManifest,
    DeploymentRefusalCode,
    PublicationStatusContract,
    PublicationTransitionPhase,
    PublicationTransitionReceipt,
    _digest_sha256,
    _now_iso,
)
from rig_relay.publication._models import (
    PreviewEvidenceReceipt,
    ProjectPageCompilerResult,
)

_GITHUB_API_BASE = "https://api.github.com"


class GitHubPagesDeploymentService:
    """Governed GitHub Pages deployment application service.

    X3.2: Accepts genuine T1.2 preview-only receipts and creates
    separately authorized publication transitions.
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

    # ── Gate A: Publication Transition Preparation ─────────────────────

    def prepare_transition(
        self,
        compiler_result: ProjectPageCompilerResult,
        *,
        preview_receipt: PreviewEvidenceReceipt,
        target_repo_owner: str = "",
        target_repo_name: str = "",
        source_branch: str = "gh-pages",
        source_path: str = "/",
        target_surface: str = "project_page",
        publication_operation_id: str | None = None,
    ) -> AuthorizedPublicationTransitionPreparation:
        """Gate A: Validate T1.2 preview receipt and create transition preparation.

        Accepts genuine T1.2 receipts with preview_only=True,
        deployment_ready=False. These are NOT blockers — they are
        required producer truth.

        Returns a preparation that authorization must bind to.
        Refuses on missing/invalid preview evidence.
        """
        op_id = publication_operation_id or _uuid.uuid4().hex
        now = _now_iso()

        if preview_receipt is None:
            raise ValueError("T1.2 PreviewEvidenceReceipt is required")

        verified = self._verify_t12_receipt(preview_receipt, compiler_result)
        if not verified["valid"]:
            raise ValueError(
                f"Preview evidence invalid: {'; '.join(verified['reasons'])}"
            )

        bundle = ApprovedStaticPublicationBundle.from_compiler_result(
            compiler_result, target_surface=target_surface
        )

        repo_id = _digest_sha256(f"{target_repo_owner}/{target_repo_name}")
        bundle_digest = (
            bundle.content_digest
            if bundle and not bundle.is_empty()
            else _digest_sha256(f"no-content:{op_id}")
        )

        prep = AuthorizedPublicationTransitionPreparation(
            publication_operation_id=op_id,
            preview_operation_id=getattr(preview_receipt, "receipt_id", ""),
            preview_evidence_digest=preview_receipt.evidence_digest,
            preview_receipt_digest=preview_receipt.compute_digest(),
            preview_result_digest=preview_receipt.result_digest or "",
            static_bundle_digest=bundle_digest,
            target_repository_identity_digest=repo_id,
            target_surface=target_surface,
            source_branch=source_branch,
            source_path=source_path,
            requested_pages_action="configure_and_deploy",
            publication_policy="public_release",
            authorization_required=True,
            created_at=now,
        )
        prep.compute_digest()
        return prep

    def _verify_t12_receipt(
        self,
        receipt: PreviewEvidenceReceipt,
        compiler_result: ProjectPageCompilerResult,
    ) -> dict:
        """Verify T1.2 preview receipt integrity and safety state.

        X3.2: preview_only=True and deployment_ready=False are NOT blockers.
        They are required T1.2 producer truth.
        """
        reasons: list[str] = []

        stored_digest = receipt.evidence_digest
        computed_digest = receipt.compute_digest()
        if stored_digest and stored_digest != computed_digest:
            reasons.append(
                f"Receipt evidence_digest mismatch: stored={stored_digest[:20]}..., "
                f"computed={computed_digest[:20]}..."
            )

        if not receipt.compilation_successful:
            reasons.append("compilation_successful is False")
        if not receipt.safety_passed:
            reasons.append("safety_passed is False")
        if receipt.refusal_code is not None:
            reasons.append(f"refusal_code present: {receipt.refusal_code}")

        result_digest = receipt.result_digest
        compiler_digest = compiler_result.compute_result_digest()
        if result_digest and result_digest != compiler_digest:
            reasons.append(
                f"result_digest mismatch: receipt={result_digest[:20]}..., "
                f"compiler={compiler_digest[:20]}..."
            )

        return {"valid": len(reasons) == 0, "reasons": reasons}

    # ── Gate B: Digest-Bound Content Verification ──────────────────────

    def validate_bundle(
        self,
        bundle: ApprovedStaticPublicationBundle,
        transition_prep: AuthorizedPublicationTransitionPreparation,
    ) -> dict:
        """Gate B: Verify bundle integrity and path safety before publication.

        Returns dict with 'valid', 'reasons', 'content_digest'.
        """
        reasons: list[str] = []

        if bundle.is_empty():
            reasons.append("Bundle has no files")
        else:
            computed = bundle.compute_content_digest()
            if computed != transition_prep.static_bundle_digest:
                reasons.append(
                    f"Bundle content_digest mismatch: "
                    f"computed={computed[:20]}..., "
                    f"expected={transition_prep.static_bundle_digest[:20]}..."
                )

        path_violations = bundle.validate_paths()
        if path_violations:
            reasons.extend(path_violations)

        return {
            "valid": len(reasons) == 0,
            "reasons": reasons,
            "content_digest": bundle.content_digest,
        }

    # ── Publication Execute ────────────────────────────────────────────

    async def execute_publication(
        self,
        transition_prep: AuthorizedPublicationTransitionPreparation,
        bundle: ApprovedStaticPublicationBundle | None = None,
        *,
        authorization_receipt_id: str = "",
        target_repo_owner: str = "",
        target_repo_name: str = "",
        content_files: dict[str, str] | None = None,
    ) -> PublicationTransitionReceipt:
        """Execute the full publication transition.

        Gate A: transition_prep must be valid.
        Gate B: bundle content must match preparation digest.
        Gate C: authorize, configure Pages (create/update/no-change),
                publish content, verify.
        Gate D: phase receipts durably appended.
        """
        op_id = transition_prep.publication_operation_id
        now = _now_iso()

        bundle_obj = bundle
        if content_files and not bundle_obj:
            builder = ApprovedStaticPublicationBundle(
                files=content_files,
                preview_result_digest=transition_prep.preview_result_digest,
                preparation_digest=transition_prep.preparation_digest,
                target_surface=transition_prep.target_surface,
            )
            builder.compute_content_digest()
            bundle_obj = builder

        if bundle_obj:
            validation = self.validate_bundle(bundle_obj, transition_prep)
            if not validation["valid"]:
                return self._record_phase(
                    op_id=op_id,
                    prep=transition_prep,
                    phase=PublicationTransitionPhase.REFUSED,
                    refusal=DeploymentRefusalCode.BUNDLE_DIGEST_MISMATCH,
                    reasons=validation["reasons"],
                    now=now,
                )

        if not authorization_receipt_id:
            return self._record_phase(
                op_id=op_id,
                prep=transition_prep,
                phase=PublicationTransitionPhase.REFUSED,
                refusal=DeploymentRefusalCode.AUTHORIZATION_MISSING,
                reasons=["No authorization receipt provided"],
                now=now,
            )

        if not target_repo_owner or not target_repo_name:
            return self._record_phase(
                op_id=op_id,
                prep=transition_prep,
                phase=PublicationTransitionPhase.REFUSED,
                refusal=DeploymentRefusalCode.REPO_NOT_FOUND,
                reasons=["Missing target repo"],
                now=now,
            )

        auth_result = await self._authorize_transition(
            authorization_id=authorization_receipt_id, transition_prep=transition_prep
        )
        if not auth_result["authorized"]:
            return self._record_phase(
                op_id=op_id,
                prep=transition_prep,
                phase=PublicationTransitionPhase.REFUSED,
                refusal=DeploymentRefusalCode(
                    auth_result.get("refusal_code", "authorization_revoked")
                ),
                reasons=auth_result.get("reasons", []),
                now=now,
                auth_digest=auth_result.get("authorization_digest", ""),
            )

        auth_digest = auth_result["authorization_digest"]

        # ── Inspect Pages state ───────────────────────────────────────
        pages_state = await self._inspect_pages_state(
            target_repo_owner, target_repo_name
        )
        has_pages = pages_state.get("has_pages", False)
        current_branch = pages_state.get("source_branch", "")
        source_branch = transition_prep.source_branch

        if pages_state.get("error"):
            return self._record_phase(
                op_id=op_id,
                prep=transition_prep,
                phase=PublicationTransitionPhase.REFUSED,
                refusal=DeploymentRefusalCode.PAGES_NOT_CONFIGURED,
                reasons=[pages_state["error"]],
                now=now,
                auth_digest=auth_digest,
            )

        # ── Configure Pages (create/update/no-change) ─────────────────
        pages_created = False
        pages_updated = False
        cfg_result: dict = {"success": False, "site_url": "", "verification_digest": ""}

        if not has_pages:
            cfg = await self._configure_pages(
                target_repo_owner,
                target_repo_name,
                source_branch,
                transition_prep.source_path,
                site_exists=False,
            )
            cfg_result = cfg
            if not cfg_result.get("success"):
                return self._record_phase(
                    op_id=op_id,
                    prep=transition_prep,
                    phase=PublicationTransitionPhase.REFUSED,
                    refusal=DeploymentRefusalCode.PAGES_CREATE_FAILED,
                    reasons=[cfg_result.get("error", "Pages create failed")],
                    now=now,
                    auth_digest=auth_digest,
                )
            pages_created = True
            pages_phase = PublicationTransitionPhase.PAGES_CREATED
        elif current_branch != source_branch:
            cfg = await self._configure_pages(
                target_repo_owner,
                target_repo_name,
                source_branch,
                transition_prep.source_path,
                site_exists=True,
            )
            cfg_result = cfg
            if not cfg_result.get("success"):
                return self._record_phase(
                    op_id=op_id,
                    prep=transition_prep,
                    phase=PublicationTransitionPhase.REFUSED,
                    refusal=DeploymentRefusalCode.PAGES_UPDATE_FAILED,
                    reasons=[cfg_result.get("error", "Pages update failed")],
                    now=now,
                    auth_digest=auth_digest,
                )
            pages_updated = True
            pages_phase = PublicationTransitionPhase.PAGES_UPDATED
        else:
            pages_phase = PublicationTransitionPhase.PAGES_CONFIGURATION_UNCHANGED

        _ = self._record_phase(
            op_id=op_id,
            prep=transition_prep,
            phase=pages_phase,
            now=now,
            auth_digest=auth_digest,
            pages_created=pages_created,
            pages_updated=pages_updated,
            site_url=cfg_result.get("site_url", "")
            if not has_pages or current_branch != source_branch
            else pages_state.get("html_url", ""),
        )

        # ── Publish content ───────────────────────────────────────────
        if bundle_obj and not bundle_obj.is_empty():
            manifest = await self._publish_bundle(
                bundle_obj=bundle_obj,
                branch=source_branch,
                target_repo_owner=target_repo_owner,
                target_repo_name=target_repo_name,
                transition_prep=transition_prep,
                operation_id=op_id,
                auth_digest=auth_digest,
            )

            if manifest.publication_complete:
                return self._record_phase(
                    op_id=op_id,
                    prep=transition_prep,
                    phase=PublicationTransitionPhase.CONTENT_PUBLISHED,
                    now=now,
                    auth_digest=auth_digest,
                    pages_created=pages_created,
                    pages_updated=pages_updated,
                    content_published=True,
                    content_manifest_digest=manifest.evidence_digest,
                    site_url=cfg_result.get("site_url", "")
                    if (pages_created or pages_updated)
                    else pages_state.get("html_url", ""),
                )
            elif manifest.publication_partial:
                return self._record_phase(
                    op_id=op_id,
                    prep=transition_prep,
                    phase=PublicationTransitionPhase.RECOVERY_REQUIRED,
                    now=now,
                    auth_digest=auth_digest,
                    pages_created=pages_created,
                    pages_updated=pages_updated,
                    content_published=False,
                    content_manifest_digest=manifest.evidence_digest,
                    recovery_required=True,
                    recovery_hint="Partial content publication; retry or verify remaining files",
                )
            else:
                return self._record_phase(
                    op_id=op_id,
                    prep=transition_prep,
                    phase=PublicationTransitionPhase.RECOVERY_REQUIRED,
                    refusal=DeploymentRefusalCode.CONTENT_PUSH_FAILED,
                    reasons=[
                        f"Content push failed for {len(manifest.failed_files)} files"
                    ],
                    now=now,
                    auth_digest=auth_digest,
                    pages_created=pages_created,
                    pages_updated=pages_updated,
                    content_manifest_digest=manifest.evidence_digest,
                    recovery_required=True,
                    recovery_hint="All files failed; retry content push",
                )

        return self._record_phase(
            op_id=op_id,
            prep=transition_prep,
            phase=pages_phase,
            now=now,
            auth_digest=auth_digest,
            pages_created=pages_created,
            pages_updated=pages_updated,
            site_url=cfg_result.get("site_url", "")
            if (pages_created or pages_updated)
            else pages_state.get("html_url", ""),
        )

    # ── Verify Publication ─────────────────────────────────────────────

    async def verify_publication(
        self,
        receipt: PublicationTransitionReceipt,
        transition_prep: AuthorizedPublicationTransitionPreparation,
        *,
        target_repo_owner: str = "",
        target_repo_name: str = "",
    ) -> PublicationTransitionReceipt:
        """Poll remote Pages build status and verify.

        Gate C: verification is durably appended.
        """
        if (
            not receipt.pages_created
            and not receipt.pages_updated
            and not receipt.content_published
        ):
            return receipt

        status = await self._inspect_pages_state(target_repo_owner, target_repo_name)

        if status.get("build_status") == "built":
            phase = PublicationTransitionPhase.PUBLISHED_VERIFIED
            verified = True
            recovery = False
            hint = ""
        elif status.get("build_status") == "errored":
            phase = PublicationTransitionPhase.RECOVERY_REQUIRED
            verified = False
            recovery = True
            hint = f"Pages build errored for {target_repo_owner}/{target_repo_name}"
        elif status.get("build_status") in ("building", "queued"):
            phase = PublicationTransitionPhase.BUILD_PENDING
            verified = False
            recovery = False
            hint = "Build in progress"
        else:
            phase = PublicationTransitionPhase.BUILD_REQUESTED
            verified = False
            recovery = False
            hint = "Build status unknown"

        return self._record_phase(
            op_id=receipt.operation_id,
            prep=transition_prep,
            phase=phase,
            now=_now_iso(),
            auth_digest=receipt.authorization_receipt_digest,
            pages_created=receipt.pages_created,
            pages_updated=receipt.pages_updated,
            content_published=receipt.content_published,
            content_manifest_digest=receipt.content_publication_manifest_digest,
            site_url=status.get("html_url", ""),
            build_status=status.get("build_status", ""),
            remote_verified=verified,
            verification_digest=status.get(
                "verification_digest", status.get("evidence_digest", "")
            ),
            recovery_required=recovery,
            recovery_hint=hint,
        )

    # ── Status Contract ────────────────────────────────────────────────

    def build_status_contract(
        self,
        receipt: PublicationTransitionReceipt,
        transition_prep: AuthorizedPublicationTransitionPreparation,
    ) -> PublicationStatusContract:
        """Gate F: Build X0-consumable status projection."""
        return PublicationStatusContract(
            publication_operation_id=receipt.operation_id,
            transition_phase=receipt.transition_phase,
            target_repository_digest=transition_prep.target_repository_identity_digest,
            target_surface=transition_prep.target_surface,
            authorization_required=transition_prep.authorization_required,
            authorization_status=(
                "accepted" if receipt.authorization_receipt_digest else "pending"
            ),
            pages_configured=receipt.pages_created or receipt.pages_updated,
            content_published=receipt.content_published,
            build_status=receipt.pages_build_status,
            published_verified=receipt.remote_verified,
            refusal_code=receipt.refusal_code,
            recovery_required=receipt.recovery_required,
            status_message=_phase_message(receipt.transition_phase),
        )

    # ── Private: Phase recording ───────────────────────────────────────

    def _record_phase(
        self,
        *,
        op_id: str,
        prep: AuthorizedPublicationTransitionPreparation,
        phase: PublicationTransitionPhase,
        refusal: DeploymentRefusalCode | None = None,
        reasons: list[str] | None = None,
        now: str = "",
        auth_digest: str = "",
        pages_created: bool = False,
        pages_updated: bool = False,
        content_published: bool = False,
        content_manifest_digest: str = "",
        site_url: str = "",
        build_status: str = "",
        remote_verified: bool = False,
        verification_digest: str = "",
        recovery_required: bool = False,
        recovery_hint: str = "",
    ) -> PublicationTransitionReceipt:
        receipt_id = _digest_sha256(f"{op_id}:{phase.value}")[:22]
        reason_list = reasons or []
        r = PublicationTransitionReceipt(
            receipt_id=receipt_id,
            operation_id=op_id,
            transition_preparation_digest=prep.preparation_digest,
            preview_evidence_digest=prep.preview_evidence_digest,
            preview_receipt_digest=prep.preview_receipt_digest,
            static_bundle_digest=prep.static_bundle_digest,
            authorization_receipt_digest=auth_digest,
            transition_phase=phase.value,
            pages_site_url=site_url,
            pages_build_status=build_status,
            pages_created=pages_created,
            pages_updated=pages_updated,
            content_publication_manifest_digest=content_manifest_digest,
            content_published=content_published,
            remote_verified=remote_verified,
            remote_verification_digest=verification_digest,
            refusal_code=refusal.value if refusal else None,
            refusal_reasons=reason_list,
            recovery_required=recovery_required,
            recovery_hint=recovery_hint,
            deployed_at=now or _now_iso(),
        )
        r.evidence_digest = r.compute_digest()
        self._ledger.append_event(f"{op_id}:{phase.value}", r)
        return r

    # ── Private: Authorization ────────────────────────────────────────

    async def _authorize_transition(
        self,
        authorization_id: str,
        transition_prep: AuthorizedPublicationTransitionPreparation,
    ) -> dict:
        """Gate A: authorize the transition preparation, not the preview receipt."""
        try:
            from rig_relay.integrations.github_provider._authorization_consumer import (
                ConsumerOutcome,
                GitHubAuthorizationConsumer,
            )
        except ImportError:
            return {
                "authorized": False,
                "refusal_code": DeploymentRefusalCode.AUTHORIZATION_MISSING.value,
                "reasons": ["GitHub auth consumer not available"],
                "authorization_digest": "",
            }

        target = None
        parts = transition_prep.target_repository_identity_digest
        if parts and "/" not in parts:
            target = parts

        # Bind authorization to preparation digest + target + operation id
        payload: dict = {
            "publication_operation_id": transition_prep.publication_operation_id,
            "preparation_digest": transition_prep.preparation_digest,
            "static_bundle_digest": transition_prep.static_bundle_digest,
            "source_branch": transition_prep.source_branch,
            "source_path": transition_prep.source_path,
            "target_surface": transition_prep.target_surface,
        }
        result = GitHubAuthorizationConsumer.validate_and_consume(
            authorization_id=authorization_id,
            operation_kind="pages_publish",
            request_payload=payload,
            target_identity=target or "",
            prior_evidence_digest=transition_prep.preparation_digest,
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
            "reasons": [result.error_detail]
            if result.error_detail and not authorized
            else [],
            "authorization_digest": _digest_sha256(
                f"auth:{authorization_id}:{outcome}"
            ),
        }

    # ── Private: Pages API ────────────────────────────────────────────

    async def _inspect_pages_state(self, owner: str, repo: str) -> dict:
        if self._token_getter is None:
            return {"has_pages": False}
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
                        "evidence_digest": _digest_sha256(
                            json.dumps(data, sort_keys=True, default=str)
                        ),
                        "build_type": data.get("build_type"),
                    }
                if resp.status_code == 404:
                    return {"has_pages": False}
                return {"has_pages": False, "error": f"HTTP {resp.status_code}"}
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
        """Gate C: POST create or PUT update based on current state."""
        if self._token_getter is None:
            return {"success": False, "error": "No token_getter"}
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

                ok = resp.status_code in {200, 201, 204}
                if not ok:
                    return {
                        "success": False,
                        "error": f"Pages {method} returned {resp.status_code}",
                    }

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
                    "verification_digest": _digest_sha256(f"cfg:{owner}/{repo}"),
                }
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}

    # ── Private: Content publication ───────────────────────────────────

    async def _publish_bundle(
        self,
        bundle_obj: ApprovedStaticPublicationBundle,
        branch: str,
        target_repo_owner: str,
        target_repo_name: str,
        transition_prep: AuthorizedPublicationTransitionPreparation,
        operation_id: str,
        auth_digest: str,
    ) -> ContentPublicationManifest:
        """Gate B: Publish each file with manifest tracking and recovery."""
        expected = sorted(bundle_obj.files.keys())
        manifest = ContentPublicationManifest(
            operation_id=operation_id,
            bundle_content_digest=bundle_obj.content_digest,
            target_branch=branch,
            expected_files=list(expected),
        )

        if self._git_boundary is None:
            manifest.publication_partial = True
            for f in expected:
                manifest.failed_files.append({"path": f, "error": "No git boundary"})
            manifest.compute_digest()
            return manifest

        published: list[str] = []
        failed: list[dict] = []

        for file_path in expected:
            content = bundle_obj.files[file_path]
            try:
                result = await self._git_boundary.put_file_contents(
                    path=file_path,
                    branch=branch,
                    message=f"Deploy {file_path} via Rig Relay X3.2",
                    content=content,
                )
                if result.get("success", False):
                    published.append(file_path)
                else:
                    failed.append({
                        "path": file_path,
                        "error": result.get("error", "unknown"),
                    })
            except Exception as e:
                failed.append({"path": file_path, "error": str(e)[:200]})

        manifest.published_files = published
        manifest.failed_files = failed
        manifest.publication_complete = len(failed) == 0 and len(published) == len(
            expected
        )
        manifest.publication_partial = 0 < len(published) < len(expected)
        manifest.compute_digest()
        return manifest


def _phase_message(phase: str) -> str:
    messages = {
        "prepared": "Publication transition prepared",
        "authorization_required": "Authorization required to proceed",
        "authorized": "Authorization granted",
        "pages_configuration_unchanged": "Pages configuration unchanged",
        "pages_created": "Pages site created",
        "pages_updated": "Pages site updated",
        "content_publication_started": "Content publication started",
        "content_publication_partial": "Content publication partially complete",
        "content_published": "Content published",
        "build_requested": "Build requested",
        "build_pending": "Build pending",
        "published_verified": "Publication verified",
        "refused": "Publication refused",
        "failed": "Publication failed",
        "recovery_required": "Recovery required",
    }
    return messages.get(phase, phase)


__all__ = ["GitHubPagesDeploymentService"]
