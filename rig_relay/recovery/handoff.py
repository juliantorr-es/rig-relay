"""Lane B5 / D1 runtime integration handoff contract.

Defines the digest-bound interface between D0 recovery decisions
and B5 live runtime delivery. D1A builds this contract; D1 executes it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RecoveryHandoffReadOnly(BaseModel):
    """Handoff for a recovered read-only tool call."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.tool_recovery_runtime_handoff.v1"
    handoff_kind: str = "read_only"
    recovery_receipt_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    manifest_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    canonical_tool_name: str
    admission_decision: str = "auto_execute_read_only"
    payload_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    runtime_correlation_id: str = ""


class RecoveryHandoffValidation(BaseModel):
    """Handoff for a recovered validation tool call."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.tool_recovery_runtime_handoff.v1"
    handoff_kind: str = "validation"
    recovery_receipt_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    manifest_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    canonical_tool_name: str
    admission_decision: str = "auto_execute_validation"
    payload_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    admitted_validation_profile: str | None = None
    bounded_paths: list[str] = Field(default_factory=list)
    runtime_correlation_id: str = ""


class RecoveryHandoffMutationProposal(BaseModel):
    """Handoff for a recovered mutation — must become proposal-only.

    Hard invariant: no direct mutation execution.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.tool_recovery_runtime_handoff.v1"
    handoff_kind: str = "mutation_proposal_only"
    recovery_receipt_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    manifest_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    canonical_tool_name: str
    admission_decision: str = "proposal_only_mutation"
    payload_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    mutation_class: str = ""
    patch_proposal_required: bool = True
    runtime_correlation_id: str = ""


class RecoveryHandoffRefusal(BaseModel):
    """Handoff for a refused recovery — model-visible refusal outcome."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.tool_recovery_runtime_handoff.v1"
    handoff_kind: str = "refusal"
    recovery_receipt_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    manifest_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    refusal_code: str
    reason: str = ""
    runtime_correlation_id: str = ""


def build_read_only_handoff(
    receipt_sha256: str,
    manifest_digest: str,
    canonical_tool_name: str,
    payload_digest: str,
    correlation_id: str = "",
) -> RecoveryHandoffReadOnly:
    return RecoveryHandoffReadOnly(
        recovery_receipt_sha256=receipt_sha256,
        manifest_digest=manifest_digest,
        canonical_tool_name=canonical_tool_name,
        payload_digest=payload_digest,
        runtime_correlation_id=correlation_id,
    )


def build_validation_handoff(
    receipt_sha256: str,
    manifest_digest: str,
    canonical_tool_name: str,
    payload_digest: str,
    correlation_id: str = "",
) -> RecoveryHandoffValidation:
    return RecoveryHandoffValidation(
        recovery_receipt_sha256=receipt_sha256,
        manifest_digest=manifest_digest,
        canonical_tool_name=canonical_tool_name,
        payload_digest=payload_digest,
        runtime_correlation_id=correlation_id,
    )


def build_mutation_handoff(
    receipt_sha256: str,
    manifest_digest: str,
    canonical_tool_name: str,
    payload_digest: str,
    mutation_class: str,
    correlation_id: str = "",
) -> RecoveryHandoffMutationProposal:
    return RecoveryHandoffMutationProposal(
        recovery_receipt_sha256=receipt_sha256,
        manifest_digest=manifest_digest,
        canonical_tool_name=canonical_tool_name,
        payload_digest=payload_digest,
        mutation_class=mutation_class,
        runtime_correlation_id=correlation_id,
    )


def build_refusal_handoff(
    receipt_sha256: str,
    manifest_digest: str,
    refusal_code: str,
    reason: str = "",
    correlation_id: str = "",
) -> RecoveryHandoffRefusal:
    return RecoveryHandoffRefusal(
        recovery_receipt_sha256=receipt_sha256,
        manifest_digest=manifest_digest,
        refusal_code=refusal_code,
        reason=reason,
        runtime_correlation_id=correlation_id,
    )
