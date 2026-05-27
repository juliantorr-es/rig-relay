"""Built-in harness compatibility profile registry.

Defines the canonical set of provider-harness compatibility profiles
that the resolver uses to match provider/model/role combinations.
"""

from __future__ import annotations

import hashlib

from rig_relay.profiles.models import (
    CachingPosture,
    CapabilityRequirements,
    ContextEnvelopeStrategy,
    HarnessCompatibilityProfile,
    InstructionRenderingStrategy,
    ProfileStatus,
    ReasoningEffortPosture,
    TaskRole,
    ToolDialectStrategy,
    WorkspaceSubagentPosture,
)


def _compute_digest(profile: HarnessCompatibilityProfile) -> str:
    """Compute SHA256 digest of a profile's canonical serialization."""
    payload = profile.model_dump_json(
        exclude={"profile_digest"}, exclude_defaults=False
    )
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


def _build_rig_native_governed() -> HarnessCompatibilityProfile:
    profile = HarnessCompatibilityProfile(
        profile_id="rig.native.governed.v1",
        profile_version="1.0.0",
        display_name="Rig Native Governed",
        description=(
            "Rig Relay's own governed mode with full context packet, "
            "receipt-backed evidence, mission envelope, dirty file guard, "
            "and subsys map. Exposes all Rig capabilities natively."
        ),
        provider_families=[
            "openai",
            "anthropic",
            "google",
            "openrouter",
            "deepseek",
            "local_inference",
        ],
        model_patterns=[".*"],
        supported_roles=[
            TaskRole.IMPLEMENTATION,
            TaskRole.ARCHITECTURE_PLANNING,
            TaskRole.CODE_REVIEW_ADVERSARIAL,
            TaskRole.AUDIT_REVIEW,
            TaskRole.UI_NATIVE_TASK,
            TaskRole.RESTRICTED_SENSITIVE_INSPECTION,
        ],
        required_capabilities=CapabilityRequirements(
            requires_tool_use=True,
            requires_streaming=False,
            requires_structured_output=False,
            requires_thinking=False,
            requires_vision=False,
            requires_embeddings=False,
            min_context_window=8000,
            min_output_tokens=1024,
        ),
        context_envelope_strategy=ContextEnvelopeStrategy.RIG_GOVERNED,
        instruction_rendering_strategy=InstructionRenderingStrategy.RIG_DEFAULT,
        tool_dialect_strategy=ToolDialectStrategy.RIG_NATIVE,
        reasoning_effort_posture=ReasoningEffortPosture(
            supports_effort_control=True,
            default_effort="medium",
            available_efforts=["low", "medium", "high"],
        ),
        caching_posture=CachingPosture(),
        workspace_subagent_posture=WorkspaceSubagentPosture(
            supports_subagents=True,
            subagent_context_isolation=True,
            max_parallel_subagents=4,
            subagent_model_selection="same_as_parent",
        ),
        unsupported_claims=[],
        evaluation_status=ProfileStatus.CANDIDATE,
        authority_rule=(
            "May shape context packaging, instruction rendering, tool vocabulary, "
            "task-role/model recommendation, reasoning/effort controls, subagent/workspace posture, "
            "prompt caching layout, observation/result formatting. Must never authorize file mutation, "
            "shell execution, secret persistence/transmission, evidence omission, publication, "
            "workspace reset/retirement, verified/live UI claims."
        ),
    )
    return profile.model_copy(update={"profile_digest": _compute_digest(profile)})


