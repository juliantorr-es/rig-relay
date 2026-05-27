"""rig_relay.local_inference.runtime — Rig-governed internal MLX-backed runtime.

X2.3: Scheduler, cache authority, tool proposal corridor, X0 consumer contract,
canonical evidence with schema validation, locking, and idempotency.
"""

from __future__ import annotations

from rig_relay.local_inference.runtime._cache_authority import RiggedCacheAuthority
from rig_relay.local_inference.runtime._engine import (
    LoadedModel,
    MlxNotAvailableError,
    ModelNotLoadedError,
    RiggedMlxEngine,
)
from rig_relay.local_inference.runtime._evidence import (
    EvidenceLedger,
    EvidenceLedgerError,
    emit_cache_evidence,
    emit_execution_receipt,
    emit_lifecycle_event,
    emit_refusal_receipt,
    emit_tool_proposal_evidence,
    reconstruct_ledgers,
)
from rig_relay.local_inference.runtime._inventory import scan_model_inventory
from rig_relay.local_inference.runtime._models import (
    CapabilityPosture,
    ContextPrivacyClass,
    ExecutionStatus,
    FinishReason,
    LocalInferenceResponse,
    ModelInventoryEntry,
    ModelTypeClass,
    RefusalReason,
    RuntimeCachePolicy,
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
from rig_relay.local_inference.runtime._scheduler import (
    RequestState,
    RiggedInferenceScheduler,
)
from rig_relay.local_inference.runtime._secrets import scan_messages_for_secrets
from rig_relay.local_inference.runtime._service import (
    RiggedLocalRuntime,
    get_runtime,
    reset_runtime,
)

__all__ = [
    "CapabilityPosture",
    "ContextPrivacyClass",
    "EvidenceLedger",
    "EvidenceLedgerError",
    "ExecutionStatus",
    "FinishReason",
    "LoadedModel",
    "LocalInferenceResponse",
    "MlxNotAvailableError",
    "ModelInventoryEntry",
    "ModelNotLoadedError",
    "ModelTypeClass",
    "RefusalReason",
    "RequestState",
    "RiggedCacheAuthority",
    "RiggedInferenceScheduler",
    "RiggedLocalRuntime",
    "RiggedMlxEngine",
    "RuntimeCachePolicy",
    "RuntimeIdentity",
    "RuntimeLifecycleState",
    "TaskAdmissionDecision",
    "TaskAdmissionResult",
    "TaskKind",
    "TaskRefusal",
    "ToolCallProposal",
    "discover_runtime",
    "emit_cache_evidence",
    "emit_execution_receipt",
    "emit_lifecycle_event",
    "emit_refusal_receipt",
    "emit_tool_proposal_evidence",
    "get_runtime",
    "probe_runtime_health",
    "probe_runtime_models",
    "reconstruct_ledgers",
    "reset_runtime",
    "scan_messages_for_secrets",
    "scan_model_inventory",
]
