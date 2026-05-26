"""Authorization binding contracts for Lane B GitHub operations.

Provides typed authorization-pending states for all GitHub mutation operations
while Lane A's disclosure/authorization authority is not integrated.
Never invents Lane B-specific approval receipts.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuthorizationState(StrEnum):
    PENDING = "pending"
    GRANTED = "granted"
    REFUSED = "refused"
    UNAVAILABLE = "unavailable"
    NOT_REQUIRED = "not_required"


class AuthorizationBinding(BaseModel):
    """Typed authorization requirement for a GitHub mutation operation."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str
    operation_kind: (
        str  # profile_update, repo_create, issue_mutate, pages_publish, workflow_rerun
    )
    authorization_state: str = AuthorizationState.PENDING.value
    required_github_permission: str = ""
    required_user_token: bool = False
    required_installation_token: bool = False
    lane_a_authority_required: bool = True
    lane_a_integrated: bool = False
    refusal_code: str = "authorization_authority_pending"
    suggested_next_action: str = (
        "Lane A authorization authority required for this operation"
    )
    stale: bool = False

    def is_granted(self) -> bool:
        return (
            self.authorization_state == AuthorizationState.GRANTED.value
            and not self.stale
        )

    def refusal_result(self) -> dict[str, Any]:
        """Return a content-light refusal result for operator/agent consumption."""
        return {
            "operation_id": self.operation_id,
            "status": "refused",
            "refusal_code": self.refusal_code,
            "suggested_next_action": self.suggested_next_action,
            "required_github_permission": self.required_github_permission,
            "lane_a_integrated": self.lane_a_integrated,
        }


# ── Pre-built bindings for each operation kind ─────────────────────────


def authorization_binding_for(
    operation_kind: str,
    required_github_permission: str = "",
    required_user_token: bool = False,
    required_installation_token: bool = False,
) -> AuthorizationBinding:
    return AuthorizationBinding(
        operation_id=f"github.{operation_kind}",
        operation_kind=operation_kind,
        required_github_permission=required_github_permission,
        required_user_token=required_user_token,
        required_installation_token=required_installation_token,
    )


class AuthorizationManifest(BaseModel):
    """Registry of all Lane B authorization bindings."""

    model_config = ConfigDict(extra="forbid")

    bindings: list[AuthorizationBinding] = Field(default_factory=list)

    @classmethod
    def lane_b_defaults(cls) -> AuthorizationManifest:
        return cls(
            bindings=[
                authorization_binding_for(
                    "profile_update",
                    required_github_permission="Profile:write",
                    required_user_token=True,
                ),
                authorization_binding_for(
                    "repo_create",
                    required_github_permission="Administration:write",
                    required_user_token=True,
                ),
                authorization_binding_for(
                    "issue_create",
                    required_github_permission="Issues:write",
                    required_installation_token=True,
                ),
                authorization_binding_for(
                    "issue_comment",
                    required_github_permission="Issues:write",
                    required_installation_token=True,
                ),
                authorization_binding_for(
                    "issue_close",
                    required_github_permission="Issues:write",
                    required_installation_token=True,
                ),
                authorization_binding_for(
                    "pages_publish",
                    required_github_permission="Pages:write",
                    required_installation_token=True,
                ),
                authorization_binding_for(
                    "workflow_rerun",
                    required_github_permission="Actions:write",
                    required_installation_token=True,
                ),
                authorization_binding_for(
                    "workflow_dispatch",
                    required_github_permission="Actions:write",
                    required_installation_token=True,
                ),
            ]
        )

    def for_operation(self, operation_kind: str) -> AuthorizationBinding | None:
        for b in self.bindings:
            if b.operation_kind == operation_kind:
                return b
        return None


__all__ = ["AuthorizationBinding", "AuthorizationManifest", "AuthorizationState"]
