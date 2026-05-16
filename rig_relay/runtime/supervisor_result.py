"""Canonical terminal evidence for supervised subprocess execution."""

from __future__ import annotations

from enum import StrEnum
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict


class RuntimeSupervisorResultClassification(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    KILLED = "killed"
    CANCELLED = "cancelled"
    SPAWN_FAILED = "spawn_failed"
    CLEANUP_FAILED = "cleanup_failed"
    ERRORED = "errored"
    REFUSED = "refused"


class RuntimeSupervisorCommandDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executable: str
    argv_hash: str
    argc: int
    cwd_hash: str
    cwd_kind: str


class RuntimeSupervisorOutputDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class RuntimeSupervisorTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: float | None = None


class RuntimeSupervisorResourceUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exit_code: int | None = None
    signal: int | None = None
    timed_out: bool = False
    killed: bool = False
    cancelled: bool = False
    pid: int | None = None


class RuntimeSupervisorFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_kind: str
    reason: str | None = None
    cleanup_status: str | None = None


class RuntimeSupervisorCleanup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    reason: str | None = None


class RuntimeSupervisorEnvelopeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str | None = None
    parent_span_id: str | None = None
    span_id: str | None = None
    error: RuntimeSupervisorFailure | None = None
    cleanup: RuntimeSupervisorCleanup | None = None
    evidence: dict[str, str | None] | None = None


class RuntimeSupervisorResultEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.runtime_supervisor.result.v1"
    result_id: str
    trace_id: str | None = None
    parent_span_id: str | None = None
    span_id: str | None = None
    command: RuntimeSupervisorCommandDigest
    cwd: dict[str, str]
    state: str
    previous_state: str | None = None
    last_event: str | None = None
    classification: RuntimeSupervisorResultClassification
    resource_usage: RuntimeSupervisorResourceUsage
    output: RuntimeSupervisorOutputDigest
    timing: RuntimeSupervisorTiming
    error: RuntimeSupervisorFailure | None = None
    cleanup: RuntimeSupervisorCleanup | None = None
    state_projection: dict[str, Any] | None = None
    evidence: dict[str, str | None] | None = None


def _stable_result_id(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def build_runtime_supervisor_result_envelope(
    *,
    command: RuntimeSupervisorCommandDigest,
    cwd: dict[str, str],
    state_projection: dict[str, Any],
    classification: RuntimeSupervisorResultClassification | str,
    resource_usage: RuntimeSupervisorResourceUsage,
    output: RuntimeSupervisorOutputDigest,
    timing: RuntimeSupervisorTiming,
    context: RuntimeSupervisorEnvelopeContext | None = None,
) -> RuntimeSupervisorResultEnvelope:
    classification_value = RuntimeSupervisorResultClassification(str(classification))
    projection = dict(state_projection)
    context = context or RuntimeSupervisorEnvelopeContext()
    payload = {
        "trace_id": context.trace_id,
        "parent_span_id": context.parent_span_id,
        "span_id": context.span_id,
        "command": command.model_dump(mode="json"),
        "cwd": cwd,
        "state_projection": projection,
        "classification": classification_value.value,
        "resource_usage": resource_usage.model_dump(mode="json"),
        "output": output.model_dump(mode="json"),
        "timing": timing.model_dump(mode="json"),
        "error": context.error.model_dump(mode="json") if context.error else None,
        "cleanup": context.cleanup.model_dump(mode="json") if context.cleanup else None,
        "evidence": context.evidence,
    }
    result_id = _stable_result_id(payload)
    return RuntimeSupervisorResultEnvelope(
        result_id=result_id,
        trace_id=context.trace_id,
        parent_span_id=context.parent_span_id,
        span_id=context.span_id,
        command=command,
        cwd=cwd,
        state=str(projection.get("current_state", "")),
        previous_state=projection.get("previous_state"),
        last_event=projection.get("last_event"),
        classification=classification_value,
        resource_usage=resource_usage,
        output=output,
        timing=timing,
        error=context.error,
        cleanup=context.cleanup,
        state_projection=projection,
        evidence=context.evidence,
    )


__all__ = [
    "RuntimeSupervisorCleanup",
    "RuntimeSupervisorCommandDigest",
    "RuntimeSupervisorEnvelopeContext",
    "RuntimeSupervisorFailure",
    "RuntimeSupervisorOutputDigest",
    "RuntimeSupervisorResourceUsage",
    "RuntimeSupervisorResultClassification",
    "RuntimeSupervisorResultEnvelope",
    "RuntimeSupervisorTiming",
    "build_runtime_supervisor_result_envelope",
]
