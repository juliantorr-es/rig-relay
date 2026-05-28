"""rig_relay.local_inference.runtime — Rig-governed internal MLX-backed runtime.

X2.5: Deferred capability implementation wave — coordinated thread lifecycle
(B4), cache write-back + SSD persistence, continuous batching scheduler,
multi-model pool manager, tool execution bridge.
"""

from __future__ import annotations

from rig_relay.local_inference.runtime._bridge import ToolExecutionBridge
from rig_relay.local_inference.runtime._cache_authority import RiggedCacheAuthority
from rig_relay.local_inference.runtime._evidence import (
    EvidenceLedger,
    EvidenceLedgerError,
    emit_cache_evidence,
    emit_execution_receipt,
    emit_lifecycle_event,
    emit_refusal_receipt,
    emit_scheduler_event,
    emit_tool_execution_outcome,
    emit_tool_proposal_evidence,
    reconstruct_ledgers,
)
from rig_relay.local_inference.runtime._inventory import scan_model_inventory
from rig_relay.local_inference.runtime._models import (
    BatchingStatus,
    CapabilityPosture,
    ContextPrivacyClass,
    ExecutionStatus,
    FinishReason,
    LocalAgentLoopRequest,
    LocalAgentLoopResult,
    LocalInferenceResponse,
    LoopState,
    ModelInventoryEntry,
    ModelPoolState,
    ModelTypeClass,
    PoolEvictionReason,
    RefusalReason,
    RuntimeCachePolicy,
    RuntimeIdentity,
    RuntimeLifecycleState,
    SSDCacheState,
    TaskAdmissionDecision,
    TaskAdmissionResult,
    TaskKind,
    TaskRefusal,
    ToolCallProposal,
    ToolObservation,
)
from rig_relay.local_inference.runtime._pool import ModelPoolManager
from rig_relay.local_inference.runtime._probe import (
    discover_runtime,
    probe_runtime_health,
    probe_runtime_models,
)
from rig_relay.local_inference.runtime._scheduler import (
    RequestState,
    RiggedBatchScheduler,
    RiggedInferenceScheduler,
    ScheduledRequest,
)
from rig_relay.local_inference.runtime._secrets import scan_messages_for_secrets
from rig_relay.local_inference.runtime._service import (
    RiggedLocalRuntime,
    get_runtime,
    reset_runtime,
)

__all__ = [
    "BatchingStatus",
    "CapabilityPosture",
    "ContextPrivacyClass",
    "EvidenceLedger",
    "EvidenceLedgerError",
    "ExecutionStatus",
    "FinishReason",
    "LocalAgentLoopRequest",
    "LocalAgentLoopResult",
    "LocalInferenceResponse",
    "LoopState",
    "ModelInventoryEntry",
    "ModelPoolManager",
    "ModelPoolState",
    "ModelTypeClass",
    "PoolEvictionReason",
    "RefusalReason",
    "RequestState",
    "RiggedBatchScheduler",
    "RiggedCacheAuthority",
    "RiggedInferenceScheduler",
    "RiggedLocalRuntime",
    "RuntimeCachePolicy",
    "RuntimeIdentity",
    "RuntimeLifecycleState",
    "SSDCacheState",
    "ScheduledRequest",
    "TaskAdmissionDecision",
    "TaskAdmissionResult",
    "TaskKind",
    "TaskRefusal",
    "ToolCallProposal",
    "ToolExecutionBridge",
    "ToolObservation",
    "discover_runtime",
    "emit_cache_evidence",
    "emit_execution_receipt",
    "emit_lifecycle_event",
    "emit_refusal_receipt",
    "emit_scheduler_event",
    "emit_tool_execution_outcome",
    "emit_tool_proposal_evidence",
    "get_runtime",
    "probe_runtime_health",
    "probe_runtime_models",
    "reconstruct_ledgers",
    "reset_runtime",
    "scan_messages_for_secrets",
    "scan_model_inventory",
]
