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
    OMLX = "omlx"
    RIGGED_MLX = "rigged_mlx"
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


class OutputContractKind(StrEnum):
    NONE = "none"
    NON_EMPTY_TEXT = "non_empty_text"
    VALID_JSON = "valid_json"
    JSON_OBJECT = "json_object"
    JSON_SCHEMA = "json_schema"
    CONTAINS_REQUIRED_KEYS = "contains_required_keys"
    MAX_LENGTH = "max_length"
    TOOL_CALL_SHAPE = "tool_call_shape"
    REFUSAL_OR_BLOCKED_ALLOWED = "refusal_or_blocked_allowed"


class ContractResultStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    EXECUTION_FAILED = "execution_failed"
    BLOCKED_BEFORE_EXECUTION = "blocked_before_execution"


class ComparisonStatus(StrEnum):
    NO_REFERENCE = "no_reference"
    COMPARABLE = "comparable"
    COMPARISON_PASSED = "comparison_passed"
    COMPARISON_FAILED = "comparison_failed"
    COMPARISON_UNAVAILABLE = "comparison_unavailable"


class PromptSourceKind(StrEnum):
    INLINE_EPHEMERAL = "inline_ephemeral"
    PROMPT_FILE_EPHEMERAL = "prompt_file_ephemeral"
    HASHED_FIXTURE = "hashed_fixture"


class ShadowScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.shadow_scenario.v1", frozen=True
    )
    scenario_id: str
    task_profile: str = "chat_light"
    request_class: RequestClass = RequestClass.CHAT
    endpoint_hash: str = ""
    prompt_source: PromptSourceKind = PromptSourceKind.HASHED_FIXTURE
    prompt_sha256: str = ""
    prompt_byte_count: int = 0
    prompt_text_synthetic_safe: str = ""
    expected_output_contract: OutputContractKind = OutputContractKind.NON_EMPTY_TEXT
    required_keys: list[str] = Field(default_factory=list)
    max_length_chars: int = 0
    max_output_tokens: int = 512
    temperature: float = 0.0
    structured_output_required: bool = False
    tool_calling_required: bool = False
    streaming_allowed: bool = False
    reference_evidence_hash: str = ""
    persistence_policy: str = "hash_only"
    redaction_summary: str = "content_light"


class ShadowRunReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.shadow_run_receipt.v1", frozen=True
    )
    shadow_run_id: str
    scenario_id: str
    generated_at: str
    status: str = "blocked"
    task_profile: str = ""
    request_class: str = ""
    endpoint_hash: str = ""
    model_safe_id: str = ""
    approval_id: str = ""
    selection_policy_status: str = ""
    manual_execution_receipt_ref: str = ""
    prompt_sha256: str = ""
    prompt_byte_count: int = 0
    completion_sha256: str = ""
    completion_byte_count: int = 0
    latency_ms: int = 0
    output_token_count: int = 0
    input_token_count: int = 0
    output_contract: str = ""
    contract_result: str = ""
    contract_failure_codes: list[str] = Field(default_factory=list)
    comparison_result: str = ""
    fallback_required: bool = False
    blocked_reasons: list[str] = Field(default_factory=list)
    redaction_summary: str = "content_light"
    raw_prompt_persisted: bool = False
    raw_completion_persisted: bool = False
    automatic_agent_execution: bool = False
    agent_state_mutated: bool = False
    tool_execution_allowed: bool = False
    file_mutation_allowed: bool = False
    provider_fallback_execution_allowed: bool = False
    shadow_output_promotable_to_user: bool = False
    shadow_output_promotable_to_training: bool = False


class OutputContractResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.output_contract_result.v1", frozen=True
    )
    result_id: str
    scenario_id: str
    contract: str = ""
    status: str = ""
    failure_codes: list[str] = Field(default_factory=list)
    completion_sha256: str = ""
    completion_byte_count: int = 0
    completion_is_json: bool = False
    completion_top_level_type: str = ""
    completion_required_keys_found: list[str] = Field(default_factory=list)
    completion_required_keys_missing: list[str] = Field(default_factory=list)
    completion_char_count: int = 0
    max_length_exceeded: bool = False


class ReferenceComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.reference_comparison.v1", frozen=True
    )
    comparison_id: str
    scenario_id: str
    reference_hash: str = ""
    reference_contract_result: str = ""
    comparison_status: str = "no_reference"
    completion_hash_match: bool = False
    contract_result_match: bool = False
    latency_class_match: bool = False
    token_count_class_match: bool = False
    comparison_details: str = ""


class ShadowSafetyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.shadow_safety_policy.v1", frozen=True
    )
    policy_id: str
    generated_at: str
    automatic_agent_execution: bool = False
    agent_state_mutated: bool = False
    tool_execution_allowed: bool = False
    file_mutation_allowed: bool = False
    provider_fallback_execution_allowed: bool = False
    shadow_output_promotable_to_user: bool = False
    shadow_output_promotable_to_training: bool = False
    raw_prompt_persisted: bool = False
    raw_completion_persisted: bool = False


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


class AutoRoutingStatus(StrEnum):
    AUTO_ROUTING_DISABLED = "auto_routing_disabled"
    ELIGIBLE_FOR_AUTO_ROUTING = "eligible_for_auto_routing"
    BLOCKED_BY_NO_RUNTIME = "blocked_by_no_runtime"
    BLOCKED_BY_MODEL_MISSING = "blocked_by_model_missing"
    BLOCKED_BY_DOWNLOAD_REQUIRED = "blocked_by_download_required"
    BLOCKED_BY_SERVER_NOT_RUNNING = "blocked_by_server_not_running"
    BLOCKED_BY_FAILED_HEALTH = "blocked_by_failed_health"
    BLOCKED_BY_MISSING_CAPABILITY = "blocked_by_missing_capability"
    BLOCKED_BY_MISSING_BENCHMARK = "blocked_by_missing_benchmark"
    BLOCKED_BY_MISSING_SHADOW_EVIDENCE = "blocked_by_missing_shadow_evidence"
    BLOCKED_BY_SHADOW_REGRESSION = "blocked_by_shadow_regression"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    BLOCKED_BY_DEBUG_RETENTION_POLICY = "blocked_by_debug_retention_policy"
    FALLBACK_TO_REMOTE = "fallback_to_remote"


class ProposalActionType(StrEnum):
    ANSWER_ONLY = "answer_only"
    PLANNING_NOTE = "planning_note"
    TOOL_CALL_PROPOSAL = "tool_call_proposal"
    FILE_MUTATION_PROPOSAL = "file_mutation_proposal"
    SHELL_COMMAND_PROPOSAL = "shell_command_proposal"
    UNKNOWN_OR_UNSAFE = "unknown_or_unsafe"


class RetentionMode(StrEnum):
    DISABLED = "disabled"
    METADATA_ONLY = "metadata_only"
    REDACTED_LOCAL = "redacted_local"
    RAW_LOCAL_TTL = "raw_local_ttl"
    RAW_LOCAL_UNTIL_SESSION_END = "raw_local_until_session_end"
    RAW_LOCAL_DEBUG_PACKET = "raw_local_debug_packet"


class BackendLifecycleStatus(StrEnum):
    NOT_INSTALLED = "not_installed"
    INSTALLED = "installed"
    DOWNLOAD_PLANNED = "download_planned"
    DOWNLOADING = "downloading"
    MODEL_READY = "model_ready"
    STARTING = "starting"
    RUNNING = "running"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class RuntimeBackend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.runtime_backend_registry.v1", frozen=True
    )
    backend_id: str
    display_name: str = ""
    executable_name: str = ""
    default_host: str = "127.0.0.1"
    default_port: int = 11434
    health_endpoint: str = "/health"
    openai_base_url: str = ""
    pull_command_template: str = ""
    start_command_template: str = ""
    stop_strategy: str = "process_sigterm"
    supported_platforms: list[str] = Field(default_factory=list)
    expected_model_formats: list[str] = Field(default_factory=list)
    risk_level: str = "medium"
    content_exposure_notes: str = ""
    enabled_default: bool = False
    auto_start_allowed_default: bool = False
    auto_download_allowed_default: bool = False
    raw_retention_allowed_default: bool = False


class ModelAcquisitionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.model_acquisition_plan.v1", frozen=True
    )
    plan_id: str
    generated_at: str
    backend_id: str = ""
    model_id: str = ""
    model_id_hash: str = ""
    source: str = ""
    license_family: str = ""
    estimated_size_bytes: int = 0
    estimated_size_unknown: bool = True
    storage_policy: str = "local_cache"
    backend_managed_storage: bool = False
    command_hash: str = ""
    command_safe_preview: str = ""
    network_required: bool = True
    disk_required_unknown: bool = True
    approval_required: bool = True
    approval_status: str = "blocked"
    live_download_enabled: bool = False
    download_executed: bool = False
    blocked_reasons: list[str] = Field(default_factory=list)
    redaction_summary: str = "content_light"


class ServerLifecycleReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.server_lifecycle_receipt.v1", frozen=True
    )
    lifecycle_id: str
    generated_at: str
    backend_id: str = ""
    model_id_hash: str = ""
    command_hash: str = ""
    command_safe_preview: str = ""
    cwd_policy: str = "temp_dir"
    env_policy: str = "scrubbed"
    host: str = "127.0.0.1"
    port: int = 0
    pid: int = 0
    started_by_rig: bool = False
    health_status: str = "unknown"
    timeout_sec: int = 30
    stdout_stderr_persistence_policy: str = "disabled"
    raw_log_persisted: bool = False
    remote_network_exposed: bool = False
    localhost_only: bool = True
    port_collision_detected: bool = False
    stopped_by_rig: bool = False
    lifecycle_action: str = "plan"
    blocked_reasons: list[str] = Field(default_factory=list)
    redaction_summary: str = "content_light"


class AutoRoutingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.auto_routing_decision.v1", frozen=True
    )
    decision_id: str
    generated_at: str
    status: str = "auto_routing_disabled"
    backend_id: str = ""
    model_id_hash: str = ""
    endpoint_url: str = ""
    health_check_passed: bool = False
    capability_match_passed: bool = False
    benchmark_evidence_available: bool = False
    shadow_evidence_available: bool = False
    task_profile: str = ""
    routing_confidence: str = "fallback"
    fallback_required: bool = True
    blocked_reasons: list[str] = Field(default_factory=list)
    redaction_summary: str = "content_light"


class RawRetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.raw_retention_policy.v1", frozen=True
    )
    policy_id: str
    generated_at: str
    mode: str = "disabled"
    retention_dir: str = ""
    ttl_seconds: int = 0
    max_bytes_per_session: int = 0
    export_to_telemetry_allowed: bool = False
    redaction_scan_enabled: bool = True
    user_visible_disclosure: str = "Raw local inference transcripts are disabled."
    includes_credentials_protection: bool = True
    includes_private_repo_protection: bool = True


class LocalOutputProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.local_output_proposal.v1", frozen=True
    )
    proposal_id: str
    source_execution_receipt: str = ""
    model_safe_id: str = ""
    prompt_sha256: str = ""
    completion_sha256: str = ""
    proposed_action_type: str = "answer_only"
    risk_classification: str = "low"
    required_gate: str = ""
    default_status: str = "blocked_pending_gate"
    raw_output_persisted: bool = False
    tool_execution_allowed: bool = False
    file_mutation_allowed: bool = False
    shell_execution_allowed: bool = False
    redaction_summary: str = "content_light"
    blocked_reasons: list[str] = Field(default_factory=list)


class CapacityClass(StrEnum):
    TINY_CPU = "tiny_cpu"
    SMALL_CPU = "small_cpu"
    APPLE_SILICON_LIGHT = "apple_silicon_light"
    APPLE_SILICON_MEDIUM = "apple_silicon_medium"
    APPLE_SILICON_HEAVY = "apple_silicon_heavy"
    CUDA_LIGHT = "cuda_light"
    CUDA_MEDIUM = "cuda_medium"
    CUDA_HEAVY = "cuda_heavy"
    UNKNOWN = "unknown"


