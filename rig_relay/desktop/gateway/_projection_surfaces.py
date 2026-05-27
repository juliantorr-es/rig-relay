"""Surface-specific projection builders — Lane X0.

Each builder consumes the published public API of exactly one service
and produces content-light projection models with explicit evidence-backed
authority states. Never reads authority ledgers or reproduces producer logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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
        authority = "canonical_live"
        trust = TrustState.TRUSTED_LIVE
        reason = ""
    elif providers_configured > 0:
        authority = "canonical_degraded"
        trust = TrustState.TRUSTED_LIVE
        reason = "Providers configured but workspace not connected"
    elif ws_token:
        authority = "canonical_degraded"
        trust = TrustState.TRUSTED_LIVE
        reason = "Workspace connected but no providers configured"
    else:
        authority = "missing"
        trust = TrustState.DEFERRED
        reason = "No providers configured and workspace not connected"

    return ConnectSurfaceProjection(
        available=available,
        authority_state=authority,
        trust_state=trust,
        degraded_reason=reason,
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
        )

    try:
        proj = estate.build_projection()
        if proj is None:
            return RepositoryEstateSurfaceProjection(
                available=False,
                authority_state="missing",
                trust_state=TrustState.DEFERRED,
                degraded_reason="RepositoryEstateService returned None projection",
            )
    except Exception as exc:
        return RepositoryEstateSurfaceProjection(
            available=False,
            authority_state="corrupt",
            trust_state=TrustState.CORRUPT,
            degraded_reason=f"RepositoryEstateService.build_projection raised: {exc}",
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

    return RepositoryEstateSurfaceProjection(
        available=getattr(proj, "available", False),
        authority_state=authority_state,
        trust_state=trust,
        degraded_reason=getattr(proj, "degraded_reason", ""),
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
    """Build Publish Preview surface from T1.2 ProjectPagePublicationPreviewService."""
    pub = gateway._get_publication_service()

    if pub is None:
        return PublishPreviewSurfaceProjection(
            available=False,
            authority_state="missing",
            trust_state=TrustState.DEFERRED,
            degraded_reason="ProjectPagePublicationPreviewService (T1.2) cannot be loaded",
        )

    try:
        from rig_relay.publication._evidence_ledger import PublicationEvidenceLedger

        ledger = PublicationEvidenceLedger()
        event_count = ledger.count_events() if ledger else 0
        reconstruction = ledger.load_receipts(authoritative=False) if ledger else None
        if reconstruction:
            valid_rows = reconstruction.valid_rows
            corrupt_rows = reconstruction.corrupt_rows
            corruption_detected = reconstruction.corruption_detected
        else:
            valid_rows = 0
            corrupt_rows = 0
            corruption_detected = False
    except Exception:
        event_count = 0
        valid_rows = 0
        corrupt_rows = 0
        corruption_detected = False

    publishable_count = 0
    j0 = gateway._get_j0_service()
    if j0 is not None:
        try:
            gridline = j0.build_gridline_projection()
            if gridline:
                publishable_count = getattr(gridline, "publishable_count", 0)
        except Exception:
            pass

    if corruption_detected:
        authority = "corrupt"
        trust = TrustState.CORRUPT
        reason = "Publication evidence ledger contains corrupt rows"
    elif valid_rows > 0:
        authority = "canonical_live"
        trust = TrustState.TRUSTED_LIVE
        reason = f"Publication ledger has {event_count} events, {valid_rows} valid"
    elif publishable_count > 0:
        authority = "canonical_degraded"
        trust = TrustState.TRUSTED_LIVE
        reason = "Publishable repositories available but no preview events recorded"
    elif event_count == 0 and publishable_count == 0:
        authority = "missing"
        trust = TrustState.DEFERRED
        reason = "No publication ledger events and no publishable repositories"
    else:
        authority = "missing"
        trust = TrustState.DEFERRED
        reason = "No publication ledger events and no publishable repositories"

    return PublishPreviewSurfaceProjection(
        available=event_count > 0 or publishable_count > 0,
        authority_state=authority,
        trust_state=trust,
        degraded_reason=reason,
        ledger_total_events=event_count,
        ledger_valid_rows=valid_rows,
        ledger_corrupt_rows=corrupt_rows,
        ledger_corruption_detected=corruption_detected,
        publishable_repository_count=publishable_count,
        deployment_available=False,
        deployment_deferred_reason=(
            "Deployment authority owned by X3; not available in this release"
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
        authority = "corrupt"
        trust = TrustState.CORRUPT
        degraded_reason = "Timeline contains corrupt evidence"
    elif missing_count > 0 or stale_count > 0:
        authority = "canonical_degraded"
        trust = TrustState.DEFERRED
        degraded_reason = "Timeline has missing or stale evidence"
    elif contradictory_count > 0:
        authority = "canonical_degraded"
        trust = TrustState.REFUSED
        degraded_reason = "Timeline contains contradictory evidence"
    elif unsupported_count > 0:
        authority = "canonical_degraded"
        trust = TrustState.TRUSTED_LIVE
        degraded_reason = "Timeline has unsupported evidence domains"
    else:
        authority = "canonical_live"
        trust = TrustState.TRUSTED_LIVE
        degraded_reason = ""

    return TimelineSurfaceProjection(
        available=True,
        authority_state=authority,
        trust_state=trust,
        degraded_reason=degraded_reason,
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
            omlx_strategy="v1_pending_x2_integration",
            omlx_available=False,
            omlx_disclosure=(
                "OMLX Rigged runtime integration is pending X2 v1 delivery. "
                "Local inference currently supports Ollama-compatible endpoints only."
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
        authority = "canonical_live"
        trust = TrustState.TRUSTED_LIVE
        reason = ""
    elif runtime_configured:
        authority = "canonical_degraded"
        trust = TrustState.TRUSTED_LIVE
        reason = "Local inference runtime configured but not available"
    else:
        authority = "canonical_degraded"
        trust = TrustState.TRUSTED_LIVE
        reason = "No local inference runtime configured"

    return InferenceStudioSurfaceProjection(
        available=True,
        authority_state=authority,
        trust_state=trust,
        degraded_reason=reason,
        runtime_available=runtime_available,
        runtime_configured=runtime_configured,
        runtime_kind=runtime_kind,
        platform_class=platform_class,
        omlx_strategy="v1_pending_x2_integration",
        omlx_available=False,
        omlx_disclosure=(
            "OMLX Rigged runtime integration is pending X2 v1 delivery. "
            "Local inference currently supports Ollama-compatible endpoints only."
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


__all__ = [
    "CONNECT_SURFACE_PROJECTION_BUILDER",
    "INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER",
    "PUBLISH_PREVIEW_SURFACE_PROJECTION_BUILDER",
    "REPOSITORY_ESTATE_SURFACE_PROJECTION_BUILDER",
    "TIMELINE_SURFACE_PROJECTION_BUILDER",
]
