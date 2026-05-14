from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum, auto
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolDeterminismClass(StrEnum):
    DETERMINISTIC_PURE = auto()
    DETERMINISTIC_REPO_STATE = auto()
    DETERMINISTIC_ENV_SENSITIVE = auto()
    DETERMINISTIC_TIME_SENSITIVE = auto()
    NONDETERMINISTIC_PROVIDER = auto()
    NONDETERMINISTIC_EXTERNAL_IO = auto()
    UNKNOWN = auto()


class ToolMutationClass(StrEnum):
    READ_ONLY = auto()
    WRITES_WORKSPACE = auto()
    WRITES_EVIDENCE_ONLY = auto()
    WRITES_TEMP_ONLY = auto()
    MUTATES_GIT_STATE = auto()
    EXTERNAL_SIDE_EFFECT = auto()
    UNKNOWN = auto()


class ToolOutputKind(StrEnum):
    INLINE = auto()
    ARTIFACTED = auto()
    EMPTY = auto()
    ERROR = auto()
    MIXED = auto()
    UNKNOWN = auto()


class ToolDogfoodContract(BaseModel):
    """Structured contract for tool-use evidence during self-dogfood sessions."""

    model_config = ConfigDict(extra="allow")

    # available_now
    tool_name: str
    status: str  # success, failure, skipped
    tool_call_id: str | None = None
    session_id: str | None = None
    message_id: str | None = None

    # requires_instrumentation / requires_derivation
    input_sha256: str | None = None
    output_sha256: str | None = None
    output_kind: ToolOutputKind = ToolOutputKind.UNKNOWN
    determinism_class: ToolDeterminismClass = ToolDeterminismClass.UNKNOWN
    mutation_class: ToolMutationClass = ToolMutationClass.UNKNOWN

    # metadata
    agent_profile_name: str | None = None
    model: str | None = None
    duration_ms: float | None = None

    # findings
    warnings: list[str] = []
    determinism_notes: str | None = None


class ToolDeterminismSummary(BaseModel):
    session_id: str
    tool_calls: list[ToolDogfoodContract]
    coverage_stats: dict[str, Any] = {}
    warnings: list[str] = []


class ToolReasoningTrace(BaseModel):
    """Observable reasoning trace around a single tool call.

    Records what the model chose, what it received, and what followed —
    without capturing hidden chain-of-thought. All rationale fields are
    optional and should be left empty when the provider does not expose them.
    """

    schema_version: str = "rig.relay.artifact.tool_reasoning_trace.v1"
    artifact_kind: str = "tool_reasoning_trace"

    session_id: str
    message_id: str | None = None
    tool_call_id: str
    tool_name: str
    step_index: int = 0

    # Observable rationale (empty if provider does not expose)
    user_goal_summary: str = ""
    active_plan_summary: str = ""
    tool_selection_rationale_summary: str = ""

    # Input evidence
    normalized_input_sha256: str
    input_summary: str = ""

    # Output evidence
    tool_output_kind: ToolOutputKind = ToolOutputKind.UNKNOWN
    tool_output_sha256: str = ""
    tool_output_artifact_path: str | None = None

    # Observation / decision (populated after tool result)
    observation_summary: str = ""
    decision_after_observation: str = ""
    next_action_kind: str = "unknown"
    retry_of_tool_call_id: str | None = None

    # Latency + byte metrics
    latency_ms: float = 0.0
    input_bytes: int = 0
    output_bytes: int = 0
    inline_output_bytes: int = 0
    artifacted_output_bytes: int = 0
    estimated_prompt_pressure_bytes: int = 0
    truncated: bool = False

    # Classification
    determinism_class: str = "unknown"
    mutation_class: str = "unknown"

    # Findings
    warnings: list[str] = Field(default_factory=list)

    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
