"""Local Project Inference Service — M0.

Typed application service that accepts a sanitized, provenance-bound
project context packet and an explicitly defined assistance task, checks
whether the configured local runtime is admitted for the required
enforcement class, executes only when admissible, records content-light
outcome evidence, and emits reviewable draft projections.

Consumes Lane D's:
- RecoveryConstraintCapabilityAdmissionService (D3)
- LocalInferenceAirlock / is_local_inference_available (providers/local_inference)
- execute_chat_completion (execution_client)

Never bypasses capability admission, publishes model output automatically,
or writes raw content into telemetry/evidence artifacts.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import httpx

from rig_relay.core.logger import logger
from rig_relay.local_inference._models import (
    AssistanceExecutionStatus,
    AssistanceResult,
    AssistanceTask,
    AssistanceTaskKind,
    OutputDisposition,
    ProjectContextPacket,
    PublicationApplicability,
)
from rig_relay.providers.local_inference.airlock import (
    get_airlock,
    is_local_inference_available,
)
from rig_relay.recovery.capability_admission import (
    CapabilityAdmissionDecision,
    CapabilityQuery,
    ConstraintCapabilityDisposition,
    EnforcementClass,
    RecoveryConstraintCapabilityAdmissionService,
)

DRAFT_STORE_ROOT = ".build/rig-relay/local_inference/drafts"


class LocalProjectInferenceService:
    """Capability-admitted local assistance over sanitized project context.

    Accepts a sanitized context packet and assistance task, verifies
    capability admission, executes when admissible, and produces
    review-required draft outputs and content-light evidence.

    This service is read-side for evidence: it never modifies recovery
    evidence, runtime configuration, provider state, or handoff/execution
    authority.
    """

    def __init__(self) -> None:
        self._admission_service = RecoveryConstraintCapabilityAdmissionService()
        self._results: dict[str, AssistanceResult] = {}
        self._drafts: dict[str, str] = {}

    def register_disposition(
        self, disposition: ConstraintCapabilityDisposition
    ) -> None:
        """Register a Lane D capability disposition from canonical evidence."""
        self._admission_service.register_disposition(disposition)

    def is_runtime_available(self) -> bool:
        """Check whether a local inference runtime is configured and reachable."""
        return is_local_inference_available()

    def get_runtime_info(self) -> dict[str, Any]:
        """Get safe runtime metadata for display/projection."""
        airlock = get_airlock()
        snapshot = airlock.build_config_snapshot()
        if not snapshot.get("configured"):
            return {"available": False, "configured": False}
        return {
            "available": self.is_runtime_available(),
            "configured": True,
            "endpoint_url": snapshot.get("endpoint_url", ""),
            "endpoint_sha256": snapshot.get("endpoint_sha256", ""),
            "runtime_kind": snapshot.get("runtime_kind", "unknown"),
            "platform_class": snapshot.get("platform_class", "unknown"),
        }

    def admit_task(self, task: AssistanceTask) -> CapabilityAdmissionDecision:
        """Query Lane D's capability admission for this task's requirements."""
        query = CapabilityQuery(
            query_id=f"m0_{task.task_id}",
            required_enforcement_class=task.required_enforcement_class,
            require_captured_local_model_evidence=True,
            require_receipt_bound=True,
        )
        return self._admission_service.admit_capability(query)

    async def execute_task(
        self, task: AssistanceTask, packet: ProjectContextPacket
    ) -> AssistanceResult:
        """Execute an assistance task against a sanitized context packet."""
        result_id = f"res_{task.task_id}_{int(time.monotonic() * 1000)}"

        refusal = self._preflight_check(task, packet, result_id)
        if refusal is not None:
            return refusal

        admission_decision = self.admit_task(task)
        if not admission_decision.runtime_capable:
            return _refused(
                task,
                result_id,
                AssistanceExecutionStatus.REFUSED_CAPABILITY_UNPROVEN,
                admission_decision.reason,
                "capability_unproven",
                admission_decision=admission_decision,
            )

        airlock = get_airlock()
        config = airlock.get_config()
        if config is None or not config.endpoint_url:
            return _refused(
                task,
                result_id,
                AssistanceExecutionStatus.REFUSED_RUNTIME_UNAVAILABLE,
                "No endpoint configured",
                "no_endpoint",
            )

        prompt = _build_task_prompt(task, packet)
        started = time.monotonic()

        try:
            completion = await _call_local_inference(
                endpoint_url=config.endpoint_url,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=_max_tokens_for_task(task.task_kind),
                temperature=0.0,
            )
        except Exception as exc:
            logger.error("Local inference execution failed: %s", exc)
            return _refused(
                task,
                result_id,
                AssistanceExecutionStatus.REFUSED_MODEL_ERROR,
                f"Execution failed: {type(exc).__name__}",
                "model_error",
                admission_decision=admission_decision,
            )

        return self._build_success_result(
            task, packet, completion, started, result_id, admission_decision
        )

    def _preflight_check(
        self, task: AssistanceTask, packet: ProjectContextPacket, result_id: str
    ) -> AssistanceResult | None:
        """Return a refusal result if any pre-execution guard fails, else None."""
        if not packet.is_public_safe():
            return _refused(
                task,
                result_id,
                AssistanceExecutionStatus.REFUSED_UNSAFE_PACKET,
                "Input context packet is not public-safe for assistance tasks",
                "unsafe_packet",
            )

        if (
            task.context_packet_digest
            and task.context_packet_digest != packet.packet_digest
        ):
            return _refused(
                task,
                result_id,
                AssistanceExecutionStatus.REFUSED_UNSAFE_PACKET,
                f"Task context packet digest mismatch: expected {task.context_packet_digest}, got {packet.packet_digest}",
                "packet_digest_mismatch",
            )

        if not self.is_runtime_available():
            return _refused(
                task,
                result_id,
                AssistanceExecutionStatus.REFUSED_RUNTIME_UNAVAILABLE,
                "Local inference runtime is not configured or available",
                "runtime_unavailable",
            )

        return None

    def _build_success_result(
        self,
        task: AssistanceTask,
        packet: ProjectContextPacket,
        completion: dict[str, Any],
        started: float,
        result_id: str,
        admission_decision: CapabilityAdmissionDecision,
    ) -> AssistanceResult:
        latency = int((time.monotonic() - started) * 1000)
        refusal = _check_completion(
            task, completion, latency, result_id, admission_decision
        )
        if refusal is not None:
            return refusal

        raw_output = completion["ephemeral_content"]
        draft_sha = hashlib.sha256(raw_output.encode()).hexdigest()
        self._drafts[draft_sha] = raw_output

        output_disposition = _classify_output(task, raw_output)
        publication = task.target_publication_applicability
        if output_disposition == OutputDisposition.REFUSED_PUBLICATION:
            publication = PublicationApplicability.NONE

        result = AssistanceResult(
            result_id=result_id,
            task_id=task.task_id,
            status=_status_from_enforcement(
                admission_decision.requested_enforcement_class
            ),
            execution_latency_ms=latency,
            model_safe_id=completion.get("model_safe_id", ""),
            required_enforcement_class=task.required_enforcement_class,
            enforcement_class_used=admission_decision.requested_enforcement_class,
            capability_admission_decision_digest=(
                admission_decision.evidence_disposition_digest
            ),
            capability_admission_decision_id=admission_decision.decision_id,
            output_disposition=output_disposition,
            publication_applicability=publication,
            draft_sha256=draft_sha,
            draft_byte_count=len(raw_output.encode()),
            context_packet_digest=packet.packet_digest,
            refusal_reason="",
            refusal_code="",
            output_token_count=completion.get("output_token_count", 0),
            input_token_count=completion.get("input_token_count", 0),
        )
        self._results[result_id] = result
        return result

    def get_draft(self, draft_sha256: str) -> str | None:
        """Retrieve a reviewable draft by its SHA256 digest.

        Drafts exist in the review domain only — never in telemetry or
        public publication.
        """
        return self._drafts.get(draft_sha256)

    def get_result(self, result_id: str) -> AssistanceResult | None:
        return self._results.get(result_id)

    def list_results(self) -> list[AssistanceResult]:
        return sorted(self._results.values(), key=lambda r: r.created_at, reverse=True)

    def clear_drafts(self) -> None:
        self._drafts.clear()


def _refused(
    task: AssistanceTask,
    result_id: str,
    status: AssistanceExecutionStatus,
    reason: str,
    refusal_code: str,
    *,
    admission_decision: CapabilityAdmissionDecision | None = None,
) -> AssistanceResult:
    return AssistanceResult(
        result_id=result_id,
        task_id=task.task_id,
        status=status,
        required_enforcement_class=task.required_enforcement_class,
        enforcement_class_used=EnforcementClass.UNSUPPORTED,
        capability_admission_decision_digest=(
            admission_decision.evidence_disposition_digest if admission_decision else ""
        ),
        capability_admission_decision_id=(
            admission_decision.decision_id if admission_decision else ""
        ),
        output_disposition=OutputDisposition.REFUSED_PUBLICATION,
        publication_applicability=PublicationApplicability.NONE,
        refusal_reason=reason,
        refusal_code=refusal_code,
        context_packet_digest=task.context_packet_digest,
    )


def _status_from_enforcement(ec: EnforcementClass) -> AssistanceExecutionStatus:
    if ec == EnforcementClass.JSON_OBJECT_FORMATTING_ONLY:
        return AssistanceExecutionStatus.DEGRADED_JSON_OBJECT_ONLY
    return AssistanceExecutionStatus.EXECUTED


_SYSTEM_PROMPT = (
    "You are an assistant that produces structured, public-safe project "
    "documentation from sanitized context data. You must only use the "
    "provided context. Never invent capabilities, package dependencies, "
    "or achievements not present in the input. Your output must be "
    "concise, truthful, and suitable for developer review before any "
    "publication. Do not include raw file paths, code snippets with "
    "private identifiers, or security-sensitive details."
)


async def _call_local_inference(
    *,
    endpoint_url: str,
    messages: list[dict[str, str]],
    max_tokens: int = 512,
    temperature: float = 0.0,
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    """M0-owned temporary local inference adapter.

    Narrow OpenAI-compatible chat completion call to a configured local
    endpoint. Content-light: sends only provided prompts, never stores
    completions raw in evidence.

    Uses the actual model name from the Ollama API rather than a
    hardcoded placeholder. This adapter is explicitly temporary and
    makes no claim of general provider transport unification.
    When Lane C releases a proper provider/local-runtime boundary
    with model name support, this adapter should be retired.
    """
    started = time.monotonic()
    model_name = await _discover_local_model_name(endpoint_url)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_sec)) as client:
            response = await client.post(
                f"{endpoint_url}/v1/chat/completions",
                json={
                    "model": model_name,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "stream": False,
                },
            )
    except httpx.TimeoutException:
        return _cline_error("timed_out", "httpx.TimeoutException", _latency(started))
    except httpx.ConnectError as exc:
        return _cline_error("failed", f"ConnectError: {exc}", _latency(started))
    except Exception as exc:
        return _cline_error("failed", f"{type(exc).__name__}", _latency(started))

    return _parse_completion_response(response, started)


def _latency(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _parse_completion_response(
    response: httpx.Response, started: float
) -> dict[str, Any]:
    latency = _latency(started)
    if response.status_code != _HTTP_OK:
        return _cline_error("failed", f"HTTP {response.status_code}", latency)
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return _cline_error("malformed_response", "JSONDecodeError", latency)
    choices = body.get("choices", [])
    if not choices:
        return _cline_error("malformed_response", "empty_choices", latency)
    message = choices[0].get("message", {})
    content = message.get("content", "")
    completion_bytes = content.encode("utf-8")
    return {
        "status": "executed",
        "latency_ms": latency,
        "completion_sha256": hashlib.sha256(completion_bytes).hexdigest(),
        "completion_byte_count": len(completion_bytes),
        "output_token_count": body.get("usage", {}).get("completion_tokens", 0),
        "input_token_count": body.get("usage", {}).get("prompt_tokens", 0),
        "model_safe_id": body.get("model", ""),
        "ephemeral_content": content,
    }


async def _discover_local_model_name(endpoint_url: str) -> str:
    """Discover the first available model name from a local Ollama/OAI endpoint."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            response = await client.get(f"{endpoint_url}/api/tags")
            if response.status_code == _HTTP_OK:
                data = response.json()
                models = data.get("models", [])
                if models:
                    return models[0].get("name", "unknown")
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            response = await client.get(f"{endpoint_url}/v1/models")
            if response.status_code == _HTTP_OK:
                data = response.json()
                models = data.get("data", [])
                if models:
                    return models[0].get("id", "unknown")
    except Exception:
        pass

    return "local_model"