def _build_openai_codex_compatible_engineering() -> HarnessCompatibilityProfile:
    profile = HarnessCompatibilityProfile(
        profile_id="openai.codex.compatible_engineering.v1",
        profile_version="1.0.0",
        display_name="OpenAI Codex Compatible Engineering",
        description=(
            "OpenAI Codex-compatible profile for implementation and architecture planning. "
            "Uses AGENTS.md discovery chain with nested precedence, git rules, "
            "citation format instructions, and standard OpenAI function calling."
        ),
        provider_families=["openai"],
        model_patterns=["gpt-.*", "o1-.*", "o3-.*", "o4-.*", "codex-.*"],
        supported_roles=[TaskRole.IMPLEMENTATION, TaskRole.ARCHITECTURE_PLANNING],
        required_capabilities=CapabilityRequirements(
            requires_tool_use=True,
            requires_streaming=False,
            requires_structured_output=False,
            requires_thinking=False,
            requires_vision=False,
            requires_embeddings=False,
            min_context_window=128000,
        ),
        context_envelope_strategy=ContextEnvelopeStrategy.CODEX_COMPATIBLE,
        instruction_rendering_strategy=InstructionRenderingStrategy.CODEX,
        tool_dialect_strategy=ToolDialectStrategy.OPENAI_FUNCTION_CALLING,
        reasoning_effort_posture=ReasoningEffortPosture(
            supports_effort_control=True,
            default_effort="medium",
            available_efforts=["none", "low", "medium", "high", "xhigh"],
        ),
        caching_posture=CachingPosture(
            caching_active=True,
            cache_mechanism="automatic_prefix",
            cache_ttl_seconds=300,
            prefix_stable_content="System message + AGENTS.md chain",
            suffix_dynamic_content="User task + repo context",
            supports_extended_cache=True,
            cache_cost_discount_pct=75.0,
        ),
        workspace_subagent_posture=WorkspaceSubagentPosture(
            supports_subagents=True,
            subagent_context_isolation=True,
            max_parallel_subagents=4,
        ),
        unsupported_claims=[
            "Does not replicate Codex Web sandbox execution environment",
            "Does not replicate Codex Cloud model routing",
            "Citation format is advisory, not enforced by Rig",
            "Codex Web-specific multi-agent task dispatch is not replicated",
            "Codex model training specifics are proprietary and not replicated",
        ],
        evaluation_status=ProfileStatus.EXPERIMENTAL,
        authority_rule=(
            "May shape context packaging, instruction rendering, tool vocabulary, "
            "task-role/model recommendation, reasoning/effort controls, subagent/workspace posture, "
            "prompt caching layout, observation/result formatting. Must never authorize file mutation, "
            "shell execution, secret persistence/transmission, evidence omission, publication, "
            "workspace reset/retirement, verified/live UI claims."
        ),
    )
    return profile.model_copy(update={"profile_digest": _compute_digest(profile)})


def _build_anthropic_claude_code_compatible_execution() -> HarnessCompatibilityProfile:
    profile = HarnessCompatibilityProfile(
        profile_id="anthropic.claude_code.compatible_execution.v1",
        profile_version="1.0.0",
        display_name="Anthropic Claude Code Compatible Execution",
        description=(
            "Anthropic Claude Code-compatible profile for implementation and architecture planning. "
            "Uses CLAUDE.md 4-layer load order (managed→user→project→local), "
            "user-message delivery convention, Anthropic tool_use blocks, "
            "and adaptive reasoning with keyword triggers."
        ),
        provider_families=["anthropic"],
        model_patterns=["claude-.*"],
        supported_roles=[TaskRole.IMPLEMENTATION, TaskRole.ARCHITECTURE_PLANNING],
        required_capabilities=CapabilityRequirements(
            requires_tool_use=True,
            requires_streaming=False,
            requires_structured_output=False,
            requires_thinking=False,
            requires_vision=False,
            requires_embeddings=False,
            min_context_window=100000,
        ),
        context_envelope_strategy=ContextEnvelopeStrategy.CLAUDE_COMPATIBLE,
        instruction_rendering_strategy=InstructionRenderingStrategy.CLAUDE,
        tool_dialect_strategy=ToolDialectStrategy.ANTHROPIC_TOOL_USE,
        reasoning_effort_posture=ReasoningEffortPosture(
            supports_effort_control=True,
            default_effort="high",
            available_efforts=["low", "medium", "high", "xhigh", "max"],
            adaptive_reasoning=True,
            uses_keyword_triggers=True,
        ),
        caching_posture=CachingPosture(
            caching_active=True,
            cache_mechanism="automatic_prefix",
            cache_ttl_seconds=300,
            prefix_stable_content="System prompt + CLAUDE.md",
            suffix_dynamic_content="Conversation",
            supports_extended_cache=True,
        ),
        workspace_subagent_posture=WorkspaceSubagentPosture(
            supports_subagents=True,
            subagent_context_isolation=True,
            max_parallel_subagents=4,
            subagent_model_selection="auto_select",
        ),
        unsupported_claims=[
            "Does not replicate Claude Code's managed policy layer",
            "Does not replicate Claude Code's Opus→Sonnet automatic plan-mode switching",
            "Does not replicate Claude Code's auto-memory (MEMORY.md)",
            "Does not replicate Claude Code's experimental agent teams",
            "Adaptive reasoning is model-dependent, not profile-guaranteed",
        ],
        evaluation_status=ProfileStatus.EXPERIMENTAL,
        authority_rule=(
            "May shape context packaging, instruction rendering, tool vocabulary, "
            "task-role/model recommendation, reasoning/effort controls, subagent/workspace posture, "
            "prompt caching layout, observation/result formatting. Must never authorize file mutation, "
            "shell execution, secret persistence/transmission, evidence omission, publication, "
            "workspace reset/retirement, verified/live UI claims."
        ),
    )
    return profile.model_copy(update={"profile_digest": _compute_digest(profile)})


