"""Profile models — Pydantic models for provider-harness compatibility profiles.

Content-light by design: no raw API keys, secrets, file contents, or prompts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum, auto

from pydantic import BaseModel, ConfigDict, Field


class ProfileStatus(StrEnum):
    EXPERIMENTAL = auto()
    CANDIDATE = auto()
    VERIFIED = auto()
    DEPRECATED = auto()


class TaskRole(StrEnum):
    IMPLEMENTATION = auto()
    ARCHITECTURE_PLANNING = auto()
    CODE_REVIEW_ADVERSARIAL = auto()
    AUDIT_REVIEW = auto()
    UI_NATIVE_TASK = auto()
    RESTRICTED_SENSITIVE_INSPECTION = auto()


class ContextEnvelopeStrategy(StrEnum):
    RIG_GOVERNED = auto()
    CODEX_COMPATIBLE = auto()
    CLAUDE_COMPATIBLE = auto()
    COPILOT_COMPATIBLE = auto()


class InstructionRenderingStrategy(StrEnum):
    RIG_DEFAULT = auto()
    CODEX = auto()
    CLAUDE = auto()
    COPILOT = auto()


class ToolDialectStrategy(StrEnum):
    RIG_NATIVE = auto()
    OPENAI_FUNCTION_CALLING = auto()
    ANTHROPIC_TOOL_USE = auto()
    MODEL_DRIVEN = auto()


class ReasoningEffortPosture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    supports_effort_control: bool = False
    default_effort: str | None = None
    available_efforts: list[str] = Field(default_factory=list)
    adaptive_reasoning: bool = False
    uses_keyword_triggers: bool = False
    max_thinking_tokens: int | None = None
    effort_persists_across_sessions: bool = False


class CachingPosture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    caching_active: bool = False
    cache_mechanism: str = "none"
    cache_ttl_seconds: int = 0
    prefix_stable_content: str = ""
    suffix_dynamic_content: str = ""
    supports_extended_cache: bool = False
    cache_cost_discount_pct: float = 0.0


class WorkspaceSubagentPosture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    supports_subagents: bool = False
    subagent_context_isolation: bool = False
    max_parallel_subagents: int = 0
    subagent_model_selection: str = "same_as_parent"
    supports_worktrees: bool = False
    supports_background_agents: bool = False
    subagent_recursion_allowed: bool = False
    subagent_tool_scoping: bool = False


class CapabilityRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requires_tool_use: bool = True
    requires_streaming: bool = False
    requires_structured_output: bool = False
    requires_thinking: bool = False
    requires_vision: bool = False
    requires_embeddings: bool = False
    min_context_window: int = 8000
    min_output_tokens: int = 1024
    max_input_price_per_million: float = 0.0


class HarnessCompatibilityProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: str
    profile_version: str
    display_name: str
    description: str
    provider_families: list[str]
    model_patterns: list[str]
    supported_roles: list[TaskRole]
    required_capabilities: CapabilityRequirements = Field(
        default_factory=CapabilityRequirements
    )
    context_envelope_strategy: ContextEnvelopeStrategy = (
        ContextEnvelopeStrategy.RIG_GOVERNED
    )
    instruction_rendering_strategy: InstructionRenderingStrategy = (
        InstructionRenderingStrategy.RIG_DEFAULT
    )
    tool_dialect_strategy: ToolDialectStrategy = ToolDialectStrategy.RIG_NATIVE
    reasoning_effort_posture: ReasoningEffortPosture = Field(
        default_factory=ReasoningEffortPosture
    )
    caching_posture: CachingPosture = Field(default_factory=CachingPosture)
    workspace_subagent_posture: WorkspaceSubagentPosture = Field(
        default_factory=WorkspaceSubagentPosture
    )
    unsupported_claims: list[str] = Field(default_factory=list)
    evaluation_status: ProfileStatus = ProfileStatus.EXPERIMENTAL
    authority_rule: str = ""
    profile_digest: str = ""


class ProfileResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model_id: str
    task_role: TaskRole = TaskRole.IMPLEMENTATION
    prefer_profile_id: str | None = None
    model_capabilities: dict[str, object] | None = None


class ProfileResolutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_id: str
    provider: str
    model_id: str
    task_role: TaskRole
    selected_profile: HarnessCompatibilityProfile
    selected_reason: str
    confidence: str
    alternatives_considered: list[str] = Field(default_factory=list)
    alternatives_rejected_reasons: dict[str, str] = Field(default_factory=dict)
    is_user_override: bool = False
    override_source_profile_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
    resolved_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ProfileResolutionError(Exception):
    def __init__(
        self,
        message: str,
        provider: str,
        model_id: str,
        reasons: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model_id = model_id
        self.reasons = reasons or []


class ProfileEvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    task_role: TaskRole
    provider: str
    model_id: str
    test_fixture_sha256: str | None = None


class ProfileEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluation_id: str
    profile_id: str
    task_role: TaskRole
    provider: str
    model_id: str
    context_assembly_correct: bool | None = None
    tool_authority_preserved: bool | None = None
    deterministic_resolution: bool | None = None
    unsupported_capability_refused: bool | None = None
    receipt_reconstructable: bool | None = None
    warnings: list[str] = Field(default_factory=list)
    evaluated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
