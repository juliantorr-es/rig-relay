"""Developer studio gateway intent handlers — Lane O0.

Routes typed intents from the bridge frontend to the correct producer
service through the DeveloperStudioGatewayService. Never bypasses J0/K0/
L0/M0 authority. All intent payloads are validated before dispatch.
"""

from __future__ import annotations

from typing import Any

from rig_relay.desktop.gateway._models import GatewayErrorKind
from rig_relay.desktop.gateway._service import DeveloperStudioGatewayService

_GATEWAY_INTENT_NAMES: frozenset[str] = frozenset({
    "get_developer_studio_projection",
    "studio_connect_workspace",
    "studio_discover_repositories",
    "studio_select_repository",
    "studio_import_repository",
    "studio_inspect_publication_readiness",
    "studio_prepare_pages_action",
    "studio_start_investigation",
    "studio_get_investigation",
    "studio_close_investigation",
    "studio_assemble_project_profile",
    "studio_assemble_context_packet",
    "studio_request_local_assistance",
    "studio_get_local_draft",
})

_SINGLETON_GATEWAY: DeveloperStudioGatewayService | None = None


def get_gateway_service() -> DeveloperStudioGatewayService:
    global _SINGLETON_GATEWAY
    if _SINGLETON_GATEWAY is None:
        _SINGLETON_GATEWAY = DeveloperStudioGatewayService()
    return _SINGLETON_GATEWAY


def reset_gateway_service() -> None:
    global _SINGLETON_GATEWAY
    _SINGLETON_GATEWAY = None


def execute_gateway_intent(
    intent_name: str,
    parameters: dict[str, Any] | None = None,
    *,
    gateway: DeveloperStudioGatewayService | None = None,
) -> dict[str, Any]:
    """Route a named intent to the gateway service.

    All intents are read-only or safe-local. Mutation intents
    (Pages deployment, proposal approval, live publication) are
    explicitly refused. Never bypasses J0/K0/L0/M0 authority.
    """
    gw = gateway or get_gateway_service()
    params = parameters or {}

    match intent_name:
        case "get_developer_studio_projection":
            proj = gw.build_projection()
            result = proj.model_dump(mode="json")
            return {
                "status": "completed",
                "intent_name": intent_name,
                "data": result,
                "projection_refresh_recommended": False,
            }

        # ── J0 intents ────────────────────────────────────────
        case "studio_connect_workspace":
            return gw.connect_workspace()

        case "studio_discover_repositories":
            return gw.discover_repositories()

        case "studio_select_repository":
            repo_hash = params.get("repository_hash", "")
            if not repo_hash:
                return _refused_msg(intent_name, "repository_hash is required")
            return gw.select_repository(repo_hash)

        case "studio_import_repository":
            repo_hash = params.get("repository_hash", "")
            owner = params.get("owner", "")
            repo = params.get("repo", "")
            if not repo_hash or not owner or not repo:
                return _refused_msg(
                    intent_name, "repository_hash, owner, and repo are required"
                )
            return gw.import_repository(repo_hash, owner, repo)

        case "studio_inspect_publication_readiness":
            owner = params.get("owner", "")
            repo = params.get("repo", "")
            if not owner or not repo:
                return _refused_msg(intent_name, "owner and repo are required")
            return gw.inspect_publication_readiness(owner, repo)

        case "studio_prepare_pages_action":
            return gw.prepare_pages_action(
                owner=params.get("owner", ""),
                repo=params.get("repo", ""),
                target_type=params.get("target_type", "project_page"),
                source_branch=params.get("source_branch", ""),
                source_path=params.get("source_path", "/"),
            )

        # ── K0 intents ────────────────────────────────────────
        case "studio_start_investigation":
            repo_label = params.get("repository_label", "")
            purpose = params.get("purpose", "Investigate repository for publication")
            if not repo_label:
                return _refused_msg(intent_name, "repository_label is required")
            return gw.start_investigation(
                repository_label=repo_label,
                purpose=purpose,
                workspace_root=params.get("workspace_root", ""),
                head_sha=params.get("head_sha", ""),
                branch=params.get("branch", ""),
                agent_profile_name=params.get("agent_profile_name", "plan"),
            )

        case "studio_get_investigation":
            session_id = params.get("session_id", "")
            if not session_id:
                return _refused_msg(intent_name, "session_id is required")
            return gw.get_investigation_projection(session_id)

        case "studio_close_investigation":
            session_id = params.get("session_id", "")
            if not session_id:
                return _refused_msg(intent_name, "session_id is required")
            return gw.close_investigation(session_id)

        # ── L0 intents ────────────────────────────────────────
        case "studio_assemble_project_profile":
            project_name = params.get("project_name", "")
            if not project_name:
                return _refused_msg(intent_name, "project_name is required")
            return gw.assemble_project_profile(
                project_name=project_name,
                repository_root=params.get("repository_root", ""),
                head_sha=params.get("head_sha", ""),
                branch=params.get("branch", ""),
            )

        case "studio_assemble_context_packet":
            project_name = params.get("project_name", "")
            if not project_name:
                return _refused_msg(intent_name, "project_name is required")
            return gw.assemble_context_packet(
                project_name=project_name,
                repository_root=params.get("repository_root", ""),
                head_sha=params.get("head_sha", ""),
                branch=params.get("branch", ""),
            )

        # ── M0 intents ────────────────────────────────────────
        case "studio_request_local_assistance":
            task_kind = params.get("task_kind", "")
            if not task_kind:
                return _refused_msg(intent_name, "task_kind is required")
            valid_kinds = {
                "project_summary",
                "page_section_ordering",
                "capability_classification",
                "missing_material_checklist",
            }
            if task_kind not in valid_kinds:
                return _refused_msg(
                    intent_name,
                    f"task_kind must be one of: {', '.join(sorted(valid_kinds))}",
                )
            return gw.request_local_assistance(task_kind=task_kind)

        case "studio_get_local_draft":
            draft_sha256 = params.get("draft_sha256", "")
            if not draft_sha256:
                return _refused_msg(intent_name, "draft_sha256 is required")
            return gw.get_local_draft(draft_sha256)

        case _:
            return {
                "status": "refused",
                "intent_name": intent_name,
                "error_kind": GatewayErrorKind.INTENT_UNKNOWN.value,
                "error_message": f"Unknown gateway intent: {intent_name}",
            }


def _refused_msg(intent_name: str, message: str) -> dict[str, Any]:
    return {
        "status": "refused",
        "intent_name": intent_name,
        "error_kind": GatewayErrorKind.INTENT_REFUSED.value,
        "error_message": message,
    }


def is_gateway_intent(intent_name: str) -> bool:
    return intent_name in _GATEWAY_INTENT_NAMES
