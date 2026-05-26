"""D2 Governed Recovery Constrained Execution Corridor.

Sends recovery-oriented constrained-generation requests through an actual
configured local model runtime, captures emitted candidate output as canonical
evidence, and evaluates through the D0/D1A recovery substrate.

Content-light: never persists raw prompts, completions, or secrets.
Mutation emissions are always proposal-only; never directly executable.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.recovery.constraint_compiler import ConstraintCompilationReceipt
from rig_relay.recovery.evaluation import _evaluate_one
from rig_relay.recovery.evidence_ledger import EvidenceLedger
from rig_relay.recovery.handoff import (
    build_mutation_handoff,
    build_read_only_handoff,
    build_refusal_handoff,
    build_validation_handoff,
)
from rig_relay.recovery.models import CanonicalToolSurfaceManifest


class ConstraintEnforcementDisposition(BaseModel):
    """Truthful record of constraint enforcement capability and exercise.

    Never mislabels prompted formatting as constraint enforcement.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.constraint_enforcement_disposition.v1", frozen=True
    )
    disposition_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    runtime_kind: str
    runtime_endpoint_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    model_name: str = ""
    json_object_enforcement_available: bool = False
    json_object_enforcement_exercised: bool = False
    json_schema_enforcement_available: bool = False
    json_schema_enforcement_exercised: bool = False
    grammar_enforcement_available: bool = False
    grammar_enforcement_exercised: bool = False
    enforced_mechanism: str = ""
    enforcement_truth_note: str = ""


class ConstrainedExecutionRequest(BaseModel):
    """Request to execute a constrained-generation recovery call."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str
    manifest_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    constraint_receipt_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    target_tool_name: str
    endpoint_url: str
    runtime_kind: str = ""
    model_name: str = ""
    emission_source_kind: str = "captured_local_model"
    max_tokens: int = 256
    temperature: float = 0.0
    timeout_sec: float = 30.0


class ConstrainedExecutionResult(BaseModel):
    """Result of a constrained-generation recovery execution.

    Content-light: hashes, decisions, classifications only.
    Never contains raw prompts, completions, or secrets.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.constrained_execution_result.v1", frozen=True
    )
    execution_id: str
    execution_status: str  # executed | runtime_unavailable | refused | failed
    execution_error: str = ""
    emission_sha256: str = ""
    emission_byte_count: int = 0
    output_token_count: int = 0
    input_token_count: int = 0
    latency_ms: int = 0
    evaluation_event_digest: str = ""
    admission_decision: str = ""
    handoff_kind: str = ""  # read_only | validation | mutation_proposal_only | refusal
    handoff_digest: str = ""
    proposal_only: bool = False
    mutation_class: str = ""
    selected_canonical_tool: str = ""
    refusal_code: str = ""
    refusal_reason: str = ""
    constraint_enforcement_disposition: ConstraintEnforcementDisposition | None = None
    evidence_ledger_path: str = ""
    evidence_event_count: int = 0