def _cline_error(status: str, error_class: str, latency_ms: int) -> dict[str, Any]:
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


_TASK_PROMPTS: dict[AssistanceTaskKind, str] = {
    AssistanceTaskKind.PROJECT_SUMMARY: (
        "Based on the project context below, output ONLY a JSON object with "
        'key "summary" containing a concise public-safe project summary (2-4 '
        "sentences). Do not include markdown fences or extra text.\n\n"
        "Project context:\n{context}"
    ),
    AssistanceTaskKind.PAGE_SECTION_ORDERING: (
        "Based on the following project context, suggest a logical "
        "page-section ordering for a project page. List 5-8 sections "
        "in recommended order. For each section, give a one-sentence "
        "description of what it should contain. The ordering should "
        "lead with project identity and purpose, followed by evidence "
        "of capabilities, and end with open work.\n\n"
        "Project context:\n{context}"
    ),
    AssistanceTaskKind.CAPABILITY_CLASSIFICATION: (
        "Based on the following project context, classify this project "
        "into 3-5 portfolio capability categories (e.g., 'agent orchestration', "
        "'constrained execution', 'desktop application', 'governed tools', "
        "'evidence systems'). For each category, give a one-sentence "
        "justification grounded in the project context.\n\n"
        "Project context:\n{context}"
    ),
    AssistanceTaskKind.MISSING_MATERIAL_CHECKLIST: (
        "Based on the following project context, suggest a checklist "
        "of 3-6 materials that could improve the project's presentation "
        "for a developer portfolio. Focus on gaps: missing demos, "
        "screenshots, architecture diagrams, benchmark reports, or "
        "case studies. Be constructive and specific.\n\n"
        "Project context:\n{context}"
    ),
}

