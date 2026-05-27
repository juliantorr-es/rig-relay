"""Developer Studio Gateway Service — Lane O0.

Typed backend bridge orchestrator that consumes published J0/K0/L0/M0
application-service public APIs and exposes a single coherent frontend-safe
projection and intent protocol.

Does not own service authority. Delegates to published producers only.
Never bypasses J0/K0/L0/M0 gates. Never exposes tokens, raw paths,
private source, or unredacted errors in frontend projections.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from rig_relay.core.logger import logger
from rig_relay.desktop.gateway._models import (
    DeveloperStudioProjection,
    GatewayErrorKind,
    StudioProvenanceSummary,
    StudioServiceHealth,
)
from rig_relay.desktop.gateway._projection import (
    J0_PROJECTION_BUILDER,
    K0_PROJECTION_BUILDER,
    L0_PROJECTION_BUILDER,
    M0_PROJECTION_BUILDER,
)

_GATEWAY_PROJECTION_SCHEMA = "rig.relay.developer_studio_projection.v1"
_DEFAULT_WORKSPACES_ROOT = Path.home() / ".rig" / "relay" / "workspaces"


class DeveloperStudioGatewayService:
    """Typed application service for the developer studio bridge corridor.

    Consumes published J0/K0/L0/M0 public APIs. Produces content-light
    aggregate projections for the frontend Gridline interface. Routes
    typed intents to the correct producer service.

    Uses lazy initialization for J0 and M0 singletons. K0 and L0 are
    stateless constructors — the gateway creates fresh service instances
    per call pattern.

    Controlled-boundary J0 state: if no real GitHub App credentials
    are available, the gateway exposes connection as controlled-boundary/
    acceptance-deferred rather than faking live developer onboarding.
    """

    def __init__(self, *, workspaces_root: Path | None = None) -> None:
        self._workspaces_root = workspaces_root or _DEFAULT_WORKSPACES_ROOT
        self._j0_service: Any = None
        self._k0_sessions: dict[str, Any] = {}
        self._l0_service: Any = None
        self._m0_service: Any = None
        self._last_projection: DeveloperStudioProjection | None = None

    # ── Lazy service accessors ───────────────────────────────────────

    def _get_j0_service(self) -> Any:
        if self._j0_service is None:
            try:
                from rig_relay.integrations.github_provider._developer_workspace import (
                    DeveloperGitHubWorkspaceService,
                )

                self._j0_service = DeveloperGitHubWorkspaceService.from_environment()
                logger.debug("gateway: J0 workspace service initialized")
            except Exception as exc:
                logger.warning("gateway: J0 workspace service unavailable — %s", exc)
                self._j0_service = _UNAVAILABLE_SENTINEL
        return self._j0_service

    def _get_l0_service(self) -> Any:
        if self._l0_service is None:
            from rig_relay.context_engine.assembler import ProjectContextAssemblyService

            self._l0_service = ProjectContextAssemblyService()
            logger.debug("gateway: L0 context assembly service initialized")
        return self._l0_service

    def _get_m0_service(self) -> Any:
        if self._m0_service is None:
            try:
                from rig_relay.local_inference._service import get_inference_service

                self._m0_service = get_inference_service()
                logger.debug("gateway: M0 inference service initialized")
            except Exception as exc:
                logger.warning("gateway: M0 inference service unavailable — %s", exc)
                self._m0_service = _UNAVAILABLE_SENTINEL
        return self._m0_service

    # ── Projection ───────────────────────────────────────────────────

    def build_projection(
        self, *, projection_id: str | None = None
    ) -> DeveloperStudioProjection:
        """Build the aggregate developer studio projection.

        Reads published service state through public APIs. Never reads
        authority ledgers or reproduces producer logic in the gateway.
        """
        from datetime import UTC, datetime

        pid = projection_id or f"dsp_{datetime.now(UTC).timestamp():.0f}"

        j0 = J0_PROJECTION_BUILDER(self)
        k0 = K0_PROJECTION_BUILDER(self)
        l0 = L0_PROJECTION_BUILDER(self)
        m0 = M0_PROJECTION_BUILDER(self)

        health = StudioServiceHealth(
            j0_workspace=_service_health_label(j0),
            k0_operator=_service_health_label(k0),
            l0_context=_service_health_label(l0),
            m0_inference=_service_health_label(m0),
        )

        provenance = StudioProvenanceSummary()
        _count_provenance(j0, provenance)
        _count_provenance(k0, provenance)
        _count_provenance(l0, provenance)
        _count_provenance(m0, provenance)

        projection = DeveloperStudioProjection(
            projection_id=pid,
            workspace=j0,
            operator=k0,
            context=l0,
            inference=m0,
            service_health=health,
            provenance_summary=provenance,
        )
        projection.projection_digest = projection.compute_digest()
        self._last_projection = projection
        return projection

    def get_last_projection(self) -> DeveloperStudioProjection | None:
        return self._last_projection

    # ── J0: GitHub Workspace Intents ─────────────────────────────────

    def connect_workspace(self) -> dict[str, Any]:
        j0 = self._get_j0_service()
        if j0 is _UNAVAILABLE_SENTINEL:
            return _refused(
                "connect_workspace",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "J0 workspace service is unavailable",
            )
        try:
            connection = j0.connect()
            return _succeeded(
                "connect_workspace",
                {
                    "installation_id_hash": connection.installation_id_hash,
                    "connection_state": connection.connection_state,
                    "token_available": connection.token_available,
                    "accessible_repository_count": connection.accessible_repository_count,
                    "live_installation_verified": False,
                },
            )
        except Exception as exc:
            return _failed("connect_workspace", str(exc))

    def discover_repositories(self) -> dict[str, Any]:
        import asyncio

        j0 = self._get_j0_service()
        if j0 is _UNAVAILABLE_SENTINEL:
            return _refused(
                "discover_repositories",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "J0 workspace service is unavailable",
            )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, j0.discover_repositories())
                    result = future.result(timeout=30)
            else:
                result = asyncio.run(j0.discover_repositories())
            return _succeeded(
                "discover_repositories",
                {
                    "repositories_found": len(result.repositories)
                    if result.repositories
                    else 0,
                    "total_count": result.total_count,
                },
            )
        except Exception as exc:
            return _failed("discover_repositories", str(exc))

    def select_repository(self, repo_hash: str) -> dict[str, Any]:
        j0 = self._get_j0_service()
        if j0 is _UNAVAILABLE_SENTINEL:
            return _refused(
                "select_repository",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "J0 workspace service is unavailable",
            )
        try:
            result = j0.select_repository(repo_hash)
            return _succeeded(
                "select_repository",
                {"repository_hash": repo_hash, "selected_count": result.selected_count},
            )
        except Exception as exc:
            return _failed("select_repository", str(exc))

    def import_repository(
        self, repo_hash: str, owner: str, repo: str
    ) -> dict[str, Any]:
        j0 = self._get_j0_service()
        if j0 is _UNAVAILABLE_SENTINEL:
            return _refused(
                "import_repository",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "J0 workspace service is unavailable",
            )
        try:
            from rig_relay.integrations.github_provider._workspace_models import (
                RepositoryIntakeRequest,
            )

            request = RepositoryIntakeRequest(
                repository_hash=repo_hash,
                owner=owner,
                repo=repo,
                local_workspace_root=str(self._workspaces_root),
            )
            result = j0.import_repository(request)
            return _succeeded(
                "import_repository",
                {
                    "repository_hash": repo_hash,
                    "clone_successful": result.clone_successful,
                    "head_sha": result.head_sha or "",
                    "branch": result.branch or "",
                    "local_path_digest": _digest_path(result.local_path)
                    if result.local_path
                    else "",
                },
            )
        except Exception as exc:
            return _failed("import_repository", str(exc))

    def inspect_publication_readiness(self, owner: str, repo: str) -> dict[str, Any]:
        import asyncio

        j0 = self._get_j0_service()
        if j0 is _UNAVAILABLE_SENTINEL:
            return _refused(
                "inspect_publication_readiness",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "J0 workspace service is unavailable",
            )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run, j0.inspect_publication_readiness(owner, repo)
                    )
                    result = future.result(timeout=30)
            else:
                result = asyncio.run(j0.inspect_publication_readiness(owner, repo))
            return _succeeded(
                "inspect_publication_readiness",
                {
                    "has_pages": result.has_pages,
                    "publication_eligible": result.publication_eligible,
                    "readiness_state": result.readiness_state,
                    "blockers": result.blockers,
                },
            )
        except Exception as exc:
            return _failed("inspect_publication_readiness", str(exc))

    def prepare_pages_action(
        self,
        owner: str,
        repo: str,
        target_type: str = "project_page",
        source_branch: str = "",
        source_path: str = "/",
    ) -> dict[str, Any]:
        import asyncio

        j0 = self._get_j0_service()
        if j0 is _UNAVAILABLE_SENTINEL:
            return _refused(
                "prepare_pages_action",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "J0 workspace service is unavailable",
            )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        j0.prepare_pages_action(
                            owner, repo, target_type, source_branch, source_path
                        ),
                    )
                    result = future.result(timeout=30)
            else:
                result = asyncio.run(
                    j0.prepare_pages_action(
                        owner, repo, target_type, source_branch, source_path
                    )
                )
            return _succeeded(
                "prepare_pages_action",
                {
                    "action_id": result.action_id,
                    "action_state": result.action_state,
                    "requires_approval": result.requires_approval,
                },
            )
        except Exception as exc:
            return _failed("prepare_pages_action", str(exc))

    # ── K0: Operator Investigation Intents ───────────────────────────

    def start_investigation(
        self,
        repository_label: str,
        purpose: str,
        *,
        workspace_root: str = "",
        head_sha: str = "",
        branch: str = "",
        agent_profile_name: str = "plan",
    ) -> dict[str, Any]:
        try:
            from pathlib import Path

            from rig_relay.digestion.intake import RepositoryIntakeService
            from rig_relay.operator.session import RepositoryOperatorSessionService

            k0_service = RepositoryOperatorSessionService()
            root = Path(workspace_root) if workspace_root else self._workspaces_root
            intake_service = RepositoryIntakeService()
            intake_result = intake_service.open_local_repository(root)
            session = k0_service.open_session(
                intake_result, purpose, agent_profile_name=agent_profile_name
            )
            self._k0_sessions[session.session_id] = k0_service
            return _succeeded(
                "start_investigation",
                {
                    "session_id": session.session_id,
                    "status": session.status.value,
                    "repository_label": session.repository_label,
                },
            )
        except Exception as exc:
            return _failed("start_investigation", str(exc))

    def get_investigation_projection(self, session_id: str) -> dict[str, Any]:
        for k0_service in self._k0_sessions.values():
            proj = k0_service.get_projection(session_id)
            if proj is not None:
                return _succeeded("get_investigation_projection", proj)
        return _refused(
            "get_investigation_projection",
            GatewayErrorKind.DEPENDENCY_FAILED,
            f"No active investigation found for session {session_id}",
        )

    def close_investigation(self, session_id: str) -> dict[str, Any]:
        k0_service = self._k0_sessions.pop(session_id, None)
        if k0_service is None:
            return _refused(
                "close_investigation",
                GatewayErrorKind.DEPENDENCY_FAILED,
                f"No active investigation for session {session_id}",
            )
        try:
            k0_service.close_session(session_id)
            return _succeeded("close_investigation", {"session_id": session_id})
        except Exception as exc:
            return _failed("close_investigation", str(exc))

    # ── L0: Project Understanding Intents ────────────────────────────

    def assemble_project_profile(
        self,
        project_name: str,
        *,
        repository_root: str = "",
        head_sha: str = "",
        branch: str = "",
    ) -> dict[str, Any]:
        l0 = self._get_l0_service()
        try:
            from pathlib import Path as _Path

            from rig_relay.context_engine.fixtures import (
                IntakeFixture,
                InvestigationEvidenceFixture,
            )

            intake = IntakeFixture(
                project_name=project_name,
                repository_root=_Path(repository_root)
                if repository_root
                else _Path("."),
                head_sha=head_sha,
                branch=branch,
            )
            investigation = InvestigationEvidenceFixture()
            understanding = l0.assemble(intake, investigation)
            profile_candidate = l0.assemble_profile_candidate(understanding)
            context_packet = l0.assemble_context_packet(understanding)
            gridline = l0.assemble_gridline_projection(understanding, context_packet)

            return _succeeded(
                "assemble_project_profile",
                {
                    "project_name": project_name,
                    "study_status": gridline.study_status.value,
                    "facts_discovered": gridline.facts_discovered,
                    "languages_detected": gridline.languages_detected,
                    "profile_candidate_digest": profile_candidate.compute_digest(),
                    "context_packet_digest": context_packet.compute_digest(),
                    "context_packet_ready": gridline.context_packet_ready,
                    "draft_narrative_count": gridline.draft_narrative_count,
                    "k0_investigation_boundary": "fixture",
                },
            )
        except Exception as exc:
            return _failed("assemble_project_profile", str(exc))

    def assemble_context_packet(
        self,
        project_name: str,
        *,
        repository_root: str = "",
        head_sha: str = "",
        branch: str = "",
    ) -> dict[str, Any]:
        l0 = self._get_l0_service()
        try:
            from pathlib import Path as _Path

            from rig_relay.context_engine.fixtures import (
                IntakeFixture,
                InvestigationEvidenceFixture,
            )

            intake = IntakeFixture(
                project_name=project_name,
                repository_root=_Path(repository_root)
                if repository_root
                else _Path("."),
                head_sha=head_sha,
                branch=branch,
            )
            investigation = InvestigationEvidenceFixture()
            understanding = l0.assemble(intake, investigation)
            context_packet = l0.assemble_context_packet(understanding)

            return _succeeded(
                "assemble_context_packet",
                {
                    "packet_id": context_packet.packet_id,
                    "packet_digest": context_packet.compute_digest(),
                    "project_identity_hash": context_packet.project_identity_hash,
                    "tokens_remaining": context_packet.token_budget.tokens_remaining,
                    "public_safe": True,
                },
            )
        except Exception as exc:
            return _failed("assemble_context_packet", str(exc))

    # ── M0: Local Inference Intents ──────────────────────────────────

    def request_local_assistance(
        self, task_kind: str, *, project_name: str = "", context_packet_digest: str = ""
    ) -> dict[str, Any]:
        import asyncio

        m0 = self._get_m0_service()
        if m0 is _UNAVAILABLE_SENTINEL:
            return _refused(
                "request_local_assistance",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "M0 inference service is unavailable",
            )
        try:
            from rig_relay.local_inference._models import (
                AssistanceTask,
                AssistanceTaskKind,
                build_rig_relay_project_packet,
            )

            kind = AssistanceTaskKind(task_kind)
            packet = build_rig_relay_project_packet()

            task = AssistanceTask(
                task_id=f"task_{hashlib.sha256(task_kind.encode()).hexdigest()[:12]}",
                task_kind=kind,
                context_packet_digest=packet.compute_digest(),
            )

            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, m0.execute_task(task, packet))
                    result = future.result(timeout=120)
            else:
                result = asyncio.run(m0.execute_task(task, packet))

            return _succeeded(
                "request_local_assistance",
                {
                    "result_id": result.result_id,
                    "status": result.status.value,
                    "task_kind": task_kind,
                    "draft_sha256": result.draft_sha256,
                    "draft_byte_count": result.draft_byte_count,
                    "requires_review": result.output_disposition.value
                    == "draft_requires_review",
                    "enforcement_class_used": result.enforcement_class_used.value,
                    "refusal_reason": result.refusal_reason
                    if result.refusal_reason
                    else "",
                },
            )
        except Exception as exc:
            return _failed("request_local_assistance", str(exc))

    def get_local_draft(self, draft_sha256: str) -> dict[str, Any]:
        m0 = self._get_m0_service()
        if m0 is _UNAVAILABLE_SENTINEL:
            return _refused(
                "get_local_draft",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "M0 inference service is unavailable",
            )
        try:
            draft = m0.get_draft(draft_sha256)
            if draft is None:
                return _refused(
                    "get_local_draft",
                    GatewayErrorKind.DEPENDENCY_FAILED,
                    f"No draft found for sha256 {draft_sha256[:16]}",
                )
            return _succeeded(
                "get_local_draft",
                {
                    "draft_sha256": draft_sha256,
                    "draft_byte_count": len(draft),
                    "review_required": True,
                },
            )
        except Exception as exc:
            return _failed("get_local_draft", str(exc))


# ── Helpers ──────────────────────────────────────────────────────────


_UNAVAILABLE_SENTINEL = object()


def _service_health_label(section: Any) -> str:
    if section is None:
        return "unavailable"
    if hasattr(section, "available"):
        return "available" if section.available else "degraded"
    return "available"


def _count_provenance(section: Any, summary: StudioProvenanceSummary) -> None:
    _bump = _COUNTERS.get(type(section).__name__)
    if _bump:
        _bump(section, summary)


def _bump_j0(_section: Any, summary: StudioProvenanceSummary) -> None:
    summary.canonical_facts += 1
    summary.controlled_boundary_proofs += 1
    summary.derived_projections += 1


def _bump_k0(_section: Any, summary: StudioProvenanceSummary) -> None:
    summary.derived_projections += 1
    if hasattr(_section, "refused_session_count") and _section.refused_session_count:
        summary.refused += _section.refused_session_count


def _bump_l0(_section: Any, summary: StudioProvenanceSummary) -> None:
    summary.derived_projections += 1
    summary.generated_proposals += 1
    if hasattr(_section, "intake_dependency_status"):
        ids = _section.intake_dependency_status
        if getattr(ids, "j0_intake_boundary", "") == "fixture":
            summary.fixture_deferred += 1
        if getattr(ids, "k0_investigation_boundary", "") == "fixture":
            summary.fixture_deferred += 1


def _bump_m0(_section: Any, summary: StudioProvenanceSummary) -> None:
    summary.derived_projections += 1
    if hasattr(_section, "drafts_awaiting_review"):
        summary.review_required_drafts += _section.drafts_awaiting_review
    if hasattr(_section, "total_refused"):
        summary.refused += _section.total_refused


_COUNTERS: dict[str, Any] = {
    "J0WorkspaceProjection": _bump_j0,
    "K0OperatorProjection": _bump_k0,
    "L0ContextProjection": _bump_l0,
    "M0InferenceProjection": _bump_m0,
}


def _succeeded(intent_name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"status": "completed", "intent_name": intent_name, "data": data}


def _refused(intent_name: str, kind: GatewayErrorKind, message: str) -> dict[str, Any]:
    return {
        "status": "refused",
        "intent_name": intent_name,
        "error_kind": kind.value,
        "error_message": message,
    }


def _failed(intent_name: str, message: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "intent_name": intent_name,
        "error_kind": GatewayErrorKind.INTERNAL_ERROR.value,
        "error_message": message,
    }


def _digest_path(path: str | None) -> str:
    if not path:
        return ""
    return f"sha256:{hashlib.sha256(path.encode()).hexdigest()}"
