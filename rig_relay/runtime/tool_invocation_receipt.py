"""RuntimeToolInvocationReceipt — content-light adapter-level receipt for tool invocations.

Bridges RuntimeToolExecutionResult → tool receipt → ReceiptEnvelope.
Not a tool receipt (those are tool-specific, e.g. ValidateReceipt).
Not a ReceiptEnvelope (those have actor/subject/decision/evidence wrappers).

Content-light: no raw file contents, stdout, stderr, diffs, snippets,
or secrets. Only linkage fields, hashes, timing, and statuses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from rig_relay.runtime.tool_invocation_execution import RuntimeToolExecutionResult

# ── Constants ──────────────────────────────────────────────────────────

_SCHEMA_VERSION = "rig.relay.runtime_tool_invocation_receipt.v1"


class GitSummary(BaseModel):
    """Schema-governed Git metadata projection for git/checkpoint tools."""

    model_config = ConfigDict(extra="forbid")

    branch: str | None = None
    head: str | None = None
    dirty_files_count: int | None = None
    changed_files_count: int | None = None
    changed_paths: list[str] = Field(default_factory=list)
    truncation_triggered: bool = False
    redaction_triggered: bool = False
    warnings: list[str] = Field(default_factory=list)
    base_identity: str | None = None
    head_identity: str | None = None
    commit_identity: str | None = None
    checkpoint_receipt_sha256: str | None = None
    bounded_stdout: str | None = None


# ── Receipt model ─────────────────────────────────────────────────────


class RuntimeToolInvocationReceipt(BaseModel):
    """Content-light adapter-level receipt for a tool invocation.

    Links the RuntimeToolExecutionResult to the tool receipt and optionally
    to the ReceiptEnvelope and AuditEvent. Created by the adapter execution
    layer after a tool runs.

    Content-light: contains no raw file contents, stdout, stderr, diffs,
    snippets, or secrets. Only IDs, statuses, hashes, timing, and paths.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION
    invocation_id: str
    intent_id: str
    tool_name: str
    adapter_status: str
    tool_status: str | None = None
    tool_error_kind: str | None = None
    tool_receipt_kind: str | None = None
    tool_receipt_schema_version: str | None = None
    receipt_sha256: str | None = None
    suggested_next_action: str | None = None
    retryable: bool | None = None
    supervisor_result_envelope_id: str | None = None
    supervisor_result_envelope_sha256: str | None = None
    supervisor_result_classification: str | None = None
    envelope_id: str | None = None
    audit_event_id: str | None = None
    changed_paths: list[str] = Field(default_factory=list)
    duration_ms: float | None = None
    created_at: str = ""
    warnings: list[str] = Field(default_factory=list)
    git_summary: GitSummary | None = None


# ── Builder ───────────────────────────────────────────────────────────


def build_runtime_tool_invocation_receipt(
    result: RuntimeToolExecutionResult, *, created_at: str | None = None
) -> RuntimeToolInvocationReceipt:
    """Build a RuntimeToolInvocationReceipt from an execution result.

    Copies content-light fields from the execution result. Does not read
    files, fetch raw tool receipts, or persist anything.

    Args:
        result: The RuntimeToolExecutionResult to build from.
        created_at: Optional ISO 8601 timestamp. Auto-generated if omitted.

    Returns:
        A RuntimeToolInvocationReceipt with copied content-light fields.
    """
    stamp = created_at or datetime.now(UTC).isoformat()

    return RuntimeToolInvocationReceipt(
        schema_version=_SCHEMA_VERSION,
        invocation_id=result.invocation_id or result.intent_id,
        intent_id=result.intent_id,
        tool_name=result.tool_name,
        adapter_status=result.status.value,
        tool_status=result.tool_status,
        tool_error_kind=result.tool_error_kind or result.error_kind,
        tool_receipt_kind=result.tool_receipt_kind,
        tool_receipt_schema_version=result.tool_receipt_schema_version,
        receipt_sha256=result.receipt_sha256,
        suggested_next_action=getattr(result, "suggested_next_action", None),
        retryable=getattr(result, "retryable", None),
        supervisor_result_envelope_id=getattr(
            result, "supervisor_result_envelope_id", None
        ),
        supervisor_result_envelope_sha256=getattr(
            result, "supervisor_result_envelope_sha256", None
        ),
        supervisor_result_classification=getattr(
            result, "supervisor_result_classification", None
        ),
        envelope_id=result.receipt_envelope_id,
        audit_event_id=result.audit_event_id,
        changed_paths=list(result.changed_paths),
        duration_ms=result.duration_ms,
        created_at=stamp,
        warnings=list(result.warnings),
        git_summary=result.git_summary,
    )


__all__ = [
    "GitSummary",
    "RuntimeToolInvocationReceipt",
    "build_runtime_tool_invocation_receipt",
]