def _build_anthropic_claude_code_compatible_audit() -> HarnessCompatibilityProfile:
    profile = HarnessCompatibilityProfile(
        profile_id="anthropic.claude_code.compatible_audit.v1",
        profile_version="1.0.0",
        display_name="Anthropic Claude Code Compatible Audit",
        description=(
            "Anthropic Claude Code-compatible profile for code review and audit. "
            "Tuned for contract compliance and evidence inspection with deep reasoning. "
            "Uses CLAUDE.md 4-layer load order and Anthropic tool_use blocks "
            "with read-only emphasis (all Rig authorities preserved)."
        ),
        provider_families=["anthropic"],
        model_patterns=["claude-.*"],
        supported_roles=[TaskRole.CODE_REVIEW_ADVERSARIAL, TaskRole.AUDIT_REVIEW],
        required_capabilities=CapabilityRequirements(
            requires_tool_use=True,
            requires_streaming=False,
            requires_structured_output=False,
            requires_thinking=False,
            requires_vision=False,
            requires_embeddings=False,
            min_context_window=100000,
        ),
        context_envelope_strategy=ContextEnvelopeStrategy.CLAUDE_COMPATIBLE,
        instruction_rendering_strategy=InstructionRenderingStrategy.CLAUDE,
        tool_dialect_strategy=ToolDialectStrategy.ANTHROPIC_TOOL_USE,
        reasoning_effort_posture=ReasoningEffortPosture(
            supports_effort_control=True,
            default_effort="xhigh",
            available_efforts=["low", "medium", "high", "xhigh", "max"],
            adaptive_reasoning=True,
            uses_keyword_triggers=True,
        ),
        caching_posture=CachingPosture(
            caching_active=True,
            cache_mechanism="automatic_prefix",
            cache_ttl_seconds=300,
            prefix_stable_content="System prompt + CLAUDE.md",
            suffix_dynamic_content="Conversation",
            supports_extended_cache=True,
        ),
        workspace_subagent_posture=WorkspaceSubagentPosture(
            supports_subagents=True,
            subagent_context_isolation=True,
            max_parallel_subagents=4,
            subagent_model_selection="auto_select",
        ),
        unsupported_claims=[
            "Does not replicate Claude Code's managed policy layer",
            "Does not replicate Claude Code's Opus→Sonnet automatic plan-mode switching",
            "Does not replicate Claude Code's auto-memory (MEMORY.md)",
            "Does not replicate Claude Code's experimental agent teams",
            "Does not replicate Claude Code's Output Style system",
            "Adaptive reasoning is model-dependent, not profile-guaranteed",
        ],
        evaluation_status=ProfileStatus.EXPERIMENTAL,
        authority_rule=(
            "May shape context packaging, instruction rendering, tool vocabulary, "
            "task-role/model recommendation, reasoning/effort controls, subagent/workspace posture, "
            "prompt caching layout, observation/result formatting. Must never authorize file mutation, "
            "shell execution, secret persistence/transmission, evidence omission, publication, "
            "workspace reset/retirement, verified/live UI claims."
        ),
    )
    return profile.model_copy(update={"profile_digest": _compute_digest(profile)})