_TASK_MAX_TOKENS: dict[AssistanceTaskKind, int] = {
    AssistanceTaskKind.PROJECT_SUMMARY: 512,
    AssistanceTaskKind.PAGE_SECTION_ORDERING: 768,
    AssistanceTaskKind.CAPABILITY_CLASSIFICATION: 512,
    AssistanceTaskKind.MISSING_MATERIAL_CHECKLIST: 512,
}


def _max_tokens_for_task(kind: AssistanceTaskKind) -> int:
    return _TASK_MAX_TOKENS.get(kind, 512)


def _check_completion(
    task: AssistanceTask,
    completion: dict[str, Any],
    latency: int,
    result_id: str,
    admission_decision: CapabilityAdmissionDecision,
) -> AssistanceResult | None:
    """Validate completion output; return refusal or None if valid."""
    if completion["status"] != "executed":
        return _refused(
            task,
            result_id,
            AssistanceExecutionStatus.REFUSED_MODEL_ERROR,
            f"Model returned status: {completion['status']}",
            "model_status_error",
            admission_decision=admission_decision,
        )

    raw_output = completion.get("ephemeral_content", "")
    if not raw_output.strip():
        return _refused(
            task,
            result_id,
            AssistanceExecutionStatus.REFUSED_MODEL_ERROR,
            "Model returned empty output",
            "empty_output",
            admission_decision=admission_decision,
        )

    output_valid, validation_error = _validate_output(task, raw_output)
    if not output_valid:
        return _refused(
            task,
            result_id,
            AssistanceExecutionStatus.REFUSED_MODEL_ERROR,
            f"Output validation failed: {validation_error}",
            "output_validation_failed",
            admission_decision=admission_decision,
        )

    return None


