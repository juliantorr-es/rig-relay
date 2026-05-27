"""Surface-specific projection builders — Lane X0.

Each builder consumes the published public API of exactly one service
and produces content-light projection models with explicit evidence-backed
authority states. Never reads authority ledgers or reproduces producer logic.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from rig_relay.core.logger import logger
from rig_relay.desktop.gateway._models import ProvenanceClass, TrustState
from rig_relay.desktop.gateway._models_surfaces import (
    ConnectSurfaceProjection,
    EstateChangeEntry,
    EstateCorruptionEntry,
    EstateRepositoryEntry,
    InferenceStudioSurfaceProjection,
    ProviderConnectionEntry,
    PublishPreviewSurfaceProjection,
    RepositoryEstateSurfaceProjection,
    SurfaceStatus,
    TimelineEventEntry,
    TimelineSurfaceProjection,
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


# ── Repository Estate Surface Projection Builder ──────


def REPOSITORY_ESTATE_SURFACE_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> RepositoryEstateSurfaceProjection:
    """Build Repository Estate surface from T3.1 RepositoryEstateService."""
    estate = gateway._get_repository_estate_service()

    if estate is None:
        return RepositoryEstateSurfaceProjection(
            available=False,
            authority_state="missing",
            trust_state=TrustState.DEFERRED,
            degraded_reason="RepositoryEstateService (T3.1) cannot be loaded",
            surface_status=SurfaceStatus.VERIFICATION_PENDING.value,
            status_detail="Repository estate service is being verified",
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
    """Build Publish Preview surface — integration-blocked on public history API.

    T1.2 does not expose a public history projection API. The PublicationEvidenceLedger
    is a producer-internal store. The gateway must not interpret canonical publication
    evidence without a published consumer boundary.

    Integration contract required (T1.2 / X3.2):
        ProjectPagePublicationPreviewService.build_preview_history(operation_id=None)
            -> PublicationPreviewHistoryProjection
        Required fields: authority_state, operation_count, terminal_success_count,
        terminal_refusal_count, corruption_detected, reconstruction_status,
        latest_events (content-light), deployment_authority_available.
    """
    pub = gateway._get_publication_service()

    if pub is None:
        return PublishPreviewSurfaceProjection(
            available=False,
            authority_state="missing",
            trust_state=TrustState.DEFERRED,
            degraded_reason="ProjectPagePublicationPreviewService (T1.2) cannot be loaded",
            surface_status=SurfaceStatus.VERIFICATION_PENDING.value,
            status_detail="Publication preview is awaiting upstream handoff",
        )

    publishable_count = 0
    j0 = gateway._get_j0_service()
    if j0 is not None:
        try:
            gridline = j0.build_gridline_projection()
            if gridline:
                publishable_count = getattr(gridline, "publishable_count", 0)
        except Exception:
            pass

    if publishable_count > 0:
        surface_status = SurfaceStatus.BLOCKED.value
        status_detail = "Publication integration is pending upstream verification"
        authority = "integration_blocked"
        trust = TrustState.DEFERRED
        reason = (
            "Publishable repositories exist but publication evidence "
            "consumption is blocked pending upstream infrastructure "
            "verification."
        )
    else:
        surface_status = SurfaceStatus.VERIFICATION_PENDING.value
        status_detail = "No publishable repositories available"
        authority = "missing"
        trust = TrustState.DEFERRED
        reason = "No publishable repositories and no public publication history API"

    return PublishPreviewSurfaceProjection(
        available=publishable_count > 0,
        authority_state=authority,
        trust_state=trust,
        degraded_reason=reason,
        surface_status=surface_status,
        status_detail=status_detail,
        ledger_total_events=0,
        ledger_valid_rows=0,
        ledger_corrupt_rows=0,
        ledger_corruption_detected=False,
        publishable_repository_count=publishable_count,
        deployment_available=False,
        deployment_deferred_reason=(
            "Publication integration is pending upstream infrastructure verification."
        ),
        content_light_guarantee=True,
    )


# ── Timeline History Surface Projection Builder ────────


def TIMELINE_SURFACE_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> TimelineSurfaceProjection:
    """Build Timeline History surface from T4.2 InvestigationEvidenceTimelineService."""
    tl = gateway._get_timeline_service()

    if tl is None:
        return TimelineSurfaceProjection(
            available=False,
            authority_state="missing",
            trust_state=TrustState.DEFERRED,
            degraded_reason="InvestigationEvidenceTimelineService (T4.2) cannot be loaded",
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

    return _merge_safari_surface_fields(
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
    )


def _merge_safari_surface_fields(
    model: InferenceStudioSurfaceProjection,
) -> InferenceStudioSurfaceProjection:
    try:
        from rig_relay.native._safari_x0_contract import build_safari_native_projection

        native = build_safari_native_projection()
        return model.model_copy(
            update={
                "safari_companion_state": native.safari_companion_state,
                "safari_extension_built": native.safari_extension_built,
                "safari_distribution_signing_state": native.safari_distribution_signing_state,
                "safari_notarization_state": native.safari_notarization_state,
                "safari_update_delivery_state": native.safari_update_delivery_state,
                "safari_diagnostic_export_state": native.safari_diagnostic_export_state,
                "safari_diagnostic_export_blocked": native.safari_diagnostic_export_blocked,
                "safari_recovery_action_state": native.safari_recovery_action_state,
                "safari_artifact_manifest_available": native.safari_artifact_manifest_available,
                "safari_running": native.safari_running,
                "safari_extension_installed": native.safari_extension_installed,
                "safari_extension_enabled": native.safari_extension_enabled,
                "safari_extension_error": native.safari_extension_error,
                "safari_build_environment": native.build_environment,
                "safari_projection_generated_at": native.generated_at,
            }
        )
    except (
        ImportError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return model.model_copy(
            update={
                "safari_companion_state": "error",
                "safari_diagnostic_export_state": "error",
                "safari_diagnostic_export_blocked": True,
            }
        )
    except Exception as exc:
        logger.warning(
            "Unexpected exception merging safari fields into "
            "Inference Studio surface projection: %s",
            exc,
        )
        return model.model_copy(
            update={
                "safari_companion_state": "error",
                "safari_diagnostic_export_state": "error",
                "safari_diagnostic_export_blocked": True,
            }
        )


__all__ = [
    "CONNECT_SURFACE_PROJECTION_BUILDER",
    "INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER",
    "PUBLISH_PREVIEW_SURFACE_PROJECTION_BUILDER",
    "REPOSITORY_ESTATE_SURFACE_PROJECTION_BUILDER",
    "TIMELINE_SURFACE_PROJECTION_BUILDER",
]