def _build_github_copilot_fleet_compatible_orchestration() -> (
    HarnessCompatibilityProfile
):
    profile = HarnessCompatibilityProfile(
        profile_id="github.copilot.fleet.compatible_orchestration.v1",
        profile_version="1.0.0",
        display_name="GitHub Copilot Fleet Compatible Orchestration",
        description=(
            "GitHub Copilot-compatible profile for architecture planning and implementation "
            "with fleet orchestration. Uses multi-layer instruction discovery "
            "(AGENTS.md + .github/copilot-instructions.md + path-specific patterns), "
            "built-in agent profile descriptions, and OpenAI-style function calling."
        ),
        provider_families=["openai", "anthropic"],
        model_patterns=["gpt-.*", "claude-.*"],
        supported_roles=[TaskRole.ARCHITECTURE_PLANNING, TaskRole.IMPLEMENTATION],
        required_capabilities=CapabilityRequirements(
            requires_tool_use=True,
            requires_streaming=False,
            requires_structured_output=False,
            requires_thinking=False,
            requires_vision=False,
            requires_embeddings=False,
            min_context_window=128000,
        ),
        context_envelope_strategy=ContextEnvelopeStrategy.COPILOT_COMPATIBLE,
        instruction_rendering_strategy=InstructionRenderingStrategy.COPILOT,
        tool_dialect_strategy=ToolDialectStrategy.OPENAI_FUNCTION_CALLING,
        reasoning_effort_posture=ReasoningEffortPosture(
            supports_effort_control=True,
            default_effort="medium",
            available_efforts=["low", "medium", "high"],
        ),
        caching_posture=CachingPosture(
            caching_active=True, cache_mechanism="automatic_prefix"
        ),
        workspace_subagent_posture=WorkspaceSubagentPosture(
            supports_subagents=True,
            subagent_context_isolation=True,
            max_parallel_subagents=4,
            subagent_model_selection="auto_select",
            supports_worktrees=True,
            subagent_tool_scoping=True,
        ),
        unsupported_claims=[
            "Does not replicate Copilot's cloud agent or Copilot App",
            "Does not replicate Copilot's auto-compaction at 80%",
            "Does not replicate Copilot's /chronicle insights",
            "Does not replicate Copilot's auto model selection with health routing",
            "Does not replicate Copilot's SQLite session store",
            "Fleet/parallelism is Rig-governed, not Copilot's internal /fleet dispatcher",
        ],
        evaluation_status=ProfileStatus.EXPERIMENTAL,
        authority_rule=(
            "May shape context packaging, instruction rendering, tool vocabulary, "
            "task-role/model recommendation, reasoning/effort controls, subagent/workspace posture, "
            "prompt caching layout, observation/result formatting. Must never authorize file mutation, "
            "shell execution, secret persistence/transmission, evidence omission, publication, "
            "workspace reset/retirement, verified/live UI claims."
        ),
    )
    return profile.model_copy(update={"profile_digest": _compute_digest(profile)})


BUILTIN_PROFILES: tuple[HarnessCompatibilityProfile, ...] = tuple([
    _build_rig_native_governed(),
    _build_openai_codex_compatible_engineering(),
    _build_anthropic_claude_code_compatible_execution(),
    _build_anthropic_claude_code_compatible_audit(),
    _build_github_copilot_fleet_compatible_orchestration(),
])
