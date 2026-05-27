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
        auth_override: dict | None = None,
    ) -> None:
        self._ledger = ledger or DeploymentEvidenceLedger()
        self._token_getter = token_getter
        self._git_boundary = git_boundary
        self._auth_override = auth_override

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
        if not stored_digest:
            reasons.append("Receipt missing evidence_digest — not yet sealed")
        elif stored_digest != computed_digest:
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
        pages_authorization_receipt_id: str = "",
        target_repo_owner: str = "",
        target_repo_name: str = "",
        content_files: dict[str, str] | None = None,
    ) -> PublicationTransitionReceipt:
        """Execute the full publication transition.

        X3.7 ordering with concurrency control:
        validate → acquire branch lock → check idempotency →
        authorize content mutation → publish approved content (commit/ref) →
        authorize Pages mutation → configure Pages → release lock.
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
                reasons=["No content authorization receipt provided"],
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

        # ── Concurrency control: acquire branch-level publication lock (D1) ──
        source_branch = transition_prep.source_branch
        content_digest_for_dedup = (
            bundle_obj.content_digest
            if bundle_obj and not bundle_obj.is_empty()
            else _digest_sha256(f"no-content:{op_id}")
        )

        lock_acquired = self._ledger.acquire_branch_publication_lock(
            target_repo_owner, target_repo_name, source_branch
        )

        if not lock_acquired:
            # Check lock file state to determine if same or different content
            return self._record_phase(
                op_id=op_id,
                prep=transition_prep,
                phase=PublicationTransitionPhase.REFUSED,
                refusal=DeploymentRefusalCode.CONCURRENT_PUBLICATION_CONFLICT,
                reasons=[
                    f"Another publication is in progress for "
                    f"{target_repo_owner}/{target_repo_name}:{source_branch}"
                ],
                now=now,
            )

        branch_lock_held = True
        try:
            # ── Idempotency check under lock (D2) ──
            branch_state = self._ledger.check_branch_publication_state(
                target_repo_owner,
                target_repo_name,
                source_branch,
                content_digest_for_dedup,
            )
            if branch_state["already_published"]:
                return self._record_phase(
                    op_id=op_id,
                    prep=transition_prep,
                    phase=PublicationTransitionPhase.CONTENT_PUBLISHED,
                    now=now,
                    auth_digest="",
                    content_published=True,
                    published_commit_sha=branch_state.get("pending_commit_sha", ""),
                    git_publication_mode="atomic_git_commit",
                    recovery_required=False,
                    recovery_hint="Content already published (idempotent detection)",
                )

            # ── Authorize content publication (Contents:write) ──────────
            content_auth = await self._authorize_content_publication(
                authorization_id=authorization_receipt_id,
                transition_prep=transition_prep,
            )
            if not content_auth["authorized"]:
                return self._record_phase(
                    op_id=op_id,
                    prep=transition_prep,
                    phase=PublicationTransitionPhase.REFUSED,
                    refusal=DeploymentRefusalCode(
                        content_auth.get("refusal_code", "authorization_revoked")
                    ),
                    reasons=content_auth.get("reasons", []),
                    now=now,
                    auth_digest=content_auth.get("authorization_digest", ""),
                )

            content_auth_digest = content_auth["authorization_digest"]

            # ── Publish content FIRST (before Pages mutation) ────────────
            content_published = False
            published_commit_sha_value = ""
            git_publication_mode_value = "none"
            pages_created = False
            pages_updated = False
            pages_phase = PublicationTransitionPhase.PAGES_CONFIGURATION_UNCHANGED
            cfg_result: dict = {
                "success": False,
                "site_url": "",
                "verification_digest": "",
            }
            pages_state: dict = {}

            if bundle_obj and not bundle_obj.is_empty():
                manifest = await self._publish_bundle(
                    bundle_obj=bundle_obj,
                    branch=source_branch,
                    target_repo_owner=target_repo_owner,
                    target_repo_name=target_repo_name,
                    transition_prep=transition_prep,
                    operation_id=op_id,
                    auth_digest=content_auth_digest,
                )

                if manifest.publication_complete:
                    content_published = True
                    published_commit_sha_value = manifest.commit_sha
                    git_publication_mode_value = manifest.git_publication_mode
                elif manifest.commit_created and not manifest.ref_updated:
                    return self._record_phase(
                        op_id=op_id,
                        prep=transition_prep,
                        phase=PublicationTransitionPhase.CONTENT_COMMIT_CREATED_REF_NOT_UPDATED,
                        now=now,
                        auth_digest=content_auth_digest,
                        content_published=False,
                        content_manifest_digest=manifest.evidence_digest,
                        published_commit_sha=manifest.orphaned_commit_sha
                        or manifest.commit_sha,
                        git_publication_mode=manifest.git_publication_mode,
                        recovery_required=True,
                        recovery_hint="Content commit created but ref not updated — remote conflict or ref update failed",
                    )
                elif manifest.publication_partial:
                    return self._record_phase(
                        op_id=op_id,
                        prep=transition_prep,
                        phase=PublicationTransitionPhase.RECOVERY_REQUIRED,
                        now=now,
                        auth_digest=content_auth_digest,
                        content_published=False,
                        content_manifest_digest=manifest.evidence_digest,
                        published_commit_sha=manifest.commit_sha,
                        git_publication_mode=manifest.git_publication_mode,
                        recovery_required=True,
                        recovery_hint="Partial content publication; retry or verify",
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
                        auth_digest=content_auth_digest,
                        content_manifest_digest=manifest.evidence_digest,
                        published_commit_sha=manifest.commit_sha,
                        git_publication_mode=manifest.git_publication_mode,
                        recovery_required=True,
                        recovery_hint="All files failed; retry content push",
                    )

            # ── Read Pages state (read-only, no mutation yet) ────────────
            pages_state = await self._inspect_pages_state(
                target_repo_owner, target_repo_name
            )
            has_pages = pages_state.get("has_pages", False)
            current_branch = pages_state.get("source_branch", "")

            if pages_state.get("error"):
                return self._record_phase(
                    op_id=op_id,
                    prep=transition_prep,
                    phase=PublicationTransitionPhase.RECOVERY_REQUIRED,
                    refusal=DeploymentRefusalCode.PAGES_INSPECT_FAILED,
                    reasons=[pages_state["error"]],
                    now=now,
                    auth_digest=content_auth_digest,
                    pages_created=False,
                    pages_updated=False,
                    content_published=content_published,
                    recovery_required=True,
                    recovery_hint="Content published but Pages inspection failed; configure Pages manually",
                )

            # ── Only configure Pages if content was published ───────────
            needs_pages_mutation = not has_pages or current_branch != source_branch

            if needs_pages_mutation and content_published:
                if not pages_authorization_receipt_id:
                    return self._record_phase(
                        op_id=op_id,
                        prep=transition_prep,
                        phase=PublicationTransitionPhase.RECOVERY_REQUIRED,
                        now=now,
                        auth_digest=content_auth_digest,
                        content_published=True,
                        recovery_required=True,
                        recovery_hint="Content published but Pages configuration requires separate authorization",
                    )

                pages_auth = await self._authorize_pages_configuration(
                    authorization_id=pages_authorization_receipt_id,
                    transition_prep=transition_prep,
                )
                if not pages_auth["authorized"]:
                    return self._record_phase(
                        op_id=op_id,
                        prep=transition_prep,
                        phase=PublicationTransitionPhase.RECOVERY_REQUIRED,
                        now=now,
                        auth_digest=content_auth_digest,
                        content_published=True,
                        recovery_required=True,
                        recovery_hint="Content published but Pages authorization refused",
                    )

                pages_auth_digest = pages_auth["authorization_digest"]

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
                            phase=PublicationTransitionPhase.RECOVERY_REQUIRED,
                            refusal=DeploymentRefusalCode.PAGES_CREATE_FAILED,
                            reasons=[cfg_result.get("error", "Pages create failed")],
                            now=now,
                            auth_digest=pages_auth_digest,
                            content_published=True,
                            recovery_required=True,
                            recovery_hint="Content published but Pages creation failed",
                        )
                    pages_created = True
                    pages_phase = PublicationTransitionPhase.PAGES_CREATED
                else:
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
                            phase=PublicationTransitionPhase.RECOVERY_REQUIRED,
                            refusal=DeploymentRefusalCode.PAGES_UPDATE_FAILED,
                            reasons=[cfg_result.get("error", "Pages update failed")],
                            now=now,
                            auth_digest=pages_auth_digest,
                            content_published=True,
                            recovery_required=True,
                            recovery_hint="Content published but Pages update failed",
                        )
                    pages_updated = True
                    pages_phase = PublicationTransitionPhase.PAGES_UPDATED
            else:
                pages_phase = PublicationTransitionPhase.PAGES_CONFIGURATION_UNCHANGED

            return self._record_phase(
                op_id=op_id,
                prep=transition_prep,
                phase=pages_phase,
                now=now,
                auth_digest=content_auth_digest,
                pages_created=pages_created,
                pages_updated=pages_updated,
                content_published=content_published,
                published_commit_sha=published_commit_sha_value,
                git_publication_mode=git_publication_mode_value,
                site_url=cfg_result.get("site_url", "")
                if (pages_created or pages_updated)
                else pages_state.get("html_url", ""),
            )
        finally:
            if branch_lock_held:
                self._ledger.release_branch_publication_lock()

    # ── Verify Publication ─────────────────────────────────────────────

    async def verify_publication(
        self,
        receipt: PublicationTransitionReceipt,
        transition_prep: AuthorizedPublicationTransitionPreparation,
        *,
        target_repo_owner: str = "",
        target_repo_name: str = "",
    ) -> PublicationTransitionReceipt:
        """Poll remote Pages build status and verify with commit correlation.

        Gate C: verification is durably appended. Calls Pages latest-build
        API to correlate the build commit with the published content commit.
        Only returns PUBLISHED_VERIFIED when build_status == "built" AND
        the build commit matches the published content commit.
        """
        if (
            not receipt.pages_created
            and not receipt.pages_updated
            and not receipt.content_published
        ):
            return receipt

        status = await self._inspect_pages_state(target_repo_owner, target_repo_name)

        build_commit_sha = ""
        published_commit = receipt.published_commit_sha
        build_commit_matches = False

        # Fetch latest build to correlate commit identity when available
        if self._git_boundary and hasattr(
            self._git_boundary, "get_pages_builds_latest"
        ):
            try:
                latest_build = await self._git_boundary.get_pages_builds_latest()
                build_commit_sha = latest_build.get("build_commit", "")
                if (
                    published_commit
                    and build_commit_sha
                    and published_commit == build_commit_sha
                ):
                    build_commit_matches = True
            except Exception:
                pass

        if (
            status.get("build_status") == "built"
            and build_commit_matches
            and published_commit
        ):
            phase = PublicationTransitionPhase.PUBLISHED_VERIFIED
            verified = True
            recovery = False
            hint = ""
        elif status.get("build_status") == "built" and published_commit:
            phase = PublicationTransitionPhase.CONTENT_PUBLISHED
            verified = False
            recovery = False
            hint = (
                f"Build status is 'built' but commit does not match "
                f"published {published_commit[:12]}... vs build "
                f"{build_commit_sha[:12]}... — correlation pending"
            )
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
            published_commit_sha=published_commit,
            git_publication_mode=receipt.git_publication_mode,
            site_url=status.get("html_url", ""),
            build_status=status.get("build_status", ""),
            remote_verified=verified,
            verification_digest=status.get(
                "verification_digest", status.get("evidence_digest", "")
            ),
            build_commit_sha=build_commit_sha,
            build_commit_matches_published=build_commit_matches,
            recovery_required=recovery,
            recovery_hint=hint,
        )

    # ── Status Contract ────────────────────────────────────────────────

    def build_status_contract(
        self,
        receipt: PublicationTransitionReceipt,
        transition_prep: AuthorizedPublicationTransitionPreparation,
    ) -> PublicationStatusContract:
        """Gate F: Build X0-consumable typed publication surface state.

        All fields populated from durable evidence — no empty defaults.
        projection_digest is a partial presentation digest (status only).
        terminal_receipt_digest links to the durable terminal evidence
        receipt so X0 can trace UI state back to canonical evidence.
        """
        git_mode = receipt.git_publication_mode or "none"
        published_sha = receipt.published_commit_sha or ""
        build_sha = receipt.build_commit_sha or ""
        build_matches = receipt.build_commit_matches_published

        projection_digest = _digest_sha256(
            f"{receipt.operation_id}:{receipt.transition_phase}:"
            f"{published_sha}:{build_sha}:{build_matches}:"
            f"{transition_prep.target_surface}"
        )

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
        )

    # ── Private: Orphaned publication recovery (D3) ──────────────────

    async def _find_prepared_manifest(
        self,
        *,
        bundle_obj: ApprovedStaticPublicationBundle,
        branch: str,
        target_repo_owner: str,
        target_repo_name: str,
        transition_prep: AuthorizedPublicationTransitionPreparation,
    ) -> ContentPublicationManifest | None:
        """Scan evidence ledger for a prior CONTENT_PUBLICATION_PREPARED manifest.

        Returns the ContentPublicationManifest if found, else None.
        """
        reconstruction = self._ledger.load_receipts()
        for receipt_data in reconstruction.get("receipts", []):
            if receipt_data.get("transition_phase") != "content_publication_prepared":
                continue
            if receipt_data.get("static_bundle_digest") != bundle_obj.content_digest:
                continue
            published_sha = receipt_data.get("published_commit_sha", "")
            if not published_sha:
                continue
            manifest = ContentPublicationManifest(
                operation_id=receipt_data.get("operation_id", ""),
                bundle_content_digest=bundle_obj.content_digest,
                target_branch=branch,
                commit_sha=published_sha,
                commit_created=True,
                orphaned_commit_sha=published_sha,
                git_publication_mode=receipt_data.get(
                    "git_publication_mode", "atomic_git_commit"
                ),
            )
            return manifest
        return None

    async def _resume_orphaned_publication(
        self,
        orphaned_commit_sha: str,
        commit_tree_sha: str,
        branch: str,
        target_repo_owner: str,
        target_repo_name: str,
        transition_prep: AuthorizedPublicationTransitionPreparation | None = None,
    ) -> ContentPublicationManifest:
        """Resume publication from an already-created but unreferenced commit.

        Verifies the commit still exists, checks that the current ref
        hasn't diverged, and fast-forwards the ref to recover.
        """
        gb = self._git_boundary
        manifest = ContentPublicationManifest(
            operation_id=_digest_sha256(f"resume:{orphaned_commit_sha}"),
            bundle_content_digest="",
            target_branch=branch,
            commit_sha=orphaned_commit_sha,
            commit_created=True,
            orphaned_commit_sha=orphaned_commit_sha,
            git_publication_mode="atomic_git_commit_recovery",
        )

        if gb is None:
            manifest.publication_partial = True
            manifest.failed_files = [
                {"path": "__recovery__", "error": "No git boundary"}
            ]
            manifest.compute_digest()
            return manifest

        # Verify orphaned commit still exists
        try:
            tree_result = await gb.get_commit_tree(orphaned_commit_sha)
            if not tree_result.get("tree_sha"):
                manifest.failed_files = [
                    {
                        "path": "__recovery__",
                        "error": "Orphaned commit no longer exists",
                    }
                ]
                manifest.compute_digest()
                return manifest
        except Exception as e:
            manifest.failed_files = [{"path": "__recovery__", "error": str(e)[:200]}]
            manifest.compute_digest()
            return manifest

        # Get current ref to check for divergence
        try:
            ref_resp = await gb.get_base_ref(f"heads/{branch}")
            current_ref_sha = ref_resp.get("ref_sha", "")
        except Exception:
            current_ref_sha = ""

        # If current ref is empty (new branch) or is the parent of the
        # orphaned commit, fast-forward is safe
        try:
            ref_result = await gb.update_ref(
                f"heads/{branch}", orphaned_commit_sha, force=False
            )
            if ref_result.get("success", False):
                manifest.ref_updated = True
                manifest.publication_complete = True
            else:
                status = ref_result.get("status_code", 0)
                if status == 409:
                    manifest.failed_files = [
                        {
                            "path": "__recovery__",
                            "error": (
                                f"Ref has diverged; orphaned commit "
                                f"{orphaned_commit_sha[:12]}... cannot be "
                                f"fast-forwarded onto branch {branch} at "
                                f"{current_ref_sha[:12]}..."
                            ),
                        }
                    ]
                else:
                    manifest.failed_files = [
                        {
                            "path": "__recovery__",
                            "error": ref_result.get(
                                "error", "ref update failed during recovery"
                            ),
                        }
                    ]
        except Exception as e:
            manifest.failed_files = [{"path": "__recovery__", "error": str(e)[:200]}]

        manifest.compute_digest()
        if manifest.publication_complete and transition_prep is not None:
            self._record_phase(
                op_id=manifest.operation_id,
                prep=transition_prep,
                phase=PublicationTransitionPhase.CONTENT_PUBLISHED,
                now=_now_iso(),
                auth_digest="",
                content_published=True,
                content_manifest_digest=manifest.evidence_digest,
                published_commit_sha=manifest.commit_sha,
                git_publication_mode=manifest.git_publication_mode,
            )
        return manifest

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
        published_commit_sha: str = "",
        git_publication_mode: str = "none",
        site_url: str = "",
        build_status: str = "",
        remote_verified: bool = False,
        verification_digest: str = "",
        build_commit_sha: str = "",
        build_commit_matches_published: bool = False,
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
            published_commit_sha=published_commit_sha,
            git_publication_mode=git_publication_mode,
            remote_verified=remote_verified,
            remote_verification_digest=verification_digest,
            build_commit_sha=build_commit_sha,
            build_commit_matches_published=build_commit_matches_published,
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

    async def _authorize_content_publication(
        self,
        authorization_id: str,
        transition_prep: AuthorizedPublicationTransitionPreparation,
    ) -> dict:
        """Authorize content publication — Git Data API (Contents:write)."""
        return await self._authorize_operation(
            authorization_id=authorization_id,
            operation_kind="git_content_publish",
            transition_prep=transition_prep,
        )

    async def _authorize_pages_configuration(
        self,
        authorization_id: str,
        transition_prep: AuthorizedPublicationTransitionPreparation,
    ) -> dict:
        """Authorize Pages configuration — Pages API (Pages:write, Administration:write)."""
        return await self._authorize_operation(
            authorization_id=authorization_id,
            operation_kind="pages_configure",
            transition_prep=transition_prep,
        )

    async def _authorize_operation(
        self,
        *,
        authorization_id: str,
        operation_kind: str,
        transition_prep: AuthorizedPublicationTransitionPreparation,
    ) -> dict:
        """Consume one Lane A authorization receipt for the given operation."""
        if self._auth_override is not None:
            return self._auth_override

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
            operation_kind=operation_kind,
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

    # ── Private: Content publication (X3.3 atomic pipeline) ─────────────

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
        """X3.7 Gate B: Atomic git commit/reference publication.

        Pipeline: blobs → tree → commit → CONTENT_PUBLICATION_PREPARED → ref update.
        Checks for prior CONTENT_PUBLICATION_PREPARED manifest before creating
        new objects. Falls back to per-file sequential push only if Git Data
        API unavailable. Refuses sequential fallback for public_release policy.
        """
        expected = sorted(bundle_obj.files.keys())
        manifest = ContentPublicationManifest(
            operation_id=operation_id,
            bundle_content_digest=bundle_obj.content_digest,
            target_branch=branch,
            expected_files=list(expected),
        )

        gb = self._git_boundary
        if gb is None:
            manifest.publication_partial = True
            for f in expected:
                manifest.failed_files.append({"path": f, "error": "No git boundary"})
            manifest.compute_digest()
            return manifest

        has_atomic = all(
            hasattr(gb, m)
            for m in ("create_blob", "create_tree", "create_commit", "update_ref")
        )

        if not has_atomic:
            if transition_prep.publication_policy == "public_release":
                manifest.publication_partial = True
                manifest.failed_files = [
                    {
                        "path": "__atomic__",
                        "error": (
                            "Sequential fallback refused for public_release policy"
                        ),
                    }
                ]
                manifest.compute_digest()
                return manifest
            return await self._publish_sequential(
                bundle_obj, branch, expected, manifest, gb
            )

        # Check for prior prepared manifest (crash recovery)
        prior_manifest = await self._find_prepared_manifest(
            bundle_obj=bundle_obj,
            branch=branch,
            target_repo_owner=target_repo_owner,
            target_repo_name=target_repo_name,
            transition_prep=transition_prep,
        )
        if prior_manifest is not None:
            return await self._resume_orphaned_publication(
                orphaned_commit_sha=prior_manifest.commit_sha,
                commit_tree_sha="",
                branch=branch,
                target_repo_owner=target_repo_owner,
                target_repo_name=target_repo_name,
                transition_prep=transition_prep,
            )

        return await self._publish_atomic(
            bundle_obj,
            branch,
            expected,
            manifest,
            gb,
            transition_prep=transition_prep,
            target_repo_owner=target_repo_owner,
            target_repo_name=target_repo_name,
        )

    async def _publish_atomic(
        self,
        bundle_obj: ApprovedStaticPublicationBundle,
        branch: str,
        expected: list[str],
        manifest: ContentPublicationManifest,
        gb: object,
        *,
        transition_prep: AuthorizedPublicationTransitionPreparation | None = None,
        target_repo_owner: str = "",
        target_repo_name: str = "",
    ) -> ContentPublicationManifest:
        """X3.7: Atomic publication via Git Data API (blob→tree→commit→prepare→ref).

        Critical safety properties:
        - Tree preservation: resolves current branch commit tree SHA as
          base_tree so unrelated branch content is NOT destroyed.
        - Durable pre-ref manifest: persists CONTENT_PUBLICATION_PREPARED
          after commit creation but before ref update.
        - Effect-accurate tracking: blobs_created, tree_created,
          commit_created, ref_updated are distinct; published_files
          is set ONLY after ref update succeeds.
        - A failed ref update records orphaned_commit_sha, not false
          partial publication.
        """
        failed: list[dict] = []
        blob_shas: dict[str, str] = {}

        # Step 1: Create blobs for all files
        for file_path in expected:
            content = bundle_obj.files[file_path]
            try:
                result = await gb.create_blob(content, "utf-8")
                sha = result.get("blob_sha", "")
                if sha:
                    blob_shas[file_path] = sha
                    manifest.blobs_created.append(file_path)
                else:
                    failed.append({
                        "path": file_path,
                        "error": result.get("error", "no sha returned"),
                    })
            except Exception as e:
                failed.append({"path": file_path, "error": str(e)[:200]})

        if not blob_shas:
            manifest.failed_files = failed
            manifest.compute_digest()
            return manifest

        # Step 2: Get current ref SHA and resolve base_tree
        current_sha = ""
        base_tree_sha = ""
        try:
            ref_resp = await gb.get_base_ref(f"heads/{branch}")
            current_sha = ref_resp.get("ref_sha", "")
        except Exception:
            pass

        if current_sha:
            try:
                tree_resp = await gb.get_commit_tree(current_sha)
                base_tree_sha = tree_resp.get("tree_sha", "")
            except Exception:
                pass

        # Step 3: Create tree with base_tree for preservation
        tree_entries = [
            {"path": fp, "mode": "100644", "type": "blob", "sha": sha}
            for fp, sha in blob_shas.items()
        ]
        try:
            tree_result = await gb.create_tree(
                tree_entries, base_tree=base_tree_sha if base_tree_sha else None
            )
            tree_sha = tree_result.get("tree_sha", "")
            if not tree_sha:
                manifest.failed_files = failed
                manifest.compute_digest()
                return manifest
            manifest.tree_created = True
        except Exception as e:
            for fp in blob_shas:
                failed.append({"path": fp, "error": f"tree creation: {e}"})
            manifest.failed_files = failed
            manifest.compute_digest()
            return manifest

        # Step 4: Create commit
        parents = [current_sha] if current_sha else None
        try:
            commit_result = await gb.create_commit(
                message="Publish site bundle via Rig Relay",
                tree_sha=tree_sha,
                parents=parents,
            )
            commit_sha = commit_result.get("commit_sha", "")
            if not commit_sha:
                manifest.failed_files = [
                    {"path": "__commit__", "error": "commit creation failed"}
                ]
                manifest.compute_digest()
                return manifest
            manifest.commit_sha = commit_sha
            manifest.commit_created = True
            manifest.git_publication_mode = "atomic_git_commit"

            # ── Durable pre-ref manifest (D3) ─────────────────────
            if transition_prep is not None:
                self._record_phase(
                    op_id=manifest.operation_id,
                    prep=transition_prep,
                    phase=PublicationTransitionPhase.CONTENT_PUBLICATION_PREPARED,
                    now=_now_iso(),
                    auth_digest="",
                    content_published=False,
                    content_manifest_digest="",
                    published_commit_sha=commit_sha,
                    git_publication_mode="atomic_git_commit",
                )
        except Exception as e:
            manifest.failed_files = [{"path": "__commit__", "error": str(e)[:200]}]
            manifest.compute_digest()
            return manifest

        # Step 5: Update ref (compare-and-swap via force=false)
        try:
            ref_result = await gb.update_ref(f"heads/{branch}", commit_sha, force=False)
            if ref_result.get("success", False):
                manifest.ref_updated = True
                manifest.published_files = list(blob_shas.keys())
                manifest.publication_complete = True
                # ── Record CONTENT_PUBLISHED after successful ref update ──
                if transition_prep is not None:
                    self._record_phase(
                        op_id=manifest.operation_id,
                        prep=transition_prep,
                        phase=PublicationTransitionPhase.CONTENT_PUBLISHED,
                        now=_now_iso(),
                        auth_digest="",
                        content_published=True,
                        content_manifest_digest=manifest.evidence_digest,
                        published_commit_sha=commit_sha,
                        git_publication_mode="atomic_git_commit",
                    )
            else:
                manifest.orphaned_commit_sha = commit_sha
                status = ref_result.get("status_code", 0)
                if status == 409:
                    manifest.failed_files = [
                        {
                            "path": "__ref__",
                            "error": "ref conflict — branch advanced since preparation",
                        }
                    ]
                else:
                    manifest.failed_files = [
                        {
                            "path": "__ref__",
                            "error": ref_result.get("error", "ref update failed"),
                        }
                    ]
        except Exception as e:
            manifest.orphaned_commit_sha = manifest.commit_sha
            manifest.failed_files = [{"path": "__ref__", "error": str(e)[:200]}]

        manifest.compute_digest()
        return manifest

    async def _publish_sequential(
        self,
        bundle_obj: ApprovedStaticPublicationBundle,
        branch: str,
        expected: list[str],
        manifest: ContentPublicationManifest,
        gb: object,
    ) -> ContentPublicationManifest:
        """Fallback: sequential per-file push via Contents API."""
        published: list[str] = []
        failed: list[dict] = []
        manifest.git_publication_mode = "sequential_put_file"

        for file_path in expected:
            content = bundle_obj.files[file_path]
            try:
                result = await gb.put_file_contents(
                    path=file_path,
                    branch=branch,
                    message=f"Deploy {file_path} via Rig Relay",
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
        "content_publication_prepared": "Content commit prepared — ref update pending",
        "content_published": "Content published",
        "content_commit_created_ref_not_updated": "Content commit created but branch ref not updated — recovery required",
        "build_requested": "Build requested",
        "build_pending": "Build pending",
        "published_verified": "Publication verified",
        "refused": "Publication refused",
        "failed": "Publication failed",
        "recovery_required": "Recovery required",
    }
    return messages.get(phase, phase)


def _available_actions(phase: str) -> list[str]:
    phase_actions: dict[str, list[str]] = {
        "prepared": ["authorize", "cancel"],
        "authorization_required": ["authorize", "cancel"],
        "authorized": ["publish_content", "authorize_pages", "cancel"],
        "pages_configuration_unchanged": ["verify_publication", "cancel"],
        "pages_created": ["verify_publication", "cancel"],
        "pages_updated": ["verify_publication", "cancel"],
        "content_published": ["configure_pages", "verify_publication", "cancel"],
        "content_publication_prepared": [
            "retry_content_publication",
            "verify_publication",
            "cancel",
        ],
        "content_commit_created_ref_not_updated": [
            "retry_content_publication",
            "cancel",
        ],
        "build_requested": ["verify_publication", "cancel"],
        "build_pending": ["verify_publication", "cancel"],
        "published_verified": [],
        "refused": ["retry_publication", "cancel"],
        "failed": ["retry_publication", "cancel"],
        "recovery_required": ["retry_publication", "verify_publication", "cancel"],
    }
    return phase_actions.get(phase, ["inspect"])


__all__ = ["GitHubPagesDeploymentService"]