class RecommendationStatus(StrEnum):
    RECOMMENDED = "recommended"
    POSSIBLE_BUT_RISKY = "possible_but_risky"
    NOT_RECOMMENDED = "not_recommended"
    UNKNOWN_CAPACITY = "unknown_capacity"
    BLOCKED_BY_POLICY = "blocked_by_policy"


class ScientificComparisonStatus(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    LOCAL_BETTER_LATENCY = "local_better_latency"
    CLOUD_BETTER_LATENCY = "cloud_better_latency"
    LOCAL_BETTER_COST = "local_better_cost"
    CLOUD_BETTER_QUALITY = "cloud_better_quality"
    LOCAL_CONTRACT_PASSED = "local_contract_passed"
    LOCAL_CONTRACT_FAILED = "local_contract_failed"
    CLOUD_REFERENCE_MISSING = "cloud_reference_missing"
    MIXED_RESULTS = "mixed_results"
    REGRESSION_DETECTED = "regression_detected"
    PROMOTION_CANDIDATE = "promotion_candidate"
    BLOCKED_BY_POLICY = "blocked_by_policy"


class BenchmarkMode(StrEnum):
    DRY_RUN_PLAN = "dry_run_plan"
    FAKE_ENDPOINT = "fake_endpoint"
    LOCAL_ENDPOINT_LIVE = "local_endpoint_live"
    MANAGED_SERVER_LIVE = "managed_server_live"
    CLOUD_REFERENCE_FIXTURE = "cloud_reference_fixture"
    CLOUD_REFERENCE_LIVE = "cloud_reference_live"


class CapacityScan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.capacity_scan.v1", frozen=True
    )
    scan_id: str
    collected_at: str
    capacity_class: str = "unknown"
    os_name: str = ""
    cpu_arch: str = ""
    cpu_core_count: int = 0
    ram_total_mb: int = 0
    gpu_detected: bool = False
    gpu_class: str = ""
    metal_available: bool = False
    cuda_available: bool = False
    rocm_available: bool = False
    disk_free_model_path_mb: int = 0
    runtimes_detected: list[str] = Field(default_factory=list)
    python_version: str = ""
    redaction_summary: str = "content_light"


class ModelCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    backend_id: str = ""
    model_family: str = ""
    model_size_class: str = ""
    quantization_hint: str = ""
    context_window_hint: int = 0
    estimated_disk_bytes: int = 0
    estimated_ram_vram_bytes: int = 0
    expected_runtime: str = ""
    expected_task_profiles: list[str] = Field(default_factory=list)
    risk_level: str = "medium"
    license_notes: str = ""
    source: str = "registry"
    download_requires_approval: bool = True
    recommendation_status: str = "not_recommended"
    reasons: list[str] = Field(default_factory=list)


class ModelFitPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.model_fit_plan.v1", frozen=True
    )
    plan_id: str
    generated_at: str
    capacity_class: str = ""
    candidates: list[ModelCandidate] = Field(default_factory=list)
    recommendations_count: int = 0
    redaction_summary: str = "content_light"


class CapacityBenchmarkPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.capacity_benchmark_plan.v1", frozen=True
    )
    plan_id: str
    generated_at: str
    mode: str = "dry_run_plan"
    endpoint_url: str = ""
    backend_id: str = ""
    model_safe_id: str = ""
    task_profiles: list[str] = Field(default_factory=list)
    sample_count: int = 0
    dimensions: list[str] = Field(default_factory=list)
    approval_required: bool = True
    blocked_reasons: list[str] = Field(default_factory=list)
    redaction_summary: str = "content_light"


class CapacityBenchmarkSample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.capacity_benchmark_sample.v1", frozen=True
    )
    sample_id: str
    plan_id: str
    trace_id: str = ""
    mode: str = ""
    task_profile: str = ""
    prompt_sha256: str = ""
    completion_sha256: str = ""
    ttft_ms: int = 0
    latency_ms: int = 0
    tokens_per_sec: float = 0.0
    input_token_count: int = 0
    output_token_count: int = 0
    concurrency_level: int = 1
    error_class: str = ""
    status: str = ""
    contract_result: str = ""
    memory_peak_mb: int = 0
    power_estimate_watts: float | None = None
    thermal_state: str = ""
    redaction_summary: str = "content_light"


class CorrelatedTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.correlated_trace_event.v1", frozen=True
    )
    trace_id: str
    span_id: str
    parent_span_id: str = ""
    event_type: str = ""
    provider_id: str = ""
    runtime_backend_id: str = ""
    model_hash: str = ""
    task_profile: str = ""
    scenario_id: str = ""
    benchmark_run_id: str = ""
    execution_receipt_id: str = ""
    shadow_run_id: str = ""
    proposal_id: str = ""
    routing_decision_id: str = ""
    fallback_decision_id: str = ""
    status: str = ""
    latency_ms: int = 0
    error_class: str = ""
    timestamp: str = ""
    redaction_summary: str = "content_light"


class ScientificComparisonReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.scientific_comparison_report.v1", frozen=True
    )
    report_id: str
    generated_at: str
    task_profile: str = ""
    scenario_id: str = ""
    local_provider_id: str = ""
    cloud_provider_id: str = ""
    local_model_hash: str = ""
    cloud_model_hash: str = ""
    local_contract_result: str = ""
    cloud_contract_result: str = ""
    local_ttft_ms: int = 0
    cloud_ttft_ms: int = 0
    local_latency_ms: int = 0
    cloud_latency_ms: int = 0
    local_tokens_per_sec: float = 0.0
    cloud_tokens_per_sec: float = 0.0
    local_error_rate: float = 0.0
    cloud_error_rate: float = 0.0
    local_fallback_rate: float = 0.0
    cloud_reference_available: bool = False
    comparison_status: str = "insufficient_evidence"
    local_privacy_score: float = 1.0
    local_cost_estimate_cents: int = 0
    cloud_cost_estimate_cents: int = 0
    redaction_summary: str = "content_light"


class TelemetrySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.telemetry_summary.v1", frozen=True
    )
    summary_id: str
    generated_at: str
    capacity_class: str = ""
    runtimes_detected: list[str] = Field(default_factory=list)
    benchmark_runs_completed: int = 0
    comparison_reports_generated: int = 0
    local_vs_cloud_comparisons: int = 0
    raw_prompt_telemetry: int = 0
    raw_completion_telemetry: int = 0
    telemetry_export_allowed: bool = False
    redaction_summary: str = "content_light"


class RecommendedRoute(StrEnum):
    LOCAL_FIRST = "local_first"
    SHADOW_FIRST = "shadow_first"
    CLOUD_ESCALATION = "cloud_escalation"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class DatasetExportMode(StrEnum):
    LOCAL_ONLY = "local_only"
    AGGREGATE_ONLY = "aggregate_only"
    DEIDENTIFIED_DERIVED = "deidentified_derived"
    EXPORT_BLOCKED = "export_blocked"


class CapabilityEvidenceRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.capability_evidence_row.v1", frozen=True
    )
    evidence_id: str
    generated_at: str
    trace_id: str = ""
    session_id_hash: str = ""
    machine_class: str = ""
    hardware_summary_hash: str = ""
    runtime_backend_id: str = ""
    runtime_kind: str = ""
    model_safe_id: str = ""
    model_family: str = ""
    model_size_class: str = ""
    quantization_hint: str = ""
    context_bucket: str = ""
    task_profile: str = ""
    request_class: str = ""
    output_contract: str = ""
    contract_passed: bool = False
    contract_failure_codes: list[str] = Field(default_factory=list)
    structured_output_passed: bool | None = None
    tool_call_shape_passed: bool | None = None
    proposal_type: str = ""
    required_gate: str = ""
    mutation_risk: str = "low"
    proposal_gate_status: str = ""
    local_latency_ms: int = 0
    local_ttft_ms: int = 0
    local_tokens_per_sec: float = 0.0
    local_input_tokens: int = 0
    local_output_tokens: int = 0
    memory_pressure_class: str = ""
    disk_pressure_class: str = ""
    energy_joules_estimate: float | None = None
    joules_per_token_estimate: float | None = None
    cloud_reference_available: bool = False
    cloud_contract_passed: bool | None = None
    cloud_latency_ms: int | None = None
    local_vs_cloud_status: str = ""
    fallback_required: bool = False
    fallback_reason_codes: list[str] = Field(default_factory=list)
    recommended_route: str = "insufficient_evidence"
    confidence: str = "insufficient"
    raw_prompt_persisted: bool = False
    raw_completion_persisted: bool = False
    telemetry_exportable: bool = False
    redaction_summary: str = "content_light"
    source_artifact_refs: list[str] = Field(default_factory=list)


class CapabilityEvidenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.capability_evidence_report.v1", frozen=True
    )
    report_id: str
    generated_at: str
    total_rows: int = 0
    rows_by_machine_class: dict[str, int] = Field(default_factory=dict)
    rows_by_task_profile: dict[str, int] = Field(default_factory=dict)
    contract_pass_rate: float = 0.0
    local_latency_p50: float = 0.0
    local_latency_p95: float = 0.0
    local_tokens_per_sec_p50: float = 0.0
    local_tokens_per_sec_p95: float = 0.0
    cloud_reference_coverage: float = 0.0
    local_better_latency_rate: float = 0.0
    promotion_candidate_count: int = 0
    insufficient_evidence_count: int = 0
    redaction_summary: str = "content_light"


class CapabilityRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.capability_recommendation.v1", frozen=True
    )
    recommendation_id: str
    generated_at: str
    task_profile: str = ""
    request_class: str = ""
    recommended_route: str = "insufficient_evidence"
    confidence: str = "insufficient"
    reasons: list[str] = Field(default_factory=list)
    evidence_row_count: int = 0
    source_report_hash: str = ""


class DatasetExportPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.local_inference.dataset_export_policy.v1", frozen=True
    )
    policy_id: str
    generated_at: str
    mode: str = "aggregate_only"
    exportable_fields: list[str] = Field(default_factory=list)
    non_exportable_fields: list[str] = Field(default_factory=list)
    raw_prompt_exported: bool = False
    raw_completion_exported: bool = False
    raw_tool_output_exported: bool = False
    redaction_summary: str = "content_light"


__all__ = [
    "APIProtocol",
    "AlternativeRuntime",
    "AutoRoutingDecision",
    "AutoRoutingStatus",
    "BackendLifecycleStatus",
    "BenchmarkAggregateStats",
    "BenchmarkEvidenceSummary",
    "BenchmarkRun",
    "BenchmarkRunHardwareContext",
    "BenchmarkSample",
    "CapabilityEvidenceReport",
    "CapabilityEvidenceRow",
    "CapabilityMatchResult",
    "CapabilityProbeCapabilities",
    "CapabilityProbeResult",
    "CapabilityRecommendation",
    "CapabilityStatus",
    "CapacityBenchmarkPlan",
    "CapacityBenchmarkSample",
    "CapacityClass",
    "CapacityScan",
    "ComparisonStatus",
    "ContractResultStatus",
    "CorrelatedTraceEvent",
    "DatasetExportMode",
    "DatasetExportPolicy",
    "EvidenceReceiptRef",
    "ExecutionStatusKind",
    "ExplanationCode",
    "HealthSummary",
    "LocalOutputProposal",
    "LocalRuntimeKind",
    "ManualExecutionApproval",
    "ManualExecutionRequest",
    "ManualExecutionResponseReceipt",
    "ModelAcquisitionPlan",
    "OutputContractKind",
    "OutputContractResult",
    "PersistencePolicy",
    "PlatformClass",
    "PolicyResultKind",
    "PrivacyLocality",
    "ProbeError",
    "ProbeStatus",
    "PromptSourceKind",
    "ProposalActionType",
    "ProviderFallbackDecision",
    "RawRetentionPolicy",
    "RecommendedRoute",
    "ReferenceComparison",
    "RequestClass",
    "RetentionMode",
    "RoutingConfidence",
    "RoutingDecision",
    "RuntimeBackend",
    "RuntimeDescriptor",
    "ScientificComparisonStatus",
    "ScientificComparisonStatus",
    "ServerLifecycleReceipt",
    "ShadowRunReceipt",
    "ShadowSafetyPolicy",
    "ShadowScenario",
    "TaskProfile",
    "TaskProfileSpec",
    "TaskType",
]
