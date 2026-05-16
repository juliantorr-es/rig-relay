"""Role model explainer — compact projection explaining orchestrator/subagent/Ralph roles.

Serves as an in-app help card so the demo is self-explanatory.
Content-light: role names, counts, descriptions. No raw data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

EXPLAINER_VERSION = "rig.ui.role_model_summary.v1"


class RoleEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_name: str = ""
    role_kind: str = ""
    emoji: str = ""
    description: str = ""
    count: int = 0


class RoleModelSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = EXPLAINER_VERSION
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    roles: list[RoleEntry] = Field(default_factory=list)

    assignable_subagent_count: int = 0
    autonomous_worker_count: int = 0
    configured_model_binding_count: int = 0
    pending_ralph_report_count: int = 0

    available_actions: list[dict[str, str | bool]] = Field(default_factory=lambda: [
        {"action": "role_model_info", "label": "Dismiss", "requires_confirmation": False},
    ])


def build_role_model_summary(
    profiles: list[Any] | None = None,
    bindings: list[Any] | None = None,
    pending_report_count: int = 0,
) -> RoleModelSummary:
    profiles = profiles or []
    bindings = bindings or []

    assignable = [p for p in profiles if getattr(p, "assignable", False) and getattr(p, "profile_kind", "") != "autonomous_background_worker"]
    autonomous = [p for p in profiles if getattr(p, "profile_kind", "") == "autonomous_background_worker"]

    roles = [
        RoleEntry(
            role_name="Orchestrator",
            role_kind="manager",
            emoji="🎯",
            description="Manages subagent profiles, assigns missions to specialist workers, and reviews autonomous Ralph reports.",
            count=1,
        ),
        RoleEntry(
            role_name="Subagents",
            role_kind="specialist",
            emoji="🔧",
            description="Specialist workers assigned missions by the orchestrator. Each has a profile defining capabilities, trust tier, and lane behavior.",
            count=len(assignable),
        ),
        RoleEntry(
            role_name="Ralph",
            role_kind="autonomous_background",
            emoji="🤖",
            description="Autonomous background convergence worker. Observes all lane projections, fixes bounded issues in Ralph-owned worktrees, and reports completed work to the orchestrator. Not a normal assignable subagent.",
            count=len(autonomous),
        ),
        RoleEntry(
            role_name="Model Bindings",
            role_kind="capability_config",
            emoji="⚡",
            description="Runtime capability configuration. Model/provider selection is attached to profiles, not treated as worker identity. Local demo mode works without API keys.",
            count=len(bindings),
        ),
    ]

    return RoleModelSummary(
        roles=roles,
        assignable_subagent_count=len(assignable),
        autonomous_worker_count=len(autonomous),
        configured_model_binding_count=len(bindings),
        pending_ralph_report_count=pending_report_count,
    )


__all__ = [
    "EXPLAINER_VERSION",
    "RoleEntry",
    "RoleModelSummary",
    "build_role_model_summary",
]
