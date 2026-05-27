"""RiggedLocalRuntime — Rig-governed internal MLX-backed inference runtime.

Integrates: RiggedMlxEngine, RiggedInferenceScheduler, RiggedCacheAuthority,
EvidenceLedgers (3), secret scanner, tool proposal corridor.

Exposes typed X0 Inference Studio consumer contract.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import secrets

from rig_relay.core.logger import logger
from rig_relay.governance.governance_engine import GovernanceEngine
from rig_relay.local_inference.runtime._cache_authority import RiggedCacheAuthority
from rig_relay.local_inference.runtime._engine import (
    MlxNotAvailableError,
    RiggedMlxEngine,
)
from rig_relay.local_inference.runtime._evidence import (
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
    RefusalReason,
    RuntimeHealth,
    RuntimeIdentity,
    RuntimeLifecycleState,
    TaskAdmissionDecision,
    TaskAdmissionResult,
    TaskKind,
    TaskRefusal,
    ToolCallProposal,
)
from rig_relay.local_inference.runtime._scheduler import RiggedInferenceScheduler
from rig_relay.local_inference.runtime._secrets import scan_messages_for_secrets
from rig_relay.runtime.models import RuntimeCapabilityKind, RuntimeProviderTrustTier


class RiggedLocalRuntime:
    def __init__(self, model_dirs: list[Path] | None = None) -> None:
        self._engine = RiggedMlxEngine()
        self._scheduler = RiggedInferenceScheduler(max_concurrent=1)
        self._cache = RiggedCacheAuthority()
        self._engine.set_cache_authority(self._cache)
        self._inventory: list[ModelInventoryEntry] = []
        self._health = RuntimeHealth()
        self._last_probe_at = ""
        self._model_dirs = model_dirs or []

    @property
    def is_configured(self) -> bool:
        return self._engine.is_mlx_available

    @property
    def runtime_kind(self) -> str:
        return "rigged_mlx_internal"

    @property
    def engine(self) -> RiggedMlxEngine:
        return self._engine

    @property
    def scheduler(self) -> RiggedInferenceScheduler:
        return self._scheduler

    @property
    def cache(self) -> RiggedCacheAuthority:
        return self._cache

    async def get_runtime_info(self) -> RuntimeIdentity:
        return RuntimeIdentity(
            runtime_kind="rigged_mlx_internal",
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
        loaded = {lm.model_id_hash for lm in self._engine.list_loaded_models()}
        for entry in self._inventory:
            entry.is_loaded = entry.model_id_hash in loaded
        return list(self._inventory)

    def _classify_and_admit(
        self,
        task_kind: TaskKind,
        messages: list[dict],
        caller_class: ContextPrivacyClass = ContextPrivacyClass.PRIVATE_LOCAL,
    ) -> tuple[TaskAdmissionDecision, ContextPrivacyClass, str]:
        effective_class = caller_class

        if not self._engine.is_mlx_available:
            return (
                TaskAdmissionDecision(
                    admitted=False,
                    task_kind=task_kind,
                    refusal_reason=RefusalReason.RUNTIME_NOT_CONFIGURED,
                ),
                effective_class,
                "",
            )

        scan = scan_messages_for_secrets(messages)
        if scan["secrets_detected"]:
            effective_class = ContextPrivacyClass.SECRET_BEARING
            logger.info(
                "runtime_secret_scan: detected=%d patterns=%s",
                scan["secrets_detected_count"],
                scan["patterns_matched"],
            )

        if effective_class == ContextPrivacyClass.SECRET_BEARING:
            return (
                TaskAdmissionDecision(
                    admitted=False,
                    task_kind=task_kind,
                    refusal_reason=RefusalReason.CONTEXT_BLOCKED_BY_POLICY,
                    context_privacy_class=effective_class,
                    admission_details=(
                        f"Secret-bearing content refused. Patterns: {scan['patterns_matched']}"
                    ),
                ),
                effective_class,
                "",
            )

        return (
            TaskAdmissionDecision(
                admitted=True,
                task_kind=task_kind,
                capability_match=True,
                privacy_approved=True,
                context_privacy_class=effective_class,
                admission_details="Admitted for governed local MLX execution.",
            ),
            effective_class,
            "",
        )

    async def execute(
        self,
        messages: list[dict],
        model_id_hash: str = "",
        task_kind: TaskKind = TaskKind.CHAT,
        context_privacy_class: ContextPrivacyClass = ContextPrivacyClass.PRIVATE_LOCAL,
        max_tokens: int = 4096,
    ) -> TaskAdmissionResult:
        admission, effective_class, _ = self._classify_and_admit(
            task_kind, messages, context_privacy_class
        )
        task_id_hash = _sha256(json.dumps(messages, sort_keys=True, default=str))

        if not admission.admitted:
            refusal = TaskRefusal(
                reason=admission.refusal_reason or RefusalReason.RUNTIME_NOT_CONFIGURED,
                detail=admission.admission_details,
                timestamp=_now_iso(),
            )
            result = TaskAdmissionResult(
                task_id_hash=task_id_hash,
                task_kind=task_kind,
                admission=admission,
                refusal=refusal,
                status=ExecutionStatus.REFUSED,
            )
            emit_refusal_receipt(
                _make_op_id(),
                {
                    "receipt_id": _make_op_id(),
                    "task_id_hash": task_id_hash,
                    "status": "refused",
                    "refusal_reason": refusal.reason.value,
                    "detail": refusal.detail,
                    "content_light": True,
                },
            )
            return result

        if not model_id_hash and self._engine.loaded_model_count > 0:
            model_id_hash = self._engine.list_loaded_models()[0].model_id_hash

        if not model_id_hash:
            refusal = TaskRefusal(
                reason=RefusalReason.CAPABILITY_UNSUPPORTED,
                detail="No model loaded.",
                timestamp=_now_iso(),
            )
            return TaskAdmissionResult(
                task_id_hash=task_id_hash,
                task_kind=task_kind,
                admission=admission,
                refusal=refusal,
                status=ExecutionStatus.BLOCKED,
            )

        req = await self._scheduler.enqueue(
            task_kind, messages, model_id_hash, max_tokens
        )
        admitted = await self._scheduler.admit_next()
        if admitted is None:
            refusal = TaskRefusal(
                reason=RefusalReason.TASK_NOT_ADMITTED,
                detail="Scheduler refused admission (max concurrent limit).",
                timestamp=_now_iso(),
            )
            return TaskAdmissionResult(
                task_id_hash=task_id_hash,
                task_kind=task_kind,
                admission=admission,
                refusal=refusal,
                status=ExecutionStatus.BLOCKED,
            )

        op_id = req.operation_id
        try:
            response = await asyncio.to_thread(
                self._engine.generate,
                model_id_hash=model_id_hash,
                messages=messages,
                max_tokens=max_tokens,
            )
        except Exception as e:
            await self._scheduler.fail(op_id, str(e))
            return TaskAdmissionResult(
                task_id_hash=task_id_hash,
                task_kind=task_kind,
                admission=admission,
                status=ExecutionStatus.ERROR,
                refusal=TaskRefusal(
                    reason=RefusalReason.RUNTIME_NOT_CONFIGURED,
                    detail=str(e),
                    timestamp=_now_iso(),
                ),
            )

        if response.tool_call_proposals:
            _handle_tool_proposals(response.tool_call_proposals, task_id_hash, op_id)

        receipt_payload = _build_execution_receipt_payload(
            task_id_hash, response, model_id_hash, effective_class, op_id
        )
        response.evidence_receipt_id = emit_execution_receipt(op_id, receipt_payload)

        await self._scheduler.complete(op_id, response)

        return TaskAdmissionResult(
            task_id_hash=task_id_hash,
            task_kind=task_kind,
            admission=admission,
            executed=True,
            status=ExecutionStatus.EXECUTED,
            response=response,
            evidence_receipt_id=response.evidence_receipt_id,
        )

    async def stream_execute(
        self,
        messages: list[dict],
        model_id_hash: str = "",
        max_tokens: int = 4096,
        task_kind: TaskKind = TaskKind.CHAT,
        context_privacy_class: ContextPrivacyClass = ContextPrivacyClass.PRIVATE_LOCAL,
    ) -> AsyncGenerator[str, None]:
        """Stream governed generation with admission gates and scheduler integration.

        Runs mlx-lm streaming in a dedicated thread via asyncio.to_thread.
        Yields tokens incrementally. Records evidence on completion.
        """
        admission, effective_class, _ = self._classify_and_admit(
            task_kind, messages, context_privacy_class
        )
        task_id_hash = _sha256(json.dumps(messages, sort_keys=True, default=str))

        if not admission.admitted:
            yield (
                f"[ERROR: {admission.refusal_reason.value}]"
                if admission.refusal_reason
                else "[ERROR: task not admitted]"
            )
            emit_refusal_receipt(
                _make_op_id(),
                {
                    "receipt_id": _make_op_id(),
                    "task_id_hash": task_id_hash,
                    "status": "refused",
                    "refusal_reason": (
                        admission.refusal_reason.value
                        if admission.refusal_reason
                        else "unknown"
                    ),
                    "detail": admission.admission_details,
                    "content_light": True,
                },
            )
            return

        if not self._engine.is_mlx_available:
            yield "[ERROR: MLX not available]"
            return

        if not model_id_hash and self._engine.loaded_model_count > 0:
            model_id_hash = self._engine.list_loaded_models()[0].model_id_hash

        if not model_id_hash:
            yield "[ERROR: No model loaded]"
            return

        req = await self._scheduler.enqueue(
            task_kind, messages, model_id_hash, max_tokens
        )
        admitted = await self._scheduler.admit_next()
        if admitted is None:
            yield "[ERROR: Scheduler refused admission]"
            return

        import queue as _sync_queue

        sync_q: _sync_queue.Queue = _sync_queue.Queue()
        cancel_flag: list[bool] = [False]

        _engine_fut = asyncio.ensure_future(
            asyncio.to_thread(
                self._engine.stream_generate_sync,
                model_id_hash,
                messages,
                max_tokens,
                sync_q,
                cancel_flag,
            )
        )

        accumulated: list[str] = []
        try:
            while True:
                item = await asyncio.to_thread(sync_q.get)
                kind, payload = item

                if kind == "token":
                    accumulated.append(str(payload))
                    yield str(payload)
                elif kind == "done":
                    break
                elif kind == "cancelled":
                    yield "[CANCELLED]"
                    await self._scheduler.cancel(req.operation_id)
                    return
                elif kind == "error":
                    yield f"[ERROR: {payload}]"
                    await self._scheduler.fail(req.operation_id, str(payload))
                    return
        except asyncio.CancelledError:
            cancel_flag[0] = True
            await self._scheduler.cancel(req.operation_id)
            raise

        full_text = "".join(accumulated)
        result: dict = payload  # type: ignore[assignment]
        tool_proposals = result.get("tool_call_proposals", [])
        finish = result.get("finish_reason", FinishReason.STOP)
        completion_tokens = result.get("completion_tokens", 0)
        cache_hit = result.get("cache_hit", False)

        response = LocalInferenceResponse(
            content=full_text,
            finish_reason=finish,
            tool_call_proposals=tool_proposals,
            completion_tokens=completion_tokens,
            model_id_hash=model_id_hash,
            cache_hit=cache_hit,
        )

        if tool_proposals:
            _handle_tool_proposals(tool_proposals, task_id_hash, req.operation_id)

        receipt_payload = _build_execution_receipt_payload(
            task_id_hash, response, model_id_hash, effective_class, req.operation_id
        )
        response.evidence_receipt_id = emit_execution_receipt(
            req.operation_id, receipt_payload
        )

        await self._scheduler.complete(req.operation_id, response)

    async def cancel_generation(self, op_id: str) -> bool:
        return await self._scheduler.cancel(op_id)

    async def clear_cache(self) -> bool:
        return await self._cache.clear_cache()

    def load_model(self, model_path: str, model_id: str = "") -> str:
        if not self._engine.is_mlx_available:
            raise MlxNotAvailableError("MLX not available")
        loaded = self._engine.load_model(model_path=model_path, model_id=model_id)
        emit_lifecycle_event(
            _make_op_id(),
            "rig.relay.runtime.model_loaded",
            {
                "schema_version": "rig.relay.runtime_lifecycle_event.v1",
                "event": "rig.relay.runtime.model_loaded",
                "model_id_hash": loaded.model_id_hash,
                "content_light": True,
            },
        )
        return loaded.model_id_hash

    def unload_model(self, model_id_hash: str) -> bool:
        result = self._engine.unload_model(model_id_hash)
        if result:
            emit_lifecycle_event(
                _make_op_id(),
                "rig.relay.runtime.model_unloaded",
                {
                    "schema_version": "rig.relay.runtime_lifecycle_event.v1",
                    "event": "rig.relay.runtime.model_unloaded",
                    "model_id_hash": model_id_hash,
                    "content_light": True,
                },
            )
        return result

    def build_projection(self) -> dict:
        """Typed X0 Inference Studio consumer contract."""
        return {
            "schema_version": "rig.relay.inference_studio_runtime_projection.v1",
            "runtime": {
                "kind": "rigged_mlx_internal",
                "platform": "metal_apple_silicon"
                if self._engine.is_mlx_available
                else "unavailable",
                "mlx_available": self._engine.is_mlx_available,
                "authority": ("governed_admission_with_pending_tool_execution"),
                "authority_detail": (
                    "Stateless governance preflight active. "
                    "Tool execution, checkpointing, and mutation safety "
                    "deferred to X0 integration."
                ),
            },
            "scheduler": self._scheduler.build_projection(),
            "cache": self._cache.build_projection(),
            "capabilities": {
                "text_generation": CapabilityPosture.SUPPORTED,
                "streaming_generation": CapabilityPosture.SUPPORTED,
                "tool_calling": CapabilityPosture.V1_REQUIRED_PENDING,
                "structured_output": CapabilityPosture.V1_REQUIRED_PENDING,
                "embeddings": CapabilityPosture.V1_REQUIRED_PENDING,
                "reranking": CapabilityPosture.V1_REQUIRED_PENDING,
                "vision_vlm": CapabilityPosture.V1_REQUIRED_PENDING,
                "continuous_batching": CapabilityPosture.V1_REQUIRED_PENDING,
                "kv_cache_reuse": CapabilityPosture.V1_REQUIRED_PENDING,
            },
            "privacy": {
                "secret_scanning": "enforced_before_admission",
                "private_local_context": "allowed",
                "secret_bearing_context": "refused",
            },
            "governance": {
                "evidence": "canonical_locked_digest_chained",
                "tool_execution": "stateless_preflight_admission_only",
                "tool_execution_detail": (
                    "Tool proposals are preflighted through "
                    "GovernanceEngine.evaluate_action_legality. Full execution "
                    "through ToolRuntime.execute_one() requires session context "
                    "and is deferred to X0 Inference Studio integration."
                ),
                "scheduler_authority": "serialized_fcfs_under_lock",
                "admission_gates": "secret_scanning_before_execution",
                "streaming_admission": "same_gates_as_execute",
            },
            "models": {
                "loaded_count": self._engine.loaded_model_count,
                "inventory_count": len(self._inventory),
                "lifecycle_events": "ledger: runtime_lifecycle_ledger.jsonl",
            },
            "health": {
                "state": self._health.state,
                "gpu_available": self._engine.is_mlx_available,
                "last_probe": self._last_probe_at,
            },
            "evidence_ledgers": {
                "execution": "runtime_execution_ledger.jsonl",
                "lifecycle": "runtime_lifecycle_ledger.jsonl",
                "cache": "runtime_cache_ledger.jsonl",
                "reconstruct": "RiggedLocalRuntime.reconstruct_evidence()",
            },
        }

    def reconstruct_evidence(self) -> dict[str, list[dict]]:
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


_TOOL_CAPABILITY_MAP: dict[str, RuntimeCapabilityKind] = {
    "bash": RuntimeCapabilityKind.SHELL_PROPOSAL,
    "write_file": RuntimeCapabilityKind.FILE_WRITE_PROPOSAL,
    "search_replace": RuntimeCapabilityKind.PATCH_PROPOSAL,
}


def _preflight_tool_proposal(proposal: ToolCallProposal) -> dict:
    """Stateless governance preflight for a single tool proposal."""
    capability = _TOOL_CAPABILITY_MAP.get(proposal.tool_name)

    arg_scan = scan_messages_for_secrets([{"content": proposal.arguments}])

    if arg_scan["secrets_detected"]:
        return {"status": "refused", "reason": "secret_in_arguments"}

    if capability is None:
        return {"status": "pending_review", "reason": "unknown_tool"}

    decision = GovernanceEngine.evaluate_action_legality(
        intent_id=proposal.call_id,
        intent_kind="tool_execution",
        requested_capabilities=[capability],
        provider_trust_tier=RuntimeProviderTrustTier.EXECUTOR_CANDIDATE,
        allow_mutation=True,
    )

    allowed = decision.decision.value == "allowed"
    return {
        "status": (
            "admitted_pending_execution" if allowed else "refused_by_governance"
        ),
        "reason": (
            str(decision.reasons[0].message)
            if decision.reasons
            else "preflight_complete"
        ),
        "governance_decision": decision.decision.value,
    }


def _handle_tool_proposals(
    proposals: list[ToolCallProposal], task_id_hash: str, op_id: str
) -> None:
    for p in proposals:
        logger.info(
            "runtime_tool_proposal: task=%s tool=%s call_id=%s",
            task_id_hash[:12],
            p.tool_name,
            p.call_id,
        )

    preflight_results = [_preflight_tool_proposal(p) for p in proposals]

    all_admitted = all(
        r["status"] == "admitted_pending_execution" for r in preflight_results
    )

    emit_tool_proposal_evidence(
        op_id,
        {
            "receipt_id": op_id,
            "task_id_hash": task_id_hash,
            "status": "tool_proposals_detected",
            "schema_version": "rig.relay.runtime.tool_proposal.v1",
            "proposal_count": len(proposals),
            "proposals": [
                {
                    "call_id": p.call_id,
                    "tool_name": p.tool_name,
                    "governance_action": r["status"],
                    "secret_safe": not (
                        r["status"] == "refused"
                        and r.get("reason") == "secret_in_arguments"
                    ),
                }
                for p, r in zip(proposals, preflight_results, strict=True)
            ],
            "governance_disposition": (
                "admitted_pending_execution" if all_admitted else "mixed_refused"
            ),
            "content_light": True,
        },
    )


def _build_execution_receipt_payload(
    task_id_hash: str,
    response: LocalInferenceResponse,
    model_id_hash: str,
    privacy_class: ContextPrivacyClass,
    op_id: str,
) -> dict:
    output_sha = (
        hashlib.sha256(response.content.encode()).hexdigest()
        if response.content
        else ""
    )
    return {
        "receipt_id": op_id,
        "task_id_hash": task_id_hash,
        "status": "executed",
        "prompt_sha256": "",
        "output_sha256": output_sha,
        "output_length_chars": len(response.content),
        "model_id_hash": model_id_hash,
        "latency_ms": response.latency_ms,
        "prompt_tokens": response.prompt_tokens,
        "completion_tokens": response.completion_tokens,
        "total_tokens": response.total_tokens,
        "finish_reason": response.finish_reason.value
        if response.finish_reason
        else None,
        "tool_call_count": len(response.tool_call_proposals),
        "tool_proposals_routed": bool(response.tool_call_proposals),
        "context_privacy_class": privacy_class.value,
        "cache_hit": response.cache_hit,
        "content_light": True,
    }


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


def _make_op_id() -> str:
    return f"op_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(6)}"
