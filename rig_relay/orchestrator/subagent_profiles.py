"""Subagent profile registry and mission assignment model.

The orchestrator manages configured subagent profiles. Each profile
defines capabilities, trust tier, and lane behavior. Ralph has a separate
profile_kind = "autonomous_background_worker" — not assignable like normal
subagents.

Mission assignments bind a mission_id to a profile_id and lane_id.
The orchestrator assigns, monitors, and can re-assign missions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

PROFILE_VERSION = "rig.subagent_profile.v1"
ASSIGNMENT_VERSION = "rig.orchestrator_mission_assignment.v1"
BINDING_VERSION = "rig.model_provider_binding.v1"

TRUST_TIER_OBSERVE = 0
TRUST_TIER_SAFE_LOCAL = 2
TRUST_TIER_PATCH_PROPOSAL = 3

PROFILE_TRUST_TIERS = {
    TRUST_TIER_OBSERVE: "observe_only",
    TRUST_TIER_SAFE_LOCAL: "safe_local_maintenance",
    TRUST_TIER_PATCH_PROPOSAL: "patch_proposal",
}

PROFILE_KIND_STANDARD_SUBAGENT = "standard_subagent"
PROFILE_KIND_AUTONOMOUS_BACKGROUND = "autonomous_background_worker"

PROFILE_KINDS = [PROFILE_KIND_STANDARD_SUBAGENT, PROFILE_KIND_AUTONOMOUS_BACKGROUND]

MISSION_ASSIGNMENT_STATUSES = [
    "proposed",
    "assigned",
    "active",
    "blocked",
    "completed",
    "failed",
]


class ProfileKind(StrEnum):
    STANDARD_SUBAGENT = "standard_subagent"
    AUTONOMOUS_BACKGROUND = "autonomous_background_worker"


class TrustTier(StrEnum):
    OBSERVE = "observe_only"
    EVIDENCE_WRITE = "evidence_write"
    SAFE_LOCAL = "safe_local_maintenance"
    PATCH_PROPOSAL = "patch_proposal"
    MAIN_MUTATION = "main_workspace_mutation"
    EXTERNAL = "external_side_effects"


BINDING_STATUS_DEMO_LOCAL = "demo_local"
BINDING_STATUS_CONFIGURED = "configured"
BINDING_STATUS_UNAVAILABLE = "unavailable"
BINDING_STATUS_DISABLED = "disabled"

BINDING_STATUSES = [
    BINDING_STATUS_DEMO_LOCAL,
    BINDING_STATUS_CONFIGURED,
    BINDING_STATUS_UNAVAILABLE,
    BINDING_STATUS_DISABLED,
]


class BindingStatus(StrEnum):
    DEMO_LOCAL = "demo_local"
    CONFIGURED = "configured"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class ModelProviderBinding(BaseModel):
    """Lightweight model/provider runtime capability binding.

    Separates the runtime backing (model/provider) from the agent
    identity (profile). A profile is the role; the binding is which
    model powers it. Demo bindings require no API key or network.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = BINDING_VERSION
    binding_id: str = Field(default_factory=lambda: str(uuid4()))
    provider_id: str = ""
    model_id: str = ""
    display_name: str = ""
    status: str = BINDING_STATUS_DEMO_LOCAL
    requires_api_key: bool = False
    requires_network: bool = False
    supports_tool_calls: bool = True
    supports_streaming: bool = True
    allowed_profile_ids: list[str] = Field(default_factory=list)


class SubagentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PROFILE_VERSION
    profile_id: str = Field(default_factory=lambda: str(uuid4()))
    display_name: str = ""
    profile_kind: str = PROFILE_KIND_STANDARD_SUBAGENT
    role: str = ""
    description: str = ""

    allowed_capabilities: list[str] = Field(default_factory=list)
    forbidden_capabilities: list[str] = Field(default_factory=list)

    default_lane_kind: str = "mission_lane"
    preferred_provider: str | None = None

    enabled: bool = True
    max_concurrent_missions: int = 2
    trust_tier: str = TrustTier.OBSERVE.value

    requires_worktree: bool = True
    can_mutate: bool = False
    can_run_validators: bool = True
    can_commit: bool = True
    can_report_to_orchestrator: bool = True

    assignable: bool = True
    reports_to_orchestrator: bool = False


class MissionAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = ASSIGNMENT_VERSION
    assignment_id: str = Field(default_factory=lambda: str(uuid4()))
    mission_id: str = ""
    assigned_profile_id: str = ""
    lane_id: str = ""
    status: str = "proposed"
    objective: str = ""
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, str]] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    latest_event_id: str = ""

    model_binding_id: str = ""
    model_binding_label: str = ""
    provider_status: str = BINDING_STATUS_DEMO_LOCAL


