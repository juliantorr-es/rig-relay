"""Canonical Pydantic models for the Deterministic Tool Intent Recovery Corridor.

D0 pure-substrate models only. No live runtime integration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum, auto
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RecoveryAdmissionTier(StrEnum):
    """Risk-tiered admission classification for recovered tool intents."""

    READ_ONLY_RECOVERABLE = auto()
    VALIDATION_RECOVERABLE = auto()
    MUTATION_PROPOSAL_ONLY = auto()
    EXTERNAL_SIDE_EFFECT_REFUSE = auto()
    RAW_SHELL_REFUSE = auto()
    UNSUPPORTED_REFUSE = auto()


class RecoveryAdmissionDecision(StrEnum):
    """Canonical admission decision for a recovered intent."""

    AUTO_EXECUTE_READ_ONLY = auto()
    AUTO_EXECUTE_VALIDATION = auto()
    PROPOSAL_ONLY_MUTATION = auto()
    REQUIRE_REMOTE_AUTHORIZATION = auto()
    REFUSE_RAW_SHELL = auto()
    REFUSE_AMBIGUOUS = auto()
    REFUSE_UNSUPPORTED = auto()


class RecoveryRefusalCode(StrEnum):
    """Recovery-layer refusal vocabulary. D0 only — not runtime refusal."""

    UNSUPPORTED_WRAPPER = auto()
    MALFORMED_INLINE_SYNTAX = auto()
    UNKNOWN_ALIAS = auto()
    AMBIGUOUS_ALIAS = auto()
    CANONICAL_TOOL_NOT_ADMITTED = auto()
    FORBIDDEN_SHELL_SURFACE = auto()
    UNSUPPORTED_PAYLOAD_KEY_ALIAS = auto()
    PAYLOAD_VALIDATION_FAILED = auto()
    MUTATION_CONTENT_MISSING = auto()
    EXTERNAL_SIDE_EFFECT_NOT_RECOVERABLE = auto()
    UNSUPPORTED_RECOVERY_FORM = auto()


class RecoveryNormalizationRule(StrEnum):
    """Stable identifiers for normalization rules applied during recovery."""

    UNWRAP_FUNCTION_OBJECT = auto()
    MAP_TOOL_TO_NAME = auto()
    MAP_ARGS_TO_ARGUMENTS = auto()
    MAP_PARAMETERS_TO_ARGUMENTS = auto()
    UNPACK_FUNCTION_DOTTED_KEYS = auto()
    PARSE_INLINE_CALL_FORM = auto()
    APPLY_EXPLICIT_ALIAS = auto()
    VALIDATE_PAYLOAD_SCHEMA = auto()


class AdmittedToolEntry(BaseModel):
    """One tool entry in the canonical tool-surface manifest."""

    model_config = ConfigDict(extra="forbid")

    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    mutation_class: str
    determinism_class: str
    args_schema_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    arg_field_names: list[str] = Field(default_factory=list)
    recovery_admission_tier: RecoveryAdmissionTier


class CanonicalToolSurfaceManifest(BaseModel):
    """Canonical, content-light manifest of admitted tools for recovery.

    Generated from the real ToolManager.available_tools surface.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.tool_surface_manifest.v1", frozen=True
    )
    manifest_id: str
    generated_at: str
    admitted_tools: list[AdmittedToolEntry]
    manifest_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class RecoveryIntent(BaseModel):
    """Normalized recovered tool intent — canonical tool name + validated payload."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    canonical_tool_name: str
    normalized_args: dict[str, Any]
    payload_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    call_id: str = ""
    rules_applied: list[str] = Field(default_factory=list)
    manifest_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    mutation_class: str | None = None
    determinism_class: str | None = None


class RecoveryRefusal(BaseModel):
    """Typed refusal — no raw model output."""

    model_config = ConfigDict(extra="forbid")

    refusal_code: RecoveryRefusalCode
    reason: str
    candidate_count: int
    manifest_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    original_emission_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    rules_attempted: list[str] = Field(default_factory=list)


class RecoveryTransducerResult(BaseModel):
    """Union-style result from the malformed-call transducer."""

    model_config = ConfigDict(extra="forbid")

    recovered_intent: RecoveryIntent | None = None
    refusal: RecoveryRefusal | None = None

    @property
    def is_recovered(self) -> bool:
        return self.recovered_intent is not None

    @property
    def is_refused(self) -> bool:
        return self.refusal is not None


class RecoveryAdmissionResult(BaseModel):
    """Result of applying the RecoveryAdmissionPolicy."""

    model_config = ConfigDict(extra="forbid")

    admission_decision: RecoveryAdmissionDecision
    canonical_tool_name: str | None = None
    mutation_class: str | None = None
    proposal_only: bool = False
    refused_reason: str | None = None


class RawRecoveryInput(BaseModel):
    """Input envelope for the transducer. Carries raw emission as hash only."""

    model_config = ConfigDict(extra="forbid")

    raw_emission: dict[str, Any] | str
    emission_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    call_id: str = ""


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()
