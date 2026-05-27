"""rig_relay.local_inference.runtime — Rig-governed internal MLX-backed runtime.

Typed application-service boundary for MLX-backed model loading, governed
inference with visible responses, durable evidence ledgers, model inventory,
and capability reporting for Inference Studio consumption.

Two-layer design:
  LocalInferenceResponse     — authorized visible content for UI/session consumer
  LocalInferenceEvidenceReceipt — content-light evidence for canonical ledger

Content-light throughout: evidence uses SHA256 hashes, never raw prompts,
completions, secrets, or private content.

OMLX-informed: model classification taxonomy, cache evidence metrics schema,
capability probe structure, MLX thread safety patterns, tool-call family parsing.
Apache 2.0 attribution in source files and THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

from rig_relay.local_inference.runtime._engine import (
    LoadedModel,
    MlxNotAvailableError,
    ModelNotLoadedError,
    RiggedMlxEngine,
)
from rig_relay.local_inference.runtime._evidence import (
    build_evidence_receipt,
    emit_cache_evidence,
    emit_execution_receipt,
    emit_lifecycle_event,
    emit_refusal_receipt,
)
from rig_relay.local_inference.runtime._inventory import scan_model_inventory
from rig_relay.local_inference.runtime._models import (
    CacheEvidenceMetrics,
    CachePrivacyClass,
    CapabilityPosture,
    ContextPrivacyClass,
    EnrichedRuntimeCapabilities,
    ExecutionStatus,
    FinishReason,
    LocalInferenceEvidenceReceipt,
    LocalInferenceResponse,
    ModelInventoryEntry,
    ModelTypeClass,
    RefusalReason,
    RuntimeCachePolicy,
    RuntimeHealth,
    RuntimeIdentity,
    RuntimeLifecycleState,
    TaskAdmissionDecision,
    TaskAdmissionResult,
    TaskKind,
    TaskRefusal,
    ToolCallProposal,
)
from rig_relay.local_inference.runtime._probe import (
    discover_runtime,
    probe_runtime_health,
    probe_runtime_models,
)
from rig_relay.local_inference.runtime._service import (
    RiggedLocalRuntime,
    get_runtime,
    reset_runtime,
)

__all__: list[str] = [
    "CacheEvidenceMetrics",
    "CachePrivacyClass",
    "CapabilityPosture",
    "ContextPrivacyClass",
    "EnrichedRuntimeCapabilities",
    "ExecutionStatus",
    "FinishReason",
    "LoadedModel",
    "LocalInferenceEvidenceReceipt",
    "LocalInferenceResponse",
    "MlxNotAvailableError",
    "ModelInventoryEntry",
    "ModelNotLoadedError",
    "ModelTypeClass",
    "RefusalReason",
    "RiggedLocalRuntime",
    "RiggedMlxEngine",
    "RuntimeCachePolicy",
    "RuntimeHealth",
    "RuntimeIdentity",
    "RuntimeLifecycleState",
    "TaskAdmissionDecision",
    "TaskAdmissionResult",
    "TaskKind",
    "TaskRefusal",
    "ToolCallProposal",
    "build_evidence_receipt",
    "discover_runtime",
    "emit_cache_evidence",
    "emit_execution_receipt",
    "emit_lifecycle_event",
    "emit_refusal_receipt",
    "get_runtime",
    "probe_runtime_health",
    "probe_runtime_models",
    "reset_runtime",
    "scan_model_inventory",
]
