"""RiggedLocalRuntime — Rig-governed internal MLX-backed runtime.

Typed application-service boundary for local model loading, governed
inference, model inventory, durable evidence emission, and capability
reporting. Returns visible responses to authorized consumers while
recording content-light evidence in append-only JSONL ledgers.

Privacy model: local runtime may process private repository content
under local-only retention controls. Only secret-bearing context
is refused. This differs from cloud providers where confidential
context requires explicit approval (W1 policy).

Rig Relay owns: admission, privacy, task authorization, tool execution
authority, evidence issuance, cache disclosure, UI projection.
The MLX runtime provides: model loading, tokenization, GPU inference.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

from rig_relay.core.logger import logger
from rig_relay.local_inference.runtime._engine import (
    MlxNotAvailableError,
    ModelNotLoadedError,
    RiggedMlxEngine,
)
from rig_relay.local_inference.runtime._evidence import (
    build_evidence_receipt,
    emit_execution_receipt,
    emit_lifecycle_event,
    emit_refusal_receipt,
)
from rig_relay.local_inference.runtime._inventory import scan_model_inventory
from rig_relay.local_inference.runtime._models import (
    CapabilityPosture,
    ContextPrivacyClass,
    EnrichedRuntimeCapabilities,
    ExecutionStatus,
    ModelInventoryEntry,
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


class RiggedLocalRuntime:
    """Typed application-service boundary for a governed local runtime."""

    def __init__(self, model_dirs: list[Path] | None = None) -> None:
        self._engine: RiggedMlxEngine = RiggedMlxEngine()
        self._inventory: list[ModelInventoryEntry] = []
        self._health: RuntimeHealth = RuntimeHealth()
        self._last_probe_at: str = ""
        self._model_dirs: list[Path] = model_dirs or []

    @property
    def is_configured(self) -> bool:
        return self._engine.is_mlx_available

    @property
    def runtime_kind(self) -> str:
        return "rigged_mlx"

    @property
    def engine(self) -> RiggedMlxEngine:
        return self._engine

    async def get_runtime_info(self) -> RuntimeIdentity:
        return RuntimeIdentity(
            runtime_kind="rigged_mlx",
            runtime_version=_mlx_version(),
            display_name="Rigged MLX Runtime",
            platform_class="metal" if self._engine.is_mlx_available else "unknown",
            api_protocol="python_module",
            endpoint_url="in-process (mlx-lm)",
            configured_at=_now_iso(),
        )

    async def probe(self) -> RuntimeHealth:
        if not self._engine.is_mlx_available:
            self._health = RuntimeHealth(
                state=RuntimeLifecycleState.UNCONFIGURED, warnings=["mlx_not_available"]
            )
            return self._health
        try:
            self._inventory = scan_model_inventory(self._model_dirs or None)
            self._health = RuntimeHealth(
                state=RuntimeLifecycleState.HEALTHY,
                reachable=True,
                health_endpoint_status="in_process",
                active_model_count=self._engine.loaded_model_count,
                gpu_available=True,
                probed_at=_now_iso(),
            )
        except Exception:
            self._health = RuntimeHealth(
                state=RuntimeLifecycleState.DEGRADED,
                warnings=["inventory_scan_failed"],
                probed_at=_now_iso(),
            )
        self._last_probe_at = _now_iso()
        return self._health

    async def check_health(self) -> RuntimeHealth:
        if not self._engine.is_mlx_available:
            return RuntimeHealth(state=RuntimeLifecycleState.UNCONFIGURED)
        return RuntimeHealth(
            state=RuntimeLifecycleState.HEALTHY,
            reachable=True,
            gpu_available=True,
            active_model_count=self._engine.loaded_model_count,
            probed_at=_now_iso(),
        )

    async def list_models(self) -> list[ModelInventoryEntry]:
        if not self._inventory:
            self._inventory = scan_model_inventory(self._model_dirs or None)
        loaded_hashes = {lm.model_id_hash for lm in self._engine.list_loaded_models()}
        for entry in self._inventory:
            entry.is_loaded = entry.model_id_hash in loaded_hashes
        return list(self._inventory)

    def get_capabilities(self) -> EnrichedRuntimeCapabilities:
        return EnrichedRuntimeCapabilities(
            chat_completions="supported",
            completions="supported",
            models_list="supported",
            health_endpoint="supported",
            runtime_version="supported",
            embeddings=CapabilityPosture.V1_REQUIRED_PENDING,
            reranking=CapabilityPosture.V1_REQUIRED_PENDING,
            vision=CapabilityPosture.V1_REQUIRED_PENDING,
            cache_metrics=CapabilityPosture.V1_REQUIRED_PENDING,
            server_metrics=CapabilityPosture.V1_REQUIRED_PENDING,
            streaming=CapabilityPosture.V1_REQUIRED_PENDING,
            tool_calling=CapabilityPosture.V1_REQUIRED_PENDING,
            structured_json_output=CapabilityPosture.V1_REQUIRED_PENDING,
            anthropic_messages=CapabilityPosture.DEFERRED,
            api_status=CapabilityPosture.DEFERRED,
        )

    def get_cache_policy(self) -> RuntimeCachePolicy:
        return RuntimeCachePolicy(
            cache_mode="local_runtime_kv",
            rig_control_level="local_manage",
            persists_across_restarts=False,
            ssd_persistence_detected=False,
            confidential_context_policy="safe_local",
            data_never_leaves_machine=True,
            rig_relay_may_read_cache_stats=True,
            rig_relay_must_not_read_cache_contents=True,
            retention_policy="ephemeral_in_memory",
            disclosure_required=True,
            disclosure_summary=(
                "mlx-lm uses in-process KV cache that is not persisted "
                "across calls or restarts. Data never leaves the machine."
            ),
        )

    def admit_task(
        self,
        task_kind: TaskKind,
        context_privacy_class: ContextPrivacyClass = ContextPrivacyClass.PRIVATE_LOCAL,
        tool_calling_requested: bool = False,
        structured_output_requested: bool = False,
    ) -> TaskAdmissionDecision:
        """Admit or refuse a governed inference task.

        Privacy model for local runtime:
          - PUBLIC_SAFE: always allowed
          - PRIVATE_LOCAL: allowed under local-only retention controls
            (data never leaves the machine; this is the point of local inference)
          - SECRET_BEARING: refused — credential/secret content must not
            enter the runtime context at all
        """
        if not self._engine.is_mlx_available:
            return TaskAdmissionDecision(
                admitted=False,
                task_kind=task_kind,
                refusal_reason=RefusalReason.RUNTIME_NOT_CONFIGURED,
                context_privacy_class=context_privacy_class,
                admission_details="MLX is not available on this platform.",
            )

        if context_privacy_class == ContextPrivacyClass.SECRET_BEARING:
            return TaskAdmissionDecision(
                admitted=False,
                task_kind=task_kind,
                refusal_reason=RefusalReason.CONTEXT_BLOCKED_BY_POLICY,
                context_privacy_class=context_privacy_class,
                admission_details=(
                    "Secret-bearing context refused. Content containing "
                    "credentials, tokens, or private keys must not enter "
                    "the runtime context."
                ),
            )

        if tool_calling_requested:
            return TaskAdmissionDecision(
                admitted=False,
                task_kind=task_kind,
                refusal_reason=RefusalReason.CAPABILITY_UNSUPPORTED,
                context_privacy_class=context_privacy_class,
                admission_details="Tool calling not yet supported in governed MLX runtime (v1_required_pending).",
            )

        if structured_output_requested:
            return TaskAdmissionDecision(
                admitted=False,
                task_kind=task_kind,
                refusal_reason=RefusalReason.CAPABILITY_UNSUPPORTED,
                context_privacy_class=context_privacy_class,
                admission_details="Structured output not yet supported (v1_required_pending).",
            )

        privacy_ok = context_privacy_class in (
            ContextPrivacyClass.PUBLIC_SAFE,
            ContextPrivacyClass.PRIVATE_LOCAL,
        )

        return TaskAdmissionDecision(
            admitted=True,
            task_kind=task_kind,
            capability_match=True,
            privacy_approved=privacy_ok,
            context_privacy_class=context_privacy_class,
            tool_calling_allowed=False,
            structured_output_allowed=False,
            admission_details=(
                "Task admitted for governed local MLX execution. "
                "Private local context permitted under local-only retention."
            ),
        )

    async def execute(
        self,
        messages: list[dict],
        model_id_hash: str = "",
        task_kind: TaskKind = TaskKind.CHAT,
        context_privacy_class: ContextPrivacyClass = ContextPrivacyClass.PRIVATE_LOCAL,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> TaskAdmissionResult:
        """Execute a governed inference task.

        Returns visible response (for UI) and content-light evidence receipt
        (for the canonical ledger). Tool-call proposals from model output are
        parsed and routed through governance — never executed directly.
        """
        admission = self.admit_task(
            task_kind=task_kind, context_privacy_class=context_privacy_class
        )
        task_id_hash = _sha256(json.dumps(messages, sort_keys=True, default=str))

        result = TaskAdmissionResult(
            task_id_hash=task_id_hash, task_kind=task_kind, admission=admission
        )

        if not admission.admitted:
            refusal = TaskRefusal(
                reason=admission.refusal_reason or RefusalReason.RUNTIME_NOT_CONFIGURED,
                detail=admission.admission_details,
                timestamp=_now_iso(),
            )
            result.refusal = refusal
            result.status = ExecutionStatus.REFUSED
            emit_refusal_receipt(refusal, task_id_hash)
            return result

        if not model_id_hash and self._engine.loaded_model_count > 0:
            model_id_hash = self._engine.list_loaded_models()[0].model_id_hash

        if not model_id_hash:
            refusal = TaskRefusal(
                reason=RefusalReason.CAPABILITY_UNSUPPORTED,
                detail="No model loaded. Call load_model() first.",
                timestamp=_now_iso(),
            )
            result.refusal = refusal
            result.status = ExecutionStatus.REFUSED
            emit_refusal_receipt(refusal, task_id_hash)
            return result

        try:
            response = self._engine.generate(
                model_id_hash=model_id_hash,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except ModelNotLoadedError as e:
            refusal = TaskRefusal(
                reason=RefusalReason.CAPABILITY_UNSUPPORTED,
                detail=str(e),
                timestamp=_now_iso(),
            )
            result.refusal = refusal
            result.status = ExecutionStatus.BLOCKED
            emit_refusal_receipt(refusal, task_id_hash)
            return result

        prompt_sha = _sha256(json.dumps(messages, sort_keys=True, default=str))

        if response.tool_call_proposals:
            _route_tool_proposals_to_governance(
                response.tool_call_proposals, task_id_hash
            )

        receipt = build_evidence_receipt(
            task_id_hash=task_id_hash,
            prompt_sha256=prompt_sha,
            response=response,
            model_id_hash=model_id_hash,
            latency_ms=response.latency_ms,
            context_privacy_class=context_privacy_class,
        )
        response.evidence_receipt_id = receipt.receipt_id
        emit_execution_receipt(receipt)

        result.executed = True
        result.status = ExecutionStatus.EXECUTED
        result.response = response
        result.evidence_receipt_id = receipt.receipt_id

        return result

    def load_model(self, model_path: str, model_id: str = "") -> str:
        if not self._engine.is_mlx_available:
            raise MlxNotAvailableError("MLX not available on this platform")
        loaded = self._engine.load_model(model_path=model_path, model_id=model_id)
        emit_lifecycle_event(
            "rig.relay.runtime.model_loaded",
            loaded.model_id_hash,
            {"model_path_hash": _sha256(model_path)[:16]},
        )
        return loaded.model_id_hash

    def unload_model(self, model_id_hash: str) -> bool:
        result = self._engine.unload_model(model_id_hash)
        if result:
            emit_lifecycle_event("rig.relay.runtime.model_unloaded", model_id_hash)
        return result

    def build_projection(self) -> dict:
        return {
            "runtime": {
                "kind": "rigged_mlx",
                "version": _mlx_version(),
                "display_name": "Rigged MLX Runtime",
                "platform_class": "metal",
                "api_protocol": "python_module",
                "mlx_available": self._engine.is_mlx_available,
            },
            "health": {
                "state": self._health.state,
                "reachable": self._health.reachable,
                "active_model_count": self._engine.loaded_model_count,
                "gpu_available": self._engine.is_mlx_available,
            },
            "capabilities": {
                "text_generation": CapabilityPosture.SUPPORTED,
                "streaming": CapabilityPosture.V1_REQUIRED_PENDING,
                "tool_calling": CapabilityPosture.V1_REQUIRED_PENDING,
                "structured_output": CapabilityPosture.V1_REQUIRED_PENDING,
                "embeddings": CapabilityPosture.V1_REQUIRED_PENDING,
                "reranking": CapabilityPosture.V1_REQUIRED_PENDING,
                "vision_vlm": CapabilityPosture.V1_REQUIRED_PENDING,
                "continuous_batching": CapabilityPosture.V1_REQUIRED_PENDING,
                "kv_cache_persistence": CapabilityPosture.V1_REQUIRED_PENDING,
                "benchmark_integration": CapabilityPosture.V1_REQUIRED_PENDING,
            },
            "cache": {
                "mode": "local_runtime_kv",
                "privacy_class": "local_in_process",
                "persistence": "none (mlx-lm in-memory only)",
                "disclosure": self.get_cache_policy().disclosure_summary,
            },
            "privacy": {
                "model": "local_runtime_permissive",
                "public_safe_context": "allowed",
                "private_local_context": "allowed (local-only retention)",
                "secret_bearing_context": "refused",
                "data_never_leaves_machine": True,
            },
            "governance": {
                "task_admission": "governed",
                "privacy_classification": "enforced",
                "tool_execution": "rig_relay_authority (proposals only)",
                "evidence_emission": "durable_append_only_jsonl",
                "content_light": True,
            },
            "evidence_ledgers": {
                "execution": ".build/rig-relay/evidence/runtime_execution_ledger.jsonl",
                "lifecycle": ".build/rig-relay/evidence/runtime_lifecycle_ledger.jsonl",
                "cache": ".build/rig-relay/evidence/runtime_cache_ledger.jsonl",
            },
            "last_probe_at": self._last_probe_at,
        }


_global_runtime: RiggedLocalRuntime | None = None


def get_runtime(model_dirs: list[Path] | None = None) -> RiggedLocalRuntime:
    global _global_runtime
    if _global_runtime is None:
        _global_runtime = RiggedLocalRuntime(model_dirs=model_dirs)
    return _global_runtime


def reset_runtime() -> None:
    global _global_runtime
    _global_runtime = None


def _route_tool_proposals_to_governance(
    proposals: list[ToolCallProposal], task_id_hash: str
) -> None:
    """Route parsed tool-call proposals to Rig Relay governance.

    Tool calls are proposals — never executed directly. This function
    records them in the governance log. Future implementation will
    route through the existing governed tool execution corridor.
    """
    for p in proposals:
        logger.info(
            "runtime_tool_proposal: task=%s tool=%s call_id=%s",
            task_id_hash[:12],
            p.tool_name,
            p.call_id,
        )


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _mlx_version() -> str:
    try:
        import mlx

        return getattr(mlx, "__version__", "available")
    except ImportError:
        return "unavailable"