class ProfileRegistry:
    """In-memory registry of configured subagent profiles."""

    def __init__(self) -> None:
        self._profiles: dict[str, SubagentProfile] = {}

    def register(self, profile: SubagentProfile) -> None:
        self._profiles[profile.profile_id] = profile

    def get(self, profile_id: str) -> SubagentProfile | None:
        return self._profiles.get(profile_id)

    def get_by_kind(self, profile_kind: str) -> list[SubagentProfile]:
        return [p for p in self._profiles.values() if p.profile_kind == profile_kind]

    def assignable(self) -> list[SubagentProfile]:
        return [p for p in self._profiles.values() if p.assignable and p.enabled]

    def autonomous_workers(self) -> list[SubagentProfile]:
        return [
            p
            for p in self._profiles.values()
            if p.profile_kind == PROFILE_KIND_AUTONOMOUS_BACKGROUND and p.enabled
        ]

    def list_all(self) -> list[SubagentProfile]:
        return list(self._profiles.values())

    def reset(self) -> None:
        self._profiles.clear()


class BindingRegistry:
    """In-memory registry of model/provider bindings."""

    def __init__(self) -> None:
        self._bindings: dict[str, ModelProviderBinding] = {}

    def register(self, binding: ModelProviderBinding) -> None:
        self._bindings[binding.binding_id] = binding

    def get(self, binding_id: str) -> ModelProviderBinding | None:
        return self._bindings.get(binding_id)

    def get_for_profile(self, profile_id: str) -> ModelProviderBinding | None:
        for b in self._bindings.values():
            if profile_id in b.allowed_profile_ids:
                return b
        return None

    def list_all(self) -> list[ModelProviderBinding]:
        return list(self._bindings.values())

    def reset(self) -> None:
        self._bindings.clear()


_global_registry: ProfileRegistry | None = None


def get_profile_registry() -> ProfileRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = ProfileRegistry()
    return _global_registry


_global_binding_registry: BindingRegistry | None = None


def get_binding_registry() -> BindingRegistry:
    global _global_binding_registry
    if _global_binding_registry is None:
        _global_binding_registry = BindingRegistry()
    return _global_binding_registry


def build_demo_bindings() -> BindingRegistry:
    registry = get_binding_registry()
    registry.reset()

    bindings = [
        ModelProviderBinding(
            binding_id="binding-demo-runtime",
            provider_id="local_demo",
            model_id="demo_local",
            display_name="Local Demo",
            status=BINDING_STATUS_DEMO_LOCAL,
            requires_api_key=False,
            requires_network=False,
            supports_tool_calls=True,
            supports_streaming=True,
            allowed_profile_ids=["profile-runtime-agent"],
        ),
        ModelProviderBinding(
            binding_id="binding-demo-frontend",
            provider_id="local_demo",
            model_id="demo_local",
            display_name="Local Demo",
            status=BINDING_STATUS_DEMO_LOCAL,
            requires_api_key=False,
            requires_network=False,
            supports_tool_calls=True,
            supports_streaming=True,
            allowed_profile_ids=["profile-frontend-agent"],
        ),
        ModelProviderBinding(
            binding_id="binding-demo-docs",
            provider_id="local_demo",
            model_id="demo_local",
            display_name="Local Demo",
            status=BINDING_STATUS_DEMO_LOCAL,
            requires_api_key=False,
            requires_network=False,
            supports_tool_calls=True,
            supports_streaming=True,
            allowed_profile_ids=["profile-docs-agent"],
        ),
        ModelProviderBinding(
            binding_id="binding-demo-tests",
            provider_id="local_demo",
            model_id="demo_local",
            display_name="Local Demo",
            status=BINDING_STATUS_DEMO_LOCAL,
            requires_api_key=False,
            requires_network=False,
            supports_tool_calls=True,
            supports_streaming=True,
            allowed_profile_ids=["profile-tests-agent"],
        ),
        ModelProviderBinding(
            binding_id="binding-demo-analytics",
            provider_id="local_demo",
            model_id="demo_local",
            display_name="Local Demo",
            status=BINDING_STATUS_DEMO_LOCAL,
            requires_api_key=False,
            requires_network=False,
            supports_tool_calls=True,
            supports_streaming=True,
            allowed_profile_ids=["profile-analytics-agent"],
        ),
        ModelProviderBinding(
            binding_id="binding-ralph-background",
            provider_id="ralph_internal",
            model_id="ralph_background",
            display_name="Ralph Background (internal)",
            status=BINDING_STATUS_DEMO_LOCAL,
            requires_api_key=False,
            requires_network=False,
            supports_tool_calls=False,
            supports_streaming=False,
            allowed_profile_ids=["profile-ralph-background"],
        ),
    ]

    for binding in bindings:
        registry.register(binding)

    return registry


