"""Developer studio gateway intent handlers — Lane S2 (hardened from O0).

Routes typed intents from the bridge frontend to the correct producer
service through the DeveloperStudioGatewayService. Never bypasses J0/K0/
L0/M0 authority. All intent payloads are validated before dispatch.

Now supports idempotency keys for mutating intents: duplicate invocations
with the same key return the cached result. Content-light enforcement
runs on intent results where applicable.
"""

from __future__ import annotations

from typing import Any

from rig_relay.desktop.gateway._content_light import enforce_content_light
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
    # X0 surface intents — consume T1.2/T3.1/T4.2
    "studio_register_repository",
    "studio_observe_repository",
    "studio_compile_preview",
    "studio_get_publication_ledger_summary",
    "studio_assemble_timeline",
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

    Idempotency keys prevent duplicate effects for mutating intents.
    """
    gw = gateway or get_gateway_service()
    params = parameters or {}
    idempotency_key = params.get("idempotency_key")

    match intent_name:
        case "get_developer_studio_projection":
            proj = gw.build_projection()
            result_dict = proj.model_dump(mode="json")
            violations = enforce_content_light(
                result_dict, source_label="developer_studio_projection"
            )
            warnings = violations if violations else []
            result = {
                "status": "completed",
                "intent_name": intent_name,
                "data": result_dict,
                "projection_refresh_recommended": False,
            }
            if warnings:
                result["warnings"] = warnings
            return result

        # ── J0 intents ────────────────────────────────────────
        case "studio_connect_workspace":
            return gw.connect_workspace(idempotency_key=idempotency_key)

        case "studio_discover_repositories":
            return gw.discover_repositories(idempotency_key=idempotency_key)

        case "studio_select_repository":
            repo_hash = params.get("repository_hash", "")
            if not repo_hash:
                return _refused_msg(intent_name, "repository_hash is required")
            return gw.select_repository(repo_hash, idempotency_key=idempotency_key)

        case "studio_import_repository":
            repo_hash = params.get("repository_hash", "")
            owner = params.get("owner", "")
            repo = params.get("repo", "")
            if not repo_hash or not owner or not repo:
                return _refused_msg(
                    intent_name, "repository_hash, owner, and repo are required"
                )
            return gw.import_repository(
                repo_hash, owner, repo, idempotency_key=idempotency_key
            )

        case "studio_inspect_publication_readiness":
            owner = params.get("owner", "")
            repo = params.get("repo", "")
            if not owner or not repo:
                return _refused_msg(intent_name, "owner and repo are required")
            return gw.inspect_publication_readiness(
                owner, repo, idempotency_key=idempotency_key
            )

        case "studio_prepare_pages_action":
            return gw.prepare_pages_action(
                owner=params.get("owner", ""),
                repo=params.get("repo", ""),
                target_type=params.get("target_type", "project_page"),
                source_branch=params.get("source_branch", ""),
                source_path=params.get("source_path", "/"),
                idempotency_key=idempotency_key,
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
                idempotency_key=idempotency_key,
            )

        case "studio_get_investigation":
            session_id = params.get("session_id", "")
            if not session_id:
                return _refused_msg(intent_name, "session_id is required")
            return gw.get_investigation_projection(
                session_id, idempotency_key=idempotency_key
            )

        case "studio_close_investigation":
            session_id = params.get("session_id", "")
            if not session_id:
                return _refused_msg(intent_name, "session_id is required")
            return gw.close_investigation(session_id, idempotency_key=idempotency_key)

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
                idempotency_key=idempotency_key,
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
                idempotency_key=idempotency_key,
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
            return gw.request_local_assistance(
                task_kind=task_kind, idempotency_key=idempotency_key
            )

        case "studio_get_local_draft":
            draft_sha256 = params.get("draft_sha256", "")
            if not draft_sha256:
                return _refused_msg(intent_name, "draft_sha256 is required")
            return gw.get_local_draft(draft_sha256, idempotency_key=idempotency_key)

        # ── X0 surface intents: T3.1 Repository Estate ─────────
        case "studio_register_repository":
            root_path_str = params.get("root_path", "")
            if not root_path_str:
                return _refused_msg(intent_name, "root_path is required")
            return gw.register_repository(
                root_path_str, idempotency_key=idempotency_key
            )

        case "studio_observe_repository":
            repository_hash = params.get("repository_hash", "")
            root_path_str = params.get("root_path", "")
            if not repository_hash:
                return _refused_msg(intent_name, "repository_hash is required")
            return gw.observe_repository(
                repository_hash,
                root_path=root_path_str,
                idempotency_key=idempotency_key,
            )

        # ── X0 surface intents: T1.2 Publication Preview ───────
        case "studio_compile_preview":
            project_name = params.get("project_name", "")
            if not project_name:
                return _refused_msg(intent_name, "project_name is required")
            return gw.compile_preview(
                project_name=project_name,
                repository_root=params.get("repository_root", ""),
                repo_owner=params.get("repo_owner", ""),
                repo_name=params.get("repo_name", ""),
                publication_policy=params.get("publication_policy", "preview_only"),
                idempotency_key=idempotency_key,
            )

        case "studio_get_publication_ledger_summary":
            return gw.get_publication_ledger_summary(idempotency_key=idempotency_key)

        # ── X0 surface intents: T4.2 Timeline ──────────────────
        case "studio_assemble_timeline":
            return gw.assemble_timeline(idempotency_key=idempotency_key)

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
