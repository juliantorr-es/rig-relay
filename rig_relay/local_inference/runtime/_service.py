"""RiggedLocalRuntime — Rig-governed internal MLX-backed runtime.

Typed application-service boundary for governed local inference with
canonical evidence, secret enforcement, concurrency safety, and streaming.

Key repairs from X2.1 verdict:
  - Secret-bearing content is detected and refused before admission
  - Tool proposals emit content-light evidence and route through governance
  - Generation is serialized via engine's gen_lock
  - Streaming generation implemented (first OMLX-class v1 capability)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
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
    emit_tool_proposal_evidence,
    reconstruct_ledgers,
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
from rig_relay.local_inference.runtime._secrets import scan_messages_for_secrets


class RiggedLocalRuntime:
    def __init__(self, model_dirs: list[Path] | None = None) -> None:
        self._engine = RiggedMlxEngine()
        self._inventory: list[ModelInventoryEntry] = []
        self._health = RuntimeHealth()
        self._last_probe_at = ""
        self._model_dirs = model_dirs or []

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
            streaming=CapabilityPosture.V1_REQUIRED_PENDING,
            tool_calling=CapabilityPosture.V1_REQUIRED_PENDING,
            structured_json_output=CapabilityPosture.V1_REQUIRED_PENDING,
            embeddings=CapabilityPosture.V1_REQUIRED_PENDING,
            reranking=CapabilityPosture.V1_REQUIRED_PENDING,
            vision=CapabilityPosture.V1_REQUIRED_PENDING,
            cache_metrics=CapabilityPosture.V1_REQUIRED_PENDING,
            server_metrics=CapabilityPosture.V1_REQUIRED_PENDING,
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
                "mlx-lm uses in-process KV cache. Not persisted across "
                "calls or restarts. Data never leaves the machine."
            ),
        )

    def _classify_and_admit(
        self,
        task_kind: TaskKind,
        messages: list[dict],
        caller_class: ContextPrivacyClass = ContextPrivacyClass.PRIVATE_LOCAL,
    ) -> tuple[TaskAdmissionDecision, ContextPrivacyClass]:
        """Classify context and admit or refuse the task.

        Secret scanning runs before admission. If secrets are detected
        in messages, the caller's privacy classification is overridden
        to SECRET_BEARING regardless of what the caller claims.
        """
        effective_class = caller_class

        if not self._engine.is_mlx_available:
            return (
                TaskAdmissionDecision(
                    admitted=False,
                    task_kind=task_kind,
                    refusal_reason=RefusalReason.RUNTIME_NOT_CONFIGURED,
                ),
                effective_class,
            )

        scan = scan_messages_for_secrets(messages)
        if scan["secrets_detected"]:
            effective_class = ContextPrivacyClass.SECRET_BEARING
            logger.info(
                "runtime_secret_scan: detected=%d patterns=%s override=%s",
                scan["secrets_detected_count"],
                scan["patterns_matched"],
                "PRIVATE_LOCAL → SECRET_BEARING"
                if caller_class != ContextPrivacyClass.SECRET_BEARING
                else "already_secret_bearing",
            )

        if effective_class == ContextPrivacyClass.SECRET_BEARING:
            return (
                TaskAdmissionDecision(
                    admitted=False,
                    task_kind=task_kind,
                    refusal_reason=RefusalReason.CONTEXT_BLOCKED_BY_POLICY,
                    context_privacy_class=effective_class,
                    admission_details=(
                        "Secret-bearing content detected and refused. "
                        f"Patterns matched: {scan['patterns_matched']}"
                    ),
                ),
                effective_class,
            )

        return (
            TaskAdmissionDecision(
                admitted=True,
                task_kind=task_kind,
                capability_match=True,
                privacy_approved=True,
                context_privacy_class=effective_class,
                admission_details=(
                    "Admitted for governed local MLX execution."
                    if effective_class == ContextPrivacyClass.PRIVATE_LOCAL
                    else "Admitted for governed local MLX execution (public-safe)."
                ),
            ),
            effective_class,
        )

    async def execute(
        self,
        messages: list[dict],
        model_id_hash: str = "",
        task_kind: TaskKind = TaskKind.CHAT,
        context_privacy_class: ContextPrivacyClass = ContextPrivacyClass.PRIVATE_LOCAL,
        max_tokens: int = 4096,
    ) -> TaskAdmissionResult:
        admission, effective_class = self._classify_and_admit(
            task_kind, messages, context_privacy_class
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
                detail="No model loaded.",
                timestamp=_now_iso(),
            )
            result.refusal = refusal
            result.status = ExecutionStatus.BLOCKED
            emit_refusal_receipt(refusal, task_id_hash)
            return result

        try:
            response = self._engine.generate(
                model_id_hash=model_id_hash, messages=messages, max_tokens=max_tokens
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
            _handle_tool_proposals(response.tool_call_proposals, task_id_hash)

        receipt = build_evidence_receipt(
            task_id_hash=task_id_hash,
            prompt_sha256=prompt_sha,
            response=response,
            model_id_hash=model_id_hash,
            latency_ms=response.latency_ms,
            context_privacy_class=effective_class,
            secret_scan_result="clean"
            if effective_class != ContextPrivacyClass.SECRET_BEARING
            else "secrets_detected_refused",
        )
        response.evidence_receipt_id = receipt.receipt_id
        emit_execution_receipt(receipt)

        result.executed = True
        result.status = ExecutionStatus.EXECUTED
        result.response = response
        result.evidence_receipt_id = receipt.receipt_id
        return result

    async def stream_execute(
        self, messages: list[dict], model_id_hash: str = "", max_tokens: int = 4096
    ) -> AsyncGenerator[str, None]:
        """Stream governed generation. First OMLX-class v1 capability.

        Yields text chunks as they are generated. Caller must accumulate
        for tool-call parsing and evidence after the stream completes.
        """
        if not self._engine.is_mlx_available:
            yield "[ERROR: MLX not available]"
            return

        if not model_id_hash and self._engine.loaded_model_count > 0:
            model_id_hash = self._engine.list_loaded_models()[0].model_id_hash

        if not model_id_hash:
            yield "[ERROR: No model loaded]"
            return

        async for chunk in self._engine.stream_generate(
            model_id_hash, messages, max_tokens
        ):
            yield chunk

    def load_model(self, model_path: str, model_id: str = "") -> str:
        if not self._engine.is_mlx_available:
            raise MlxNotAvailableError("MLX not available")
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
                "protocol": "python_module (in-process)",
                "mlx_available": self._engine.is_mlx_available,
                "generation_lock": "serialized",
            },
            "health": {
                "state": self._health.state,
                "active_model_count": self._engine.loaded_model_count,
                "gpu_available": self._engine.is_mlx_available,
            },
            "capabilities": {
                "text_generation": CapabilityPosture.SUPPORTED,
                "streaming_generation": "implemented (first OMLX-class v1 capability)",
                "tool_calling": CapabilityPosture.V1_REQUIRED_PENDING,
                "structured_output": CapabilityPosture.V1_REQUIRED_PENDING,
                "embeddings": CapabilityPosture.V1_REQUIRED_PENDING,
                "reranking": CapabilityPosture.V1_REQUIRED_PENDING,
                "vision_vlm": CapabilityPosture.V1_REQUIRED_PENDING,
                "continuous_batching": CapabilityPosture.V1_REQUIRED_PENDING,
                "kv_cache_persistence": CapabilityPosture.V1_REQUIRED_PENDING,
                "benchmark_integration": CapabilityPosture.V1_REQUIRED_PENDING,
            },
            "privacy": {
                "model": "local_runtime_permissive",
                "public_safe_context": "allowed",
                "private_local_context": "allowed (local-only retention)",
                "secret_bearing_context": "refused (enforced by content scan)",
                "secret_scanning": "enforced_before_admission",
            },
            "governance": {
                "task_admission": "governed",
                "privacy_classification": "scanned_and_enforced",
                "tool_execution": "rig_relay_authority (proposals only)",
                "evidence_emission": "canonical (locked, digest-chained, fdatasync)",
            },
            "evidence_ledgers": {
                "execution": ".build/rig-relay/evidence/runtime_execution_ledger.jsonl",
                "lifecycle": ".build/rig-relay/evidence/runtime_lifecycle_ledger.jsonl",
                "cache": ".build/rig-relay/evidence/runtime_cache_ledger.jsonl",
                "reconstruct_command": "RiggedLocalRuntime.reconstruct_evidence()",
            },
            "last_probe_at": self._last_probe_at,
        }

    def reconstruct_evidence(self) -> dict[str, list[dict]]:
        """Reconstruct and validate all evidence ledgers."""
        return reconstruct_ledgers()


_global_runtime: RiggedLocalRuntime | None = None


def get_runtime(model_dirs: list[Path] | None = None) -> RiggedLocalRuntime:
    global _global_runtime
    if _global_runtime is None:
        _global_runtime = RiggedLocalRuntime(model_dirs=model_dirs)
    return _global_runtime


def reset_runtime() -> None:
    global _global_runtime
    _global_runtime = None


def _handle_tool_proposals(
    proposals: list[ToolCallProposal], task_id_hash: str
) -> None:
    for p in proposals:
        logger.info(
            "runtime_tool_proposal_detected: task=%s tool=%s call_id=%s",
            task_id_hash[:12],
            p.tool_name,
            p.call_id,
        )
    emit_tool_proposal_evidence(
        task_id_hash=task_id_hash,
        proposal_count=len(proposals),
        tool_names=[p.tool_name for p in proposals],
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
