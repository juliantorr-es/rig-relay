"""Content-light model observation models and helpers.

This module defines the data layer for ranking cloud providers and local
models across real Rig Relay workflows. All observation records are
content-light: no raw prompts, model outputs, source code, diffs,
stdout/stderr bodies, secrets, tokens, API keys, or raw private paths.
"""

# ruff: noqa: PLR0913  — build_model_observation has many optional fields

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field

# ── Artifact reference ────────────────────────────────────────────────


class ArtifactRef(BaseModel):
    """Content-light reference to a related artifact.

    Only kind and sha256 — never raw content.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    sha256: str


# ── Provider and backend enums (non-StrEnum for pyright compat with JSON dumps) ──


class ProviderKind:
    CLOUD = "cloud"
    LOCAL = "local"


class Backend:
    API = "api"
    MLX = "mlx"
    LLAMA_CPP = "llama_cpp"


class ValidationStatus:
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"


class UserOutcome:
    ACCEPTED = "accepted"
    REVISED = "revised"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class ComfortCategory:
    COMFORTABLE = "comfortable"
    MAYBE = "maybe"
    NOT_RECOMMENDED = "not_recommended"


class ConfidenceLevel:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ── ModelObservation ──────────────────────────────────────────────────


MODEL_OBSERVATION_SCHEMA_VERSION = "rig.relay.model_observation.v1"


class ModelObservation(BaseModel):
    """Content-light observation of a model invocation.

    All fields are content-light: no raw prompts, model outputs, source
    code, diffs, stdout/stderr bodies, secrets, tokens, API keys, or
    raw private paths.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = MODEL_OBSERVATION_SCHEMA_VERSION
    observation_id: str = ""
    created_at: str = ""
    task_kind: str = ""
    task_fingerprint: str = ""
    provider_kind: str = ProviderKind.CLOUD
    provider_name: str = ""
    model_id: str = ""
    backend: str = Backend.API
    endpoint_kind: str = ""
    machine_profile_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    context_tokens: int | None = None
    latency_ms: float | None = None
    time_to_first_token_ms: float | None = None
    prompt_eval_tps: float | None = None
    decode_tps: float | None = None
    peak_memory_gb: float | None = None
    estimated_cost_usd: float | None = None
    tool_call_count: int = 0
    tool_success_count: int = 0
    retry_count: int = 0
    refusal_count: int = 0
    failure_count: int = 0
    validation_status: str = ValidationStatus.UNKNOWN
    user_outcome: str = UserOutcome.UNKNOWN
    content_light_guarantee: bool = True
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ── ProviderRankingSnapshot ───────────────────────────────────────────


PROVIDER_RANKING_SCHEMA_VERSION = "rig.relay.provider_ranking_snapshot.v1"

LOW_SAMPLE_THRESHOLD = 10


class ProviderScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_name: str
    task_success_score: float = 0.0
    cost_efficiency_score: float = 0.0
    latency_score: float = 0.0
    tool_reliability_score: float = 0.0
    privacy_score: float = 0.0
    overall_score: float = 0.0


class ModelScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    provider_name: str
    backend: str = Backend.API
    task_success_score: float = 0.0
    cost_efficiency_score: float = 0.0
    latency_score: float = 0.0
    tool_reliability_score: float = 0.0
    privacy_score: float = 0.0
    local_comfort_score: float | None = None
    overall_score: float = 0.0


class ProviderRankingSnapshot(BaseModel):
    """Content-light snapshot of aggregated provider and model rankings.

    No raw prompts, model outputs, source code, diffs, stdout/stderr
    bodies, secrets, tokens, API keys, or raw private paths.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = PROVIDER_RANKING_SCHEMA_VERSION
    ranking_id: str = ""
    created_at: str = ""
    task_kind: str = ""
    sample_count: int = 0
    provider_scores: list[ProviderScore] = Field(default_factory=list)
    model_scores: list[ModelScore] = Field(default_factory=list)
    confidence_level: str = ConfidenceLevel.LOW
    warnings: list[str] = Field(default_factory=list)


# ── LocalModelComfortScore ────────────────────────────────────────────


LOCAL_COMFORT_SCHEMA_VERSION = "rig.relay.local_model_comfort_score.v1"


class LocalModelComfortScore(BaseModel):
    """Content-light comfort score for running a model locally.

    Evaluates whether a model fits on a given machine profile based on
    observed evidence. No raw prompts, outputs, code, or secrets.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = LOCAL_COMFORT_SCHEMA_VERSION
    model_id: str = ""
    backend: str = Backend.MLX
    quantization: str | None = None
    machine_profile_id: str = ""
    memory_headroom_score: float = 0.0
    speed_score: float = 0.0
    context_score: float = 0.0
    stability_score: float = 0.0
    comfort_category: str = ComfortCategory.NOT_RECOMMENDED
    evidence_count: int = 0
    warnings: list[str] = Field(default_factory=list)