def build_demo_profiles() -> ProfileRegistry:
    registry = get_profile_registry()
    registry.reset()

    profiles = [
        SubagentProfile(
            profile_id="profile-runtime-agent",
            display_name="Runtime Agent",
            profile_kind=PROFILE_KIND_STANDARD_SUBAGENT,
            role="ToolRuntime and AgentLoop boundary specialist",
            description="Tackles core runtime boundary problems within Ralph worktrees",
            allowed_capabilities=[
                "read_file",
                "grep",
                "bash_safe",
                "validate",
                "get_context",
            ],
            forbidden_capabilities=["merge", "push_remote", "mutate_live_workspace"],
            trust_tier=TrustTier.PATCH_PROPOSAL.value,
            can_mutate=True,
            max_concurrent_missions=2,
        ),
        SubagentProfile(
            profile_id="profile-frontend-agent",
            display_name="Frontend Agent",
            profile_kind=PROFILE_KIND_STANDARD_SUBAGENT,
            role="pywebview UI and widget specialist",
            description="Implements and polishes frontend widgets, JS, CSS",
            allowed_capabilities=[
                "read_file",
                "grep",
                "bash_safe",
                "validate",
                "write_file",
                "search_replace",
            ],
            forbidden_capabilities=["merge", "push_remote", "mutate_live_workspace"],
            trust_tier=TrustTier.PATCH_PROPOSAL.value,
            can_mutate=True,
            max_concurrent_missions=2,
        ),
        SubagentProfile(
            profile_id="profile-docs-agent",
            display_name="Docs Agent",
            profile_kind=PROFILE_KIND_STANDARD_SUBAGENT,
            role="Documentation and guides specialist",
            description="Updates README, demo docs, architecture docs, and rendered site",
            allowed_capabilities=["read_file", "grep", "write_file", "validate"],
            forbidden_capabilities=[
                "merge",
                "push_remote",
                "mutate_live_workspace",
                "bash_unsafe",
            ],
            trust_tier=TrustTier.SAFE_LOCAL.value,
            can_mutate=True,
            max_concurrent_missions=1,
        ),
        SubagentProfile(
            profile_id="profile-tests-agent",
            display_name="Tests Agent",
            profile_kind=PROFILE_KIND_STANDARD_SUBAGENT,
            role="Test coverage and validation specialist",
            description="Writes and maintains tests, runs validation suites",
            allowed_capabilities=[
                "read_file",
                "grep",
                "write_file",
                "search_replace",
                "validate",
                "bash_safe",
            ],
            forbidden_capabilities=["merge", "push_remote", "mutate_live_workspace"],
            trust_tier=TrustTier.SAFE_LOCAL.value,
            can_mutate=True,
            max_concurrent_missions=2,
        ),
        SubagentProfile(
            profile_id="profile-analytics-agent",
            display_name="Analytics Agent",
            profile_kind=PROFILE_KIND_STANDARD_SUBAGENT,
            role="Bash analytics and DuckDB specialist",
            description="Builds and hardens analytics projections, DuckDB queries",
            allowed_capabilities=[
                "read_file",
                "grep",
                "bash_safe",
                "validate",
                "duckdb_query",
            ],
            forbidden_capabilities=["merge", "push_remote", "mutate_live_workspace"],
            trust_tier=TrustTier.SAFE_LOCAL.value,
            can_mutate=False,
            max_concurrent_missions=1,
        ),
        SubagentProfile(
            profile_id="profile-ralph-background",
            display_name="Ralph",
            profile_kind=PROFILE_KIND_AUTONOMOUS_BACKGROUND,
            role="Autonomous background convergence worker",
            description="Observes all lane projections, fixes bounded convergence issues in Ralph-owned worktrees, reports completed work to orchestrator",
            allowed_capabilities=[
                "read_all_projections",
                "create_isolated_worktree",
                "edit_inside_ralph_worktree",
                "run_validators",
                "commit_to_ralph_branch",
                "seal_review_bundle",
                "write_ralph_report",
            ],
            forbidden_capabilities=[
                "merge",
                "push_remote",
                "mutate_live_workspace",
                "mutate_orchestrator_lane",
                "destructive_git",
                "external_network",
            ],
            trust_tier=TrustTier.SAFE_LOCAL.value,
            can_mutate=True,
            can_report_to_orchestrator=True,
            assignable=False,
            reports_to_orchestrator=True,
            max_concurrent_missions=0,
        ),
    ]

    for profile in profiles:
        registry.register(profile)

    return registry


def build_empty_assignment() -> MissionAssignment:
    return MissionAssignment()


__all__ = [
    "ASSIGNMENT_VERSION",
    "BINDING_STATUSES",
    "BINDING_VERSION",
    "MISSION_ASSIGNMENT_STATUSES",
    "PROFILE_KINDS",
    "PROFILE_KIND_AUTONOMOUS_BACKGROUND",
    "PROFILE_KIND_STANDARD_SUBAGENT",
    "PROFILE_TRUST_TIERS",
    "PROFILE_VERSION",
    "TRUST_TIER_OBSERVE",
    "TRUST_TIER_PATCH_PROPOSAL",
    "TRUST_TIER_SAFE_LOCAL",
    "BindingRegistry",
    "BindingStatus",
    "MissionAssignment",
    "ModelProviderBinding",
    "ProfileKind",
    "ProfileRegistry",
    "SubagentProfile",
    "TrustTier",
    "build_demo_bindings",
    "build_demo_profiles",
    "build_empty_assignment",
    "get_binding_registry",
    "get_profile_registry",
]
