"""Rig-governed local runtime models — typed application-service boundary.

Content-light by construction: no raw prompts, completions, secrets, or private content.
SHA256 hashes for all content-derived references.

OMLX-informed patterns (Apache 2.0 attribution):
  - CacheEvidenceMetrics rolling window structure informed by OMLX CacheRateTracker
  - ModelTypeClass taxonomy informed by OMLX model_discovery.py model_type detection
  - EnrichedRuntimeCapabilities probe targets informed by OMLX server.py endpoint layout
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
    CONTEXT_NOT_PUBLIC_SAFE = "context_not_public_safe"
    TOOL_CALL_DETECTED = "tool_call_detected"
    OUTPUT_VALIDATION_FAILED = "output_validation_failed"


class CachePrivacyClass(StrEnum):
    LOCAL_KV_CACHE = "local_kv_cache"
    LOCAL_SSD_CACHE = "local_ssd_cache"
    LOCAL_HOT_CACHE = "local_hot_cache"
    CLOUD_PROVIDER_CACHE = "cloud_provider_cache"
    NOT_APPLICABLE = "not_applicable"


class RuntimeIdentity(BaseModel):
    """Runtime kind, version, and platform identity. Content-light."""

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
    """Runtime liveness, reachability, and enriched status. Content-light."""

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
    """Safe model identifier and capability class. Never exposes raw paths.

    OMLX-informed: model_type taxonomy (llm, vlm, embedding, reranker, audio)
    adapted from OMLX model_discovery.py model_type detection patterns.
    """

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
    """Enriched capability probe beyond basic OpenAI-compatible minimum.

    OMLX-informed: endpoint targets (embeddings, rerank, anthropic_messages,
    api_status, cache_metrics) adapted from OMLX server.py route layout.
    """

    model_config = ConfigDict(extra="forbid")
    chat_completions: str = "not_tested"
    completions: str = "not_tested"
    embeddings: str = "not_tested"
    reranking: str = "not_tested"
    anthropic_messages: str = "not_tested"
    models_list: str = "not_tested"
    health_endpoint: str = "not_tested"
    api_status: str = "not_tested"
    streaming: str = "not_tested"
    tool_calling: str = "not_tested"
    structured_json_output: str = "not_tested"
    vision: str = "not_tested"
    cache_metrics: str = "not_tested"
    server_metrics: str = "not_tested"
    runtime_version: str = "not_tested"


class RuntimeCachePolicy(BaseModel):
    """Local cache privacy classification per W1 Principle 4.

    Local KV cache is not cloud retention. Still requires disclosure
    because it persists derived context locally (GPU + optional SSD).
    """

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
    """Content-light local cache performance evidence.

    OMLX-informed: rolling window structure (recent/medium/aggregate windows)
    adapted from OMLX server_metrics.py CacheRateTracker pattern.
    """

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
    """Whether a task is admitted for governed local execution."""

    model_config = ConfigDict(extra="forbid")
    admitted: bool = False
    task_kind: TaskKind = TaskKind.CHAT
    refusal_reason: RefusalReason | None = None
    capability_match: bool = False
    privacy_safe: bool = False
    context_public_safe: bool = False
    tool_calling_allowed: bool = False
    structured_output_allowed: bool = False
    admission_details: str = ""


class TaskAdmissionResult(BaseModel):
    """Result of admitting and executing a governed task."""

    model_config = ConfigDict(extra="forbid")
    task_id_hash: str = ""
    task_kind: TaskKind = TaskKind.CHAT
    admission: TaskAdmissionDecision = Field(default_factory=TaskAdmissionDecision)
    executed: bool = False
    status: ExecutionStatus = ExecutionStatus.BLOCKED
    refusal: TaskRefusal | None = None
    outcome: ExecutionOutcome | None = None
    evidence_id: str = ""


class TaskRefusal(BaseModel):
    """Typed refusal when a task is blocked."""

    model_config = ConfigDict(extra="forbid")
    reason: RefusalReason = RefusalReason.RUNTIME_NOT_CONFIGURED
    detail: str = ""
    timestamp: str = ""


class ExecutionOutcome(BaseModel):
    """Content-light execution outcome with hashes, never raw output."""

    model_config = ConfigDict(extra="forbid")
    executed: bool = False
    status: ExecutionStatus = ExecutionStatus.BLOCKED
    output_sha256: str = ""
    output_length_chars: int = 0
    prompt_sha256: str = ""
    model_id_hash: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_hit: bool = False
    cache_read_tokens: int = 0
    streaming: bool = False
    time_to_first_token_ms: int | None = None
    tool_calls_detected: bool = False
    tool_calls_routed_to_governance: bool = False
    structured_output_valid: bool | None = None
    error_message_safe: str = ""
    content_light: bool = True