# ── Build helpers ─────────────────────────────────────────────────────


def _create_observation_id() -> str:
    return f"obs_{uuid.uuid4().hex[:12]}"


def _create_ranking_id() -> str:
    return f"rank_{uuid.uuid4().hex[:12]}"


def build_model_observation(
    *,
    task_kind: str,
    task_fingerprint: str,
    provider_kind: str,
    provider_name: str,
    model_id: str,
    backend: str = Backend.API,
    endpoint_kind: str = "",
    machine_profile_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    context_tokens: int | None = None,
    latency_ms: float | None = None,
    time_to_first_token_ms: float | None = None,
    prompt_eval_tps: float | None = None,
    decode_tps: float | None = None,
    peak_memory_gb: float | None = None,
    estimated_cost_usd: float | None = None,
    tool_call_count: int = 0,
    tool_success_count: int = 0,
    retry_count: int = 0,
    refusal_count: int = 0,
    failure_count: int = 0,
    validation_status: str = ValidationStatus.UNKNOWN,
    user_outcome: str = UserOutcome.UNKNOWN,
) -> ModelObservation:
    """Build a new ModelObservation from observed values.

    All arguments are content-light. The observation_id is auto-generated,
    created_at is set to now, and content_light_guarantee is always True.
    """
    return ModelObservation(
        observation_id=_create_observation_id(),
        created_at=datetime.now(UTC).isoformat(),
        task_kind=task_kind,
        task_fingerprint=task_fingerprint,
        provider_kind=provider_kind,
        provider_name=provider_name,
        model_id=model_id,
        backend=backend,
        endpoint_kind=endpoint_kind,
        machine_profile_id=machine_profile_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        context_tokens=context_tokens,
        latency_ms=latency_ms,
        time_to_first_token_ms=time_to_first_token_ms,
        prompt_eval_tps=prompt_eval_tps,
        decode_tps=decode_tps,
        peak_memory_gb=peak_memory_gb,
        estimated_cost_usd=estimated_cost_usd,
        tool_call_count=tool_call_count,
        tool_success_count=tool_success_count,
        retry_count=retry_count,
        refusal_count=refusal_count,
        failure_count=failure_count,
        validation_status=validation_status,
        user_outcome=user_outcome,
    )


# ── Observe tool call ─────────────────────────────────────────────────


def observe_tool_call(
    *,
    session_id: str,
    task_kind: str,
    task_fingerprint: str,
    provider_kind: str,
    provider_name: str,
    model_id: str,
    backend: str = Backend.API,
    tool_call_count: int = 1,
    tool_success_count: int = 0,
    failure_count: int = 0,
    latency_ms: float | None = None,
) -> ModelObservation | None:
    """Build and persist a content-light ModelObservation from a tool execution.

    Checks local observability gates internally. Returns the observation if
    written, None if skipped (e.g. observability disabled).

    All arguments are content-light. The observation is written to the session's
    local observability JSONL via ``log_local_event``.
    """
    observation = build_model_observation(
        task_kind=task_kind,
        task_fingerprint=task_fingerprint,
        provider_kind=provider_kind,
        provider_name=provider_name,
        model_id=model_id,
        backend=backend,
        tool_call_count=tool_call_count,
        tool_success_count=tool_success_count,
        failure_count=failure_count,
        latency_ms=latency_ms,
    )

    from rig_relay.core.telemetry.local import log_local_event

    log_local_event(
        session_id,
        "rig.relay.model_observation.captured",
        observation.model_dump(mode="json"),
    )

    return observation


# ── Observation SHA256 ────────────────────────────────────────────────


def observation_sha256(observation: ModelObservation) -> str:
    """Compute a deterministic SHA256 fingerprint of an observation.

    Uses sorted JSON serialization for deterministic output.
    The hash covers all fields except observation_id and created_at
    (which are non-deterministic).
    """
    payload = observation.model_dump(
        mode="json", exclude={"observation_id", "created_at"}
    )
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Tool receipt emission ─────────────────────────────────────────────


def capture_tool_receipt(
    *, session_id: str, tool_name: str, receipt: dict[str, Any]
) -> None:
    """Emit a content-light tool receipt event to local observability.

    Args:
        session_id: Current session identifier.
        tool_name: Name of the tool that produced the receipt.
        receipt: Content-light receipt dict (no raw stdout/stderr, file
            contents, diffs, or secrets). Typically produced by a tool's
            ``build_receipt()`` method.
    """
    from rig_relay.core.telemetry.constants import EventName
    from rig_relay.core.telemetry.local import log_local_event

    payload = {"tool_name": tool_name, "receipt": receipt}
    log_local_event(session_id, EventName.TOOL_RECEIPT_CAPTURED, payload)


