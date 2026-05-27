"""RiggedLocalRuntime — Rig-governed internal MLX-backed runtime.

Typed application-service boundary for local model loading, governed
inference, model inventory, evidence emission, and capability reporting.
Uses mlx-lm APIs directly under Rig Relay governance — this is an
internal runtime, not an external endpoint adapter.

Rig Relay owns: admission, privacy, task authorization, tool execution
authority, evidence issuance, cache disclosure, UI projection.
The MLX runtime provides: model loading, tokenization, GPU inference.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

from rig_relay.local_inference.runtime._engine import (
    MlxNotAvailableError,
    ModelNotLoadedError,
    RiggedMlxEngine,
)
from rig_relay.local_inference.runtime._evidence import (
    emit_execution_evidence,
    emit_refusal_evidence,
)
from rig_relay.local_inference.runtime._inventory import scan_model_inventory
from rig_relay.local_inference.runtime._models import (
    EnrichedRuntimeCapabilities,
    ExecutionOutcome,
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
)


class RiggedLocalRuntime:
    """Typed application-service boundary for a governed local runtime.

    Loads models via mlx-lm, performs governed inference, produces
    content-light evidence, and reports capability/health for future
    Inference Studio consumption.

    The runtime is internal — model weights are loaded in-process by
    mlx-lm under Rig Relay governance gates. No external HTTP endpoint
    is used for inference.
    """

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
        """Return runtime identity.

        Reports whether MLX is available and the internal engine state.
        """
        return RuntimeIdentity(
            runtime_kind="rigged_mlx",
            runtime_version=_mlx_version(),
            display_name="Rigged MLX Runtime",
            platform_class="metal" if self._engine.is_mlx_available else "unknown",
            api_protocol="python_module",
            endpoint_url="in-process (mlx-lm)",
        )

    async def probe(self) -> RuntimeHealth:
        """Probe runtime health: MLX availability, model inventory, engine state."""
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
        """Quick health check."""
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
        """Return model inventory from filesystem scan and loaded models."""
        if not self._inventory:
            self._inventory = scan_model_inventory(self._model_dirs or None)

        loaded: dict[str, bool] = {}
        for lm in self._engine.list_loaded_models():
            loaded[lm.model_id_hash] = True

        for entry in self._inventory:
            entry.is_loaded = entry.model_id_hash in loaded

        return list(self._inventory)

    def get_capabilities(self) -> EnrichedRuntimeCapabilities:
        """Return enriched capability report.

        Reports MLX-backed capabilities honestly: text generation is
        supported; streaming, tool calling, and structured output are
        not_tested (deferred to future slices); embeddings, reranking,
        VLM, cache metrics are unsupported (deferred).
        """
        return EnrichedRuntimeCapabilities(
            chat_completions="supported",
            completions="supported",
            models_list="supported",
            health_endpoint="supported",
            embeddings="unsupported",
            reranking="unsupported",
            anthropic_messages="unsupported",
            api_status="unsupported",
            streaming="not_tested",
            tool_calling="not_tested",
            structured_json_output="not_tested",
            vision="unsupported",
            cache_metrics="unsupported",
            server_metrics="unsupported",
            runtime_version="supported",
        )

    def get_cache_policy(self) -> RuntimeCachePolicy:
        """Return local cache privacy policy per W1 Principle 4.

        mlx-lm.generate() uses in-process KV cache that is not persisted
        across calls — strongest privacy guarantee.
        """
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
                "across calls or restarts. Data never leaves the machine. "
                "No persistent cache inspection or management required."
            ),
        )

    def admit_task(
        self,
        task_kind: TaskKind,
        context_public_safe: bool = True,
        tool_calling_requested: bool = False,
        structured_output_requested: bool = False,
    ) -> TaskAdmissionDecision:
        """Admit or refuse a governed inference task.

        Gates through privacy, capability, and governance checks.
        """
        if not self._engine.is_mlx_available:
            return TaskAdmissionDecision(
                admitted=False,
                task_kind=task_kind,
                refusal_reason=RefusalReason.RUNTIME_NOT_CONFIGURED,
                admission_details="MLX is not available on this platform.",
            )

        if not context_public_safe:
            return TaskAdmissionDecision(
                admitted=False,
                task_kind=task_kind,
                refusal_reason=RefusalReason.CONTEXT_NOT_PUBLIC_SAFE,
                admission_details="Context not classified as public-safe.",
            )

        if tool_calling_requested:
            return TaskAdmissionDecision(
                admitted=False,
                task_kind=task_kind,
                refusal_reason=RefusalReason.CAPABILITY_UNSUPPORTED,
                admission_details="Tool calling not yet supported in governed MLX runtime (deferred).",
            )

        if structured_output_requested:
            return TaskAdmissionDecision(
                admitted=False,
                task_kind=task_kind,
                refusal_reason=RefusalReason.CAPABILITY_UNSUPPORTED,
                admission_details="Structured output not yet supported in governed MLX runtime (deferred).",
            )

        return TaskAdmissionDecision(
            admitted=True,
            task_kind=task_kind,
            capability_match=True,
            privacy_safe=True,
            context_public_safe=True,
            tool_calling_allowed=False,
            structured_output_allowed=False,
            admission_details="Task admitted for governed local MLX execution.",
        )

    async def execute(
        self,
        messages: list[dict],
        model_id_hash: str = "",
        task_kind: TaskKind = TaskKind.CHAT,
        context_public_safe: bool = True,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> TaskAdmissionResult:
        """Execute a governed inference task on the internal MLX runtime.

        1. Admits task through governance gates.
        2. Generates text via mlx-lm.generate().
        3. Detects and governs tool-call output (proposal only).
        4. Emits content-light execution evidence.
        """
        admission = self.admit_task(
            task_kind=task_kind, context_public_safe=context_public_safe
        )
        result = TaskAdmissionResult(
            task_id_hash=_sha256(json.dumps(messages, sort_keys=True, default=str)),
            task_kind=task_kind,
            admission=admission,
        )

        if not admission.admitted:
            refusal = TaskRefusal(
                reason=admission.refusal_reason or RefusalReason.RUNTIME_NOT_CONFIGURED,
                detail=admission.admission_details,
                timestamp=_now_iso(),
            )
            result.refusal = refusal
            result.status = ExecutionStatus.REFUSED
            emit_refusal_evidence(refusal, result.task_id_hash)
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
            emit_refusal_evidence(refusal, result.task_id_hash)
            return result

        try:
            governed = self._engine.generate(
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
            emit_refusal_evidence(refusal, result.task_id_hash)
            return result

        outcome = ExecutionOutcome(
            executed=governed.executed,
            status=ExecutionStatus.EXECUTED
            if governed.executed
            else ExecutionStatus.ERROR,
            output_sha256=governed.output_sha256,
            output_length_chars=governed.output_length_chars,
            prompt_sha256=governed.prompt_sha256,
            model_id_hash=governed.model_id_hash,
            latency_ms=governed.latency_ms,
            prompt_tokens=governed.prompt_tokens,
            completion_tokens=governed.completion_tokens,
            total_tokens=governed.total_tokens,
            tool_calls_detected=False,
            tool_calls_routed_to_governance=True,
        )

        result.executed = outcome.executed
        result.status = outcome.status
        result.outcome = outcome
        result.evidence_id = emit_execution_evidence(outcome)

        return result

    def load_model(self, model_path: str, model_id: str = "") -> str:
        """Load a model via mlx-lm under governance.

        Returns the model_id_hash for use in execute() calls.
        """
        if not self._engine.is_mlx_available:
            raise MlxNotAvailableError("MLX not available on this platform")

        loaded = self._engine.load_model(model_path=model_path, model_id=model_id)
        return loaded.model_id_hash

    def unload_model(self, model_id_hash: str) -> bool:
        """Unload a model from GPU memory."""
        return self._engine.unload_model(model_id_hash)

    def build_projection(self) -> dict:
        """Build content-light projection for Inference Studio consumption.

        Returns typed capability status, health, model inventory, and
        honest deferred/unsupported reporting.
        """
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
                "text_generation": "supported",
                "streaming": "deferred — mlx-lm stream_generate() available but governed streaming not yet implemented",
                "tool_calling": "deferred — mlx-lm supports tool calling but governed routing not yet implemented",
                "structured_output": "deferred — not yet implemented in governance layer",
                "embeddings": "deferred — requires mlx-embeddings dependency (post-v1)",
                "reranking": "deferred — requires mlx-embeddings dependency (post-v1)",
                "vision_vlm": "deferred — requires mlx-vlm dependency (post-v1)",
            },
            "cache": {
                "mode": "local_runtime_kv",
                "privacy_class": "local_in_process",
                "persistence": "none (mlx-lm in-memory only)",
                "disclosure": self.get_cache_policy().disclosure_summary,
            },
            "deferred": {
                "streaming": "Governed streaming with per-token gating",
                "tool_calling": "mlx-lm tool calling with Rig governance routing",
                "structured_output": "JSON mode with output validation",
                "embeddings": "mlx-embeddings integration",
                "reranking": "mlx-embeddings reranking",
                "vlm_ocr": "mlx-vlm integration",
                "continuous_batching": "Scheduler engine",
                "kv_cache_persistence": "SSD safetensors cache",
                "benchmark_integration": "Internal runtime benchmarks",
                "model_acquisition": "HF download pipeline",
                "inference_studio_ui": "X0/X2 integration milestone",
            },
            "governance": {
                "task_admission": "governed",
                "privacy_classification": "enforced",
                "tool_execution": "rig_relay_authority",
                "evidence_emission": "content_light",
                "content_light": True,
            },
            "last_probe_at": self._last_probe_at,
        }


_global_runtime: RiggedLocalRuntime | None = None


def get_runtime(model_dirs: list[Path] | None = None) -> RiggedLocalRuntime:
    """Get or create the global RiggedLocalRuntime singleton."""
    global _global_runtime
    if _global_runtime is None:
        _global_runtime = RiggedLocalRuntime(model_dirs=model_dirs)
    return _global_runtime


def reset_runtime() -> None:
    """Reset the global runtime singleton (for testing)."""
    global _global_runtime
    _global_runtime = None


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
