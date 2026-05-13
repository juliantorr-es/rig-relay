from __future__ import annotations

from enum import StrEnum, auto

from pydantic import BaseModel, ConfigDict


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
    warnings: list[str] = []