# ── Content-light validation ──────────────────────────────────────────


_FORBIDDEN_OBSERVATION_FIELDS = {
    "raw_prompt",
    "prompt",
    "raw_model_output",
    "model_output",
    "source_code",
    "diff",
    "stdout",
    "stderr",
    "api_key",
    "access_token",
    "refresh_token",
    "private_path",
}


def validate_observation_content_light(observation: ModelObservation) -> list[str]:
    """Validate that a ModelObservation is content-light.

    Returns a list of warning strings. An empty list means the observation
    passed all content-light checks.

    Checks:
    - content_light_guarantee must be True
    - No forbidden field keys in the dumped dict
    - No raw paths or secrets in string fields
    """
    warnings: list[str] = []

    if not observation.content_light_guarantee:
        warnings.append("content_light_guarantee is False")

    dumped = observation.model_dump(mode="json")
    _check_forbidden_keys(dumped, warnings)

    return warnings


def _check_forbidden_keys(
    data: dict[str, Any], warnings: list[str], path: str = ""
) -> None:
    for key, value in data.items():
        full_key = f"{path}.{key}" if path else key
        if key in _FORBIDDEN_OBSERVATION_FIELDS:
            warnings.append(
                f"{full_key}: field key '{key}' is forbidden in content-light records"
            )
        if isinstance(value, dict):
            _check_forbidden_keys(value, warnings, full_key)
        elif isinstance(value, str) and _looks_like_raw_secret(value):
            warnings.append(f"{full_key}: value looks like a raw secret or key")


def _looks_like_raw_secret(value: str) -> bool:
    if value.startswith("sha256:"):
        return False
    import re

    secret_patterns = (
        re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{20,}\b"),
        re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        re.compile(r"(?i)\b-----BEGIN\s+PRIVATE\s+KEY-----"),
    )
    return any(pattern.search(value) for pattern in secret_patterns)


# ── Aggregation helpers ───────────────────────────────────────────────


def aggregate_provider_rankings(
    observations: list[ModelObservation], task_kind: str | None = None
) -> ProviderRankingSnapshot:
    """Aggregate model observations into a provider ranking snapshot.

    If task_kind is provided, only observations matching that task kind
    are included. Otherwise all observations are used.

    When sample_count is below LOW_SAMPLE_THRESHOLD (10), emits a
    low-confidence warning.
    """
    filtered = observations
    if task_kind:
        filtered = [o for o in observations if o.task_kind == task_kind]

    now = datetime.now(UTC).isoformat()
    snapshot = ProviderRankingSnapshot(
        ranking_id=_create_ranking_id(),
        created_at=now,
        task_kind=task_kind or "all",
        sample_count=len(filtered),
        confidence_level=ConfidenceLevel.HIGH,
    )

    if not filtered:
        snapshot.confidence_level = ConfidenceLevel.LOW
        snapshot.warnings.append("No observations available for ranking")
        return snapshot

    # Group by provider
    from collections import defaultdict

    by_provider: dict[str, list[ModelObservation]] = defaultdict(list)
    by_model: dict[str, list[ModelObservation]] = defaultdict(list)

    for obs in filtered:
        by_provider[obs.provider_name].append(obs)
        model_key = f"{obs.provider_name}/{obs.model_id}"
        by_model[model_key].append(obs)

    for provider_name, provider_obs in by_provider.items():
        score = _compute_aggregate_score(provider_obs)
        snapshot.provider_scores.append(
            ProviderScore(
                provider_name=provider_name,
                task_success_score=score.task_success,
                cost_efficiency_score=score.cost_efficiency,
                latency_score=score.latency,
                tool_reliability_score=score.tool_reliability,
                privacy_score=_privacy_score(provider_obs),
                overall_score=score.overall,
            )
        )

    for model_key, model_obs in by_model.items():
        parts = model_key.split("/", 1)
        provider_name = parts[0]
        model_id = parts[1] if len(parts) > 1 else model_key
        score = _compute_aggregate_score(model_obs)
        first = model_obs[0]
        snapshot.model_scores.append(
            ModelScore(
                model_id=model_id,
                provider_name=provider_name,
                backend=first.backend,
                task_success_score=score.task_success,
                cost_efficiency_score=score.cost_efficiency,
                latency_score=score.latency,
                tool_reliability_score=score.tool_reliability,
                privacy_score=_privacy_score(model_obs),
                overall_score=score.overall,
            )
        )

    # Confidence level
    if snapshot.sample_count < LOW_SAMPLE_THRESHOLD:
        snapshot.confidence_level = ConfidenceLevel.LOW
        snapshot.warnings.append(
            f"Low sample count ({snapshot.sample_count}): consider"
            f" collecting more observations before using this ranking"
        )
    elif snapshot.sample_count < LOW_SAMPLE_THRESHOLD * 3:
        snapshot.confidence_level = ConfidenceLevel.MEDIUM

    return snapshot