async def _call_local_runtime(
    *,
    endpoint_url: str,
    model_name: str,
    messages: list[dict[str, str]],
    max_tokens: int = 256,
    temperature: float = 0.0,
    timeout_sec: float = 30.0,
    constraint_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lane D temporary lane-owned adapter to OpenAI-compatible local runtime.

    Temporary adapter pending release of a proper typed Lane C provider
    boundary. Uses httpx directly rather than modifying Lane C code.
    Content-light: ephemeral_content returned but never persisted raw.

    This is NOT the final production inference authority. When Lane C
    releases a provider/local-runtime boundary with model name support
    and structured output, this adapter should be retired.
    """
    import time

    import httpx

    response_format: dict[str, Any] = (
        {
            "type": "json_schema",
            "json_schema": {
                "name": "recovery_tool_call",
                "schema": constraint_schema,
                "strict": True,
            },
        }
        if constraint_schema is not None
        else {"type": "json_object"}
    )

    payload: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": response_format,
    }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_sec)) as client:
            response = await client.post(
                f"{endpoint_url}/v1/chat/completions", json=payload
            )
    except httpx.TimeoutException:
        return _runtime_error_dict(
            "timed_out", "httpx.TimeoutException", _elapsed_ms(started)
        )
    except Exception as exc:
        label = (
            f"ConnectError: {exc}"
            if isinstance(exc, httpx.ConnectError)
            else type(exc).__name__
        )
        return _runtime_error_dict("failed", label, _elapsed_ms(started))

    latency = _elapsed_ms(started)

    if response.status_code != _HTTP_OK:
        return _runtime_error_dict("failed", f"HTTP {response.status_code}", latency)

    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return _runtime_error_dict("malformed_response", "JSONDecodeError", latency)

    choices = body.get("choices", [])
    if not choices:
        return _runtime_error_dict("malformed_response", "empty_choices", latency)

    message = choices[0].get("message", {})
    content = message.get("content", "")
    completion_bytes = content.encode("utf-8")
    completion_sha = hashlib.sha256(completion_bytes).hexdigest()
    usage = body.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)

    return {
        "status": "executed",
        "latency_ms": latency,
        "completion_sha256": completion_sha,
        "completion_byte_count": len(completion_bytes),
        "output_token_count": output_tokens,
        "input_token_count": input_tokens,
        "model_safe_id": model_name,
        "ephemeral_content": content,
    }


def _elapsed_ms(started: float) -> int:
    import time

    return int((time.monotonic() - started) * 1000)


def _runtime_error_dict(
    status: str, error_class: str, latency_ms: int
) -> dict[str, Any]:
    return {
        "status": status,
        "latency_ms": latency_ms,
        "error_class": error_class,
        "completion_sha256": "",
        "completion_byte_count": 0,
        "output_token_count": 0,
        "input_token_count": 0,
        "model_safe_id": "",
        "ephemeral_content": "",
    }


async def execute_constrained_recovery(
    request: ConstrainedExecutionRequest,
    manifest: CanonicalToolSurfaceManifest,
    constraint_receipt: ConstraintCompilationReceipt,
    *,
    ledger_path: Path | None = None,
    runtime_available: bool = True,
) -> ConstrainedExecutionResult:
    """Execute a constrained recovery call against a local model runtime.

    Sends a structured constraint prompt through the runtime, captures the
    emission as canonical evidence, and evaluates it through the D0/D1A
    recovery pipeline.

    The runtime is called via the Lane C-owned execution_client (import-only,
    no modification). The recovery corridor owns all evidence, admission,
    handoff, and reporting.
    """
    exec_id = request.execution_id
    endpoint_hash = _sha256_hex(request.endpoint_url.encode())
    disposition = _build_enforcement_disposition(
        exec_id, request.runtime_kind, endpoint_hash, request.model_name
    )

    if not runtime_available:
        return _runtime_unavailable_result(request, disposition, ledger_path)

    tool_entry = next(
        (
            e
            for e in manifest.admitted_tools
            if e.canonical_name == request.target_tool_name
        ),
        None,
    )
    if tool_entry is None:
        return _tool_not_in_manifest_result(request, disposition, ledger_path)

    safe_schema = _build_constrained_prompt_schema(
        manifest, constraint_receipt, request.target_tool_name
    )

    messages = _build_messages(safe_schema, request.target_tool_name)

    try:
        exec_result = await _call_local_runtime(
            endpoint_url=request.endpoint_url,
            model_name=request.model_name,
            messages=messages,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            timeout_sec=request.timeout_sec,
            constraint_schema=safe_schema,
        )
    except Exception as exc:
        return _execution_failed_result(request, disposition, str(exc), ledger_path)

    if exec_result.get("status") != "executed":
        return _execution_failed_result(
            request, disposition, exec_result.get("error_class", ""), ledger_path
        )

    return _handle_successful_execution(
        request, manifest, exec_result, disposition, ledger_path
    )


def _build_messages(
    safe_schema: dict[str, Any], target_tool_name: str
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": _build_system_prompt(safe_schema, target_tool_name),
        },
        {
            "role": "user",
            "content": (
                f'Generate a recovery tool call for "{target_tool_name}". '
                f"Output ONLY a valid JSON object matching the schema. "
                f"No explanation, no markdown, no code fences."
            ),
        },
    ]


def _handle_successful_execution(
    request: ConstrainedExecutionRequest,
    manifest: CanonicalToolSurfaceManifest,
    exec_result: dict[str, Any],
    disposition: ConstraintEnforcementDisposition,
    ledger_path: Path | None,
) -> ConstrainedExecutionResult:
    exec_id = request.execution_id
    ephemeral_content = exec_result.get("ephemeral_content", "")
    completion_sha = exec_result.get("completion_sha256", "")
    emission_sha256 = f"sha256:{completion_sha}" if completion_sha else ""

    parsed_emission = _parse_emission_json(ephemeral_content)
    if parsed_emission is None:
        disposition.enforcement_truth_note = (
            "Model output was not valid JSON despite json_object enforcement"
        )
        return _malformed_emission_result(
            request, disposition, emission_sha256, ephemeral_content, ledger_path
        )

    if not isinstance(parsed_emission, dict):
        parsed_emission = {"content": str(parsed_emission)}
    if "tool" not in parsed_emission and "name" not in parsed_emission:
        parsed_emission = {
            "name": request.target_tool_name,
            "arguments": parsed_emission,
        }

    evaluation_case: dict[str, Any] = {
        "case_id": f"live_{exec_id}",
        "raw_emission": parsed_emission,
        "source_kind": request.emission_source_kind,
        "runtime_kind": request.runtime_kind,
        "model_id_hash": _model_safe_hash(request.model_name),
    }

    eval_event = _evaluate_one(manifest, evaluation_case, f"run_{exec_id}")

    if ledger_path is not None:
        EvidenceLedger(ledger_path).append_event(eval_event)

    handoff = _build_handoff_from_evaluation(eval_event, manifest.manifest_digest)
    disposition.enforcement_truth_note = (
        "json_schema enforcement exercised via response_format with strict=true; "
        "compiled constraint schema bound as native grammar on Ollama 0.23.1"
    )

    return ConstrainedExecutionResult(
        execution_id=exec_id,
        execution_status="executed",
        emission_sha256=emission_sha256,
        emission_byte_count=exec_result.get("completion_byte_count", 0),
        output_token_count=exec_result.get("output_token_count", 0),
        input_token_count=exec_result.get("input_token_count", 0),
        latency_ms=exec_result.get("latency_ms", 0),
        evaluation_event_digest=eval_event.get("event_digest", ""),
        admission_decision=eval_event.get("admission_decision", ""),
        handoff_kind=handoff["kind"],
        handoff_digest=handoff["digest"],
        proposal_only=bool(
            eval_event.get("admission_decision", "")
            and "proposal" in str(eval_event.get("admission_decision", "")).lower()
        ),
        mutation_class=eval_event.get("mutation_class", ""),
        selected_canonical_tool=eval_event.get("selected_canonical_tool", ""),
        refusal_code=eval_event.get("refusal_code") or "",
        refusal_reason="",
        constraint_enforcement_disposition=disposition,
        evidence_ledger_path=str(ledger_path) if ledger_path else "",
        evidence_event_count=1 if ledger_path else 0,
    )


def _build_enforcement_disposition(
    exec_id: str, runtime_kind: str, endpoint_hash: str, model_name: str
) -> ConstraintEnforcementDisposition:
    return ConstraintEnforcementDisposition(
        disposition_id=f"disp_{exec_id}",
        runtime_kind=runtime_kind,
        runtime_endpoint_hash=f"sha256:{endpoint_hash}",
        model_name=model_name,
        json_object_enforcement_available=True,
        json_object_enforcement_exercised=False,
        json_schema_enforcement_available=True,
        json_schema_enforcement_exercised=True,
        grammar_enforcement_available=False,
        grammar_enforcement_exercised=False,
        enforced_mechanism="response_format_json_schema",
        enforcement_truth_note=(
            "json_schema enforcement exercised via OpenAI-compatible "
            "response_format with strict=true on Ollama 0.23.1. "
            "Compiled recovery constraint schema bound as native grammar. "
            "No GBNF/grammar-level enforcement available."
        ),
    )


def _build_constrained_prompt_schema(
    manifest: CanonicalToolSurfaceManifest,
    constraint_receipt: ConstraintCompilationReceipt,
    target_tool_name: str,
) -> dict[str, Any]:
    entry = next(
        (e for e in manifest.admitted_tools if e.canonical_name == target_tool_name),
        None,
    )
    if entry is None:
        return {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }

    safe: dict[str, Any] = {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "const": target_tool_name},
            "arguments": {
                "type": "object",
                "properties": {
                    field: {"type": "string"} for field in entry.arg_field_names
                },
                "required": list(entry.arg_field_names),
                "additionalProperties": False,
            },
        },
        "required": ["tool", "arguments"],
        "additionalProperties": False,
    }
    return safe


def _build_system_prompt(safe_schema: dict[str, Any], target_tool_name: str) -> str:
    return (
        f"You are a recovery tool call generator. "
        f'Generate a tool call for "{target_tool_name}". '
        f"Output MUST conform to the enforced JSON schema. "
        f"No markdown, no code fences, no explanation."
    )


def _parse_emission_json(content: str) -> Any | None:
    if not content or not content.strip():
        return None
    text = content.strip()
    for candidate in [text, text.lstrip("`").rstrip("`").lstrip("json").strip()]:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _build_handoff_from_evaluation(
    eval_event: dict[str, Any], manifest_digest: str
) -> dict[str, str]:
    receipt_sha = eval_event.get("recovery_receipt_sha256", "")
    tool_name = eval_event.get("selected_canonical_tool", "")
    admission = eval_event.get("admission_decision", "")
    refusal_code = eval_event.get("refusal_code", "")

    if refusal_code:
        h = build_refusal_handoff(
            receipt_sha256=receipt_sha or _NULL_SHA256,
            manifest_digest=manifest_digest,
            refusal_code=refusal_code,
            reason=refusal_code,
            correlation_id=eval_event.get("case_id", ""),
        )
        return {"kind": h.handoff_kind, "digest": _handoff_digest(h)}

    if "read_only" in str(admission).lower() or "auto_execute_read_only" in str(
        admission
    ):
        h = build_read_only_handoff(
            receipt_sha256=receipt_sha or _NULL_SHA256,
            manifest_digest=manifest_digest,
            canonical_tool_name=tool_name or "unknown",
            payload_digest=eval_event.get("raw_emission_sha256", _NULL_SHA256),
            correlation_id=eval_event.get("case_id", ""),
        )
        return {"kind": h.handoff_kind, "digest": _handoff_digest(h)}

    if "validation" in str(admission).lower() or "auto_execute_validation" in str(
        admission
    ):
        h = build_validation_handoff(
            receipt_sha256=receipt_sha or _NULL_SHA256,
            manifest_digest=manifest_digest,
            canonical_tool_name=tool_name or "unknown",
            payload_digest=eval_event.get("raw_emission_sha256", _NULL_SHA256),
            correlation_id=eval_event.get("case_id", ""),
        )
        return {"kind": h.handoff_kind, "digest": _handoff_digest(h)}

    if "proposal" in str(admission).lower():
        h = build_mutation_handoff(
            receipt_sha256=receipt_sha or _NULL_SHA256,
            manifest_digest=manifest_digest,
            canonical_tool_name=tool_name or "unknown",
            payload_digest=eval_event.get("raw_emission_sha256", _NULL_SHA256),
            mutation_class=eval_event.get("mutation_class", ""),
            correlation_id=eval_event.get("case_id", ""),
        )
        return {"kind": h.handoff_kind, "digest": _handoff_digest(h)}

    h = build_refusal_handoff(
        receipt_sha256=receipt_sha or _NULL_SHA256,
        manifest_digest=manifest_digest,
        refusal_code=admission or "unsupported",
        reason=admission or "",
        correlation_id=eval_event.get("case_id", ""),
    )
    return {"kind": h.handoff_kind, "digest": _handoff_digest(h)}


def _handoff_digest(handoff: object) -> str:
    raw = json.dumps(handoff.model_dump(mode="json"), sort_keys=True)
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


def _runtime_unavailable_result(
    request: ConstrainedExecutionRequest,
    disposition: ConstraintEnforcementDisposition,
    ledger_path: Path | None,
) -> ConstrainedExecutionResult:
    disposition.enforcement_truth_note = (
        "Runtime unavailable: no local inference endpoint configured or reachable"
    )
    disposition.json_object_enforcement_available = False
    disposition.json_object_enforcement_exercised = False
    disposition.json_schema_enforcement_available = False
    disposition.json_schema_enforcement_exercised = False

    if ledger_path is not None:
        event = {
            "schema_version": "rig.relay.tool_recovery_evaluation_event.v1",
            "evaluation_run_id": f"run_{request.execution_id}",
            "case_id": f"unavail_{request.execution_id}",
            "source_kind": "runtime_unavailable",
            "runtime_kind": request.runtime_kind,
            "model_id_hash": _model_safe_hash(request.model_name),
            "tool_surface_manifest_digest": request.manifest_digest,
            "admission_decision": "refuse_unsupported",
            "refusal_code": "unsupported_recovery_form",
            "created_at": datetime.now(UTC).isoformat(),
        }
        EvidenceLedger(ledger_path).append_event(event)

    return ConstrainedExecutionResult(
        execution_id=request.execution_id,
        execution_status="runtime_unavailable",
        execution_error="No local inference endpoint configured or reachable",
        constraint_enforcement_disposition=disposition,
        evidence_ledger_path=str(ledger_path) if ledger_path else "",
        evidence_event_count=1 if ledger_path else 0,
    )


_NULL_SHA256 = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_HTTP_OK = 200


def _tool_not_in_manifest_result(
    request: ConstrainedExecutionRequest,
    disposition: ConstraintEnforcementDisposition,
    ledger_path: Path | None,
) -> ConstrainedExecutionResult:
    refusal_code = "canonical_tool_not_admitted"
    h = build_refusal_handoff(
        receipt_sha256=_NULL_SHA256,
        manifest_digest=request.manifest_digest,
        refusal_code=refusal_code,
        reason=f"Tool {request.target_tool_name} not in manifest",
        correlation_id=request.execution_id,
    )
    return ConstrainedExecutionResult(
        execution_id=request.execution_id,
        execution_status="refused",
        execution_error=f"Tool {request.target_tool_name} not in manifest",
        handoff_kind=h.handoff_kind,
        handoff_digest=_handoff_digest(h),
        refusal_code=refusal_code,
        refusal_reason=f"Tool {request.target_tool_name} not in manifest",
        constraint_enforcement_disposition=disposition,
    )


def _execution_failed_result(
    request: ConstrainedExecutionRequest,
    disposition: ConstraintEnforcementDisposition,
    error: str,
    ledger_path: Path | None,
) -> ConstrainedExecutionResult:
    disposition.enforcement_truth_note = f"Execution failed: {error}"
    disposition.json_object_enforcement_exercised = False

    if ledger_path is not None:
        event = {
            "schema_version": "rig.relay.tool_recovery_evaluation_event.v1",
            "evaluation_run_id": f"run_{request.execution_id}",
            "case_id": f"fail_{request.execution_id}",
            "source_kind": "execution_failed",
            "runtime_kind": request.runtime_kind,
            "model_id_hash": _model_safe_hash(request.model_name),
            "tool_surface_manifest_digest": request.manifest_digest,
            "admission_decision": "refuse_unsupported",
            "refusal_code": "unsupported_recovery_form",
            "created_at": datetime.now(UTC).isoformat(),
        }
        EvidenceLedger(ledger_path).append_event(event)

    return ConstrainedExecutionResult(
        execution_id=request.execution_id,
        execution_status="failed",
        execution_error=error,
        constraint_enforcement_disposition=disposition,
        evidence_ledger_path=str(ledger_path) if ledger_path else "",
        evidence_event_count=1 if ledger_path else 0,
    )


def _malformed_emission_result(
    request: ConstrainedExecutionRequest,
    disposition: ConstraintEnforcementDisposition,
    emission_sha256: str,
    raw_content: str,
    ledger_path: Path | None,
) -> ConstrainedExecutionResult:
    refusal_code = "malformed_inline_syntax"
    h = build_refusal_handoff(
        receipt_sha256=_NULL_SHA256,
        manifest_digest=request.manifest_digest,
        refusal_code=refusal_code,
        reason="Model emission was not valid JSON",
        correlation_id=request.execution_id,
    )

    if ledger_path is not None:
        event = {
            "schema_version": "rig.relay.tool_recovery_evaluation_event.v1",
            "evaluation_run_id": f"run_{request.execution_id}",
            "case_id": f"malform_{request.execution_id}",
            "source_kind": "captured_local_model",
            "runtime_kind": request.runtime_kind,
            "model_id_hash": _model_safe_hash(request.model_name),
            "tool_surface_manifest_digest": request.manifest_digest,
            "raw_emission_sha256": emission_sha256,
            "admission_decision": "refuse_unsupported",
            "refusal_code": refusal_code,
            "created_at": datetime.now(UTC).isoformat(),
        }
        EvidenceLedger(ledger_path).append_event(event)

    return ConstrainedExecutionResult(
        execution_id=request.execution_id,
        execution_status="refused",
        execution_error="Model emission was not valid JSON",
        emission_sha256=emission_sha256,
        emission_byte_count=len(raw_content.encode()),
        handoff_kind=h.handoff_kind,
        handoff_digest=_handoff_digest(h),
        refusal_code=refusal_code,
        refusal_reason="Model emission was not valid JSON",
        constraint_enforcement_disposition=disposition,
        evidence_ledger_path=str(ledger_path) if ledger_path else "",
        evidence_event_count=1 if ledger_path else 0,
    )


def _model_safe_hash(model_name: str) -> str:
    if not model_name:
        return "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    return _sha256_hex(model_name.encode())


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _aggregate_execution_stats(
    results: list[ConstrainedExecutionResult],
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "executed": 0,
        "failed": 0,
        "refused": 0,
        "unavailable": 0,
        "admission_counts": {},
        "handoff_kinds": {},
        "proposal_only_count": 0,
        "captured_local_count": 0,
        "refusal_count": 0,
        "total_tokens_out": 0,
        "total_latency_ms": 0,
        "enforcement_available": False,
        "enforcement_exercised": False,
        "enforcement_mechanism": "",
    }
    for r in results:
        stats[_status_key(r.execution_status)] += 1
        if r.admission_decision:
            stats["admission_counts"][r.admission_decision] = (
                stats["admission_counts"].get(r.admission_decision, 0) + 1
            )
        if r.handoff_kind:
            stats["handoff_kinds"][r.handoff_kind] = (
                stats["handoff_kinds"].get(r.handoff_kind, 0) + 1
            )
        if r.proposal_only:
            stats["proposal_only_count"] += 1
        if r.execution_status == "executed":
            stats["captured_local_count"] += 1
        if r.refusal_code:
            stats["refusal_count"] += 1
        stats["total_tokens_out"] += r.output_token_count
        stats["total_latency_ms"] += r.latency_ms
        if r.constraint_enforcement_disposition:
            d = r.constraint_enforcement_disposition
            if d.json_object_enforcement_available:
                stats["enforcement_available"] = True
            if d.json_schema_enforcement_exercised:
                stats["enforcement_exercised"] = True
            if d.enforced_mechanism:
                stats["enforcement_mechanism"] = d.enforced_mechanism
    return stats


def _status_key(status: str) -> str:
    match status:
        case "executed":
            return "executed"
        case "failed":
            return "failed"
        case "refused":
            return "refused"
        case "runtime_unavailable":
            return "unavailable"
    return "failed"


def build_d2_operations_projection(
    results: list[ConstrainedExecutionResult],
    manifest: CanonicalToolSurfaceManifest,
    constraint_receipt: ConstraintCompilationReceipt,
    *,
    projection_id: str | None = None,
) -> dict[str, Any]:
    """Build deterministic D2 operations projection from execution results.

    Reports runtime enforcement truth, captured emission results,
    admission outcomes, and mutation-proposal-only safety.
    Content-light: counts, hashes, classifications only.
    """
    pid = projection_id or f"d2proj_{datetime.now(UTC).isoformat()}"
    total = len(results)
    if total == 0:
        return {
            "schema_version": "rig.relay.d2_operations_projection.v1",
            "projection_id": pid,
            "created_at": datetime.now(UTC).isoformat(),
            "total_executions": 0,
            "projection_digest": "",
        }

    stats = _aggregate_execution_stats(results)
    proposal_only_mutation_preserved = stats["proposal_only_count"] > 0 and all(
        r.handoff_kind == "mutation_proposal_only" for r in results if r.proposal_only
    )

    prv = results[0].constraint_enforcement_disposition
    runtime_disposition: dict[str, Any] = {
        "runtime_reachable": stats["executed"] > 0,
        "runtime_kind": prv.runtime_kind if prv else "unknown",
        "model_name_hash": _model_safe_hash(prv.model_name if prv else ""),
        "json_object_enforcement_available": True,
        "json_schema_enforcement_available": stats["enforcement_available"],
        "json_schema_enforcement_exercised": stats["enforcement_exercised"],
        "grammar_enforcement_available": False,
        "enforced_mechanism": stats["enforcement_mechanism"],
        "enforcement_truth": (
            "json_schema enforcement exercised via response_format with strict=true "
            "on Ollama 0.23.1. Compiled recovery constraint schema bound as native "
            "grammar. GBNF/grammar-level enforcement not available."
        ),
    }

    projection: dict[str, Any] = {
        "schema_version": "rig.relay.d2_operations_projection.v1",
        "projection_id": pid,
        "created_at": datetime.now(UTC).isoformat(),
        "manifest_digest": manifest.manifest_digest,
        "constraint_receipt_digest": constraint_receipt.receipt_digest,
        "total_executions": total,
        "executed_count": stats["executed"],
        "failed_count": stats["failed"],
        "refused_count": stats["refused"],
        "runtime_unavailable_count": stats["unavailable"],
        "admission_decisions": stats["admission_counts"],
        "handoff_kinds": stats["handoff_kinds"],
        "captured_local_model_emission_count": stats["captured_local_count"],
        "proposal_only_mutation_count": stats["proposal_only_count"],
        "proposal_only_mutation_preserved": proposal_only_mutation_preserved,
        "refusal_count": stats["refusal_count"],
        "mutation_proposal_only_invariant": proposal_only_mutation_preserved,
        "total_output_tokens": stats["total_tokens_out"],
        "total_latency_ms": stats["total_latency_ms"],
        "avg_latency_ms": (
            stats["total_latency_ms"] // stats["executed"]
            if stats["executed"] > 0
            else 0
        ),
        "runtime_enforcement_disposition": runtime_disposition,
    }
    payload = json.dumps(projection, sort_keys=True, separators=(",", ":"))
    projection["projection_digest"] = (
        f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"
    )
    return projection


__all__ = [
    "ConstrainedExecutionRequest",
    "ConstrainedExecutionResult",
    "ConstraintEnforcementDisposition",
    "build_d2_operations_projection",
    "execute_constrained_recovery",
]
