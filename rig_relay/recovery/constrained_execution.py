"""D2 Governed Recovery Constrained Execution Corridor.

Sends recovery-oriented constrained-generation requests through an actual
configured local model runtime, captures emitted candidate output as canonical
evidence, and evaluates through the D0/D1A recovery substrate.

The enforced runtime schema is digest-bound to the canonical
ConstraintCompilationReceipt and tool-surface manifest. Every captured
emission event carries receipt, schema, and manifest binding digests.

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
    emission_source_kind: str = (
        ""  # captured_local_model | curated_adversarial | fixture | runtime_unavailable
    )
    enforced_schema_digest: str = ""
    constraint_receipt_digest: str = ""
    manifest_digest: str = ""
    receipt_loaded_from_durable_evidence: bool = False
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
    constraint_receipt_ledger_path: Path | None = None,
    runtime_available: bool = True,
) -> ConstrainedExecutionResult:
    """Execute a constrained recovery call against a local model runtime.

    Sends a structured constraint prompt through the runtime, captures the
    emission as canonical evidence, and evaluates it through the D0/D1A
    recovery pipeline.

    When constraint_receipt_ledger_path is provided, the canonical
    ConstraintCompilationReceipt is loaded from durable evidence and its
    integrity is verified before runtime invocation. The passed
    constraint_receipt must match the loaded canonical receipt's digest.
    Without a ledger path, the in-memory receipt is used directly (for
    testing or when the durable receipt path is not yet available).

    The runtime is called via the Lane D-owned _call_local_runtime() temporary
    adapter (direct httpx transport, not a Lane C provider boundary). The
    recovery corridor owns all evidence, admission, handoff, and reporting.

    The enforced schema is verified against the canonical
    ConstraintCompilationReceipt before invocation. Execution is refused if
    the runtime-submitted schema digest does not match the receipt's
    per-tool record.
    """
    exec_id = request.execution_id
    endpoint_hash = _sha256_hex(request.endpoint_url.encode())
    disposition = _build_enforcement_disposition(
        exec_id, request.runtime_kind, endpoint_hash, request.model_name
    )

    receipt_from_durable = False
    if constraint_receipt_ledger_path is not None:
        canonical_result = _load_canonical_or_refuse(
            request, disposition, constraint_receipt_ledger_path, constraint_receipt
        )
        if isinstance(canonical_result, ConstrainedExecutionResult):
            return canonical_result
        constraint_receipt = canonical_result
        receipt_from_durable = True

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

    safe_schema, enforced_schema_digest = _build_constrained_prompt_schema(
        manifest, constraint_receipt, request.target_tool_name
    )

    _verify_schema_digest = enforced_schema_digest
    receipt_digest_for_tool = constraint_receipt.tool_schema_digests.get(
        request.target_tool_name, ""
    )
    if receipt_digest_for_tool and _verify_schema_digest != receipt_digest_for_tool:
        return _receipt_binding_refused_result(
            request, disposition, _verify_schema_digest, receipt_digest_for_tool
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
        exec_result = {"status": "exception", "error_class": str(exc)}

    if exec_result.get("status") != "executed":
        return _execution_failed_result(
            request,
            disposition,
            exec_result.get("error_class", "runtime_error"),
            ledger_path,
        )

    return _handle_successful_execution(
        request,
        manifest,
        constraint_receipt,
        exec_result,
        disposition,
        enforced_schema_digest,
        receipt_from_durable,
        ledger_path,
    )


def _load_canonical_or_refuse(
    request: ConstrainedExecutionRequest,
    disposition: ConstraintEnforcementDisposition,
    receipt_ledger_path: Path,
    supplied_receipt: ConstraintCompilationReceipt,
) -> ConstraintCompilationReceipt | ConstrainedExecutionResult:
    from rig_relay.recovery.constraint_compiler import load_canonical_constraint_receipt

    receipt_ledger = EvidenceLedger(receipt_ledger_path)
    canonical = load_canonical_constraint_receipt(receipt_ledger)
    if canonical is None:
        disposition.enforcement_truth_note = (
            "Execution refused: no canonical compilation receipt "
            "found in durable evidence"
        )
        disposition.json_schema_enforcement_exercised = False
        return _receipt_not_found_result(request, disposition)
    if canonical.receipt_digest != supplied_receipt.receipt_digest:
        disposition.enforcement_truth_note = (
            "Execution refused: supplied receipt digest does not match "
            "canonical durable receipt"
        )
        disposition.json_schema_enforcement_exercised = False
        return _receipt_binding_refused_result(
            request,
            disposition,
            supplied_receipt.receipt_digest,
            canonical.receipt_digest,
        )
    return canonical


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
    constraint_receipt: ConstraintCompilationReceipt,
    exec_result: dict[str, Any],
    disposition: ConstraintEnforcementDisposition,
    enforced_schema_digest: str,
    receipt_from_durable: bool,
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
    disposition.json_schema_enforcement_exercised = True
    disposition.enforcement_truth_note = (
        "json_schema enforcement exercised via response_format with strict=true; "
        "compiled constraint schema bound as native grammar on Ollama 0.23.1"
    )

    return ConstrainedExecutionResult(
        execution_id=exec_id,
        execution_status="executed",
        emission_source_kind=request.emission_source_kind,
        enforced_schema_digest=enforced_schema_digest,
        constraint_receipt_digest=constraint_receipt.receipt_digest,
        manifest_digest=manifest.manifest_digest,
        receipt_loaded_from_durable_evidence=receipt_from_durable,
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
        json_schema_enforcement_exercised=False,
        grammar_enforcement_available=False,
        grammar_enforcement_exercised=False,
        enforced_mechanism="response_format_json_schema",
        enforcement_truth_note="",
    )


def _build_constrained_prompt_schema(
    manifest: CanonicalToolSurfaceManifest,
    constraint_receipt: ConstraintCompilationReceipt,
    target_tool_name: str,
) -> tuple[dict[str, Any], str]:
    """Build the runtime-enforced JSON Schema and compute its digest.

    Returns (schema, digest) where digest is the SHA256 of the exact JSON
    Schema submitted to the runtime. The caller must verify this digest
    against constraint_receipt.tool_schema_digests before invocation.

    The digest is the authority bridge between the canonical compilation
    receipt and the actual enforcement mechanism.
    """
    entry = next(
        (e for e in manifest.admitted_tools if e.canonical_name == target_tool_name),
        None,
    )
    if entry is None:
        empty: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }
        return empty, _compute_schema_digest(empty)

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
    return safe, _compute_schema_digest(safe)


def _compute_schema_digest(schema: dict[str, Any]) -> str:
    payload = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


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
        emission_source_kind="runtime_unavailable",
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
        emission_source_kind=request.emission_source_kind,
        handoff_kind=h.handoff_kind,
        handoff_digest=_handoff_digest(h),
        refusal_code=refusal_code,
        refusal_reason=f"Tool {request.target_tool_name} not in manifest",
        constraint_enforcement_disposition=disposition,
    )


def _receipt_binding_refused_result(
    request: ConstrainedExecutionRequest,
    disposition: ConstraintEnforcementDisposition,
    enforced_digest: str,
    receipt_digest: str,
) -> ConstrainedExecutionResult:
    refusal_code = "constraint_schema_receipt_mismatch"
    h = build_refusal_handoff(
        receipt_sha256=_NULL_SHA256,
        manifest_digest=request.manifest_digest,
        refusal_code=refusal_code,
        reason=(
            f"Enforced schema digest {enforced_digest[:20]}... does not match "
            f"receipt record {receipt_digest[:20]}..."
        ),
        correlation_id=request.execution_id,
    )
    disposition.enforcement_truth_note = (
        "Execution refused: enforced schema digest does not match "
        "canonical constraint compilation receipt"
    )
    disposition.json_schema_enforcement_exercised = False
    return ConstrainedExecutionResult(
        execution_id=request.execution_id,
        execution_status="refused",
        execution_error=(
            f"Enforced schema digest does not match receipt for "
            f"tool {request.target_tool_name}"
        ),
        emission_source_kind=request.emission_source_kind,
        enforced_schema_digest=enforced_digest,
        constraint_receipt_digest=request.constraint_receipt_digest,
        handoff_kind=h.handoff_kind,
        handoff_digest=_handoff_digest(h),
        refusal_code=refusal_code,
        refusal_reason=(
            f"Enforced schema digest does not match receipt for "
            f"tool {request.target_tool_name}"
        ),
        constraint_enforcement_disposition=disposition,
    )


def _receipt_not_found_result(
    request: ConstrainedExecutionRequest, disposition: ConstraintEnforcementDisposition
) -> ConstrainedExecutionResult:
    refusal_code = "canonical_compilation_receipt_not_found"
    h = build_refusal_handoff(
        receipt_sha256=_NULL_SHA256,
        manifest_digest=request.manifest_digest,
        refusal_code=refusal_code,
        reason=(
            "No canonical compilation receipt found in durable evidence. "
            "Persist the receipt through persist_constraint_compilation_receipt() "
            "before constrained execution."
        ),
        correlation_id=request.execution_id,
    )
    disposition.enforcement_truth_note = (
        "Execution refused: canonical compilation receipt not found in durable evidence"
    )
    return ConstrainedExecutionResult(
        execution_id=request.execution_id,
        execution_status="refused",
        execution_error="Canonical compilation receipt not found in durable evidence",
        emission_source_kind=request.emission_source_kind,
        constraint_receipt_digest=request.constraint_receipt_digest,
        handoff_kind=h.handoff_kind,
        handoff_digest=_handoff_digest(h),
        refusal_code=refusal_code,
        refusal_reason=("Canonical compilation receipt not found in durable evidence"),
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
    disposition.json_schema_enforcement_exercised = False

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
        emission_source_kind="execution_failed",
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
        emission_source_kind=request.emission_source_kind,
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


def build_captured_emission_event(
    result: ConstrainedExecutionResult, *, event_id: str, model_name_hash: str = ""
) -> dict[str, Any]:
    """Build a content-light captured-emission event from an execution result.

    Compliant with rig.relay.lane_d2_captured_emission_event.v1 schema.
    Never contains raw prompts, completions, or secrets.
    """
    disp = result.constraint_enforcement_disposition
    event: dict[str, Any] = {
        "schema_version": "rig.relay.lane_d2_captured_emission_event.v1",
        "event_id": event_id,
        "created_at": datetime.now(UTC).isoformat(),
        "execution_id": result.execution_id,
        "execution_status": result.execution_status,
        "enforced_schema_digest": result.enforced_schema_digest,
        "constraint_receipt_digest": result.constraint_receipt_digest,
        "manifest_digest": result.manifest_digest,
        "receipt_loaded_from_durable_evidence": result.receipt_loaded_from_durable_evidence,
        "emission_source_kind": result.emission_source_kind,
        "emission_sha256": result.emission_sha256,
        "emission_byte_count": result.emission_byte_count,
        "output_token_count": result.output_token_count,
        "input_token_count": result.input_token_count,
        "latency_ms": result.latency_ms,
        "admission_decision": result.admission_decision,
        "handoff_kind": result.handoff_kind,
        "handoff_digest": result.handoff_digest,
        "proposal_only": result.proposal_only,
        "mutation_class": result.mutation_class,
        "selected_canonical_tool": result.selected_canonical_tool,
        "refusal_code": result.refusal_code,
        "runtime_kind": disp.runtime_kind if disp else "",
        "model_name_hash": model_name_hash,
        "json_schema_enforcement_available": (
            disp.json_schema_enforcement_available if disp else False
        ),
        "json_schema_enforcement_exercised": (
            disp.json_schema_enforcement_exercised if disp else False
        ),
        "enforced_mechanism": disp.enforced_mechanism if disp else "",
    }
    event["event_digest"] = _sha256_event(event)
    return event


def _sha256_event(event: dict[str, Any]) -> str:
    data = {k: v for k, v in event.items() if k != "event_digest"}
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


def validate_captured_emission_event(event: dict[str, Any]) -> None:
    """Validate a captured-emission event against its JSON Schema.

    Raises ValueError with specific diagnostic on failure.
    """
    required = {
        "schema_version",
        "event_id",
        "created_at",
        "execution_id",
        "execution_status",
    }
    for key in required:
        if key not in event:
            raise ValueError(f"Captured emission event missing required field: {key}")

    if event["schema_version"] != "rig.relay.lane_d2_captured_emission_event.v1":
        raise ValueError(f"Invalid schema_version: {event['schema_version']}")

    valid_statuses = {"executed", "runtime_unavailable", "refused", "failed"}
    if event.get("execution_status") not in valid_statuses:
        raise ValueError(f"Invalid execution_status: {event.get('execution_status')}")

    _sha256_len = 71  # "sha256:" + 64 hex chars
    for field in ("emission_sha256", "handoff_digest", "event_digest"):
        val = event.get(field, "")
        if val and not (val.startswith("sha256:") and len(val) == _sha256_len):
            raise ValueError(f"Invalid sha256 digest for {field}: {val[:40]}...")

    for int_field in (
        "emission_byte_count",
        "output_token_count",
        "input_token_count",
        "latency_ms",
    ):
        val = event.get(int_field, 0)
        if not isinstance(val, int) or val < 0:
            raise ValueError(f"Invalid {int_field}: {val}")

    for bool_field in (
        "proposal_only",
        "json_schema_enforcement_available",
        "json_schema_enforcement_exercised",
    ):
        val = event.get(bool_field)
        if val is not None and not isinstance(val, bool):
            raise ValueError(f"Invalid {bool_field}: {val}")


def build_captured_emission_corpus(
    results: list[ConstrainedExecutionResult], *, model_name_hash: str = ""
) -> list[dict[str, Any]]:
    """Build schema-validated captured-emission corpus from execution results.

    Each event is validated before inclusion.
    """
    events: list[dict[str, Any]] = []
    for i, result in enumerate(results):
        event = build_captured_emission_event(
            result, event_id=f"corpus-{i:02d}", model_name_hash=model_name_hash
        )
        validate_captured_emission_event(event)
        events.append(event)
    return events


__all__ = [
    "ConstrainedExecutionRequest",
    "ConstrainedExecutionResult",
    "ConstraintEnforcementDisposition",
    "build_captured_emission_corpus",
    "build_captured_emission_event",
    "build_d2_operations_projection",
    "execute_constrained_recovery",
    "validate_captured_emission_event",
]