class _AggregateScore:
    __slots__ = (
        "task_success",
        "cost_efficiency",
        "latency",
        "tool_reliability",
        "overall",
    )

    def __init__(
        self,
        task_success: float = 0.0,
        cost_efficiency: float = 0.0,
        latency: float = 0.0,
        tool_reliability: float = 0.0,
        overall: float = 0.0,
    ) -> None:
        self.task_success = task_success
        self.cost_efficiency = cost_efficiency
        self.latency = latency
        self.tool_reliability = tool_reliability
        self.overall = overall


def _compute_aggregate_score(observations: list[ModelObservation]) -> _AggregateScore:
    """Compute aggregate scores from a list of observations."""
    n = len(observations)
    if n == 0:
        return _AggregateScore()

    total_success = sum(o.tool_success_count for o in observations)
    total_calls = sum(o.tool_call_count for o in observations) or 1
    task_success = total_success / total_calls

    # Cost efficiency: inverse of avg cost per call, capped to [0, 1]
    costs = [
        o.estimated_cost_usd for o in observations if o.estimated_cost_usd is not None
    ]
    cost_efficiency = 1.0
    if costs:
        avg_cost = sum(costs) / len(costs)
        cost_efficiency = max(0.0, min(1.0, 1.0 - avg_cost))

    # Latency: inverse of avg latency, capped to [0, 1]
    latencies = [o.latency_ms for o in observations if o.latency_ms is not None]
    latency = 1.0
    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        latency = max(0.0, min(1.0, 1.0 - (avg_latency / 60000.0)))

    # Tool reliability: success / (success + failure) for tool calls
    total_failures = sum(o.failure_count for o in observations)
    total_tool_ops = total_success + total_failures
    tool_reliability = total_success / total_tool_ops if total_tool_ops > 0 else 1.0

    overall = (task_success + cost_efficiency + latency + tool_reliability) / 4.0

    return _AggregateScore(
        task_success=round(task_success, 4),
        cost_efficiency=round(cost_efficiency, 4),
        latency=round(latency, 4),
        tool_reliability=round(tool_reliability, 4),
        overall=round(overall, 4),
    )


def _privacy_score(observations: list[ModelObservation]) -> float:
    """Compute privacy score based on provider kind.

    Local models get 1.0 (max privacy). Cloud providers get 0.5 (baseline).
    """
    if not observations:
        return 1.0
    n_local = sum(1 for o in observations if o.provider_kind == ProviderKind.LOCAL)
    return round(n_local / len(observations), 4) if n_local > 0 else 0.5


# ── LocalModelComfortScore computation ────────────────────────────────


_COMFORT_THRESHOLDS: dict[str, tuple[float, float]] = {
    ComfortCategory.COMFORTABLE: (0.7, 1.0),
    ComfortCategory.MAYBE: (0.4, 0.7),
    ComfortCategory.NOT_RECOMMENDED: (0.0, 0.4),
}


def compute_local_model_comfort_score(
    model_id: str,
    backend: str,
    machine_profile_id: str,
    *,
    quantization: str | None = None,
    memory_headroom_score: float = 0.0,
    speed_score: float = 0.0,
    context_score: float = 0.0,
    stability_score: float = 0.0,
    evidence_count: int = 0,
) -> LocalModelComfortScore:
    """Compute a local model comfort score from measured or estimated values.

    Categories:
    - comfortable (0.7+): model runs well on this machine
    - maybe (0.4-0.7): model runs but may have constraints
    - not_recommended (<0.4): model is unlikely to perform well

    When evidence_count is 0, a warning about zero evidence is emitted.
    """
    overall = (
        memory_headroom_score + speed_score + context_score + stability_score
    ) / 4.0

    category = ComfortCategory.NOT_RECOMMENDED
    for cat, (low, high) in _COMFORT_THRESHOLDS.items():
        if low <= overall < high:
            category = cat
            break

    warnings: list[str] = []
    if evidence_count == 0:
        warnings.append("No observed evidence — score is estimated, not measured")
    _, not_rec_threshold = _COMFORT_THRESHOLDS[ComfortCategory.NOT_RECOMMENDED]
    if overall < not_rec_threshold:
        warnings.append("Model may not fit on this machine profile")

    return LocalModelComfortScore(
        model_id=model_id,
        backend=backend,
        quantization=quantization,
        machine_profile_id=machine_profile_id,
        memory_headroom_score=round(memory_headroom_score, 4),
        speed_score=round(speed_score, 4),
        context_score=round(context_score, 4),
        stability_score=round(stability_score, 4),
        comfort_category=category,
        evidence_count=evidence_count,
        warnings=warnings,
    )
