"""Rig-governed local runtime models — typed application-service boundary.

Two-layer design:
  LocalInferenceResponse     — authorized visible content for the UI/session consumer
  LocalInferenceEvidenceReceipt — content-light evidence for the canonical ledger

Content-light evidence uses SHA256 hashes for all content-derived references
and NEVER contains raw prompts, completions, secrets, or private content.

OMLX-informed patterns (Apache 2.0 attribution):
  - CacheEvidenceMetrics rolling window structure informed by OMLX CacheRateTracker
  - ModelTypeClass taxonomy informed by OMLX model_discovery.py model_type detection
  - EnrichedRuntimeCapabilities probe targets informed by OMLX server.py endpoint layout
  - ToolCallProposal format informed by OMLX api/tool_calling.py multi-family parsing
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RuntimeLifecycleState(StrEnum):
    UNCONFIGURED = "unconfigured"
    DISCOVERED = "discovered"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    ERROR = "error"


class ModelTypeClass(StrEnum):
    LLM = "llm"
    VLM = "vlm"
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    AUDIO_STT = "audio_stt"
    AUDIO_TTS = "audio_tts"
    UNKNOWN = "unknown"


class CapabilityPosture(StrEnum):
    """Honest posture for v1 capability reporting — no false 'post-v1' labels."""

    SUPPORTED = "supported"
    V1_REQUIRED_PENDING = "v1_required_pending_implementation"
    DEFERRED = "deferred"


class TaskKind(StrEnum):
    CHAT = "chat"
    TOOL_PROPOSAL = "tool_proposal"
    STRUCTURED_OUTPUT = "structured_output"
    CLASSIFICATION = "classification"


class ExecutionStatus(StrEnum):
    EXECUTED = "executed"
    BLOCKED = "blocked"
    REFUSED = "refused"
    TIMED_OUT = "timed_out"
    ERROR = "error"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"


class RefusalReason(StrEnum):
    RUNTIME_NOT_CONFIGURED = "runtime_not_configured"
    RUNTIME_UNHEALTHY = "runtime_unhealthy"
    CAPABILITY_UNSUPPORTED = "capability_unsupported"
    PRIVACY_CLASSIFICATION_DENIED = "privacy_classification_denied"
    TASK_NOT_ADMITTED = "task_not_admitted"
    CONTEXT_BLOCKED_BY_POLICY = "context_blocked_by_policy"
    TOOL_CALL_DETECTED = "tool_call_detected"
    OUTPUT_VALIDATION_FAILED = "output_validation_failed"


class ContextPrivacyClass(StrEnum):
    """Privacy classification of the context being submitted to the runtime."""

    PUBLIC_SAFE = "public_safe"
    PRIVATE_LOCAL = "private_local"
    SECRET_BEARING = "secret_bearing"


class CachePrivacyClass(StrEnum):
    LOCAL_KV_CACHE = "local_kv_cache"
    LOCAL_SSD_CACHE = "local_ssd_cache"
    LOCAL_HOT_CACHE = "local_hot_cache"
    CLOUD_PROVIDER_CACHE = "cloud_provider_cache"
    NOT_APPLICABLE = "not_applicable"


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"


class ToolCallProposal(BaseModel):
    """Parsed tool call from model output — proposal only, never executed directly."""

    model_config = ConfigDict(extra="forbid")
    call_id: str = ""
    tool_name: str = ""
    arguments: str = ""
    rationale: str = ""


class LocalInferenceResponse(BaseModel):
    """Authorized visible response for UI/session consumer.

    Contains the actual model output text and parsed tool-call proposals.
    This is transient — consumer receives it, evidence ledger does not.
    """

    model_config = ConfigDict(extra="forbid")
    content: str = ""
    finish_reason: FinishReason = FinishReason.STOP
    tool_call_proposals: list[ToolCallProposal] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    time_to_first_token_ms: int | None = None
    model_id_hash: str = ""
    cache_hit: bool = False
    evidence_receipt_id: str = ""


class LocalInferenceEvidenceReceipt(BaseModel):
    """Content-light evidence receipt for the canonical ledger.

    SHA256 hashes only. Never contains raw prompts, completions, or model output.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.relay.local_inference_evidence_receipt.v1", frozen=True
    )
    receipt_id: str = ""
    session_id: str = ""
    task_id_hash: str = ""
    status: ExecutionStatus = ExecutionStatus.BLOCKED
    refusal_reason: RefusalReason | None = None
    prompt_sha256: str = ""
    output_sha256: str = ""
    output_length_chars: int = 0
    model_id_hash: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    time_to_first_token_ms: int | None = None
    finish_reason: FinishReason | None = None
    cache_hit: bool = False
    tool_call_count: int = 0
    tool_call_ids: list[str] = Field(default_factory=list)
    tool_proposals_routed_to_governance: bool = False
    context_privacy_class: ContextPrivacyClass = ContextPrivacyClass.PRIVATE_LOCAL
    content_light: bool = True
    created_at: str = ""


class RuntimeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_kind: str = "unknown"
    runtime_version: str = ""
    display_name: str = ""
    endpoint_url: str = ""
    platform_class: str = "unknown"
    api_protocol: str = "openai_compatible"
    configured_at: str = ""
    configured_by_sha256: str = ""


class RuntimeHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: RuntimeLifecycleState = RuntimeLifecycleState.UNCONFIGURED
    reachable: bool = False
    health_endpoint_status: str = "not_probed"
    health_latency_ms: int = 0
    uptime_seconds: int | None = None
    memory_usage_mb: int | None = None
    gpu_available: bool = False
    active_model_count: int = 0
    probed_at: str = ""
    warnings: list[str] = Field(default_factory=list)


class ModelInventoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id_hash: str = ""
    model_type: ModelTypeClass = ModelTypeClass.UNKNOWN
    display_name_safe: str = ""
    is_loaded: bool = False
    is_pinned: bool = False
    estimated_size_gb: float = 0.0
    capabilities: list[str] = Field(default_factory=list)
    license_family_safe: str = ""
    source_safe: str = ""


class EnrichedRuntimeCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_completions: str = "not_tested"
    completions: str = "not_tested"
    embeddings: str = "v1_required_pending_implementation"
    reranking: str = "v1_required_pending_implementation"
    anthropic_messages: str = "deferred"
    models_list: str = "not_tested"
    health_endpoint: str = "not_tested"
    api_status: str = "not_tested"
    streaming: str = "v1_required_pending_implementation"
    tool_calling: str = "v1_required_pending_implementation"
    structured_json_output: str = "v1_required_pending_implementation"
    vision: str = "v1_required_pending_implementation"
    cache_metrics: str = "v1_required_pending_implementation"
    server_metrics: str = "v1_required_pending_implementation"
    runtime_version: str = "not_tested"


class RuntimeCachePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cache_mode: str = "local_runtime_kv"
    privacy_class: CachePrivacyClass = CachePrivacyClass.LOCAL_KV_CACHE
    rig_control_level: str = "local_manage"
    persists_across_restarts: bool = False
    ssd_persistence_detected: bool = False
    confidential_context_policy: str = "safe_local"
    data_never_leaves_machine: bool = True
    rig_relay_may_read_cache_stats: bool = True
    rig_relay_must_not_read_cache_contents: bool = True
    retention_policy: str = "runtime_managed"
    disclosure_required: bool = True
    disclosure_summary: str = ""


class CacheEvidenceMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.relay.local_cache_evidence.v1", frozen=True
    )
    evidence_id: str = ""
    runtime_kind: str = "unknown"
    captured_at: str = ""
    cache_hit_rate_recent: float | None = None
    cache_hit_rate_medium: float | None = None
    cache_hit_rate_aggregate: float | None = None
    gpu_cache_blocks_total: int | None = None
    gpu_cache_blocks_used: int | None = None
    ssd_cache_size_mb: int | None = None
    prefix_cache_entries: int | None = None
    content_light: bool = True


class TaskAdmissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    admitted: bool = False
    task_kind: TaskKind = TaskKind.CHAT
    refusal_reason: RefusalReason | None = None
    capability_match: bool = False
    privacy_approved: bool = False
    context_privacy_class: ContextPrivacyClass = ContextPrivacyClass.PRIVATE_LOCAL
    tool_calling_allowed: bool = False
    structured_output_allowed: bool = False
    admission_details: str = ""


class TaskAdmissionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id_hash: str = ""
    task_kind: TaskKind = TaskKind.CHAT
    admission: TaskAdmissionDecision = Field(default_factory=TaskAdmissionDecision)
    executed: bool = False
    status: ExecutionStatus = ExecutionStatus.BLOCKED
    refusal: TaskRefusal | None = None
    response: LocalInferenceResponse | None = None
    evidence_receipt_id: str = ""


class TaskRefusal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: RefusalReason = RefusalReason.RUNTIME_NOT_CONFIGURED
    detail: str = ""
    timestamp: str = ""