_HTTP_OK = 200
_MIN_OUTPUT_LENGTH = 10


def _build_task_prompt(task: AssistanceTask, packet: ProjectContextPacket) -> str:
    context_text = packet.build_prompt_context()
    template = _TASK_PROMPTS.get(
        task.task_kind, _TASK_PROMPTS[AssistanceTaskKind.PROJECT_SUMMARY]
    )
    return template.format(context=context_text)


def _validate_output(task: AssistanceTask, output: str) -> tuple[bool, str]:
    """Validate model output against the task's required enforcement class."""
    cleaned = _extract_clean_output(output)

    task_requires_structured = task.required_enforcement_class in {
        EnforcementClass.JSON_OBJECT_FORMATTING_ONLY,
        EnforcementClass.NATIVE_JSON_SCHEMA,
    }

    if task_requires_structured:
        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, (dict, list)):
                return False, "Output is valid JSON but not an object or array"
        except json.JSONDecodeError:
            return False, "Output is not valid JSON"

    if len(cleaned) < _MIN_OUTPUT_LENGTH:
        return False, "Output too short"

    _forbidden = [
        "API_KEY",
        "access_token",
        "refresh_token",
        "client_secret",
        "private_key",
    ]
    for pattern in _forbidden:
        if pattern.lower() in output.lower():
            return False, f"Output may contain forbidden content pattern: {pattern}"

    return True, ""


def _extract_clean_output(output: str) -> str:
    """Extract clean content from model output, stripping markdown fences."""
    text = output.strip()

    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        elif text.endswith("```\n"):
            text = text[:-4]
    return text.strip()


def _classify_output(task: AssistanceTask, output: str) -> OutputDisposition:
    if task.target_publication_applicability == PublicationApplicability.NONE:
        return OutputDisposition.INTERNAL_ONLY
    return OutputDisposition.DRAFT_REQUIRES_REVIEW


_global_service: LocalProjectInferenceService | None = None


def get_inference_service() -> LocalProjectInferenceService:
    global _global_service
    if _global_service is None:
        _global_service = LocalProjectInferenceService()
    return _global_service


def reset_inference_service() -> None:
    global _global_service
    _global_service = None


__all__ = [
    "LocalProjectInferenceService",
    "get_inference_service",
    "reset_inference_service",
]
