"""rig_relay.local_inference.runtime — Rig-governed internal MLX-backed runtime.

Typed application-service boundary for MLX-backed model loading, governed
inference, model inventory, content-light evidence, and capability reporting
for future Inference Studio consumption.

Uses mlx-lm Python APIs directly under Rig Relay governance. This is an
internal runtime — not an external HTTP endpoint adapter.

OMLX-informed: model classification taxonomy, cache evidence metrics schema,
capability probe structure, MLX thread safety patterns. Apache 2.0 attribution
in _models.py and _engine.py.

Content-light throughout: no raw prompts, completions, secrets, or private content.
"""

from __future__ import annotations

from rig_relay.local_inference.runtime._engine import (
    GovernedOutput,
    LoadedModel,
    MlxNotAvailableError,
    ModelNotLoadedError,
    RiggedMlxEngine,
)
from rig_relay.local_inference.runtime._evidence import (
    emit_cache_evidence,
    emit_execution_evidence,
    emit_probe_evidence,
    emit_refusal_evidence,
)
from rig_relay.local_inference.runtime._inventory import scan_model_inventory
from rig_relay.local_inference.runtime._models import (
    CacheEvidenceMetrics,
    CachePrivacyClass,
    EnrichedRuntimeCapabilities,
    ExecutionOutcome,
    ExecutionStatus,
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
    "EnrichedRuntimeCapabilities",
    "ExecutionOutcome",
    "ExecutionStatus",
    "GovernedOutput",
    "LoadedModel",
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
    "discover_runtime",
    "emit_cache_evidence",
    "emit_execution_evidence",
    "emit_probe_evidence",
    "emit_refusal_evidence",
    "get_runtime",
    "probe_runtime_health",
    "probe_runtime_models",
    "reset_runtime",
    "scan_model_inventory",
]
