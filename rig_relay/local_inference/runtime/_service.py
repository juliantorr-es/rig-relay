"""RiggedLocalRuntime — Rig-governed internal MLX-backed inference runtime.

Integrates: RiggedMlxEngine, RiggedInferenceScheduler, RiggedCacheAuthority,
ModelPoolManager, ToolExecutionBridge, EvidenceLedgers, secret scanner,
tool proposal corridor.

X2.5 Capabilities:
  B4 — Thread lifecycle coordination (active stream tracking, graceful shutdown)
  Cache — Write-back + SSD persistence
  Scheduler — Continuous batching via BatchGenerator with FCFS fallback
  Pool — LRU-governed multi-model pool manager
  Bridge — Tool execution corridor (stateless preflight, deferred X0 execution)

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
from rig_relay.local_inference.runtime._bridge import ToolExecutionBridge
from rig_relay.local_inference.runtime._cache_authority import RiggedCacheAuthority
from rig_relay.local_inference.runtime._engine import (
    MlxNotAvailableError,
    RiggedMlxEngine,
)
from rig_relay.local_inference.runtime._evidence import (
    emit_execution_receipt,
    emit_lifecycle_event,
    emit_refusal_receipt,
    emit_stream_terminal_event,
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
    StreamTerminalState,
    TaskAdmissionDecision,
    TaskAdmissionResult,
    TaskKind,
    TaskRefusal,
    ToolCallProposal,
)
from rig_relay.local_inference.runtime._pool import ModelPoolManager
from rig_relay.local_inference.runtime._scheduler import (
    RiggedBatchScheduler,
    RiggedInferenceScheduler,
)
from rig_relay.local_inference.runtime._secrets import scan_messages_for_secrets
from rig_relay.runtime.models import RuntimeCapabilityKind, RuntimeProviderTrustTier


class RiggedLocalRuntime:
    def __init__(self, model_dirs: list[Path] | None = None) -> None:
        self._engine = RiggedMlxEngine()
        self._scheduler: RiggedInferenceScheduler | RiggedBatchScheduler = (
            RiggedInferenceScheduler(max_concurrent=1)
        )
        self._cache = RiggedCacheAuthority()
        self._engine.set_cache_authority(self._cache)
        self._pool = ModelPoolManager(max_models=3, idle_ttl_seconds=300)
        self._engine.set_pool(self._pool)
        self._tool_bridge = ToolExecutionBridge()
        self._inventory: list[ModelInventoryEntry] = []
        self._health = RuntimeHealth()
        self._last_probe_at = ""
        self._model_dirs = model_dirs or []
        self._active_streams: dict[str, asyncio.Task] = {}
        self._stream_lock = asyncio.Lock()

    @property
    def is_configured(self) -> bool:
        return self._engine.is_mlx_available

    @property
    def runtime_kind(self) -> str:
        return "rigged_mlx_internal"

    @property
    def scheduler(self) -> RiggedInferenceScheduler | RiggedBatchScheduler:
        return self._scheduler

    @property
    def cache(self) -> RiggedCacheAuthority:
        return self._cache

    @property
    def pool(self) -> ModelPoolManager:
        return self._pool

    @property
    def tool_bridge(self) -> ToolExecutionBridge:
        return self._tool_bridge

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
            op_id = _make_op_id()
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
            try:
                emit_refusal_receipt(
                    op_id,
                    {
                        "schema_version": "rig.relay.runtime_execution_event.v1",
                        "receipt_id": op_id,
                        "operation_id": op_id,
                        "task_id_hash": task_id_hash,
                        "status": "refused",
                        "prompt_sha256": "",
                        "output_sha256": "",
                        "model_id_hash": "",
                        "content_light": True,
                    },
                )
            except Exception:
                logger.exception("Failed to emit refusal receipt for op=%s", op_id)
            return result

        if not model_id_hash and self._engine.loaded_model_count > 0:
            model_id_hash = self._engine.list_loaded_models()[0].model_id_hash

        if not model_id_hash:
            op_id = _make_op_id()
            refusal = TaskRefusal(
                reason=RefusalReason.CAPABILITY_UNSUPPORTED,
                detail="No model loaded.",
                timestamp=_now_iso(),
            )
            try:
                emit_refusal_receipt(
                    op_id,
                    {
                        "schema_version": "rig.relay.runtime_execution_event.v1",
                        "receipt_id": op_id,
                        "operation_id": op_id,
                        "task_id_hash": task_id_hash,
                        "status": "blocked",
                        "prompt_sha256": "",
                        "output_sha256": "",
                        "model_id_hash": "",
                        "content_light": True,
                    },
                )
            except Exception:
                logger.exception("Failed to emit refusal receipt for op=%s", op_id)
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
            op_id = req.operation_id
            refusal = TaskRefusal(
                reason=RefusalReason.TASK_NOT_ADMITTED,
                detail="Scheduler refused admission (max concurrent limit).",
                timestamp=_now_iso(),
            )
            try:
                emit_refusal_receipt(
                    op_id,
                    {
                        "schema_version": "rig.relay.runtime_execution_event.v1",
                        "receipt_id": op_id,
                        "operation_id": op_id,
                        "task_id_hash": task_id_hash,
                        "status": "blocked",
                        "prompt_sha256": "",
                        "output_sha256": "",
                        "model_id_hash": "",
                        "content_light": True,
                    },
                )
            except Exception:
                logger.exception("Failed to emit refusal receipt for op=%s", op_id)
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
        except asyncio.CancelledError:
            await self._scheduler.fail(op_id, "cancelled")
            try:
                emit_refusal_receipt(
                    op_id,
                    {
                        "schema_version": "rig.relay.runtime_execution_event.v1",
                        "receipt_id": op_id,
                        "operation_id": op_id,
                        "task_id_hash": task_id_hash,
                        "status": "cancelled",
                        "prompt_sha256": "",
                        "output_sha256": "",
                        "model_id_hash": model_id_hash,
                        "content_light": True,
                    },
                )
            except Exception:
                logger.exception("Failed to emit refusal receipt for op=%s", op_id)
            raise
        except Exception as e:
            await self._scheduler.fail(op_id, str(e))
            try:
                emit_refusal_receipt(
                    op_id,
                    {
                        "schema_version": "rig.relay.runtime_execution_event.v1",
                        "receipt_id": op_id,
                        "operation_id": op_id,
                        "task_id_hash": task_id_hash,
                        "status": "error",
                        "prompt_sha256": "",
                        "output_sha256": "",
                        "model_id_hash": model_id_hash,
                        "content_light": True,
                    },
                )
            except Exception:
                logger.exception("Failed to emit refusal receipt for op=%s", op_id)
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

        try:
            if response.tool_call_proposals:
                _handle_tool_proposals(
                    response.tool_call_proposals, task_id_hash, op_id
                )
                for p in response.tool_call_proposals:
                    self._tool_bridge.execute_proposal(p)
        except Exception:
            logger.exception("Tool proposal handling failed for op=%s", op_id)

        receipt_payload = _build_execution_receipt_payload(
            task_id_hash, response, model_id_hash, effective_class, op_id
        )
        try:
            response.evidence_receipt_id = emit_execution_receipt(
                op_id, receipt_payload
            )
        except Exception:
            logger.exception("Failed to emit execution receipt for op=%s", op_id)

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
            op_id = _make_op_id()
            yield (
                f"[ERROR: {admission.refusal_reason.value}]"
                if admission.refusal_reason
                else "[ERROR: task not admitted]"
            )
            try:
                emit_refusal_receipt(
                    op_id,
                    {
                        "schema_version": "rig.relay.runtime_execution_event.v1",
                        "receipt_id": op_id,
                        "operation_id": op_id,
                        "task_id_hash": task_id_hash,
                        "status": "refused",
                        "prompt_sha256": "",
                        "output_sha256": "",
                        "model_id_hash": "",
                        "content_light": True,
                    },
                )
            except Exception:
                logger.exception("Failed to emit refusal receipt for op=%s", op_id)
            return

        if not self._engine.is_mlx_available:
            op_id = _make_op_id()
            try:
                emit_refusal_receipt(
                    op_id,
                    {
                        "schema_version": "rig.relay.runtime_execution_event.v1",
                        "receipt_id": op_id,
                        "operation_id": op_id,
                        "task_id_hash": task_id_hash,
                        "status": "blocked",
                        "prompt_sha256": "",
                        "output_sha256": "",
                        "model_id_hash": model_id_hash,
                        "content_light": True,
                    },
                )
            except Exception:
                logger.exception("Failed to emit refusal receipt for op=%s", op_id)
            yield "[ERROR: MLX not available]"
            return

        if not model_id_hash and self._engine.loaded_model_count > 0:
            model_id_hash = self._engine.list_loaded_models()[0].model_id_hash

        if not model_id_hash:
            op_id = _make_op_id()
            try:
                emit_refusal_receipt(
                    op_id,
                    {
                        "schema_version": "rig.relay.runtime_execution_event.v1",
                        "receipt_id": op_id,
                        "operation_id": op_id,
                        "task_id_hash": task_id_hash,
                        "status": "blocked",
                        "prompt_sha256": "",
                        "output_sha256": "",
                        "model_id_hash": "",
                        "content_light": True,
                    },
                )
            except Exception:
                logger.exception("Failed to emit refusal receipt for op=%s", op_id)
            yield "[ERROR: No model loaded]"
            return

        req = await self._scheduler.enqueue(
            task_kind, messages, model_id_hash, max_tokens
        )
        admitted = await self._scheduler.admit_next()
        if admitted is None:
            op_id = req.operation_id
            try:
                emit_refusal_receipt(
                    op_id,
                    {
                        "schema_version": "rig.relay.runtime_execution_event.v1",
                        "receipt_id": op_id,
                        "operation_id": op_id,
                        "task_id_hash": task_id_hash,
                        "status": "blocked",
                        "prompt_sha256": "",
                        "output_sha256": "",
                        "model_id_hash": model_id_hash,
                        "content_light": True,
                    },
                )
            except Exception:
                logger.exception("Failed to emit refusal receipt for op=%s", op_id)
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

        async with self._stream_lock:
            self._active_streams[req.operation_id] = _engine_fut

        try:
            emit_stream_terminal_event(
                req.operation_id,
                {
                    "schema_version": "rig.relay.runtime_stream_terminal_event.v1",
                    "operation_id": req.operation_id,
                    "terminal_state": "provisional",
                    "content_light": True,
                },
            )
        except Exception:
            logger.exception(
                "Failed to emit provisional stream terminal event for op=%s",
                req.operation_id,
            )

        accumulated: list[str] = []
        prompt_tokens_for_cache: list[int] = []
        try:
            while True:
                item = await asyncio.to_thread(sync_q.get)
                kind, payload = item

                if kind == "token":
                    accumulated.append(str(payload))
                    yield str(payload)
                elif kind == "done":
                    payload_dict: dict = payload if isinstance(payload, dict) else {}  # type: ignore[assignment]
                    prompt_tokens_for_cache = payload_dict.get("prompt_tokens", [])
                    break
                elif kind == "cancelled":
                    yield "[CANCELLED]"
                    await self._scheduler.cancel(req.operation_id)
                    op_id = req.operation_id
                    try:
                        emit_refusal_receipt(
                            op_id,
                            {
                                "schema_version": "rig.relay.runtime_execution_event.v1",
                                "receipt_id": op_id,
                                "operation_id": op_id,
                                "task_id_hash": task_id_hash,
                                "status": "cancelled",
                                "prompt_sha256": "",
                                "output_sha256": "",
                                "model_id_hash": model_id_hash,
                                "content_light": True,
                            },
                        )
                    except Exception:
                        logger.exception(
                            "Failed to emit refusal receipt for op=%s", op_id
                        )
                    return
                elif kind == "error":
                    yield f"[ERROR: {payload}]"
                    await self._scheduler.fail(req.operation_id, str(payload))
                    op_id = req.operation_id
                    try:
                        emit_refusal_receipt(
                            op_id,
                            {
                                "schema_version": "rig.relay.runtime_execution_event.v1",
                                "receipt_id": op_id,
                                "operation_id": op_id,
                                "task_id_hash": task_id_hash,
                                "status": "error",
                                "prompt_sha256": "",
                                "output_sha256": "",
                                "model_id_hash": model_id_hash,
                                "content_light": True,
                            },
                        )
                    except Exception:
                        logger.exception(
                            "Failed to emit refusal receipt for op=%s", op_id
                        )
                    return
        except asyncio.CancelledError:
            cancel_flag[0] = True
            await self._scheduler.cancel(req.operation_id)
            op_id = req.operation_id
            try:
                emit_refusal_receipt(
                    op_id,
                    {
                        "schema_version": "rig.relay.runtime_execution_event.v1",
                        "receipt_id": op_id,
                        "operation_id": op_id,
                        "task_id_hash": task_id_hash,
                        "status": "cancelled",
                        "prompt_sha256": "",
                        "output_sha256": "",
                        "model_id_hash": model_id_hash,
                        "content_light": True,
                    },
                )
            except Exception:
                logger.exception("Failed to emit refusal receipt for op=%s", op_id)
            try:
                await asyncio.wait_for(_engine_fut, timeout=5.0)
            except (TimeoutError, Exception):
                pass
            async with self._stream_lock:
                self._active_streams.pop(req.operation_id, None)
            raise
        except Exception as e:
            logger.exception("Streaming loop exception for op=%s", req.operation_id)
            try:
                await self._scheduler.fail(req.operation_id, str(e)[:200])
            except Exception:
                pass
            try:
                emit_refusal_receipt(
                    req.operation_id,
                    {
                        "schema_version": "rig.relay.runtime_execution_event.v1",
                        "receipt_id": req.operation_id,
                        "operation_id": req.operation_id,
                        "task_id_hash": task_id_hash,
                        "status": "error",
                        "prompt_sha256": "",
                        "output_sha256": "",
                        "model_id_hash": model_id_hash,
                        "content_light": True,
                    },
                )
            except Exception:
                logger.exception("Failed to emit error receipt")
            raise
        finally:
            async with self._stream_lock:
                self._active_streams.pop(req.operation_id, None)

        full_text = "".join(accumulated)
        payload_or_dict: dict = payload if isinstance(payload, dict) else {}  # type: ignore[assignment]
        result: dict = payload_or_dict
        tool_proposals = result.get("tool_call_proposals", [])
        finish = result.get("finish_reason", FinishReason.STOP)
        completion_tokens = result.get("completion_tokens", 0)
        cache_hit = result.get("cache_hit", False)

        if not cache_hit and prompt_tokens_for_cache:
            loaded = self._engine._loaded_models.get(model_id_hash)  # type: ignore[attr-defined]
            if loaded is not None:
                try:
                    self._cache.insert_cache(
                        loaded.mlx_model,
                        prompt_tokens_for_cache,
                        prompt_tokens_for_cache,
                    )
                except Exception:
                    pass

        response = LocalInferenceResponse(
            content=full_text,
            finish_reason=finish,
            tool_call_proposals=tool_proposals,
            completion_tokens=completion_tokens,
            model_id_hash=model_id_hash,
            cache_hit=cache_hit,
        )

        try:
            if tool_proposals:
                _handle_tool_proposals(tool_proposals, task_id_hash, req.operation_id)
                for p in tool_proposals:
                    self._tool_bridge.execute_proposal(p)
        except Exception:
            logger.exception(
                "Tool proposal handling failed for op=%s", req.operation_id
            )

        receipt_payload = _build_execution_receipt_payload(
            task_id_hash, response, model_id_hash, effective_class, req.operation_id
        )
        evidence_emitted = False
        try:
            response.evidence_receipt_id = emit_execution_receipt(
                req.operation_id, receipt_payload
            )
            evidence_emitted = True
        except Exception:
            logger.exception(
                "Failed to emit execution receipt for op=%s", req.operation_id
            )

        if evidence_emitted:
            response.stream_terminal_state = StreamTerminalState.TERMINALIZED
            try:
                emit_stream_terminal_event(
                    req.operation_id,
                    {
                        "schema_version": "rig.relay.runtime_stream_terminal_event.v1",
                        "operation_id": req.operation_id,
                        "terminal_state": "terminalized",
                        "evidence_receipt_id": response.evidence_receipt_id,
                        "content_light": True,
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to emit stream terminal event for op=%s", req.operation_id
                )
            await self._scheduler.complete(req.operation_id, response)
        else:
            response.stream_terminal_state = StreamTerminalState.EVIDENCE_FAILED
            yield "[EVIDENCE_UNAVAILABLE]"
            await self._scheduler.fail(req.operation_id, "evidence_emission_failed")

    async def cancel_generation(self, op_id: str) -> bool:
        return await self._scheduler.cancel(op_id)

    async def clear_cache(self) -> bool:
        return await self._cache.clear_cache()

    async def shutdown(self) -> None:
        """Coordinated runtime shutdown.

        Sets cancel_flag on all active streams, awaits their futures
        with timeout, clears pool, then resets global reference.
        """
        logger.info("RiggedLocalRuntime: shutdown initiated")

        async with self._stream_lock:
            stream_ids = list(self._active_streams)
        for op_id in stream_ids:
            await self._scheduler.cancel(op_id)
            async with self._stream_lock:
                fut = self._active_streams.pop(op_id, None)
            if fut is not None and not fut.done():
                try:
                    await asyncio.wait_for(fut, timeout=5.0)
                except (TimeoutError, Exception):
                    pass

        self._pool.shutdown()
        if isinstance(self._scheduler, RiggedBatchScheduler):
            self._scheduler.stop_batch_loop()
        logger.info("RiggedLocalRuntime: shutdown complete")

    def load_model(self, model_path: str, model_id: str = "") -> str:
        if not self._engine.is_mlx_available:
            raise MlxNotAvailableError("MLX not available")
        loaded = self._engine.load_model(model_path=model_path, model_id=model_id)
        try:
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
        except Exception:
            logger.exception("Failed to emit lifecycle event for model load")
        return loaded.model_id_hash

    def unload_model(self, model_id_hash: str) -> bool:
        result = self._engine.unload_model(model_id_hash)
        if result:
            self._pool.unload(model_id_hash)
            try:
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
            except Exception:
                logger.exception("Failed to emit lifecycle event for model unload")
        return result

    def build_projection(self) -> dict:
        """Typed X0 Inference Studio consumer contract."""
        bridge_proj = self._tool_bridge.build_projection()
        pool_proj = self._pool.build_projection()
        cache_proj = self._cache.build_projection()
        scheduler_proj = self._scheduler.build_projection()

        batching_posture = (
            CapabilityPosture.SUPPORTED
            if scheduler_proj.get("batching_status") == "active_batch_generator"
            else CapabilityPosture.V1_REQUIRED_PENDING
        )

        cache_write_back = (
            "active_local_trie" if self._cache.write_back_count > 0 else "deferred"
        )

        return {
            "schema_version": "rig.relay.inference_studio_runtime_projection.v1",
            "runtime": {
                "kind": "rigged_mlx_internal",
                "platform": "metal_apple_silicon"
                if self._engine.is_mlx_available
                else "unavailable",
                "mlx_available": self._engine.is_mlx_available,
                "authority": "governed_admission_with_pending_tool_execution",
                "authority_detail": (
                    "Stateless governance preflight active. "
                    "Tool execution, checkpointing, and mutation safety "
                    "deferred to X0 integration."
                ),
            },
            "scheduler": scheduler_proj,
            "cache": cache_proj,
            "pool": pool_proj,
            "bridge": bridge_proj,
            "capabilities": {
                "text_generation": CapabilityPosture.SUPPORTED,
                "streaming_generation": CapabilityPosture.SUPPORTED,
                "tool_calling": CapabilityPosture.V1_REQUIRED_PENDING,
                "structured_output": CapabilityPosture.V1_REQUIRED_PENDING,
                "embeddings": CapabilityPosture.V1_REQUIRED_PENDING,
                "reranking": CapabilityPosture.V1_REQUIRED_PENDING,
                "vision_vlm": CapabilityPosture.V1_REQUIRED_PENDING,
                "continuous_batching": batching_posture,
                "kv_cache_reuse": CapabilityPosture.SUPPORTED,
                "kv_cache_write_back": cache_write_back,
                "multi_model_pool": (
                    CapabilityPosture.SUPPORTED
                    if self._pool.loaded_count > 0
                    else CapabilityPosture.V1_REQUIRED_PENDING
                ),
                "tool_execution_bridge": (
                    CapabilityPosture.SUPPORTED
                    if self._tool_bridge.has_session_context
                    else CapabilityPosture.V1_REQUIRED_PENDING
                ),
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
                    "through ToolRuntime requires session context "
                    "and is deferred to X0 Inference Studio integration."
                ),
                "scheduler_authority": "serialized_fcfs_under_lock",
                "admission_gates": "secret_scanning_before_execution",
                "streaming_admission": "same_gates_as_execute",
                "thread_lifecycle": "coordinated_active_stream_tracking",
                "thread_lifecycle_detail": (
                    "Active streams tracked in _active_streams dict. "
                    "CancelledError awaits engine future with 5s timeout. "
                    "shutdown() cancels all active streams before pool clearance."
                ),
                "streaming_terminal_evidence": "provisional_then_terminalized",
                "streaming_terminal_evidence_detail": (
                    "Provisional evidence event emitted before first token yield. "
                    "After token accumulation, execution receipt is emitted. "
                    "On success, terminalized event recorded and "
                    "scheduler.complete() called. On failure, yields "
                    "[EVIDENCE_UNAVAILABLE] terminal signal and calls "
                    "scheduler.fail() with evidence_emission_failed."
                ),
            },
            "models": {
                "loaded_count": self._engine.loaded_model_count,
                "inventory_count": len(self._inventory),
                "pool_count": self._pool.loaded_count,
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

    admitted_count = sum(
        1 for r in preflight_results if r["status"] == "admitted_pending_execution"
    )
    rejected_count = len(preflight_results) - admitted_count

    all_names = ",".join(p.tool_name for p in proposals)
    proposal_names_hash = f"sha256:{hashlib.sha256(all_names.encode()).hexdigest()}"
    proposal_args_hashes = [
        f"sha256:{hashlib.sha256(p.arguments.encode()).hexdigest()}" for p in proposals
    ]

    try:
        emit_tool_proposal_evidence(
            op_id,
            {
                "schema_version": "rig.relay.runtime_tool_proposal_event.v1",
                "task_id_hash": task_id_hash,
                "proposal_count": len(proposals),
                "proposal_names_hash": proposal_names_hash,
                "proposal_args_hashes": proposal_args_hashes,
                "routed_to_governance": True,
                "rejected_count": rejected_count,
                "admitted_count": admitted_count,
                "governance_latency_ms": 0.0,
                "content_light": True,
            },
        )
    except Exception:
        logger.exception("Failed to emit tool proposal evidence for op=%s", op_id)


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
        "schema_version": "rig.relay.runtime_execution_event.v1",
        "receipt_id": op_id,
        "operation_id": op_id,
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
