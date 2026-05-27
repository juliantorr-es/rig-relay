"""Surface-specific projection builders — Lane X0.

Each builder consumes the published public API of exactly one service
and produces content-light projection models with explicit evidence-backed
authority states. Never reads authority ledgers or reproduces producer logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from rig_relay.desktop.gateway._models import ProvenanceClass, TrustState
from rig_relay.desktop.gateway._models_surfaces import (
    AnalyticsReportsSurfaceProjection,
    ConnectSurfaceProjection,
    EstateChangeEntry,
    EstateCorruptionEntry,
    EstateRepositoryEntry,
    FleetWorkspacesSurfaceProjection,
    HarnessProfileSurfaceProjection,
    InferenceStudioSurfaceProjection,
    ProviderConnectionEntry,
    PublishPreviewEvidenceSummary,
    PublishPreviewSurfaceProjection,
    RepositoryEstateSurfaceProjection,
    RepositoryReadinessSurfaceProjection,
    SurfaceStatus,
    TimelineEventEntry,
    TimelineSurfaceProjection,
)
from rig_relay.desktop.gateway._projection import (
    _UNAVAILABLE_SENTINEL,
    _merge_safari_fields,
)

if TYPE_CHECKING:
    from rig_relay.desktop.gateway._service import DeveloperStudioGatewayService


# The service accessors on DeveloperStudioGatewayService return either
# the service instance or a module-private sentinel when unavailable.
# To avoid sentinel-instance mismatch across modules, we use try/except
# and None checks on gateway._service fields directly for each builder.


# ── Connect Surface Projection Builder ────────────────


def CONNECT_SURFACE_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> ConnectSurfaceProjection:
    """Build Connect surface projection from provider status + J0 workspace."""
    providers_list = _build_provider_entries(gateway)
    providers_total = len(providers_list)
    providers_configured = sum(1 for p in providers_list if p.configured)

    j0 = gateway._get_j0_service()
    ws_state = "disconnected"
    ws_token = False
    ws_install_hash = ""
    ws_repo_count = 0

    if j0 is not None:
        try:
            conn = getattr(j0, "connection", None)
            if conn:
                ws_state = getattr(conn, "connection_state", "disconnected")
                ws_token = getattr(conn, "token_available", False)
                ws_install_hash = getattr(conn, "installation_id_hash", "")
                ws_repo_count = getattr(conn, "accessible_repository_count", 0)
        except Exception:
            pass

    available = providers_configured > 0 or ws_token
    if available and ws_token:
        surface_status = SurfaceStatus.AVAILABLE.value
        status_detail = "Connected and ready"
        authority = "canonical_live"
        trust = TrustState.TRUSTED_LIVE
        reason = ""
    elif providers_configured > 0:
        surface_status = SurfaceStatus.AVAILABLE.value
        status_detail = f"{providers_configured} providers configured"
        authority = "canonical_degraded"
        trust = TrustState.TRUSTED_LIVE
        reason = "Providers configured but workspace not connected"
    elif ws_token:
        surface_status = SurfaceStatus.SETUP_REQUIRED.value
        status_detail = "Add a provider to begin"
        authority = "canonical_degraded"
        trust = TrustState.TRUSTED_LIVE
        reason = "Workspace connected but no providers configured"
    else:
        surface_status = SurfaceStatus.SETUP_REQUIRED.value
        status_detail = "Connect a provider and workspace to begin"
        authority = "missing"
        trust = TrustState.DEFERRED
        reason = "No providers configured and workspace not connected"

    return ConnectSurfaceProjection(
        available=available,
        authority_state=authority,
        trust_state=trust,
        degraded_reason=reason,
        surface_status=surface_status,
        status_detail=status_detail,
        providers=providers_list,
        providers_configured=providers_configured,
        providers_total=providers_total,
        workspace_connection_state=ws_state,
        workspace_token_available=ws_token,
        workspace_installation_id_hash=ws_install_hash,
        workspace_accessible_repository_count=ws_repo_count,
    )


def _build_provider_entries(
    gateway: DeveloperStudioGatewayService,
) -> list[ProviderConnectionEntry]:
    """Build provider connection entries from provider status + W1 cache policy."""
    entries: list[ProviderConnectionEntry] = []
    try:
        from rig_relay.providers import get_key_store
        from rig_relay.providers.onboarding import provider_status

        ks = get_key_store()
        status_summary = provider_status(ks)
    except Exception:
        return entries

    CACHE_POLICY: dict[str, dict[str, str | bool]] = {
        "anthropic": {
            "mode": "explicit_prefix",
            "retention": "short_lived",
            "confidential": "requires_approval",
            "disclosure": True,
        },
        "openai": {
            "mode": "automatic_provider_managed",
            "retention": "extended_24h",
            "confidential": "disclose_only",
            "disclosure": True,
        },
        "gemini": {
            "mode": "explicit_resource",
            "retention": "unknown",
            "confidential": "requires_approval",
            "disclosure": True,
        },
        "openrouter": {
            "mode": "automatic_gateway_passthrough",
            "retention": "opaque",
            "confidential": "gateway_risk",
            "disclosure": True,
        },
        "deepseek": {
            "mode": "unknown",
            "retention": "unknown",
            "confidential": "unknown",
            "disclosure": True,
        },
        "local_inference": {
            "mode": "local_runtime_kv",
            "retention": "local_only",
            "confidential": "local_safe",
            "disclosure": False,
        },
    }

    for provider_info in status_summary.get("providers", []):
        provider_name = provider_info.get("provider", "")
        policy = CACHE_POLICY.get(provider_name, {})
        entries.append(
            ProviderConnectionEntry(
                provider=provider_name,
                display_name=provider_info.get("display_name", provider_name),
                configured=provider_info.get("configured", False),
                key_source=provider_info.get("key_source") or "",
                key_fingerprint=provider_info.get("key_fingerprint") or "",
                base_url=provider_info.get("base_url") or "",
                default_model=provider_info.get("default_model") or "",
                status=provider_info.get("status", "unknown"),
                warnings=provider_info.get("warnings", []),
                cache_mode=str(policy.get("mode", "unknown")),
                cache_disclosure_required=bool(policy.get("disclosure", False)),
                cache_retention_class=str(policy.get("retention", "unknown")),
                confidential_context_disposition=str(
                    policy.get("confidential", "unknown")
                ),
            )
        )

    return entries


# ── X1.6 X0ProjectionSurface availability helpers ─────


def _derive_x0_availability(x0_surface: Any, domain: str) -> dict[str, Any]:
    """Derive availability vocabulary from X0ProjectionSurface for a domain.

    Returns availability vocabulary: unavailable, refused, corrupt_source,
    degraded, derived, rebuilt, connection_required.

    Distinguishes unavailable backend (connection refused, timeout) from
    actual evidence corruption (digest mismatch, corrupt chain links).
    An unreachable database is not corrupt evidence.
    """
    if x0_surface is None or x0_surface is _UNAVAILABLE_SENTINEL:
        return {
            "status": "unavailable",
            "reason": "X0ProjectionSurface cannot be loaded",
        }
    try:
        statuses = x0_surface.get_projection_status()
        domain_status = statuses.get(domain)
        if domain_status is None:
            return {
                "status": "unavailable",
                "reason": f"Domain {domain} not configured",
            }
        raw_status = domain_status.availability
        # Only mark corrupt_source if the domain status explicitly reports
        # corruption evidence (digest mismatch, invalid reconstruction).
        if raw_status == "corrupt_source":
            return {
                "status": "corrupt_source",
                "reason": f"Evidence corruption detected in {domain}",
                "rows_materialized": domain_status.rows_materialized,
                "corrupt_rows": domain_status.corrupt_rows,
                "deterministic": domain_status.deterministic,
                "latest_build_at": domain_status.latest_build_at or "",
                "authority_state": domain_status.authority_state,
            }
        if raw_status == "degraded":
            return {
                "status": "degraded",
                "reason": f"Degraded projection for {domain}",
                "rows_materialized": domain_status.rows_materialized,
                "corrupt_rows": domain_status.corrupt_rows,
                "deterministic": domain_status.deterministic,
                "latest_build_at": domain_status.latest_build_at or "",
                "authority_state": domain_status.authority_state,
            }
        # Otherwise: derived, rebuilt, refused, unavailable
        return {
            "status": raw_status if raw_status else "derived",
            "status_detail": domain_status.authority_state,
            "rows_materialized": domain_status.rows_materialized,
            "corrupt_rows": domain_status.corrupt_rows,
            "deterministic": domain_status.deterministic,
            "latest_build_at": domain_status.latest_build_at or "",
            "authority_state": domain_status.authority_state,
        }
    except Exception as exc:
        error_msg = str(exc).lower()
        if any(
            term in error_msg
            for term in (
                "connection",
                "connect",
                "timeout",
                "refused",
                "unreachable",
                "not found",
                "does not exist",
                "could not translate",
            )
        ):
            return {
                "status": "connection_required",
                "reason": f"Backend unreachable: {exc}",
            }
        return {"status": "unavailable", "reason": f"Backend error: {exc}"}


# ── Repository Estate Surface Projection Builder ──────


def REPOSITORY_ESTATE_SURFACE_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> RepositoryEstateSurfaceProjection:
    """Build Repository Estate surface from T3.1 RepositoryEstateService.

    X1.6 — Falls back to X0ProjectionSurface when primary service is
    unavailable, providing availability-derived status metadata.
    """
    estate = gateway._get_repository_estate_service()

    # X1.6 — Wire X0ProjectionSurface availability vocabulary
    x0_surface = gateway._get_x0_projection_surface()
    x0_availability = _derive_x0_availability(x0_surface, "repository_estate")

    if estate is None or estate is _UNAVAILABLE_SENTINEL:
        x0_status = x0_availability.get("status", "unavailable")
        # Only try X0 fallback when the backend is truly reachable
        if x0_status not in (
            "unavailable",
            "corrupt_source",
            "refused",
            "connection_required",
            "degraded",
        ):
            summary = {}
            try:
                summary = x0_surface.get_estate_summary()
            except Exception:
                pass
            repo_count = summary.get("registered_repositories", 0)
            return RepositoryEstateSurfaceProjection(
                available=repo_count > 0,
                authority_state="canonical_degraded",
                trust_state=TrustState.TRUSTED_LIVE,
                degraded_reason=(
                    f"RepositoryEstateService unavailable; X0 projection "
                    f"available ({x0_availability['status']}, "
                    f"{summary.get('registered_repositories', 0)} repos)"
                ),
                surface_status=(
                    SurfaceStatus.DERIVED.value
                    if repo_count > 0
                    else SurfaceStatus.VERIFICATION_PENDING.value
                ),
                status_detail=(
                    f"[X0: {x0_availability['status']}] "
                    f"Repository estate projection derived from backend "
                    f"data plane"
                ),
            )
        # X0 unavailable/connection_required/corrupt_source/degraded/refused
        if x0_status == "corrupt_source":
            surface_status = SurfaceStatus.ERROR.value
            status_detail = (
                f"[X0: corrupt_source] Evidence corruption detected — "
                f"{x0_availability.get('reason', 'integrity failure')}"
            )
        elif x0_status == "connection_required":
            surface_status = SurfaceStatus.CONNECTION_REQUIRED.value
            status_detail = "X0 backend is unreachable — data plane connection required"
        else:
            surface_status = SurfaceStatus.SETUP_REQUIRED.value
            status_detail = f"[X0: {x0_status}] Backend not reachable"
        return RepositoryEstateSurfaceProjection(
            available=False,
            authority_state="missing",
            trust_state=TrustState.DEFERRED,
            degraded_reason=f"RepositoryEstateService (T3.1) cannot be loaded [X0: {x0_status}]",
            surface_status=surface_status,
            status_detail=status_detail,
        )

    try:
        proj = estate.build_projection()
        if proj is None:
            return RepositoryEstateSurfaceProjection(
                available=False,
                authority_state="missing",
                trust_state=TrustState.DEFERRED,
                degraded_reason="RepositoryEstateService returned None projection",
                surface_status=SurfaceStatus.VERIFICATION_PENDING.value,
                status_detail="Repository estate service is being verified",
            )
    except Exception as exc:
        return RepositoryEstateSurfaceProjection(
            available=False,
            authority_state="corrupt",
            trust_state=TrustState.CORRUPT,
            degraded_reason=f"RepositoryEstateService.build_projection raised: {exc}",
            surface_status=SurfaceStatus.ERROR.value,
            status_detail="Could not load repository data",
        )

    repos = []
    for r in proj.registered_repositories or []:
        repos.append(
            EstateRepositoryEntry(
                provenance=ProvenanceClass.DERIVED_PROJECTION,
                repository_hash=getattr(r, "repository_hash", ""),
                repository_label=getattr(r, "repository_label", ""),
                repository_kind=str(getattr(r, "repository_kind", "local_only")),
                root_path_digest=getattr(r, "root_path_digest", ""),
                registered_at=getattr(r, "registered_at", ""),
                last_registered_at=getattr(r, "last_registered_at", ""),
                latest_observation_digest=getattr(r, "latest_observation_digest", None)
                or "",
                latest_observation_at=getattr(r, "latest_observation_at", None) or "",
                latest_status=str(getattr(r, "latest_status", "unknown")),
                latest_head_sha=getattr(r, "latest_head_sha", None) or "",
                latest_branch=getattr(r, "latest_branch", None) or "",
                is_detached=getattr(r, "is_detached", False),
                is_dirty=getattr(r, "is_dirty", False),
                dirty_modified=getattr(r, "dirty_modified", 0),
                dirty_untracked=getattr(r, "dirty_untracked", 0),
                tracked_file_count=getattr(r, "tracked_file_count", 0),
                instruction_file_count=getattr(r, "instruction_file_count", 0),
                remote_count=getattr(r, "remote_count", 0),
                degraded_reason=getattr(r, "degraded_reason", ""),
            )
        )

    changes = []
    for c in proj.recent_changes or []:
        changes.append(
            EstateChangeEntry(
                provenance=ProvenanceClass.DERIVED_PROJECTION,
                repository_hash=getattr(c, "repository_hash", ""),
                repository_label=getattr(c, "repository_label", ""),
                detected_at=getattr(c, "detected_at", ""),
                change_kinds=[
                    k.value if hasattr(k, "value") else str(k)
                    for k in (getattr(c, "change_kinds", []) or [])
                ],
            )
        )

    corruptions = []
    for ce in proj.corruption_events or []:
        corruptions.append(
            EstateCorruptionEntry(
                provenance=ProvenanceClass.CORRUPT_UNTRUSTED,
                event_kind=getattr(ce, "event_kind", ""),
                repository_hash=getattr(ce, "repository_hash", ""),
                reason=getattr(ce, "reason", ""),
            )
        )

    authority_state = (
        proj.authority_state.value
        if hasattr(proj.authority_state, "value")
        else str(getattr(proj, "authority_state", "missing"))
    )

    trust = TrustState.DEFERRED
    if authority_state == "canonical_live":
        trust = TrustState.TRUSTED_LIVE
    elif authority_state == "degraded":
        trust = TrustState.TRUSTED_LIVE
    elif authority_state == "corrupt":
        trust = TrustState.CORRUPT

    repo_count = len(repos)
    if repo_count > 0:
        surface_status = SurfaceStatus.AVAILABLE.value
        status_detail = f"{repo_count} repositories registered"
    else:
        surface_status = SurfaceStatus.DERIVED.value
        status_detail = "No repositories registered"

    return RepositoryEstateSurfaceProjection(
        available=getattr(proj, "available", False),
        authority_state=authority_state,
        trust_state=trust,
        degraded_reason=getattr(proj, "degraded_reason", ""),
        surface_status=surface_status,
        status_detail=status_detail,
        registered_repositories=repos,
        total_registered=getattr(proj, "total_registered", 0),
        local_only_count=getattr(proj, "local_only_count", 0),
        github_backed_count=getattr(proj, "github_backed_count", 0),
        dirty_count=getattr(proj, "dirty_count", 0),
        inaccessible_count=getattr(proj, "inaccessible_count", 0),
        recent_changes=changes,
        total_observations=getattr(proj, "total_observations", 0),
        corrupt_registration_count=getattr(proj, "corrupt_registration_count", 0),
        corrupt_observation_count=getattr(proj, "corrupt_observation_count", 0),
        corrupt_chain_links=getattr(proj, "corrupt_chain_links", 0),
        corruption_events=corruptions,
        content_light_guarantee=getattr(proj, "content_light_guarantee", True),
    )


# ── Publish Preview Surface Projection Builder ────────


def PUBLISH_PREVIEW_SURFACE_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> PublishPreviewSurfaceProjection:
    """Build Publish Preview surface from X3.8 PublicationStatusContract."""
    # Try X3.8 publication projection first
    try:
        from rig_relay.publication._projection import build_publication_projection

        pub_contract = build_publication_projection()
        if pub_contract is not None:
            return _build_from_publication_contract(pub_contract, gateway)
    except Exception:
        pass

    # Fallback: try T1.2 service
    pub = gateway._get_publication_service()
    if pub is not None and pub is not _UNAVAILABLE_SENTINEL:
        try:
            preview = pub.build_preview()
            if preview is not None:
                return _build_from_preview(preview, gateway)
        except Exception:
            pass

    # Unavailable fallback
    return PublishPreviewSurfaceProjection(
        available=False,
        authority_state="missing",
        trust_state=TrustState.DEFERRED,
        degraded_reason=(
            "Publication projection unavailable: X3.8 PublicationStatusContract "
            "not found and T1.2 preview service not available"
        ),
        surface_status=SurfaceStatus.VERIFICATION_PENDING.value,
        status_detail="Publication preview is awaiting upstream handoff",
    )


# ── Publish Preview helper builders ───────────────────


def _build_from_publication_contract(
    pub_contract: Any, gateway: DeveloperStudioGatewayService
) -> PublishPreviewSurfaceProjection:
    """Build PublishPreviewSurfaceProjection from X3.8 PublicationStatusContract."""
    status = getattr(pub_contract, "transition_phase", "unavailable")

    surface_status = _map_publication_status_to_surface(status)
    authority = _map_publication_status_to_authority(status)

    return PublishPreviewSurfaceProjection(
        available=status not in ("unavailable", "corrupt_source"),
        authority_state=authority,
        trust_state=(
            TrustState.TRUSTED_LIVE
            if authority == "canonical_live"
            else TrustState.DEFERRED
        ),
        degraded_reason=getattr(pub_contract, "status_message", ""),
        surface_status=surface_status,
        status_detail=f"Publication status: {status}",
        operation_id=getattr(pub_contract, "publication_operation_id", ""),
        last_result_status=status,
        preview_result=_build_preview_evidence(pub_contract),
        ledger_total_events=(
            1 if getattr(pub_contract, "available_actions", None) else 0
        ),
        ledger_valid_rows=(
            1
            if getattr(pub_contract, "published_verified", False)
            and not getattr(pub_contract, "refusal_code", None)
            else 0
        ),
        ledger_corrupt_rows=(
            1
            if getattr(pub_contract, "refusal_code", None)
            and not getattr(pub_contract, "published_verified", False)
            else 0
        ),
        ledger_corruption_detected=getattr(pub_contract, "refusal_code", None)
        is not None,
        publishable_repository_count=0,
        deployment_available=status == "content_published",
        deployment_deferred_reason=_map_deployment_reason(status),
        content_light_guarantee=True,
        # X3.8 publication contract fields
        publication_preparation_available=status == "prepared",
        authorization_status_field=getattr(
            pub_contract, "authorization_status", "unavailable"
        ),
        authorization_receipt_digest=getattr(pub_contract, "evidence_linkage", {}).get(
            "terminal_receipt_digest", ""
        ),
        content_commit_prepared=status
        in ("content_published", "published_verified", "build_pending"),
        ref_update_complete=getattr(pub_contract, "published_verified", False),
        pages_configuration_state=(
            "configured"
            if getattr(pub_contract, "pages_configured", False)
            else "unavailable"
        ),
        build_status_field=getattr(pub_contract, "build_status", "unavailable"),
        published_verification_complete=getattr(
            pub_contract, "published_verified", False
        ),
        conflict_detected=status == "refused",
        recovery_available=getattr(pub_contract, "recovery_required", False),
        external_acceptance_state=(
            "verified"
            if getattr(pub_contract, "published_verified", False)
            else "pending"
        ),
    )


def _build_from_preview(
    preview: Any, gateway: DeveloperStudioGatewayService
) -> PublishPreviewSurfaceProjection:
    """Build PublishPreviewSurfaceProjection from T1.2 preview result."""
    receipt = getattr(preview, "receipt", None)
    preview_result = None
    if receipt is not None:
        try:
            preview_result = PublishPreviewEvidenceSummary(
                receipt_id=getattr(receipt, "receipt_id", ""),
                compiled_at=getattr(receipt, "compiled_at", ""),
                compilation_successful=getattr(
                    receipt, "compilation_successful", False
                ),
                profile_candidate_digest=getattr(
                    receipt, "profile_candidate_digest", ""
                ),
                safety_passed=getattr(receipt, "safety_passed", False),
                preview_only=getattr(receipt, "preview_only", True),
                deployment_ready=getattr(receipt, "deployment_ready", False),
                evidence_digest=getattr(receipt, "evidence_digest", ""),
            )
        except Exception:
            pass

    publishable_count = 0
    j0 = gateway._get_j0_service()
    if j0 is not None and j0 is not _UNAVAILABLE_SENTINEL:
        try:
            gridline = j0.build_gridline_projection()
            if gridline:
                publishable_count = getattr(gridline, "publishable_count", 0)
        except Exception:
            pass

    if publishable_count > 0:
        surface_status = SurfaceStatus.BLOCKED.value
        authority = "integration_blocked"
    else:
        surface_status = SurfaceStatus.VERIFICATION_PENDING.value
        authority = "missing"

    return PublishPreviewSurfaceProjection(
        available=publishable_count > 0,
        authority_state=authority,
        trust_state=TrustState.DEFERRED,
        degraded_reason=(
            "Publishable repositories exist but publication evidence "
            "consumption is blocked pending upstream infrastructure "
            "verification."
        )
        if publishable_count > 0
        else "No publishable repositories and no public publication history API",
        surface_status=surface_status,
        status_detail=(
            "Publication integration is pending upstream verification"
            if publishable_count > 0
            else "No publishable repositories available"
        ),
        preview_result=preview_result,
        publishable_repository_count=publishable_count,
        deployment_available=False,
        deployment_deferred_reason=(
            "Publication integration is pending upstream infrastructure verification."
        ),
        content_light_guarantee=True,
    )


def _map_publication_status_to_surface(status: str) -> str:
    mapping = {
        "prepared": SurfaceStatus.SETUP_REQUIRED.value,
        "authorization_required": SurfaceStatus.SETUP_REQUIRED.value,
        "authorized": SurfaceStatus.AVAILABLE.value,
        "refused": SurfaceStatus.BLOCKED.value,
        "content_commit_created_ref_not_updated": SurfaceStatus.AVAILABLE.value,
        "content_published": SurfaceStatus.AVAILABLE.value,
        "pages_configuration_unchanged": SurfaceStatus.SETUP_REQUIRED.value,
        "build_requested": SurfaceStatus.VERIFICATION_PENDING.value,
        "build_pending": SurfaceStatus.VERIFICATION_PENDING.value,
        "published_verified": SurfaceStatus.AVAILABLE.value,
        "failed": SurfaceStatus.ERROR.value,
        "recovery_required": SurfaceStatus.ERROR.value,
        "content_publication_started": SurfaceStatus.VERIFICATION_PENDING.value,
        "content_publication_partial": SurfaceStatus.ERROR.value,
        "content_publication_prepared": SurfaceStatus.AVAILABLE.value,
        "pages_created": SurfaceStatus.AVAILABLE.value,
        "pages_updated": SurfaceStatus.AVAILABLE.value,
    }
    return mapping.get(status, SurfaceStatus.VERIFICATION_PENDING.value)


def _map_publication_status_to_authority(status: str) -> str:
    if status in (
        "content_published",
        "published_verified",
        "pages_created",
        "pages_updated",
    ):
        return "canonical_live"
    if status in (
        "authorized",
        "content_commit_created_ref_not_updated",
        "build_requested",
        "build_pending",
        "content_publication_started",
        "content_publication_prepared",
    ):
        return "canonical_degraded"
    if status in ("failed", "recovery_required"):
        return "corrupt"
    if status in ("refused",):
        return "refused"
    return "missing"


def _map_deployment_reason(status: str) -> str:
    reasons = {
        "prepared": "Publication not yet prepared",
        "authorization_required": "Step-up authorization required",
        "authorization_refused": "Authorization was refused",
        "content_commit_created_ref_not_updated": "Content prepared but not yet pushed",
        "content_published": "",
        "pages_configuration_unchanged": "GitHub Pages configuration required",
        "build_requested": "GitHub Pages build pending",
        "build_pending": "GitHub Pages build pending",
        "published_verified": "",
        "failed": "Publication conflict detected",
        "recovery_required": "Publication recovery required",
        "content_publication_started": "Publication in progress",
        "content_publication_partial": "Publication partially completed",
    }
    return reasons.get(status, "Publication not available")


def _build_preview_evidence(pub_contract: Any) -> PublishPreviewEvidenceSummary | None:
    try:
        evidence_linkage = getattr(pub_contract, "evidence_linkage", {}) or {}
        return PublishPreviewEvidenceSummary(
            receipt_id=evidence_linkage.get("terminal_receipt_digest", ""),
            compiled_at=evidence_linkage.get("evidence_ledger_path", ""),
            compilation_successful=not getattr(pub_contract, "refusal_code", None),
            profile_candidate_digest=getattr(pub_contract, "projection_digest", ""),
            safety_passed=not getattr(pub_contract, "refusal_code", None),
            preview_only=True,
            deployment_ready=getattr(pub_contract, "transition_phase", "")
            == "content_published",
            evidence_digest=getattr(pub_contract, "projection_digest", ""),
        )
    except Exception:
        return None


# ── Timeline History Surface Projection Builder ────────


def TIMELINE_SURFACE_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> TimelineSurfaceProjection:
    """Build Timeline History surface from T4.2 InvestigationEvidenceTimelineService.

    X1.6 — Falls back to X0ProjectionSurface when primary service is
    unavailable, providing availability-derived status metadata.
    """
    tl = gateway._get_timeline_service()

    # X1.6 — Wire X0ProjectionSurface availability vocabulary
    x0_surface = gateway._get_x0_projection_surface()
    x0_availability = _derive_x0_availability(x0_surface, "investigation_timeline")

    if tl is None or tl is _UNAVAILABLE_SENTINEL:
        x0_status = x0_availability.get("status", "unavailable")
        # Only try X0 fallback when the backend is truly reachable
        if x0_status not in (
            "unavailable",
            "corrupt_source",
            "refused",
            "connection_required",
            "degraded",
        ):
            summary = {}
            try:
                summary = x0_surface.get_timeline_summary()
            except Exception:
                pass
            event_count = summary.get("total_events", 0)
            return TimelineSurfaceProjection(
                available=event_count > 0,
                authority_state="canonical_degraded",
                trust_state=TrustState.TRUSTED_LIVE,
                degraded_reason=(
                    f"InvestigationEvidenceTimelineService unavailable; "
                    f"X0 projection available ({x0_availability['status']}, "
                    f"{event_count} events)"
                ),
                surface_status=(
                    SurfaceStatus.DERIVED.value
                    if event_count > 0
                    else SurfaceStatus.VERIFICATION_PENDING.value
                ),
                status_detail=(
                    f"[X0: {x0_availability['status']}] "
                    f"Timeline projection derived from backend data plane"
                ),
                corrupt_count=summary.get("corrupt", 0),
                missing_count=summary.get("missing", 0),
                contradictory_count=summary.get("contradictory", 0),
                stale_count=summary.get("stale", 0),
                unsupported_count=summary.get("unsupported", 0),
                verified_canonical_count=summary.get("verified_canonical", 0),
            )
        # X0 unavailable/connection_required/corrupt_source/degraded/refused
        if x0_status == "corrupt_source":
            surface_status = SurfaceStatus.ERROR.value
            status_detail = (
                f"[X0: corrupt_source] Evidence corruption detected — "
                f"{x0_availability.get('reason', 'integrity failure')}"
            )
        elif x0_status == "connection_required":
            surface_status = SurfaceStatus.CONNECTION_REQUIRED.value
            status_detail = "X0 backend is unreachable — data plane connection required"
        else:
            surface_status = SurfaceStatus.SETUP_REQUIRED.value
            status_detail = f"[X0: {x0_status}] Backend not reachable"
        return TimelineSurfaceProjection(
            available=False,
            authority_state="missing",
            trust_state=TrustState.DEFERRED,
            degraded_reason=f"InvestigationEvidenceTimelineService (T4.2) cannot be loaded [X0: {x0_status}]",
            surface_status=surface_status,
            status_detail=status_detail,
        )

    try:
        result = tl.assemble_timeline()
        if result is None:
            return TimelineSurfaceProjection(
                available=False,
                authority_state="missing",
                trust_state=TrustState.DEFERRED,
                degraded_reason="Timeline assembly returned None",
            )
        timeline = result.timeline
    except Exception as exc:
        return TimelineSurfaceProjection(
            available=False,
            authority_state="corrupt",
            trust_state=TrustState.CORRUPT,
            degraded_reason=f"Timeline assembly raised: {exc}",
        )

    events: list[TimelineEventEntry] = []
    for e in (timeline.events or [])[:500]:
        events.append(
            TimelineEventEntry(
                event_id=getattr(e, "event_id", ""),
                timeline_sequence=getattr(e, "timeline_sequence", 0),
                observed_at=getattr(e, "observed_at", ""),
                event_kind=(
                    getattr(e, "event_kind", "").value
                    if hasattr(getattr(e, "event_kind", ""), "value")
                    else str(getattr(e, "event_kind", ""))
                ),
                source_domain=(
                    getattr(e, "source_domain", "").value
                    if hasattr(getattr(e, "source_domain", ""), "value")
                    else str(getattr(e, "source_domain", ""))
                ),
                verification_class=(
                    getattr(e, "verification_class", "").value
                    if hasattr(getattr(e, "verification_class", ""), "value")
                    else str(getattr(e, "verification_class", "parsed_unverified"))
                ),
                authority_classification=(
                    getattr(e, "authority_classification", "").value
                    if hasattr(getattr(e, "authority_classification", ""), "value")
                    else str(getattr(e, "authority_classification", "canonical_live"))
                ),
                degradation_detail=getattr(e, "degradation_detail", None),
                session_id=getattr(e, "session_id", None),
                task_id=getattr(e, "task_id", None),
                operation_id=getattr(e, "operation_id", None),
                outcome=getattr(e, "outcome", None),
                status=getattr(e, "status", None),
                latency_ms=getattr(e, "latency_ms", None),
                path_count=getattr(e, "path_count", None),
                artifact_kind=getattr(e, "artifact_kind", None),
                commit_sha=getattr(e, "commit_sha", None),
                refusal_code=getattr(e, "refusal_code", None),
            )
        )

    dg = getattr(timeline, "degradation_summary", None)
    assembly_errors = result.errors if hasattr(result, "errors") else []

    corrupt_count = getattr(dg, "corrupt_count", 0) if dg else 0
    missing_count = getattr(dg, "missing_count", 0) if dg else 0
    contradictory_count = getattr(dg, "contradictory_count", 0) if dg else 0
    stale_count = getattr(dg, "stale_count", 0) if dg else 0
    unsupported_count = getattr(dg, "unsupported_count", 0) if dg else 0

    if assembly_errors or corrupt_count > 0:
        surface_status = SurfaceStatus.ERROR.value
        status_detail = "Timeline contains evidence integrity issues"
        authority = "corrupt"
        trust = TrustState.CORRUPT
        degraded_reason = "Timeline contains corrupt evidence"
    elif missing_count > 0 or stale_count > 0:
        surface_status = SurfaceStatus.DERIVED.value
        status_detail = "Timeline assembled with partial evidence"
        authority = "canonical_degraded"
        trust = TrustState.DEFERRED
        degraded_reason = "Timeline has missing or stale evidence"
    elif contradictory_count > 0:
        surface_status = SurfaceStatus.DERIVED.value
        status_detail = "Timeline contains contradictory evidence"
        authority = "canonical_degraded"
        trust = TrustState.REFUSED
        degraded_reason = "Timeline contains contradictory evidence"
    elif unsupported_count > 0:
        surface_status = SurfaceStatus.DERIVED.value
        status_detail = "Timeline has unsupported evidence domains"
        authority = "canonical_degraded"
        trust = TrustState.TRUSTED_LIVE
        degraded_reason = "Timeline has unsupported evidence domains"
    else:
        surface_status = SurfaceStatus.AVAILABLE.value
        status_detail = f"{len(events)} events assembled"
        authority = "canonical_live"
        trust = TrustState.TRUSTED_LIVE
        degraded_reason = ""

    return TimelineSurfaceProjection(
        available=True,
        authority_state=authority,
        trust_state=trust,
        degraded_reason=degraded_reason,
        surface_status=surface_status,
        status_detail=status_detail,
        timeline_id=getattr(timeline, "timeline_id", ""),
        assembled_at=getattr(timeline, "assembled_at", ""),
        investigation_id=getattr(timeline, "investigation_id", None),
        session_id=getattr(timeline, "session_id", None),
        project_id=getattr(timeline, "project_id", None),
        events=events,
        event_count=getattr(timeline, "event_count", len(events)),
        domain_coverage=getattr(timeline, "domain_coverage", {}) or {},
        unsupported_domains=getattr(timeline, "unsupported_domains", []) or [],
        verified_canonical_count=getattr(dg, "verified_canonical_count", 0)
        if dg
        else 0,
        parsed_unverified_count=getattr(dg, "parsed_unverified_count", 0) if dg else 0,
        canonical_degraded_count=getattr(dg, "canonical_degraded_count", 0)
        if dg
        else 0,
        corrupt_count=getattr(dg, "corrupt_count", 0) if dg else 0,
        unsupported_count=getattr(dg, "unsupported_count", 0) if dg else 0,
        missing_count=getattr(dg, "missing_count", 0) if dg else 0,
        contradictory_count=getattr(dg, "contradictory_count", 0) if dg else 0,
        stale_count=getattr(dg, "stale_count", 0) if dg else 0,
        assembly_warnings=result.warnings if hasattr(result, "warnings") else [],
        assembly_errors=result.errors if hasattr(result, "errors") else [],
        content_light_guarantee=getattr(timeline, "content_light_guarantee", True),
    )


# ── Inference Studio Surface Projection Builder ────────


def INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> InferenceStudioSurfaceProjection:
    """Build Inference Studio surface with truthful OMLX/X2 pending disclosure."""
    m0 = gateway._get_m0_service()

    if m0 is None:
        return InferenceStudioSurfaceProjection(
            available=False,
            authority_state="missing",
            trust_state=TrustState.DEFERRED,
            degraded_reason="M0 inference service cannot be loaded",
            surface_status=SurfaceStatus.VERIFICATION_PENDING.value,
            status_detail="Inference Studio service is being verified",
            omlx_strategy="pending_infrastructure_handoff",
            omlx_available=False,
            omlx_disclosure=(
                "Hardware-accelerated local inference is pending "
                "infrastructure integration and verification."
            ),
        )

    runtime_available = False
    runtime_configured = False
    runtime_kind = "unknown"
    platform_class = "unknown"

    try:
        runtime_info = m0.get_runtime_info()
        runtime_available = runtime_info.get("available", False)
        runtime_configured = runtime_info.get("configured", False)
        runtime_kind = runtime_info.get("runtime_kind", "unknown")
        platform_class = runtime_info.get("platform_class", "unknown")
    except Exception:
        pass

    total_results = 0
    total_executed = 0
    total_refused = 0
    drafts_awaiting = 0

    try:
        results = m0.list_results()
        for r in results:
            total_results += 1
            if r.status.value in {"executed", "degraded_json_object_only"}:
                total_executed += 1
                if (
                    hasattr(r, "output_disposition")
                    and r.output_disposition.value == "draft_requires_review"
                ):
                    drafts_awaiting += 1
            else:
                total_refused += 1
    except Exception:
        pass

    if runtime_available and runtime_configured:
        surface_status = SurfaceStatus.AVAILABLE.value
        status_detail = "Local runtime ready"
        authority = "canonical_live"
        trust = TrustState.TRUSTED_LIVE
        reason = ""
    elif runtime_configured:
        surface_status = SurfaceStatus.SETUP_REQUIRED.value
        status_detail = "Runtime configured but not responding"
        authority = "canonical_degraded"
        trust = TrustState.TRUSTED_LIVE
        reason = "Local inference runtime configured but not available"
    else:
        surface_status = SurfaceStatus.VERIFICATION_PENDING.value
        status_detail = "Inference Studio service is being verified"
        authority = "canonical_degraded"
        trust = TrustState.TRUSTED_LIVE
        reason = "No local inference runtime configured"

    return cast(
        InferenceStudioSurfaceProjection,
        _merge_safari_fields(
            InferenceStudioSurfaceProjection(
                available=True,
                authority_state=authority,
                trust_state=trust,
                degraded_reason=reason,
                surface_status=surface_status,
                status_detail=status_detail,
                runtime_available=runtime_available,
                runtime_configured=runtime_configured,
                runtime_kind=runtime_kind,
                platform_class=platform_class,
                omlx_strategy="pending_infrastructure_handoff",
                omlx_available=False,
                omlx_disclosure=(
                    "Hardware-accelerated local inference is pending "
                    "infrastructure integration and verification."
                ),
                task_suitability_count=4,
                total_results=total_results,
                total_executed=total_executed,
                total_refused=total_refused,
                drafts_awaiting_review=drafts_awaiting,
                native_schema_capability_claimed=False,
                native_schema_capability_proven=False,
                grammar_capability_claimed=False,
                grammar_capability_proven=False,
            )
        ),
    )


# ── Y1-Y4 Deferred Surface Projection Builders ──────


def REPOSITORY_READINESS_SURFACE_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> RepositoryReadinessSurfaceProjection:
    """Repository Readiness surface — deferred to Y1."""
    return RepositoryReadinessSurfaceProjection()


def FLEET_WORKSPACES_SURFACE_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> FleetWorkspacesSurfaceProjection:
    """Fleet Workspaces surface — deferred to Y2."""
    return FleetWorkspacesSurfaceProjection()


def HARNESS_PROFILE_SURFACE_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> HarnessProfileSurfaceProjection:
    """Harness Profile surface — deferred to Y3."""
    return HarnessProfileSurfaceProjection()


def ANALYTICS_REPORTS_SURFACE_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> AnalyticsReportsSurfaceProjection:
    """Analytics & Reports surface — deferred to Y4."""
    return AnalyticsReportsSurfaceProjection()


__all__ = [
    "ANALYTICS_REPORTS_SURFACE_PROJECTION_BUILDER",
    "CONNECT_SURFACE_PROJECTION_BUILDER",
    "FLEET_WORKSPACES_SURFACE_PROJECTION_BUILDER",
    "HARNESS_PROFILE_SURFACE_PROJECTION_BUILDER",
    "INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER",
    "PUBLISH_PREVIEW_SURFACE_PROJECTION_BUILDER",
    "REPOSITORY_ESTATE_SURFACE_PROJECTION_BUILDER",
    "REPOSITORY_READINESS_SURFACE_PROJECTION_BUILDER",
    "TIMELINE_SURFACE_PROJECTION_BUILDER",
    "_build_from_preview",
    "_build_from_publication_contract",
    "_build_preview_evidence",
    "_derive_x0_availability",
    "_map_deployment_reason",
    "_map_publication_status_to_authority",
    "_map_publication_status_to_surface",
]
