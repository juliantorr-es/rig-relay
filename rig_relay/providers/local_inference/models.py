"""Local inference runtime models — Pydantic models for capability probes, benchmarks, and routing.

Content-light by construction: no raw prompts, completions, secrets, or private content.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class LocalRuntimeKind(StrEnum):
    VLLM = "vllm"
    LLAMA_CPP = "llama_cpp"
    MLX_LM = "mlx_lm"
    UNKNOWN = "unknown"


class APIProtocol(StrEnum):
    OPENAI_COMPATIBLE = "openai_compatible"
    CLI_SUBPROCESS = "cli_subprocess"
    PYTHON_MODULE = "python_module"


class PlatformClass(StrEnum):
    CPU = "cpu"
    CUDA = "cuda"
    METAL = "metal"
    VULKAN = "vulkan"
    ROCM = "rocm"
    UNKNOWN = "unknown"


class CapabilityStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    ERROR = "error"
    NOT_TESTED = "not_tested"


class ProbeStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    REFUSED = "refused"


class TaskType(StrEnum):
    CHAT = "chat"
    TOOL_USE = "tool_use"
    STRUCTURED_OUTPUT = "structured_output"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    VISION = "vision"


class PrivacyLocality(StrEnum):
    MUST_BE_LOCAL = "must_be_local"
    PREFER_LOCAL = "prefer_local"
    REMOTE_OK = "remote_ok"


class RoutingConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    FALLBACK = "fallback"


class PolicyResultKind(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CONFIGURED_BUT_UNPROBED = "configured_but_unprobed"
    PROBED_BUT_NOT_BENCHMARKED = "probed_but_not_benchmarked"
    ELIGIBLE_FOR_MANUAL_SELECTION = "eligible_for_manual_selection"
    ELIGIBLE_FOR_POLICY_SELECTION = "eligible_for_policy_selection"
    BLOCKED_BY_MISSING_CAPABILITY = "blocked_by_missing_capability"
    BLOCKED_BY_MISSING_APPROVAL = "blocked_by_missing_approval"
    BLOCKED_BY_DEGRADED_DIAGNOSTICS = "blocked_by_degraded_diagnostics"
    BLOCKED_BY_FAILED_PROBE = "blocked_by_failed_probe"
    BLOCKED_BY_STALE_EVIDENCE = "blocked_by_stale_evidence"
    BLOCKED_BY_POLICY = "blocked_by_policy"


class ExplanationCode(StrEnum):
    STRUCTURED_JSON_MISSING = "structured_json_missing"
    TOOL_CALLING_MISSING = "tool_calling_missing"
    CONTEXT_WINDOW_UNKNOWN = "context_window_unknown"
    STREAMING_UNVERIFIED = "streaming_unverified"
    BENCHMARK_MISSING = "benchmark_missing"
    PROBE_STALE = "probe_stale"
    ENDPOINT_UNCONFIGURED = "endpoint_unconfigured"
    DIAGNOSTICS_DISABLED = "diagnostics_disabled"
    FALLBACK_REQUIRED = "fallback_required"
    EMBEDDINGS_MISSING = "embeddings_missing"
    VISION_MISSING = "vision_missing"
    ENDPOINT_HASH_MISMATCH = "endpoint_hash_mismatch"
    PROBE_FAILED = "probe_failed"
    BENCHMARK_STALE = "benchmark_stale"
    APPROVAL_MISSING = "approval_missing"
    LATENCY_UNVERIFIED = "latency_unverified"


class ApprovalStatus(StrEnum):
    MISSING = "missing"
    DENIED = "denied"
    EXPIRED = "expired"
    SCOPE_MISMATCH = "scope_mismatch"
    APPROVED_FOR_SINGLE_REQUEST = "approved_for_single_request"
    APPROVED_FOR_SESSION_MANUAL_ONLY = "approved_for_session_manual_only"


class ApprovedByMode(StrEnum):
    HUMAN = "human"
    FIXTURE = "fixture"
    POLICY = "policy"


class ExecutionStatusKind(StrEnum):
    BLOCKED = "blocked"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    MALFORMED_RESPONSE = "malformed_response"


class PersistencePolicy(StrEnum):
    METADATA_ONLY = "metadata_only"
    HASH_ONLY = "hash_only"
    EPHEMERAL_DEBUG_DISABLED = "ephemeral_debug_disabled"
    DEBUG_PACKET_REQUIRES_SEPARATE_GATE = "debug_packet_requires_separate_gate"


class RequestClass(StrEnum):
    CHAT = "chat"
    COMPLETION = "completion"
    EMBEDDING = "embedding"
    TOOL_USE = "tool_use"
    STRUCTURED_OUTPUT = "structured_output"
    VISION = "vision"


class ManualExecutionApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.manual_execution_approval.v1", frozen=True
    )
    approval_id: str
    generated_at: str
    expires_at: str = ""
    ttl_seconds: int = 300
    approved_by: ApprovedByMode = ApprovedByMode.FIXTURE
    approved_for_profile: str = ""
    scope_endpoint_hash: str = ""
    scope_task_profile: str = ""
    scope_request_class: RequestClass = RequestClass.CHAT
    scope_max_prompt_bytes: int = 4096
    scope_max_output_tokens: int = 512
    scope_streaming_allowed: bool = False
    scope_tool_calling_allowed: bool = False
    scope_structured_output_allowed: bool = False
    persistence_policy: PersistencePolicy = PersistencePolicy.HASH_ONLY
    approval_hash: str = ""
    redaction_summary: str = "content_light"


class ManualExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.manual_execution_request.v1", frozen=True
    )
    request_id: str
    task_profile: str = "unknown"
    request_class: RequestClass = RequestClass.CHAT
    endpoint_hash: str = ""
    model_safe_id: str = ""
    prompt_sha256: str = ""
    prompt_byte_count: int = 0
    prompt_line_count: int = 0
    prompt_redaction_status: str = "content_light"
    max_output_tokens: int = 512
    temperature: float = 0.0
    streaming_requested: bool = False
    structured_output_requested: bool = False
    tool_calling_requested: bool = False
    created_at: str = ""
    approval_id: str = ""
    selection_policy_receipt_hash: str = ""
    benchmark_summary_hash: str = ""


class ManualExecutionResponseReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.manual_execution_receipt.v1", frozen=True
    )
    execution_id: str
    request_id: str
    generated_at: str
    status: ExecutionStatusKind = ExecutionStatusKind.BLOCKED
    endpoint_hash: str = ""
    model_safe_id: str = ""
    task_profile: str = ""
    request_class: str = ""
    approval_id: str = ""
    selection_policy_status: str = ""
    capability_match_status: str = ""
    prompt_sha256: str = ""
    prompt_byte_count: int = 0
    completion_sha256: str = ""
    completion_byte_count: int = 0
    output_token_count: int = 0
    input_token_count: int = 0
    latency_ms: int = 0
    time_to_first_token_ms: int | None = None
    error_class: str = ""
    blocked_reasons: list[str] = Field(default_factory=list)
    persistence_policy: str = "hash_only"
    redaction_summary: str = "content_light"
    raw_prompt_persisted: bool = False
    raw_completion_persisted: bool = False
    automatic_agent_execution: bool = False


class TaskProfileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_name: str
    display_name: str = ""
    required_capabilities: list[str] = Field(default_factory=list)
    preferred_capabilities: list[str] = Field(default_factory=list)
    min_context_window_tokens: int = 0
    structured_output_required: bool = False
    tool_call_required: bool = False
    streaming_preferred: bool = False
    latency_sensitive: bool = False
    manual_selection_allowed: bool = True
    policy_selection_allowed: bool = False
    fallback_behavior: str = "use_remote"
    description: str = ""


class CapabilityMatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_name: str = ""
    matched_required: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    missing_preferred: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    confidence: RoutingConfidence = RoutingConfidence.FALLBACK
    explanation_codes: list[str] = Field(default_factory=list)


class BenchmarkEvidenceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.benchmark_summary.v1", frozen=True
    )
    summary_id: str
    benchmark_source: str = ""
    sample_count: int = 0
    runtime_url: str = ""
    runtime_engine: str = ""
    endpoint_sha256: str = ""
    model_id_hash: str = ""
    measurement_window_start: str = ""
    measurement_window_end: str = ""
    time_to_first_token_ms_p50: float | None = None
    time_to_first_token_ms_p95: float | None = None
    tokens_per_sec_decode_p50: float | None = None
    tokens_per_sec_decode_p95: float | None = None
    prompt_ingestion_tokens_per_sec_p50: float | None = None
    end_to_end_latency_ms_p50: float | None = None
    end_to_end_latency_ms_p95: float | None = None
    error_count_total: int = 0
    error_count_by_class: dict[str, int] = Field(default_factory=dict)
    cancellation_samples: int = 0
    concurrency_level: int = 0
    context_size_buckets: dict[str, int] = Field(default_factory=dict)
    evidence_status: str = "available"
    stale: bool = False
    redaction_summary: str = "content_light"
    warnings: list[str] = Field(default_factory=list)


class ProviderFallbackDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.provider_fallback_decision.v1", frozen=True
    )
    decision_id: str
    decided_at: str
    local_inference_selected: bool = False
    local_inference_blocked: bool = True
    block_reasons: list[str] = Field(default_factory=list)
    fallback_provider_class: str = ""
    fallback_rationale: str = ""
    requires_fallback_for_missing_capability: bool = False
    requires_fallback_for_missing_benchmark: bool = False
    requires_fallback_for_failed_probe: bool = False
    requires_fallback_for_degraded_diagnostics: bool = False
    requires_fallback_for_missing_approval: bool = False
    evidence_receipts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProbeError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    probe_target: str
    error_class: str
    error_safe_message: str = ""


class HealthSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = "unknown"
    model_count: int = 0
    active_model_id_hash: str = ""
    uptime_estimated_sec: int = 0


class CapabilityProbeCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_completions: CapabilityStatus = CapabilityStatus.NOT_TESTED
    completions: CapabilityStatus = CapabilityStatus.NOT_TESTED
    embeddings: CapabilityStatus = CapabilityStatus.NOT_TESTED
    models_list: CapabilityStatus = CapabilityStatus.NOT_TESTED
    health_endpoint: CapabilityStatus = CapabilityStatus.NOT_TESTED
    streaming: CapabilityStatus = CapabilityStatus.NOT_TESTED
    tool_calling: CapabilityStatus = CapabilityStatus.NOT_TESTED
    structured_json_output: CapabilityStatus = CapabilityStatus.NOT_TESTED
    vision: CapabilityStatus = CapabilityStatus.NOT_TESTED
    reranking: CapabilityStatus = CapabilityStatus.NOT_TESTED
    metrics_endpoint: CapabilityStatus = CapabilityStatus.NOT_TESTED


class CapabilityProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.runtime_capability_probe.v1", frozen=True
    )
    probe_id: str
    runtime_url: str
    runtime_engine: LocalRuntimeKind = LocalRuntimeKind.UNKNOWN
    probed_at: str
    probe_duration_ms: int
    reachable: bool = False
    capabilities: CapabilityProbeCapabilities = Field(
        default_factory=CapabilityProbeCapabilities
    )
    health_summary: HealthSummary = Field(default_factory=HealthSummary)
    errors: list[ProbeError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BenchmarkRunHardwareContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform_class: PlatformClass = PlatformClass.UNKNOWN
    gpu_name_safe: str = ""
    cpu_core_count: int = 0
    ram_gb: float = 0.0


class BenchmarkAggregateStats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time_to_first_token_ms_p50: float = 0.0
    time_to_first_token_ms_p95: float = 0.0
    tokens_per_sec_decode_p50: float = 0.0
    tokens_per_sec_decode_p95: float = 0.0
    end_to_end_latency_ms_p50: float = 0.0
    end_to_end_latency_ms_p95: float = 0.0
    prompt_ingestion_tokens_per_sec_p50: float | None = None
    streaming_chunk_cadence_ms_p50: float | None = None
    tool_call_correctness_rate: float = 0.0
    structured_output_compliance_rate: float = 0.0
    cancellation_success_rate: float | None = None
    memory_peak_mb: int | None = None
    cold_start_sec: float | None = None
    model_load_time_sec: float | None = None


class BenchmarkRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.benchmark_run.v1", frozen=True
    )
    run_id: str
    runtime_url: str
    runtime_engine: LocalRuntimeKind = LocalRuntimeKind.UNKNOWN
    model_id_hash: str = ""
    started_at: str
    ended_at: str
    duration_ms: int
    sample_count: int
    aggregate_stats: BenchmarkAggregateStats = Field(
        default_factory=BenchmarkAggregateStats
    )
    hardware_context: BenchmarkRunHardwareContext = Field(
        default_factory=BenchmarkRunHardwareContext
    )
    warnings: list[str] = Field(default_factory=list)
    errors: list[ProbeError] = Field(default_factory=list)


class BenchmarkSample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.benchmark_sample.v1", frozen=True
    )
    sample_id: str
    run_id: str
    prompt_sha256: str
    prompt_token_count: int = 0
    completion_sha256: str = ""
    completion_token_count: int = 0
    tool_calls_count: int = 0
    status: ProbeStatus = ProbeStatus.COMPLETED
    duration_ms: int = 0
    time_to_first_token_ms: float | None = None
    tokens_per_sec_decode: float | None = None
    streaming_chunk_count: int | None = None
    streaming_chunk_interval_ms_p50: float | None = None
    tool_call_correct: bool | None = None
    structured_output_complies: bool | None = None
    temperature_zero_deterministic: bool | None = None
    cancellation_requested_at_ms: int | None = None
    cancellation_effective_ms: int | None = None
    error_class: str | None = None
    error_safe_message: str | None = None
    server_reported_tokens_match: bool | None = None
    token_accounting_discrepancy: str | None = None


class TaskProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_type: TaskType = TaskType.CHAT
    context_size_tokens: int = 0
    latency_target_ms: int = 0
    privacy_locality: PrivacyLocality = PrivacyLocality.REMOTE_OK
    tool_call_required: bool = False
    structured_output_required: bool = False


class EvidenceReceiptRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt_kind: str
    receipt_id: str


class AlternativeRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_url: str
    runtime_engine: str = ""
    excluded_reason: str
    matched_dimensions: list[str] = Field(default_factory=list)
    failed_dimensions: list[str] = Field(default_factory=list)


class RoutingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.routing_decision.v1", frozen=True
    )
    decision_id: str
    decided_at: str
    task_profile: TaskProfile = Field(default_factory=TaskProfile)
    selected_runtime_url: str
    selected_runtime_engine: str = ""
    decision_rationale: str
    confidence: RoutingConfidence = RoutingConfidence.FALLBACK
    matched_dimensions: list[str] = Field(default_factory=list)
    unmatched_dimensions: list[str] = Field(default_factory=list)
    evidence_receipts: list[EvidenceReceiptRef] = Field(default_factory=list)
    alternatives_considered: list[AlternativeRuntime] = Field(default_factory=list)


@dataclass
class RuntimeDescriptor:
    runtime_id: str
    runtime_kind: LocalRuntimeKind = LocalRuntimeKind.UNKNOWN
    endpoint_url: str = ""
    api_protocol: APIProtocol = APIProtocol.OPENAI_COMPATIBLE
    platform_class: PlatformClass = PlatformClass.UNKNOWN
    backend_engine: str = ""
    model_format: str = ""


__all__ = [
    "APIProtocol",
    "AlternativeRuntime",
    "ApprovalStatus",
    "ApprovedByMode",
    "BenchmarkAggregateStats",
    "BenchmarkEvidenceSummary",
    "BenchmarkRun",
    "BenchmarkRunHardwareContext",
    "BenchmarkSample",
    "CapabilityMatchResult",
    "CapabilityProbeCapabilities",
    "CapabilityProbeResult",
    "CapabilityStatus",
    "EvidenceReceiptRef",
    "ExecutionStatusKind",
    "ExplanationCode",
    "HealthSummary",
    "LocalRuntimeKind",
    "ManualExecutionApproval",
    "ManualExecutionRequest",
    "ManualExecutionResponseReceipt",
    "PersistencePolicy",
    "PlatformClass",
    "PolicyResultKind",
    "PrivacyLocality",
    "ProbeError",
    "ProbeStatus",
    "ProviderFallbackDecision",
    "RequestClass",
    "RoutingConfidence",
    "RoutingDecision",
    "RuntimeDescriptor",
    "TaskProfile",
    "TaskProfileSpec",
    "TaskType",
]
