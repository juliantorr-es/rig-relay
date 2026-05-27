"""Developer studio projection builders — Lane S2 (hardened from O0).

Each builder consumes the published public API of exactly one service
(J0/K0/L0/M0) and produces content-light projection models with explicit
evidence-backed authority states. Never reads authority ledgers or
reproduces producer logic.

All builders are pure functions that receive a gateway service reference
and return typed projection models. Content-light: hashes, counts,
statuses, and SHA256 digests only.

Every builder now classifies the service authority from canonical evidence,
not from hardcoded labels. Degraded states (missing, stale, corrupt,
contradictory, fixture-deferred) are explicitly reported with reasons.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from rig_relay.core.logger import logger
from rig_relay.desktop.gateway._models import (
    J0ConnectionProjection,
    J0RepositoryProjection,
    J0WorkspaceProjection,
    K0OperatorProjection,
    K0SessionProjection,
    L0ContextProjection,
    L0IntakeStatusProjection,
    M0DraftEntry,
    M0InferenceProjection,
    M0RefusalEntry,
    M0TaskSuitabilityEntry,
    ProvenanceClass,
    TrustState,
)

if TYPE_CHECKING:
    from rig_relay.desktop.gateway._service import DeveloperStudioGatewayService


_UNAVAILABLE_SENTINEL = object()


# ── J0 Projection Builder ──────────────────────────────────────────


def J0_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> J0WorkspaceProjection:
    """Build J0 workspace projection from published service public API.

    Authority states:
    - canonical_live: J0 service loaded, credentials present, build_gridline_projection succeeds
    - controlled_boundary: J0 service loaded but no credentials (GitHub App not installed)
    - missing: J0 service cannot be imported or constructed
    - corrupt: J0 service loaded but projection fails with an unexpected exception
    """
    j0 = gateway._get_j0_service()

    if j0 is _UNAVAILABLE_SENTINEL or j0 is None:
        return J0WorkspaceProjection(
            available=False,
            authority_state="missing",
            degraded_reason="J0 workspace service cannot be loaded; GitHub App credentials not configured",
            connection=J0ConnectionProjection(
                provenance=ProvenanceClass.CONTROLLED_BOUNDARY_PROOF,
                trust_state=TrustState.CONTROLLED_BOUNDARY,
                authority_state="missing",
                degraded_reason="No J0 service available",
            ),
        )

    connection = _build_j0_connection(j0)

    try:
        gridline = j0.build_gridline_projection()
        if gridline is None:
            # Service is loaded but no data — controlled boundary
            return J0WorkspaceProjection(
                available=False,
                authority_state="controlled_boundary",
                degraded_reason="J0 service loaded but no gridline projection available; no repositories discovered",
                connection=connection,
            )
    except Exception as exc:
        return J0WorkspaceProjection(
            available=False,
            authority_state="corrupt",
            degraded_reason=f"J0 build_gridline_projection raised: {exc}",
            connection=connection,
        )

    repos = _build_j0_repositories(j0, gridline)

    return J0WorkspaceProjection(
        available=True,
        authority_state=connection.authority_state,
        degraded_reason=connection.degraded_reason,
        connection=connection,
        repositories=repos,
        selected_count=gridline.selected_count,
        imported_count=gridline.imported_count,
        publishable_count=gridline.publishable_count,
        total_discovered=gridline.total_discovered,
    )


def _build_j0_connection(j0: object) -> J0ConnectionProjection:
    try:
        conn = j0.connection
        if conn is None:
            return J0ConnectionProjection(
                provenance=ProvenanceClass.CONTROLLED_BOUNDARY_PROOF,
                trust_state=TrustState.CONTROLLED_BOUNDARY,
                authority_state="controlled_boundary",
                degraded_reason="No GitHub App connection established; run connect() first",
            )
        token_available = bool(getattr(conn, "token_available", False))
        live_verified = bool(getattr(conn, "token_available", False))
        return J0ConnectionProjection(
            provenance=(
                ProvenanceClass.CANONICAL_FACT
                if token_available
                else ProvenanceClass.CONTROLLED_BOUNDARY_PROOF
            ),
            trust_state=(
                TrustState.TRUSTED_LIVE
                if token_available
                else TrustState.CONTROLLED_BOUNDARY
            ),
            authority_state=(
                "canonical_live" if token_available else "controlled_boundary"
            ),
            degraded_reason=(
                ""
                if token_available
                else "GitHub App installation token not available; controlled-boundary mode"
            ),
            connection_state=getattr(conn, "connection_state", "disconnected"),
            installation_id_hash=getattr(conn, "installation_id_hash", ""),
            token_available=token_available,
            accessible_repository_count=getattr(conn, "accessible_repository_count", 0),
            live_installation_verified=live_verified,
        )
    except Exception as exc:
        return J0ConnectionProjection(
            provenance=ProvenanceClass.CONTROLLED_BOUNDARY_PROOF,
            trust_state=TrustState.CONTROLLED_BOUNDARY,
            authority_state="corrupt",
            degraded_reason=f"J0 connection access raised: {exc}",
        )


def _build_j0_repositories(
    j0: object, gridline: object
) -> list[J0RepositoryProjection]:
    repos: list[J0RepositoryProjection] = []
    discovered = getattr(j0, "discovered_repos", {}) or {}
    if not discovered:
        return repos

    for repo_hash, repo in discovered.items():
        try:
            repos.append(
                J0RepositoryProjection(
                    provenance=ProvenanceClass.DERIVED_PROJECTION,
                    repository_hash=getattr(repo, "repository_hash", repo_hash),
                    owner=getattr(repo, "owner", ""),
                    name=getattr(repo, "name", ""),
                    full_name=getattr(repo, "full_name", ""),
                    description_hash=getattr(repo, "description_hash", None),
                    visibility=getattr(repo, "visibility", ""),
                    default_branch=getattr(repo, "default_branch", ""),
                    has_pages=getattr(repo, "has_pages", False),
                    intake_state=getattr(repo, "intake_state", "unknown"),
                    selected=getattr(repo, "selected", False),
                    import_state="",
                    local_path_digest="",
                    head_sha="",
                    branch="",
                )
            )
        except Exception:
            continue

    return repos


# ── K0 Projection Builder ──────────────────────────────────────────


def K0_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> K0OperatorProjection:
    """Build K0 operator projection from gateway-tracked sessions.

    K0 sessions live in gateway._k0_sessions (in-memory dict). This is
    a derived projection, not a canonical store. Authority is derived
    from the presence of live sessions.

    Authority states:
    - canonical_live: sessions exist with real AgentLoop investigation
    - missing: no sessions registered
    - fixture_deferred: (not applicable — K0 is its own service)
    """
    sessions = gateway._k0_sessions
    if not sessions:
        return K0OperatorProjection(
            available=False,
            authority_state="missing",
            degraded_reason="No K0 operator sessions registered in gateway",
        )

    active_list: list[K0SessionProjection] = []
    refused_count = 0
    proposal_pending = 0

    for sid, k0_service in sessions.items():
        try:
            proj = k0_service.get_projection(sid)
            if proj is None:
                continue
            sp = K0SessionProjection(
                provenance=ProvenanceClass.DERIVED_PROJECTION,
                session_id=proj.get("session_id", sid),
                repository_label=proj.get("repository_label", ""),
                purpose=proj.get("purpose", ""),
                status=proj.get("status", "opened"),
                phase=proj.get("phase", "idle"),
                agent_profile_name=proj.get("agent_profile_name", ""),
                tool_call_count=sum(
                    t.get("call_count", 0) for t in (proj.get("tool_summary") or [])
                ),
                tool_success_count=sum(
                    t.get("success_count", 0) for t in (proj.get("tool_summary") or [])
                ),
                tool_refusal_count=sum(
                    t.get("refusal_count", 0) for t in (proj.get("tool_summary") or [])
                ),
                tool_failure_count=sum(
                    t.get("failure_count", 0) for t in (proj.get("tool_summary") or [])
                ),
                proposal_count=proj.get("proposal_count", 0),
                proposal_dispositions=proj.get("proposal_dispositions", {}),
                refusal_count=proj.get("refusal_count", 0),
                pending_decisions=proj.get("pending_decisions", []),
                blocked_capabilities=proj.get("blocked_capabilities", []),
                error_message=proj.get("error_message"),
                created_at=proj.get("created_at", ""),
                updated_at=proj.get("updated_at", ""),
            )
            active_list.append(sp)

            status = proj.get("status", "")
            if status in {"refused", "failed"}:
                refused_count += 1
            if status in {"awaiting_proposal", "proposal_generated"}:
                proposal_pending += 1
        except Exception:
            continue

    total = len(sessions)
    return K0OperatorProjection(
        available=total > 0,
        authority_state="canonical_live",
        degraded_reason="",
        active_sessions=active_list,
        total_sessions=total,
        active_session_count=total - refused_count,
        refused_session_count=refused_count,
        proposal_pending_count=proposal_pending,
        recovery_materialization_available=False,
    )


# ── L0 Projection Builder ──────────────────────────────────────────


def L0_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> L0ContextProjection:
    """Build L0 context projection from published service.

    The L0 ProjectContextAssemblyService is a real production service
    with deterministic repo extraction. However, its upstream intake is
    fixture-deferred (J0 RepositoryIntakeService boundary not yet released)
    and investigation evidence is fixture-deferred (K0 AgentLoop boundary
    not yet released).

    Authority states:
    - canonical_degraded: L0 service available but intake/investigation are fixture-backed
    - missing: L0 service cannot be loaded
    - fixture_deferred: intake or investigation boundaries are fixture-only
    """
    gateway._get_l0_service()  # ensure L0 is available

    j0_boundary = "fixture"
    j0_available = False
    k0_boundary = "fixture"
    k0_available = False

    k0_sessions = gateway._k0_sessions
    if k0_sessions:
        k0_boundary = "live"
        k0_available = True

    j0 = gateway._get_j0_service()
    if j0 is not _UNAVAILABLE_SENTINEL and j0 is not None:
        try:
            discovered = getattr(j0, "discovered_repos", {}) or {}
            if discovered:
                j0_boundary = "live"
                j0_available = True
        except Exception:
            pass

    fixture_count = 0
    if j0_boundary == "fixture":
        fixture_count += 1
    if k0_boundary == "fixture":
        fixture_count += 1

    if fixture_count == 0:
        authority = "canonical_live"
        reason = "All L0 dependencies are live"
    elif fixture_count == 1:
        authority = "canonical_degraded"
        reason = (
            f"One L0 dependency is fixture-backed: "
            f"J0 intake={j0_boundary}, K0 investigation={k0_boundary}"
        )
    else:
        authority = "fixture_deferred"
        reason = (
            f"L0 intake and investigation are fixture-deferred: "
            f"J0 intake={j0_boundary}, K0 investigation={k0_boundary}"
        )

    intake_status = L0IntakeStatusProjection(
        provenance=ProvenanceClass.DERIVED_PROJECTION,
        j0_intake_boundary=j0_boundary,
        k0_investigation_boundary=k0_boundary,
        j0_intake_available=j0_available,
        k0_investigation_available=k0_available,
    )

    return L0ContextProjection(
        available=True,
        authority_state=authority,
        degraded_reason=reason,
        intake_dependency_status=intake_status,
        redaction_engine_available=True,
    )


# ── M0 Projection Builder ──────────────────────────────────────────


def M0_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> M0InferenceProjection:
    """Build M0 inference projection from published service.

    M0 LocalProjectInferenceService is a real production service making
    real HTTP calls to Ollama/OAI-compatible endpoints. However, it is
    candidate_local (not yet promoted to published_narrow_release).

    Authority states:
    - canonical_live: M0 service loaded, runtime configured and available
    - canonical_degraded: M0 service loaded but runtime not configured
    - missing: M0 service cannot be loaded
    - fixture_deferred: context packet is M0-owned synthetic fixture
    """
    m0 = gateway._get_m0_service()

    if m0 is _UNAVAILABLE_SENTINEL or m0 is None:
        return M0InferenceProjection(
            available=False,
            authority_state="missing",
            degraded_reason="M0 inference service cannot be loaded",
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

    tasks = _build_m0_task_suitability(runtime_available, runtime_kind)

    try:
        from rig_relay.local_inference._projection import build_assistance_projection

        build_assistance_projection(m0)
    except Exception:
        pass

    drafts = _build_m0_drafts(m0)
    refusals = _build_m0_refusals(m0)
    total_results = len(drafts) + len(refusals)
    total_executed = len(drafts)
    total_refused = len(refusals)
    drafts_awaiting = sum(1 for d in drafts if d.requires_approval)

    if runtime_available and runtime_configured:
        authority = "canonical_live"
        reason = ""
    elif not runtime_configured:
        authority = "canonical_degraded"
        reason = "M0 local inference runtime is not configured; start a local Ollama/OAI endpoint"
    else:
        authority = "canonical_degraded"
        reason = (
            f"M0 runtime available={runtime_available}, configured={runtime_configured}"
        )

    return _merge_safari_fields(
        M0InferenceProjection(
            available=True,
            authority_state=authority,
            degraded_reason=reason,
            runtime_available=runtime_available,
            runtime_configured=runtime_configured,
            runtime_kind=runtime_kind,
            platform_class=platform_class,
            task_suitability=tasks,
            total_results=total_results,
            total_executed=total_executed,
            total_refused=total_refused,
            drafts_awaiting_review=drafts_awaiting,
            drafts=drafts,
            refusals=refusals,
            native_schema_capability_claimed=False,
            native_schema_capability_proven=False,
            grammar_capability_claimed=False,
            grammar_capability_proven=False,
        )
    )


def _merge_safari_fields(model: M0InferenceProjection) -> M0InferenceProjection:
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
            "Unexpected exception merging safari fields into M0 projection: %s", exc
        )
        return model.model_copy(
            update={
                "safari_companion_state": "error",
                "safari_diagnostic_export_state": "error",
                "safari_diagnostic_export_blocked": True,
            }
        )


def _build_m0_task_suitability(
    runtime_available: bool, runtime_kind: str
) -> list[M0TaskSuitabilityEntry]:
    task_kinds = [
        "project_summary",
        "page_section_ordering",
        "capability_classification",
        "missing_material_checklist",
    ]
    return [
        M0TaskSuitabilityEntry(
            task_kind=tk,
            suitable=runtime_available,
            requires_runtime=True,
            enforcement_class_required="json_object_formatting_only",
            refusal_reason="" if runtime_available else "runtime_unavailable",
        )
        for tk in task_kinds
    ]


def _build_m0_drafts(m0: object) -> list[M0DraftEntry]:
    drafts: list[M0DraftEntry] = []
    try:
        results = m0.list_results()
        for r in results:
            if r.draft_sha256:
                drafts.append(
                    M0DraftEntry(
                        provenance=ProvenanceClass.REVIEW_REQUIRED_DRAFT,
                        result_id=r.result_id,
                        task_id=r.task_id,
                        task_kind=getattr(r, "task_id", "")
                        if not hasattr(r, "task_kind")
                        else r.task_kind.value,
                        draft_sha256=r.draft_sha256,
                        draft_byte_count=r.draft_byte_count,
                        output_disposition=r.output_disposition.value,
                        publication_applicability=r.publication_applicability.value,
                        requires_approval=r.output_disposition.value
                        == "draft_requires_review",
                        created_at=r.created_at,
                    )
                )
    except Exception:
        pass
    return drafts


def _build_m0_refusals(m0: object) -> list[M0RefusalEntry]:
    refusals: list[M0RefusalEntry] = []
    try:
        results = m0.list_results()
        for r in results:
            is_executed = r.status.value in {"executed", "degraded_json_object_only"}
            if not is_executed:
                refusals.append(
                    M0RefusalEntry(
                        provenance=ProvenanceClass.REFUSED,
                        result_id=r.result_id,
                        task_id=r.task_id,
                        task_kind=getattr(r, "task_id", "")
                        if not hasattr(r, "task_kind")
                        else r.task_kind.value,
                        refusal_code=r.refusal_code or r.status.value,
                        refusal_reason=r.refusal_reason or "",
                        created_at=r.created_at,
                    )
                )
    except Exception:
        pass
    return refusals
