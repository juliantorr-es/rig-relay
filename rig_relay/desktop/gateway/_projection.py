"""Developer studio projection builders — Lane O0.

Each builder consumes the published public API of exactly one service
(J0/K0/L0/M0) and produces content-light projection models. Never reads
authority ledgers or reproduces producer logic.

All builders are pure functions that receive a gateway service reference
and return typed projection models. Content-light: hashes, counts,
statuses, and SHA256 digests only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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


# ── J0 Projection Builder ──────────────────────────────────────────


def J0_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> J0WorkspaceProjection:
    """Build J0 workspace projection from published service public API."""
    j0 = gateway._get_j0_service()

    if j0 is _UNAVAILABLE_SENTINEL or j0 is None:
        return J0WorkspaceProjection(
            available=False,
            connection=J0ConnectionProjection(
                provenance=ProvenanceClass.CONTROLLED_BOUNDARY_PROOF,
                trust_state=TrustState.CONTROLLED_BOUNDARY,
            ),
        )

    try:
        gridline = j0.build_gridline_projection()
        if gridline is None:
            return J0WorkspaceProjection(available=False)
    except Exception:
        return J0WorkspaceProjection(available=False)

    connection = _build_j0_connection(j0)
    repos = _build_j0_repositories(j0, gridline)

    return J0WorkspaceProjection(
        available=True,
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
            )
        return J0ConnectionProjection(
            provenance=ProvenanceClass.CANONICAL_FACT,
            trust_state=(
                TrustState.TRUSTED_LIVE
                if getattr(conn, "token_available", False)
                else TrustState.CONTROLLED_BOUNDARY
            ),
            connection_state=getattr(conn, "connection_state", "disconnected"),
            installation_id_hash=getattr(conn, "installation_id_hash", ""),
            token_available=getattr(conn, "token_available", False),
            accessible_repository_count=getattr(conn, "accessible_repository_count", 0),
            live_installation_verified=bool(getattr(conn, "token_available", False)),
        )
    except Exception:
        return J0ConnectionProjection(
            provenance=ProvenanceClass.CONTROLLED_BOUNDARY_PROOF,
            trust_state=TrustState.CONTROLLED_BOUNDARY,
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
    """Build K0 operator projection from gateway-tracked sessions."""
    sessions = gateway._k0_sessions
    if not sessions:
        return K0OperatorProjection(available=False)

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
    """Build L0 context projection from published service."""
    gateway._get_l0_service()  # ensure L0 is available

    intake_status = L0IntakeStatusProjection(
        provenance=ProvenanceClass.DERIVED_PROJECTION,
        j0_intake_boundary="fixture",
        k0_investigation_boundary="fixture",
        j0_intake_available=False,
        k0_investigation_available=False,
    )

    k0_sessions = gateway._k0_sessions
    if k0_sessions:
        intake_status.k0_investigation_available = True
        intake_status.k0_investigation_boundary = "live"

    j0 = gateway._get_j0_service()
    if j0 is not _UNAVAILABLE_SENTINEL and j0 is not None:
        try:
            discovered = getattr(j0, "discovered_repos", {}) or {}
            if discovered:
                intake_status.j0_intake_available = True
                intake_status.j0_intake_boundary = "live"
        except Exception:
            pass

    return L0ContextProjection(
        available=True,
        intake_dependency_status=intake_status,
        redaction_engine_available=True,
    )


# ── M0 Projection Builder ──────────────────────────────────────────


def M0_PROJECTION_BUILDER(
    gateway: DeveloperStudioGatewayService,
) -> M0InferenceProjection:
    """Build M0 inference projection from published service."""
    m0 = gateway._get_m0_service()

    if m0 is _UNAVAILABLE_SENTINEL or m0 is None:
        return M0InferenceProjection(available=False)

    try:
        runtime_info = m0.get_runtime_info()
    except Exception:
        return M0InferenceProjection(available=False)

    runtime_available = runtime_info.get("available", False)
    runtime_kind = runtime_info.get("runtime_kind", "unknown")
    platform_class = runtime_info.get("platform_class", "unknown")

    tasks = _build_m0_task_suitability(runtime_available, runtime_kind)

    try:
        from rig_relay.local_inference._projection import build_assistance_projection

        build_assistance_projection(m0)  # ensure M0 projection is available
    except Exception:
        pass

    drafts = _build_m0_drafts(m0)
    refusals = _build_m0_refusals(m0)
    total_results = len(drafts) + len(refusals)
    total_executed = len(drafts)
    total_refused = len(refusals)
    drafts_awaiting = sum(1 for d in drafts if d.requires_approval)

    return M0InferenceProjection(
        available=True,
        runtime_available=runtime_available,
        runtime_configured=runtime_info.get("configured", False),
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


# ── Helpers ──────────────────────────────────────────────────────────


_UNAVAILABLE_SENTINEL = object()
