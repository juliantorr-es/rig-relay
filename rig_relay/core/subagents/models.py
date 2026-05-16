"""SubagentRuntime contracts — mission, result, error, trace.

SubagentRuntime executes bounded missions without instantiating AgentLoop.
Only OrchestratorLoop may own the full turn loop.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Profile / trust ─────────────────────────────────────────────


class SubagentProfileKind(StrEnum):
    STANDARD = "standard"
    AUTONOMOUS_BACKGROUND = "autonomous_background"


class SubagentTrustTier(StrEnum):
    OBSERVE = "observe"
    PATCH_PROPOSAL = "patch_proposal"
    SAFE_LOCAL = "safe_local"
    WRITE_LOCAL = "write_local"


# ── Mission contract ────────────────────────────────────────────


class SubagentMission(BaseModel):
    """Input contract for a bounded subagent mission.

    Explicitly scoped: what may the subagent do, with what tools,
    under what budget, and with what expected outputs.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    mission_id: str = Field(default_factory=lambda: SubagentMission._make_id())
    parent_session_id: str = ""
    parent_turn_id: str | None = None
    parent_tool_call_id: str | None = None
    parent_trace_id: str | None = None

    task: str = ""
    agent_profile: str = "explore"
    profile_kind: str = SubagentProfileKind.STANDARD.value
    trust_tier: str = SubagentTrustTier.OBSERVE.value

    scope_allowed_paths: list[str] = Field(default_factory=list)
    scope_allow_write: bool = False
    scope_allow_bash: bool = False
    scope_dirty_file_policy: str = "preserve_existing"

    budget_max_turns: int = 10
    budget_max_seconds: float = 300.0
    budget_max_tool_calls: int = 20

    model: str | None = None
    provider: str | None = None
    thinking_enabled: bool | None = None
    timeout_seconds: float | None = None

    enabled_tools: list[str] = Field(default_factory=list)
    disabled_tools: list[str] = Field(default_factory=list)

    expected_outputs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def _make_id() -> str:
        import uuid

        return uuid.uuid4().hex[:12]


# ── Result contract ─────────────────────────────────────────────


class SubagentResult(BaseModel):
    """Output contract from a bounded subagent mission.

    Compact JSON-safe artifact. No raw message content, tool outputs,
    or privileged session data.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    mission_id: str = ""
    status: str = "unknown"
    summary: str = ""
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    turns_used: int = 0
    tool_calls_attempted: int = 0
    tool_calls_succeeded: int = 0
    tool_calls_failed: int = 0
    tool_calls_skipped: int = 0

    provider: str | None = None
    model: str | None = None

    started_at: str = ""
    completed_at: str = ""

    output_sha256: str | None = None
    child_session_id: str | None = None
    child_artifact_manifest_sha256: str | None = None
    trace_id: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Runtime error ───────────────────────────────────────────────


class SubagentRuntimeError(Exception):
    """Structured error from SubagentRuntime.

    Carries error kind and trace context for evidence consumers.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str = "unknown",
        mission_id: str = "",
        trace_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.mission_id = mission_id
        self.trace_id = trace_id


# ── Trace evidence ──────────────────────────────────────────────


class SubagentRuntimeTrace(BaseModel):
    """Trace payload emitted at mission start, end, error, or cancel.

    JSON-safe. No raw message content or tool outputs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: str = ""
    mission_id: str = ""
    parent_session_id: str = ""
    parent_turn_id: str | None = None
    parent_trace_id: str | None = None
    trace_id: str | None = None
    timestamp: str = ""
    status: str | None = None
    reason: str | None = None
    turns_used: int = 0
    tool_calls_attempted: int = 0
    duration_ms: float | None = None
