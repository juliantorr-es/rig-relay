"""GitHub Repository Bootstrap — plan and governed creation of remote repositories.

Implements a typed bootstrap plan from local project evidence and project-profile input.
Repository creation requires a GitHub App user access token with Administration:write.
All real mutation is authorization-gated; returns authorization_authority_pending
until Lane A authority is integrated.
"""

from __future__ import annotations

from enum import StrEnum
import json
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from rig_relay.integrations.github_provider._authorization_binding import (
    AuthorizationBinding,
    AuthorizationState,
)
from rig_relay.integrations.github_provider._redaction import assert_no_raw_github_token

GITHUB_API_BASE = "https://api.github.com"


def _map_bootstrap_consumer_outcome(outcome: str) -> str:
    return {
        "authorized": "github.bootstrap.authorized",
        "missing_authorization": BootstrapErrorKind.AUTHORIZATION_PENDING,
        "request_digest_mismatch": "github.bootstrap.request_digest_mismatch",
        "action_mismatch": "github.bootstrap.action_mismatch",
        "target_mismatch": "github.bootstrap.target_mismatch",
        "provider_mismatch": "github.bootstrap.provider_mismatch",
        "stale_evidence": "github.bootstrap.stale_evidence",
        "expired_receipt": "github.bootstrap.expired_receipt",
        "already_consumed": "github.bootstrap.already_consumed",
        "integrity_tampered": "github.bootstrap.integrity_tampered",
    }.get(outcome, BootstrapErrorKind.UNKNOWN)


# ── Bootstrap Plan ─────────────────────────────────────────────────────


class RepoPurpose(StrEnum):
    ORDINARY = "ordinary"
    PROFILE_README = "profile_readme"
    USER_PAGES = "user_pages"
    PROJECT_PAGES = "project_pages"
    EXISTING_REMOTE = "existing_remote"


class BootstrapPlan(BaseModel):
    """Typed bootstrap plan for creating a GitHub repository from a local project."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = ""
    purpose: str = RepoPurpose.ORDINARY.value

    # Remote target
    proposed_owner: str = ""
    proposed_name: str = ""
    proposed_visibility: str = "public"  # public, private
    proposed_description: str = ""
    proposed_homepage: str = ""
    proposed_default_branch: str = "main"

    # Local evidence (content-light)
    local_repo_root: str = ""  # hashed
    local_branch: str = ""
    local_head_sha: str = ""
    is_dirty: bool = True
    dirty_file_count: int = 0

    # Required permissions
    required_user_token: bool = True
    required_permissions: list[str] = Field(
        default_factory=list
    )  # e.g., ["Administration:write"]

    # Authorization
    authorization_binding: AuthorizationBinding | None = None
    authorization_status: str = AuthorizationState.PENDING.value

    # State
    status: str = "planned"  # planned, ready, executing, executed, refused, error
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    stale: bool = False
    suggested_next_action: str | None = None

    def is_ready(self) -> bool:
        return (
            bool(self.proposed_name)
            and not self.blockers
            and self.authorization_status == AuthorizationState.GRANTED.value
            and not self.stale
        )


class BootstrapResult(BaseModel):
    """Result of a repository bootstrap attempt."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    status: str  # executed, refused, authorization_pending, stale_refused, error
    repository_name: str = ""
    repository_full_name: str = ""
    repository_url: str = ""
    repository_id: int = 0
    remote_head_sha: str | None = None
    verification_match: bool | None = None
    error_kind: str | None = None
    suggested_next_action: str | None = None


# ── Bootstrap Error Vocabulary ─────────────────────────────────────────


class BootstrapErrorKind:
    MISSING_USER_TOKEN = "github.bootstrap.missing_user_token"
    MISSING_ADMIN_PERMISSION = "github.bootstrap.missing_admin_permission"
    NAME_COLLISION = "github.bootstrap.name_collision"
    STALE_LOCAL_HEAD = "github.bootstrap.stale_local_head"
    REMOTE_ALREADY_EXISTS = "github.bootstrap.remote_already_exists"
    DIRTY_LOCAL = "github.bootstrap.dirty_local"
    AUTHORIZATION_PENDING = "github.bootstrap.authorization_pending"
    RATE_LIMITED = "github.bootstrap.rate_limited"
    API_UNAVAILABLE = "github.bootstrap.api_unavailable"
    UNKNOWN = "github.bootstrap.unknown_error"


# ── Bootstrap Adapter ──────────────────────────────────────────────────


class GitHubBootstrapError(Exception):
    def __init__(self, error_kind: str, message: str) -> None:
        super().__init__(message)
        self.error_kind = error_kind


