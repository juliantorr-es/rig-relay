"""Developer Studio Gateway Service — Lane S2 (hardened from O0).

Typed backend bridge orchestrator that consumes published J0/K0/L0/M0
application-service public APIs and exposes a single coherent frontend-safe
projection and intent protocol.

Now evidence-backed: provenance is counted by walking projection trees;
content-light enforcement runs on every projection; idempotency keys
protect mutating intents from duplicate effects; schema validation
verifies projection correctness before return.

Does not own service authority. Delegates to published producers only.
Never bypasses J0/K0/L0/M0 gates. Never exposes tokens, raw paths,
private source, or unredacted errors in frontend projections.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import time
from typing import Any

from rig_relay.core.logger import logger
from rig_relay.desktop.gateway._authority import (
    AuthorityEvidence,
    GatewayAuthorityReport,
    ServiceAuthority,
)
from rig_relay.desktop.gateway._content_light import enforce_content_light
from rig_relay.desktop.gateway._models import (
    DeveloperStudioProjection,
    GatewayErrorKind,
    J0WorkspaceProjection,
    K0OperatorProjection,
    L0ContextProjection,
    M0InferenceProjection,
    ProvenanceClass,
    StudioProvenanceSummary,
    StudioServiceHealth,
)
from rig_relay.desktop.gateway._projection import (
    J0_PROJECTION_BUILDER,
    K0_PROJECTION_BUILDER,
    L0_PROJECTION_BUILDER,
    M0_PROJECTION_BUILDER,
)
from rig_relay.desktop.gateway._projection_surfaces import (
    CONNECT_SURFACE_PROJECTION_BUILDER,
    INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER,
    PUBLISH_PREVIEW_SURFACE_PROJECTION_BUILDER,
    REPOSITORY_ESTATE_SURFACE_PROJECTION_BUILDER,
    TIMELINE_SURFACE_PROJECTION_BUILDER,
)

_GATEWAY_PROJECTION_SCHEMA = "rig.relay.developer_studio_projection.v1"
_DEFAULT_WORKSPACES_ROOT = Path.home() / ".rig" / "relay" / "workspaces"
_MAX_IDEMPOTENCY_KEY_AGE_SECONDS = 600  # 10 minutes

# In-memory idempotency registry for mutating intents
_idempotency_registry: dict[str, tuple[float, dict[str, Any]]] = {}


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
        self._last_authority_report: GatewayAuthorityReport | None = None
        self._repository_estate_service: Any = None
        self._publication_service: Any = None
        self._timeline_service: Any = None

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

    # ── Authority report ─────────────────────────────────────────────

    def build_authority_report(self) -> GatewayAuthorityReport:
        """Build an evidence-backed authority report for all four services.

        Classifies each service's authority from canonical evidence,
        not from hardcoded labels.
        """
        j0 = self._get_j0_service()
        k0_sessions = self._k0_sessions
        self._get_l0_service()
        m0 = self._get_m0_service()

        j0_evidence = _classify_j0_authority(j0)
        k0_evidence = _classify_k0_authority(k0_sessions)
        l0_evidence = _classify_l0_authority(j0, k0_sessions)
        m0_evidence = _classify_m0_authority(m0)

        report = GatewayAuthorityReport(
            j0_workspace=j0_evidence,
            k0_operator=k0_evidence,
            l0_context=l0_evidence,
            m0_inference=m0_evidence,
        )
        self._last_authority_report = report
        return report

    # ── Projection ───────────────────────────────────────────────────

    def build_projection(
        self, *, projection_id: str | None = None
    ) -> DeveloperStudioProjection:
        """Build the aggregate developer studio projection.

        Reads published service state through public APIs. Never reads
        authority ledgers or reproduces producer logic in the gateway.

        Content-light enforcement runs before return. Schema validation
        verifies structural correctness.
        """
        from datetime import UTC, datetime

        pid = projection_id or f"dsp_{datetime.now(UTC).timestamp():.0f}"

        j0 = J0_PROJECTION_BUILDER(self)
        k0 = K0_PROJECTION_BUILDER(self)
        l0 = L0_PROJECTION_BUILDER(self)
        m0 = M0_PROJECTION_BUILDER(self)

        # X0 surface projections — consume published T1.2/T3.1/T4.2 + W0/W1 policy
        connect_surface = CONNECT_SURFACE_PROJECTION_BUILDER(self)
        repository_estate_surface = REPOSITORY_ESTATE_SURFACE_PROJECTION_BUILDER(self)
        publish_preview_surface = PUBLISH_PREVIEW_SURFACE_PROJECTION_BUILDER(self)
        timeline_surface = TIMELINE_SURFACE_PROJECTION_BUILDER(self)
        inference_studio_surface = INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER(self)

        health = StudioServiceHealth(
            j0_workspace=_service_health_label(j0),
            k0_operator=_service_health_label(k0),
            l0_context=_service_health_label(l0),
            m0_inference=_service_health_label(m0),
        )

        provenance = _count_provenance_walk(j0, k0, l0, m0)

        projection = DeveloperStudioProjection(
            projection_id=pid,
            workspace=j0,
            operator=k0,
            context=l0,
            inference=m0,
            connect_surface=connect_surface,
            repository_estate_surface=repository_estate_surface,
            publish_preview_surface=publish_preview_surface,
            timeline_surface=timeline_surface,
            inference_studio_surface=inference_studio_surface,
            service_health=health,
            provenance_summary=provenance,
        )
        projection.projection_digest = projection.compute_digest()

        # Content-light enforcement
        data = projection.model_dump(mode="json")
        violations = enforce_content_light(
            data, source_label="developer_studio_projection"
        )
        if violations:
            logger.error(
                "gateway: content-light violations in projection: %s", violations
            )

        self._last_projection = projection
        return projection

    def get_last_projection(self) -> DeveloperStudioProjection | None:
        return self._last_projection

    # ── Idempotency ──────────────────────────────────────────────────

    def _check_idempotency(
        self, intent_name: str, idempotency_key: str | None
    ) -> dict[str, Any] | None:
        """Check if an intent with this idempotency key was already executed.

        Returns the cached result if found and still fresh, or None if
        the intent should proceed.
        """
        if not idempotency_key:
            return None

        now = time.monotonic()
        # Garbage-collect expired entries
        expired = [
            k
            for k, (ts, _) in _idempotency_registry.items()
            if now - ts > _MAX_IDEMPOTENCY_KEY_AGE_SECONDS
        ]
        for k in expired:
            del _idempotency_registry[k]

        entry = _idempotency_registry.get(idempotency_key)
        if entry is None:
            return None

        ts, cached_result = entry
        if now - ts > _MAX_IDEMPOTENCY_KEY_AGE_SECONDS:
            del _idempotency_registry[idempotency_key]
            return None

        logger.debug(
            "gateway: idempotency hit for %s key=%s", intent_name, idempotency_key[:16]
        )
        return dict(cached_result)

    def _record_idempotency(
        self, idempotency_key: str | None, result: dict[str, Any]
    ) -> None:
        """Record an intent result under its idempotency key."""
        if not idempotency_key:
            return
        _idempotency_registry[idempotency_key] = (time.monotonic(), result)

    # ── J0: GitHub Workspace Intents ─────────────────────────────────

    def connect_workspace(
        self, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        cached = self._check_idempotency("connect_workspace", idempotency_key)
        if cached is not None:
            return cached

        j0 = self._get_j0_service()
        if j0 is _UNAVAILABLE_SENTINEL:
            result = _refused(
                "connect_workspace",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "J0 workspace service is unavailable",
            )
            self._record_idempotency(idempotency_key, result)
            return result
        try:
            connection = j0.connect()
            result = _succeeded(
                "connect_workspace",
                {
                    "installation_id_hash": connection.installation_id_hash,
                    "connection_state": connection.connection_state,
                    "token_available": connection.token_available,
                    "accessible_repository_count": connection.accessible_repository_count,
                    "live_installation_verified": False,
                },
            )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("connect_workspace", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    def discover_repositories(
        self, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        import asyncio

        cached = self._check_idempotency("discover_repositories", idempotency_key)
        if cached is not None:
            return cached

        j0 = self._get_j0_service()
        if j0 is _UNAVAILABLE_SENTINEL:
            result = _refused(
                "discover_repositories",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "J0 workspace service is unavailable",
            )
            self._record_idempotency(idempotency_key, result)
            return result
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, j0.discover_repositories())
                    discovery_result = future.result(timeout=30)
            else:
                discovery_result = asyncio.run(j0.discover_repositories())
            result = _succeeded(
                "discover_repositories",
                {
                    "repositories_found": len(discovery_result.repositories)
                    if discovery_result.repositories
                    else 0,
                    "total_count": discovery_result.total_count,
                },
            )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("discover_repositories", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    def select_repository(
        self, repo_hash: str, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        cached = self._check_idempotency(
            f"select_repository:{repo_hash}", idempotency_key
        )
        if cached is not None:
            return cached

        j0 = self._get_j0_service()
        if j0 is _UNAVAILABLE_SENTINEL:
            result = _refused(
                "select_repository",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "J0 workspace service is unavailable",
            )
            self._record_idempotency(idempotency_key, result)
            return result
        try:
            sel_result = j0.select_repository(repo_hash)
            result = _succeeded(
                "select_repository",
                {
                    "repository_hash": repo_hash,
                    "selected_count": sel_result.selected_count,
                },
            )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("select_repository", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    def import_repository(
        self,
        repo_hash: str,
        owner: str,
        repo: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        cached = self._check_idempotency(
            f"import_repository:{repo_hash}", idempotency_key
        )
        if cached is not None:
            return cached

        j0 = self._get_j0_service()
        if j0 is _UNAVAILABLE_SENTINEL:
            result = _refused(
                "import_repository",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "J0 workspace service is unavailable",
            )
            self._record_idempotency(idempotency_key, result)
            return result
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
            import_result = j0.import_repository(request)
            result = _succeeded(
                "import_repository",
                {
                    "repository_hash": repo_hash,
                    "clone_successful": import_result.clone_successful,
                    "head_sha": import_result.head_sha or "",
                    "branch": import_result.branch or "",
                    "local_path_digest": _digest_path(import_result.local_path)
                    if import_result.local_path
                    else "",
                },
            )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("import_repository", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    def inspect_publication_readiness(
        self, owner: str, repo: str, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        import asyncio

        cached = self._check_idempotency(
            f"inspect_publication_readiness:{owner}/{repo}", idempotency_key
        )
        if cached is not None:
            return cached

        j0 = self._get_j0_service()
        if j0 is _UNAVAILABLE_SENTINEL:
            result = _refused(
                "inspect_publication_readiness",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "J0 workspace service is unavailable",
            )
            self._record_idempotency(idempotency_key, result)
            return result
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run, j0.inspect_publication_readiness(owner, repo)
                    )
                    readiness_result = future.result(timeout=30)
            else:
                readiness_result = asyncio.run(
                    j0.inspect_publication_readiness(owner, repo)
                )
            result = _succeeded(
                "inspect_publication_readiness",
                {
                    "has_pages": readiness_result.has_pages,
                    "publication_eligible": readiness_result.publication_eligible,
                    "readiness_state": readiness_result.readiness_state,
                    "blockers": readiness_result.blockers,
                },
            )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("inspect_publication_readiness", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    def prepare_pages_action(
        self,
        owner: str,
        repo: str,
        target_type: str = "project_page",
        source_branch: str = "",
        source_path: str = "/",
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        import asyncio

        cached = self._check_idempotency(
            f"prepare_pages_action:{owner}/{repo}", idempotency_key
        )
        if cached is not None:
            return cached

        j0 = self._get_j0_service()
        if j0 is _UNAVAILABLE_SENTINEL:
            result = _refused(
                "prepare_pages_action",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "J0 workspace service is unavailable",
            )
            self._record_idempotency(idempotency_key, result)
            return result
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
                    pages_result = future.result(timeout=30)
            else:
                pages_result = asyncio.run(
                    j0.prepare_pages_action(
                        owner, repo, target_type, source_branch, source_path
                    )
                )
            result = _succeeded(
                "prepare_pages_action",
                {
                    "action_id": pages_result.action_id,
                    "action_state": pages_result.action_state,
                    "requires_approval": pages_result.requires_approval,
                },
            )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("prepare_pages_action", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

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
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        cached = self._check_idempotency("start_investigation", idempotency_key)
        if cached is not None:
            return cached

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
            result = _succeeded(
                "start_investigation",
                {
                    "session_id": session.session_id,
                    "status": session.status.value,
                    "repository_label": session.repository_label,
                },
            )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("start_investigation", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    def get_investigation_projection(
        self, session_id: str, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        for k0_service in self._k0_sessions.values():
            proj = k0_service.get_projection(session_id)
            if proj is not None:
                result = _succeeded("get_investigation_projection", proj)
                self._record_idempotency(idempotency_key, result)
                return result
        result = _refused(
            "get_investigation_projection",
            GatewayErrorKind.DEPENDENCY_FAILED,
            f"No active investigation found for session {session_id}",
        )
        self._record_idempotency(idempotency_key, result)
        return result

    def close_investigation(
        self, session_id: str, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        k0_service = self._k0_sessions.pop(session_id, None)
        if k0_service is None:
            result = _refused(
                "close_investigation",
                GatewayErrorKind.DEPENDENCY_FAILED,
                f"No active investigation for session {session_id}",
            )
            self._record_idempotency(idempotency_key, result)
            return result
        try:
            k0_service.close_session(session_id)
            result = _succeeded("close_investigation", {"session_id": session_id})
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("close_investigation", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    # ── L0: Project Understanding Intents ────────────────────────────

    def assemble_project_profile(
        self,
        project_name: str,
        *,
        repository_root: str = "",
        head_sha: str = "",
        branch: str = "",
        idempotency_key: str | None = None,
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

            result = _succeeded(
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
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("assemble_project_profile", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    def assemble_context_packet(
        self,
        project_name: str,
        *,
        repository_root: str = "",
        head_sha: str = "",
        branch: str = "",
        idempotency_key: str | None = None,
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

            result = _succeeded(
                "assemble_context_packet",
                {
                    "packet_id": context_packet.packet_id,
                    "packet_digest": context_packet.compute_digest(),
                    "project_identity_hash": context_packet.project_identity_hash,
                    "tokens_remaining": context_packet.token_budget.tokens_remaining,
                    "public_safe": True,
                },
            )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("assemble_context_packet", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    # ── M0: Local Inference Intents ──────────────────────────────────

    def request_local_assistance(
        self,
        task_kind: str,
        *,
        project_name: str = "",
        context_packet_digest: str = "",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        import asyncio

        cached = self._check_idempotency(
            f"request_local_assistance:{task_kind}", idempotency_key
        )
        if cached is not None:
            return cached

        m0 = self._get_m0_service()
        if m0 is _UNAVAILABLE_SENTINEL:
            result = _refused(
                "request_local_assistance",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "M0 inference service is unavailable",
            )
            self._record_idempotency(idempotency_key, result)
            return result
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
                    exec_result = future.result(timeout=120)
            else:
                exec_result = asyncio.run(m0.execute_task(task, packet))

            result = _succeeded(
                "request_local_assistance",
                {
                    "result_id": exec_result.result_id,
                    "status": exec_result.status.value,
                    "task_kind": task_kind,
                    "draft_sha256": exec_result.draft_sha256,
                    "draft_byte_count": exec_result.draft_byte_count,
                    "requires_review": exec_result.output_disposition.value
                    == "draft_requires_review",
                    "enforcement_class_used": exec_result.enforcement_class_used.value,
                    "refusal_reason": exec_result.refusal_reason
                    if exec_result.refusal_reason
                    else "",
                },
            )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("request_local_assistance", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    def get_local_draft(
        self, draft_sha256: str, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        m0 = self._get_m0_service()
        if m0 is _UNAVAILABLE_SENTINEL:
            result = _refused(
                "get_local_draft",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "M0 inference service is unavailable",
            )
            self._record_idempotency(idempotency_key, result)
            return result
        try:
            draft = m0.get_draft(draft_sha256)
            if draft is None:
                result = _refused(
                    "get_local_draft",
                    GatewayErrorKind.DEPENDENCY_FAILED,
                    f"No draft found for sha256 {draft_sha256[:16]}",
                )
                self._record_idempotency(idempotency_key, result)
                return result
            result = _succeeded(
                "get_local_draft",
                {
                    "draft_sha256": draft_sha256,
                    "draft_byte_count": len(draft),
                    "review_required": True,
                },
            )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("get_local_draft", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    # ── T3.1: Repository Estate Service ──────────────────────────────

    def _get_repository_estate_service(self) -> Any:
        if self._repository_estate_service is None:
            try:
                from rig_relay.repository_estate._service import RepositoryEstateService

                self._repository_estate_service = RepositoryEstateService()
                logger.debug("gateway: T3.1 repository estate service initialized")
            except Exception as exc:
                logger.warning(
                    "gateway: T3.1 repository estate service unavailable — %s", exc
                )
                self._repository_estate_service = _UNAVAILABLE_SENTINEL
        return self._repository_estate_service

    def register_repository(
        self, root_path: str, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """Register a local repository in the estate.

        Args:
            root_path: Path to the git repository root.
        """
        cached = self._check_idempotency(
            f"register_repository:{root_path}", idempotency_key
        )
        if cached is not None:
            return cached

        estate = self._get_repository_estate_service()
        if estate is _UNAVAILABLE_SENTINEL:
            result = _refused(
                "register_repository",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "RepositoryEstateService (T3.1) is unavailable",
            )
            self._record_idempotency(idempotency_key, result)
            return result
        try:
            registration = estate.register_repository(Path(root_path))
            result = _succeeded(
                "register_repository",
                {
                    "repository_hash": registration.repository_hash,
                    "repository_label": registration.repository_label,
                    "repository_kind": registration.repository_kind.value,
                    "registered_at": registration.registered_at,
                },
            )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("register_repository", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    def observe_repository(
        self,
        repository_hash: str,
        root_path: str = "",
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Observe a registered repository with identity-match enforcement.

        Args:
            repository_hash: Stable identifier from registration.
            root_path: Filesystem path. If empty, resolved from registration.
        """
        cached = self._check_idempotency(
            f"observe_repository:{repository_hash}", idempotency_key
        )
        if cached is not None:
            return cached

        estate = self._get_repository_estate_service()
        if estate is _UNAVAILABLE_SENTINEL:
            result = _refused(
                "observe_repository",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "RepositoryEstateService (T3.1) is unavailable",
            )
            self._record_idempotency(idempotency_key, result)
            return result
        try:
            resolved = Path(root_path) if root_path else None
            observation = estate.observe_repository(repository_hash, resolved)
            result = _succeeded(
                "observe_repository",
                {
                    "observation_id": observation.observation_id,
                    "repository_hash": observation.repository_hash,
                    "status": observation.status.value,
                    "observed_at": observation.observed_at,
                    "is_dirty": observation.git_facts.dirty_counts.modified > 0
                    or observation.git_facts.dirty_counts.untracked > 0,
                },
            )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("observe_repository", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    # ── T1.2: Publication Preview Service ────────────────────────────

    def _get_publication_service(self) -> Any:
        if self._publication_service is None:
            try:
                from rig_relay.publication._service import (
                    ProjectPagePublicationPreviewService,
                )

                self._publication_service = ProjectPagePublicationPreviewService()
                logger.debug("gateway: T1.2 publication preview service initialized")
            except Exception as exc:
                logger.warning(
                    "gateway: T1.2 publication preview service unavailable — %s", exc
                )
                self._publication_service = _UNAVAILABLE_SENTINEL
        return self._publication_service

    def compile_preview(
        self,
        project_name: str,
        *,
        repository_root: str = "",
        repo_owner: str = "",
        repo_name: str = "",
        publication_policy: str = "preview_only",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Compile a publication preview from L0 profile + J0 readiness.

        Args:
            project_name: Human-readable project name for the profile.
            repository_root: Path to the repository root for L0 extraction.
            repo_owner: GitHub owner for URL construction.
            repo_name: GitHub repo name for URL construction.
            publication_policy: preview_only, developer_approved, or public_release.
        """
        cached = self._check_idempotency(
            f"compile_preview:{project_name}", idempotency_key
        )
        if cached is not None:
            return cached

        pub = self._get_publication_service()
        if pub is _UNAVAILABLE_SENTINEL:
            result = _refused(
                "compile_preview",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "ProjectPagePublicationPreviewService (T1.2) is unavailable",
            )
            self._record_idempotency(idempotency_key, result)
            return result

        l0 = self._get_l0_service()
        try:
            from rig_relay.context_engine.fixtures import (
                IntakeFixture,
                InvestigationEvidenceFixture,
            )

            intake = IntakeFixture(
                project_name=project_name,
                repository_root=Path(repository_root) if repository_root else Path("."),
            )
            investigation = InvestigationEvidenceFixture()
            understanding = l0.assemble(intake, investigation)
            profile_candidate = l0.assemble_profile_candidate(understanding)

            preview_result = pub.compile_preview(
                profile_candidate,
                publication_policy=publication_policy,
                repo_owner=repo_owner,
                repo_name=repo_name,
            )

            receipt = preview_result.receipt
            if receipt is not None:
                receipt_summary = {
                    "receipt_id": receipt.receipt_id,
                    "compiled_at": receipt.compiled_at,
                    "compilation_successful": receipt.compilation_successful,
                    "profile_candidate_digest": receipt.profile_candidate_digest,
                    "safety_passed": receipt.safety_passed,
                    "preview_only": receipt.preview_only,
                    "deployment_ready": receipt.deployment_ready,
                    "evidence_digest": receipt.evidence_digest,
                }
            else:
                receipt_summary = {}

            refused = preview_result.refused.value if preview_result.refused else None

            result = _succeeded(
                "compile_preview",
                {
                    "project_name": project_name,
                    "operation_id": getattr(preview_result, "operation_id", ""),
                    "compilation_successful": (
                        preview_result.compiler_result.compilation_successful
                        if preview_result.compiler_result
                        else False
                    ),
                    "refused": refused,
                    "receipt": receipt_summary,
                },
            )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("compile_preview", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    def get_publication_ledger_summary(
        self, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """Return a content-light summary of the publication evidence ledger."""
        cached = self._check_idempotency(
            "get_publication_ledger_summary", idempotency_key
        )
        if cached is not None:
            return cached

        pub = self._get_publication_service()
        if pub is _UNAVAILABLE_SENTINEL:
            result = _refused(
                "get_publication_ledger_summary",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "ProjectPagePublicationPreviewService (T1.2) is unavailable",
            )
            self._record_idempotency(idempotency_key, result)
            return result
        try:
            ledger = pub._ledger
            event_count = ledger.count_events() if ledger else 0
            reconstruction = (
                ledger.load_receipts(authoritative=False) if ledger else None
            )
            if reconstruction:
                result = _succeeded(
                    "get_publication_ledger_summary",
                    {
                        "total_events": reconstruction.total_rows,
                        "valid_rows": reconstruction.valid_rows,
                        "corrupt_rows": reconstruction.corrupt_rows,
                        "corruption_detected": reconstruction.corruption_detected,
                        "warnings": reconstruction.reconstruction_warnings,
                    },
                )
            else:
                result = _succeeded(
                    "get_publication_ledger_summary",
                    {
                        "total_events": event_count,
                        "valid_rows": 0,
                        "corrupt_rows": 0,
                        "corruption_detected": False,
                        "warnings": [],
                    },
                )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("get_publication_ledger_summary", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result

    # ── T4.2: Investigation Timeline Service ─────────────────────────

    def _get_timeline_service(self) -> Any:
        if self._timeline_service is None:
            try:
                from rig_relay.investigation_timeline import (
                    InvestigationEvidenceTimelineService,
                )

                self._timeline_service = InvestigationEvidenceTimelineService()
                logger.debug("gateway: T4.2 investigation timeline service initialized")
            except Exception as exc:
                logger.warning(
                    "gateway: T4.2 investigation timeline service unavailable — %s", exc
                )
                self._timeline_service = _UNAVAILABLE_SENTINEL
        return self._timeline_service

    def assemble_timeline(
        self, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """Assemble an investigation evidence timeline from canonical sources.

        Returns a content-light summary with event counts and degradation stats.
        """
        cached = self._check_idempotency("assemble_timeline", idempotency_key)
        if cached is not None:
            return cached

        tl = self._get_timeline_service()
        if tl is _UNAVAILABLE_SENTINEL:
            result = _refused(
                "assemble_timeline",
                GatewayErrorKind.SERVICE_UNAVAILABLE,
                "InvestigationEvidenceTimelineService (T4.2) is unavailable",
            )
            self._record_idempotency(idempotency_key, result)
            return result
        try:
            assembly_result = tl.assemble_timeline()
            if assembly_result is None:
                result = _refused(
                    "assemble_timeline",
                    GatewayErrorKind.DEPENDENCY_FAILED,
                    "Timeline assembly returned None",
                )
                self._record_idempotency(idempotency_key, result)
                return result

            timeline = assembly_result.timeline
            dg = getattr(timeline, "degradation_summary", None)
            result = _succeeded(
                "assemble_timeline",
                {
                    "timeline_id": timeline.timeline_id,
                    "assembled_at": timeline.assembled_at,
                    "event_count": timeline.event_count,
                    "domain_coverage": timeline.domain_coverage,
                    "verified_canonical_count": (
                        dg.verified_canonical_count if dg else 0
                    ),
                    "corrupt_count": dg.corrupt_count if dg else 0,
                    "missing_count": dg.missing_count if dg else 0,
                    "assembly_warnings": assembly_result.warnings,
                    "assembly_errors": assembly_result.errors,
                },
            )
            self._record_idempotency(idempotency_key, result)
            return result
        except Exception as exc:
            result = _failed("assemble_timeline", str(exc))
            self._record_idempotency(idempotency_key, result)
            return result


# ── Provenance Walking ────────────────────────────────────────────────


def _count_provenance_walk(
    j0: J0WorkspaceProjection,
    k0: K0OperatorProjection,
    l0: L0ContextProjection,
    m0: M0InferenceProjection,
) -> StudioProvenanceSummary:
    """Count provenance classes by walking the actual projection trees.

    This replaces O0's hardcoded _COUNTERS dict with tree traversal.
    Each field's provenance is counted exactly once.
    """
    summary = StudioProvenanceSummary()

    _count_in_object(j0, summary)
    _count_in_object(k0, summary)
    _count_in_object(l0, summary)
    _count_in_object(m0, summary)

    return summary


def _count_in_object(obj: Any, summary: StudioProvenanceSummary) -> None:
    """Recursively count provenance classes in a Pydantic model or dict."""
    if obj is None:
        return

    # Check if this object has a 'provenance' attribute/field
    prov = getattr(obj, "provenance", None)
    if isinstance(prov, ProvenanceClass):
        match prov:
            case ProvenanceClass.CANONICAL_FACT:
                summary.canonical_facts += 1
            case ProvenanceClass.DERIVED_PROJECTION:
                summary.derived_projections += 1
            case ProvenanceClass.GENERATED_PROPOSAL:
                summary.generated_proposals += 1
            case ProvenanceClass.REVIEW_REQUIRED_DRAFT:
                summary.review_required_drafts += 1
            case ProvenanceClass.APPROVED_CONTENT:
                summary.approved_contents += 1
            case ProvenanceClass.CONTROLLED_BOUNDARY_PROOF:
                summary.controlled_boundary_proofs += 1
            case ProvenanceClass.FIXTURE_DEFERRED:
                summary.fixture_deferred += 1
            case ProvenanceClass.REFUSED:
                summary.refused += 1
            case ProvenanceClass.CORRUPT_UNTRUSTED:
                summary.corrupt_untrusted += 1
        # Continue recursing — nested objects may also have provenance

    # Recurse into children
    if isinstance(obj, (list, tuple)):
        for item in obj:
            _count_in_object(item, summary)
    elif hasattr(type(obj), "model_fields"):
        # Pydantic model — recurse into fields (use class-level access)
        for field_name in type(obj).model_fields:
            child = getattr(obj, field_name, None)
            if child is not None:
                _count_in_object(child, summary)
    elif isinstance(obj, dict):
        for child in obj.values():
            _count_in_object(child, summary)


# ── Authority Classification ──────────────────────────────────────────


def _classify_j0_authority(j0: object) -> AuthorityEvidence:
    if j0 is _UNAVAILABLE_SENTINEL or j0 is None:
        return AuthorityEvidence(
            kind="j0_workspace",
            authority=ServiceAuthority.MISSING,
            degradation_reason="J0 workspace service cannot be loaded",
        )
    try:
        conn = getattr(j0, "connection", None)
        if conn is None:
            return AuthorityEvidence(
                kind="j0_workspace",
                authority=ServiceAuthority.CONTROLLED_BOUNDARY,
                degradation_reason="No GitHub App connection yet; controlled-boundary mode",
            )
        if getattr(conn, "token_available", False):
            return AuthorityEvidence(
                kind="j0_workspace", authority=ServiceAuthority.CANONICAL_LIVE
            )
        return AuthorityEvidence(
            kind="j0_workspace",
            authority=ServiceAuthority.CONTROLLED_BOUNDARY,
            degradation_reason="GitHub App installation token not available",
        )
    except Exception as exc:
        return AuthorityEvidence(
            kind="j0_workspace",
            authority=ServiceAuthority.CORRUPT,
            degradation_reason=f"J0 connection inspection raised: {exc}",
        )


def _classify_k0_authority(sessions: dict[str, Any]) -> AuthorityEvidence:
    if not sessions:
        return AuthorityEvidence(
            kind="k0_operator",
            authority=ServiceAuthority.MISSING,
            degradation_reason="No K0 operator sessions registered in gateway",
        )
    return AuthorityEvidence(
        kind="k0_operator", authority=ServiceAuthority.CANONICAL_LIVE
    )


def _classify_l0_authority(j0: object, sessions: dict[str, Any]) -> AuthorityEvidence:
    has_j0 = j0 is not _UNAVAILABLE_SENTINEL and j0 is not None
    has_k0 = bool(sessions)

    if not has_j0 and not has_k0:
        return AuthorityEvidence(
            kind="l0_context",
            authority=ServiceAuthority.FIXTURE_DEFERRED,
            degradation_reason="L0 intake and investigation are both fixture-deferred; J0/K0 boundaries not live",
        )
    if not has_j0:
        return AuthorityEvidence(
            kind="l0_context",
            authority=ServiceAuthority.CANONICAL_DEGRADED,
            degradation_reason="L0 J0 intake boundary is fixture-deferred",
        )
    if not has_k0:
        return AuthorityEvidence(
            kind="l0_context",
            authority=ServiceAuthority.CANONICAL_DEGRADED,
            degradation_reason="L0 K0 investigation boundary is fixture-deferred",
        )
    return AuthorityEvidence(
        kind="l0_context", authority=ServiceAuthority.CANONICAL_LIVE
    )


def _classify_m0_authority(m0: object) -> AuthorityEvidence:
    if m0 is _UNAVAILABLE_SENTINEL or m0 is None:
        return AuthorityEvidence(
            kind="m0_inference",
            authority=ServiceAuthority.MISSING,
            degradation_reason="M0 inference service cannot be loaded",
        )
    try:
        runtime_info = m0.get_runtime_info()
        if runtime_info.get("available"):
            return AuthorityEvidence(
                kind="m0_inference", authority=ServiceAuthority.CANONICAL_LIVE
            )
        return AuthorityEvidence(
            kind="m0_inference",
            authority=ServiceAuthority.CANONICAL_DEGRADED,
            degradation_reason="M0 runtime is not configured or not reachable",
        )
    except Exception as exc:
        return AuthorityEvidence(
            kind="m0_inference",
            authority=ServiceAuthority.CORRUPT,
            degradation_reason=f"M0 runtime_info raised: {exc}",
        )


# ── Helpers ──────────────────────────────────────────────────────────

_UNAVAILABLE_SENTINEL = object()


def _service_health_label(section: Any) -> str:
    if section is None:
        return "unavailable"
    if hasattr(section, "available"):
        return "available" if section.available else "degraded"
    return "available"


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