class GitHubBootstrapAdapter:
    """Governed repository creation and bootstrap adapter."""

    def __init__(self, user_token: str | None = None) -> None:
        self._token = user_token

    def build_bootstrap_plan(
        self,
        purpose: str,
        proposed_name: str,
        proposed_owner: str = "",
        proposed_visibility: str = "public",
        proposed_description: str = "",
        local_head_sha: str = "",
        is_dirty: bool = False,
    ) -> BootstrapPlan:
        plan = BootstrapPlan(
            plan_id=f"bootstrap-{proposed_name}-{int(time.time())}",
            purpose=purpose,
            proposed_owner=proposed_owner,
            proposed_name=proposed_name,
            proposed_visibility=proposed_visibility,
            proposed_description=proposed_description,
            local_head_sha=local_head_sha,
            is_dirty=is_dirty,
            required_user_token=True,
            required_permissions=["Administration:write"],
            authorization_status=AuthorizationState.PENDING.value,
            suggested_next_action="Authorization required from Lane A before repository creation",
        )

        # Blockers
        if is_dirty:
            plan.blockers.append("Local repository has uncommitted changes")
            plan.status = "refused"
            plan.suggested_next_action = (
                "Commit or stash local changes before bootstrap"
            )

        if not proposed_name:
            plan.blockers.append("Repository name is required")
            plan.status = "refused"

        if purpose == RepoPurpose.USER_PAGES.value and not proposed_name.endswith(
            ".github.io"
        ):
            plan.warnings = [
                f"User Pages repo should be named <owner>.github.io, got {proposed_name}"
            ]
            plan.blockers.append("User Pages repository name convention violation")

        if purpose == RepoPurpose.PROFILE_README.value and not proposed_name:
            plan.blockers.append(
                "Profile README repository must be named after GitHub username"
            )

        return plan

    async def create_repository(
        self, plan: BootstrapPlan, authorization_id: str = ""
    ) -> BootstrapResult:
        """Create a repository. Consumes Lane A authorization receipt."""
        from rig_relay.integrations.github_provider._authorization_consumer import (
            ConsumerOutcome,
            GitHubAuthorizationConsumer,
        )

        if plan.stale:
            return BootstrapResult(
                plan_id=plan.plan_id,
                status="stale_refused",
                error_kind=BootstrapErrorKind.STALE_LOCAL_HEAD,
                suggested_next_action="Rebuild bootstrap plan with current local state",
            )

        if not authorization_id:
            return BootstrapResult(
                plan_id=plan.plan_id,
                status="authorization_required",
                error_kind=BootstrapErrorKind.AUTHORIZATION_PENDING,
                suggested_next_action="Provide a Lane A remote-action authorization receipt",
            )

        if not self._token:
            return BootstrapResult(
                plan_id=plan.plan_id,
                status="refused",
                error_kind=BootstrapErrorKind.MISSING_USER_TOKEN,
                suggested_next_action="No GitHub App user access token available",
            )

        payload: dict[str, Any] = {
            "name": plan.proposed_name,
            "private": plan.proposed_visibility == "private",
            "auto_init": False,
        }
        if plan.proposed_description:
            payload["description"] = plan.proposed_description
        if plan.proposed_homepage:
            payload["homepage"] = plan.proposed_homepage

        target = plan.proposed_owner or "authenticated-user"
        consumer_result = GitHubAuthorizationConsumer.validate_and_consume(
            authorization_id=authorization_id,
            operation_kind="repo_create",
            request_payload=payload,
            target_identity=f"{target}/{plan.proposed_name}",
        )

        if consumer_result.outcome != ConsumerOutcome.AUTHORIZED.value:
            return BootstrapResult(
                plan_id=plan.plan_id,
                status="refused",
                error_kind=_map_bootstrap_consumer_outcome(consumer_result.outcome),
                suggested_next_action=consumer_result.suggested_next_action,
            )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{GITHUB_API_BASE}/user/repos",
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "rig-relay-bootstrap/1.0",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            assert_no_raw_github_token(json.dumps(data, sort_keys=True))

            return BootstrapResult(
                plan_id=plan.plan_id,
                status="executed",
                repository_name=data.get("name", plan.proposed_name),
                repository_full_name=data.get("full_name", ""),
                repository_url=data.get("html_url", ""),
                repository_id=data.get("id", 0),
                suggested_next_action=f"Repository {data.get('full_name', plan.proposed_name)} created; push local content when authorized",
            )

        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            if status_code == 422:
                return BootstrapResult(
                    plan_id=plan.plan_id,
                    status="refused",
                    error_kind=BootstrapErrorKind.NAME_COLLISION,
                    suggested_next_action=f"Repository name '{plan.proposed_name}' already exists or is invalid",
                )
            if status_code == 401:
                return BootstrapResult(
                    plan_id=plan.plan_id,
                    status="refused",
                    error_kind=BootstrapErrorKind.MISSING_USER_TOKEN,
                    suggested_next_action="User token is invalid or expired",
                )
            if status_code == 403:
                return BootstrapResult(
                    plan_id=plan.plan_id,
                    status="refused",
                    error_kind=BootstrapErrorKind.MISSING_ADMIN_PERMISSION,
                    suggested_next_action="Token lacks Administration:write permission",
                )
            return BootstrapResult(
                plan_id=plan.plan_id,
                status="error",
                error_kind=BootstrapErrorKind.API_UNAVAILABLE,
                suggested_next_action=f"GitHub API error {status_code}",
            )
        except Exception as e:
            return BootstrapResult(
                plan_id=plan.plan_id,
                status="error",
                error_kind=BootstrapErrorKind.UNKNOWN,
                suggested_next_action=f"Unexpected error: {e}",
            )


__all__ = [
    "BootstrapErrorKind",
    "BootstrapPlan",
    "BootstrapResult",
    "GitHubBootstrapAdapter",
    "GitHubBootstrapError",
    "RepoPurpose",
]
