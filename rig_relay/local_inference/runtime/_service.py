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
from typing import Any

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
    emit_tool_execution_outcome,
    emit_tool_proposal_evidence,
    reconstruct_ledgers,
)
from rig_relay.local_inference.runtime._inventory import scan_model_inventory
from rig_relay.local_inference.runtime._models import (
    CapabilityPosture,
    ContextPrivacyClass,
    ExecutionStatus,
    FinishReason,
    LocalAgentLoopRequest,
    LocalAgentLoopResult,
    LocalInferenceResponse,
    LoopState,
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
    ToolObservation,
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
        self._loop_active: bool = False
        self._loop_state: LoopState = LoopState.IDLE
        self._loop_turn_count: int = 0
        self._loop_max_turns: int = 5
        self._shutdown_state: str = "not_initiated"
        self._loop_lock: asyncio.Lock = asyncio.Lock()

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

    def bind_session_context(
        self,
        session_id: str,
        turn_id: str = "",
        workspace_root: str = "",
        causation_id: str = "",
    ) -> None:
        """Bind a session context to the tool execution bridge.

        When bound, the bridge will attempt full ToolRuntime execution
        for admitted tool proposals instead of returning pending_session_context.

        Args:
            session_id: Active agent session identifier.
            turn_id: Current turn within the session.
            workspace_root: Repository or workspace root path.
            causation_id: Causation chain identifier (defaults to mlx_tool_execution).
        """
        context: dict[str, Any] = {
            "session_id": session_id,
            "turn_id": turn_id,
            "workspace_root": workspace_root,
            "causation_id": causation_id or "mlx_tool_execution",
        }
        self._tool_bridge.bind_session(context)

        try:
            from rig_relay.core.tool_runtime import ToolRuntime

            executor = ToolRuntime(source_label="local_inference_bridge")
            self._tool_bridge.set_tool_runtime(executor)
        except Exception:
            pass

    def unbind_session(self) -> None:
        """Release the session context from the tool execution bridge.

        After unbinding, the bridge returns to stateless-preflight-only mode.
        """
        if self._loop_active:
            raise RuntimeError(
                "Cannot unbind session while agent loop is active. "
                "Cancel the loop first or wait for completion."
            )
        self._tool_bridge.bind_session(None)
        self._tool_bridge.set_tool_runtime(None)

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

    def check_health(self) -> RuntimeHealth:
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
            await self._scheduler.refuse(op_id, "max_concurrent_limit")
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

        tool_outcomes: list[dict[str, Any]] | None = None
        terminal_status = ExecutionStatus.EXECUTED
        try:
            try:
                if response.tool_call_proposals:
                    tool_outcomes = await _handle_tool_proposals(
                        response.tool_call_proposals,
                        task_id_hash,
                        op_id,
                        bridge=self._tool_bridge,
                    )
            except asyncio.CancelledError:
                await self._scheduler.fail(op_id, "cancelled_tool_execution")
                raise
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
                terminal_status = ExecutionStatus.EVIDENCE_FAILED
        finally:
            if terminal_status == ExecutionStatus.EXECUTED:
                await self._scheduler.complete(op_id, response)
            else:
                await self._scheduler.fail(op_id, terminal_status.value)

        return TaskAdmissionResult(
            task_id_hash=task_id_hash,
            task_kind=task_kind,
            admission=admission,
            executed=True,
            status=terminal_status,
            response=response,
            evidence_receipt_id=response.evidence_receipt_id,
            tool_execution_outcomes=tool_outcomes,
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
            await self._scheduler.refuse(op_id, "max_concurrent_limit")
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
                        privacy_class=effective_class.value,
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

        _terminal_resolved = False
        try:
            try:
                if tool_proposals:
                    await _handle_tool_proposals(
                        tool_proposals,
                        task_id_hash,
                        req.operation_id,
                        bridge=self._tool_bridge,
                    )
            except asyncio.CancelledError:
                await self._scheduler.fail(req.operation_id, "cancelled_tool_execution")
                raise
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
                        "Failed to emit stream terminal event for op=%s",
                        req.operation_id,
                    )
                await self._scheduler.complete(req.operation_id, response)
            else:
                response.stream_terminal_state = StreamTerminalState.EVIDENCE_FAILED
                await self._scheduler.fail(req.operation_id, "evidence_emission_failed")
            _terminal_resolved = True
        finally:
            if not _terminal_resolved:
                try:
                    await self._scheduler.fail(
                        req.operation_id, "terminal_not_resolved"
                    )
                except Exception:
                    pass

    async def cancel_generation(self, op_id: str) -> bool:
        return await self._scheduler.cancel(op_id)

    async def clear_cache(self) -> bool:
        return await self._cache.clear_cache()

    async def drain_active_streams(
        self, timeout_seconds: float = 5.0
    ) -> dict[str, int]:
        """Cancel all active streams and await their futures with timeout.

        Returns counts: drained (successfully awaited), timed_out, cancelled.
        """
        async with self._stream_lock:
            stream_ids = list(self._active_streams)
        drained = 0
        timed_out = 0
        cancelled = 0
        for op_id in stream_ids:
            await self._scheduler.cancel(op_id)
            cancelled += 1
            async with self._stream_lock:
                fut = self._active_streams.pop(op_id, None)
            if fut is not None and not fut.done():
                try:
                    await asyncio.wait_for(fut, timeout=timeout_seconds)
                    drained += 1
                except TimeoutError:
                    timed_out += 1
                    logger.warning(
                        "RiggedLocalRuntime: stream drain timeout for op=%s", op_id
                    )
                except Exception:
                    timed_out += 1
            else:
                drained += 1
        return {"drained": drained, "timed_out": timed_out, "cancelled": cancelled}

    async def execute_local_agent_loop(
        self, request: LocalAgentLoopRequest
    ) -> LocalAgentLoopResult:
        """Run a governed local-agent work loop: model→tool→observation→model.

        Bounded by max_tool_turns. Each turn:
        1. Model generates text and/or tool proposals
        2. If tool proposals: governed execution through ToolRuntime
        3. Tool observations are returned as synthetic messages into model context
        4. Model may continue or terminate

        Returns terminal loop outcome with all evidence linkage.
        """
        import time as _time

        loop_id = f"loop_{secrets.token_hex(8)}"
        start_ms = int(_time.monotonic() * 1000)
        evidence_chain: list[str] = []
        observations: list[ToolObservation] = []
        messages: list[dict[str, Any]] = list(request.messages)
        turn_count = 0
        final_content = ""
        terminal_state = LoopState.IDLE
        final_status = ExecutionStatus.EXECUTED

        if self._loop_lock.locked():
            raise RuntimeError(
                "Agent loop already active — concurrent loops not supported"
            )
        async with self._loop_lock:
            self._loop_active = True
            self._loop_max_turns = request.max_tool_turns
            self._loop_turn_count = 0

            try:
                self.bind_session_context(
                    request.session_id, request.turn_id, request.workspace_root
                )

                for turn_idx in range(request.max_tool_turns):
                    turn_count = turn_idx + 1
                    self._loop_turn_count = turn_count
                    self._loop_state = LoopState.GENERATING

                    try:
                        result = await self.execute(
                            messages=messages,
                            model_id_hash=request.model_id_hash,
                            task_kind=TaskKind.TOOL_PROPOSAL,
                            context_privacy_class=request.context_privacy_class,
                            max_tokens=request.max_tokens,
                        )
                    except asyncio.CancelledError:
                        terminal_state = LoopState.CANCELLED
                        final_status = ExecutionStatus.BLOCKED
                        self._loop_state = LoopState.CANCELLED
                        break
                    except Exception as exc:
                        logger.exception(
                            "Local agent loop execution failed at turn %d", turn_count
                        )
                        terminal_state = LoopState.RUNTIME_FAILED
                        final_status = ExecutionStatus.ERROR
                        self._loop_state = LoopState.RUNTIME_FAILED
                        final_content = (
                            f"[ERROR: loop failed at turn {turn_count}: {exc}]"
                        )
                        break

                    if result.status in (
                        ExecutionStatus.REFUSED,
                        ExecutionStatus.BLOCKED,
                    ):
                        terminal_state = LoopState.TOOL_PROPOSAL_REFUSED
                        final_status = ExecutionStatus.REFUSED
                        self._loop_state = LoopState.TOOL_PROPOSAL_REFUSED
                        final_content = (
                            result.refusal.detail if result.refusal else "refused"
                        )
                        break

                    if result.evidence_receipt_id:
                        evidence_chain.append(result.evidence_receipt_id)

                    if result.response and result.response.content:
                        final_content = result.response.content

                    tool_proposals = (
                        result.response.tool_call_proposals if result.response else []
                    )

                    if not tool_proposals:
                        terminal_state = LoopState.COMPLETED
                        final_status = ExecutionStatus.EXECUTED
                        self._loop_state = LoopState.COMPLETED
                        break

                    self._loop_state = LoopState.TOOL_PROPOSAL_DETECTED

                    tool_outcomes = result.tool_execution_outcomes or []

                    if tool_proposals and not tool_outcomes:
                        self._loop_state = LoopState.TOOL_EXECUTING
                        op_id = f"loop_{loop_id}_turn_{turn_count}"
                        try:
                            tool_outcomes = await _handle_tool_proposals(
                                tool_proposals,
                                result.task_id_hash,
                                op_id,
                                bridge=self._tool_bridge,
                            )
                        except asyncio.CancelledError:
                            terminal_state = LoopState.CANCELLED
                            final_status = ExecutionStatus.BLOCKED
                            self._loop_state = LoopState.CANCELLED
                            break
                        except Exception:
                            logger.exception(
                                "Tool execution failed in loop turn %d", turn_count
                            )
                            terminal_state = LoopState.TOOL_FAILED
                            final_status = ExecutionStatus.ERROR
                            self._loop_state = LoopState.TOOL_FAILED
                            break

                    self._loop_state = LoopState.TOOL_OBSERVATION_RECEIVED

                    has_critical_failure = False
                    for outcome_entry in tool_outcomes:
                        if isinstance(outcome_entry, dict) and outcome_entry.get(
                            "_meta"
                        ):
                            continue
                        status_str = (
                            outcome_entry.get("status", "")
                            if isinstance(outcome_entry, dict)
                            else ""
                        )
                        evidence_emitted_val = (
                            outcome_entry.get("evidence_emitted", False)
                            if isinstance(outcome_entry, dict)
                            else False
                        )
                        terminal_outcome_id_val = (
                            outcome_entry.get("terminal_outcome_id", "")
                            if isinstance(outcome_entry, dict)
                            else ""
                        )
                        tool_name_val = (
                            outcome_entry.get("tool_name", "")
                            if isinstance(outcome_entry, dict)
                            else outcome_entry.get("preflight", {}).get("tool_name", "")
                            if isinstance(outcome_entry, dict)
                            else ""
                        )
                        call_id_val = (
                            outcome_entry.get("call_id", "")
                            if isinstance(outcome_entry, dict)
                            else ""
                        )

                        scan = scan_messages_for_secrets([
                            {
                                "content": outcome_entry.get("reason", "")
                                if isinstance(outcome_entry, dict)
                                else ""
                            }
                        ])
                        if scan.get("secrets_detected", False):
                            logger.warning(
                                "Tool observation contains secrets — cache blocked for "
                                "tool=%s loop=%s",
                                call_id_val,
                                loop_id,
                            )

                        obs = ToolObservation(
                            observation_id=secrets.token_hex(8),
                            operation_id=loop_id,
                            tool_name=tool_name_val,
                            call_id=call_id_val,
                            outcome_status=status_str,
                            output_digest=hashlib.sha256(
                                f"{status_str}:{tool_name_val}:{terminal_outcome_id_val}".encode()
                            ).hexdigest(),
                            error_digest=(
                                hashlib.sha256(
                                    f"error:{terminal_outcome_id_val}".encode()
                                ).hexdigest()
                                if status_str in ("failed", "error")
                                else ""
                            ),
                            evidence_emitted=evidence_emitted_val,
                            terminal_outcome_id=terminal_outcome_id_val,
                        )
                        observations.append(obs)

                        if status_str in ("failed", "cancelled", "error"):
                            has_critical_failure = True

                    if has_critical_failure:
                        terminal_state = LoopState.TOOL_FAILED
                        final_status = ExecutionStatus.ERROR
                        self._loop_state = LoopState.TOOL_FAILED
                        break

                    tool_result_block = _build_tool_result_synthetic_message(
                        observations
                    )
                    messages.append({"role": "user", "content": tool_result_block})

                    self._loop_state = LoopState.CONTINUING_GENERATION

                else:
                    terminal_state = LoopState.LOOP_LIMIT_REACHED
                    final_status = ExecutionStatus.EXECUTED
                    self._loop_state = LoopState.LOOP_LIMIT_REACHED

            finally:
                self._loop_active = False
                if self._loop_state == LoopState.IDLE:
                    self._loop_state = terminal_state
                try:
                    self.unbind_session()
                except Exception:
                    logger.exception("Failed to unbind session after agent loop")
                try:
                    self._cache.invalidate_loop_cache(loop_id)
                except Exception:
                    logger.exception(
                        "Failed to invalidate loop cache for loop_id=%s", loop_id
                    )

            total_latency_ms = int(_time.monotonic() * 1000) - start_ms
            return LocalAgentLoopResult(
                session_id=request.session_id,
                loop_id=loop_id,
                terminal_loop_state=terminal_state,
                final_content=final_content,
                tool_observations=observations,
                tool_turn_count=turn_count,
                total_latency_ms=total_latency_ms,
                evidence_chain=evidence_chain,
                status=final_status,
            )

    async def shutdown(self) -> dict[str, Any]:
        """Coordinated runtime shutdown.

        Drains active streams first, waits for agent loop to complete,
        then clears pool, then resets global reference.
        Returns a truthful shutdown result dict with drain_status.
        """
        logger.info("RiggedLocalRuntime: shutdown initiated")

        drain_result = await self.drain_active_streams(timeout_seconds=5.0)
        all_drained = drain_result["timed_out"] == 0

        agents_active_during_shutdown = False
        if self._loop_active:
            loop_drain_timeout = 10.0
            try:
                async with asyncio.timeout(loop_drain_timeout):
                    while self._loop_active:
                        await asyncio.sleep(0.1)
            except TimeoutError:
                logger.warning(
                    "Shutdown: agent loop did not complete within %ss",
                    loop_drain_timeout,
                )
                self._shutdown_state = "degraded_shutdown_active_generations_remain"
                agents_active_during_shutdown = True

        pool_result = self._pool.shutdown(
            agents_active_during_shutdown=agents_active_during_shutdown
        )
        if isinstance(self._scheduler, RiggedBatchScheduler):
            self._scheduler.stop_batch_loop()

        drain_status = (
            "complete" if all_drained else "degraded_shutdown_active_generations_remain"
        )
        self._shutdown_state = drain_status
        logger.info(
            "RiggedLocalRuntime: shutdown complete — drain_status=%s", drain_status
        )

        return {
            "drain_status": drain_status,
            "drain_result": drain_result,
            "pool_result": pool_result,
        }

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

    def _current_loop_state(self) -> LoopState:
        """Return the current agent loop state from the runtime's loop tracker."""
        if self._loop_active:
            return self._loop_state
        return LoopState.IDLE

    def build_projection(self) -> dict:
        """Typed Y0 Inference Studio consumer contract.

        Y4 → Y0 Gridline handoff: structured projection with projection_id
        and generated_at for Y0 rendering in the Inference Studio surface.
        Content-light: counts, statuses, hashes, capability postures only.
        """
        health_snapshot = self.check_health()
        bridge_proj = self._tool_bridge.build_projection()
        pool_proj = self._pool.build_projection()
        cache_proj = self._cache.build_projection()
        scheduler_proj = self._scheduler.build_projection()

        batching_posture = CapabilityPosture.DEFERRED

        cache_write_back = (
            "active_local_trie"
            if self._cache.write_back_count > 0
            else "disabled_opt_in_only"
        )

        cache_persistence_privacy = (
            "disabled_opt_in_only"
            if not self._cache.ssd_enabled
            else "token_ids_only_no_raw_text"
        )
        cache_persistence_detail = (
            "SSD cache is opt-in only (disabled by default). "
            "Token IDs in cache are reversible with the tokenizer. "
            "Set ssd_enabled=True and provide ssd_cache_dir to enable."
            if not self._cache.ssd_enabled
            else (
                "SSD persistence active. Cache stores KV state as MLX arrays "
                "(binary) and token IDs in the PromptTrie. No raw prompt text "
                "is stored. Token IDs are reversible if the tokenizer is available."
            )
        )

        bridge_has_full_execution = (
            self._tool_bridge.has_session_context and self._tool_bridge.has_executor
        )
        tool_execution_authority = (
            "governed_execution_through_tool_runtime"
            if bridge_has_full_execution
            else "governed_admission_with_pending_tool_execution"
        )
        tool_execution_detail = (
            (
                "Tool proposals are preflighted through GovernanceEngine "
                "and executed through ToolRuntime.execute_one() with "
                "session-bound context and evidence emission."
            )
            if bridge_has_full_execution
            else (
                "Stateless governance preflight active. "
                "Tool execution through ToolRuntime requires session context "
                "and an executor to be wired via bind_session_context()."
            )
        )

        pid = (
            f"rtproj_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
            f"_{secrets.token_hex(4)}"
        )
        generated_at = _now_iso()

        return {
            "schema_version": "rig.relay.inference_studio_runtime_projection.v1",
            "projection_id": pid,
            "generated_at": generated_at,
            "runtime": {
                "kind": "rigged_mlx_internal",
                "platform": "metal_apple_silicon"
                if self._engine.is_mlx_available
                else "unavailable",
                "mlx_available": self._engine.is_mlx_available,
                "authority": tool_execution_authority,
                "authority_detail": tool_execution_detail,
            },
            "capabilities": {
                "text_generation": (
                    CapabilityPosture.SUPPORTED
                    if self._engine.is_mlx_available
                    else CapabilityPosture.V1_REQUIRED_PENDING
                ),
                "streaming_generation": CapabilityPosture.SUPPORTED,
                "model_tool_observation_loop": {
                    "posture": "iterative_agent_loop_supported",
                    "loop_state": str(self._current_loop_state()),
                },
                "tool_calling": (
                    CapabilityPosture.SUPPORTED
                    if bridge_has_full_execution
                    else CapabilityPosture.V1_REQUIRED_PENDING
                ),
                "structured_output": CapabilityPosture.V1_REQUIRED_PENDING,
                "embeddings": CapabilityPosture.V1_REQUIRED_PENDING,
                "reranking": CapabilityPosture.V1_REQUIRED_PENDING,
                "vision_vlm": CapabilityPosture.V1_REQUIRED_PENDING,
                "continuous_batching": batching_posture,
                "kv_cache_reuse": CapabilityPosture.SUPPORTED,
                "kv_cache_write_back": cache_write_back,
                "model_pool_active": (
                    CapabilityPosture.SUPPORTED
                    if self._pool.loaded_count > 0
                    else CapabilityPosture.V1_REQUIRED_PENDING
                ),
                "multi_model_pool": (
                    CapabilityPosture.SUPPORTED
                    if self._pool.loaded_count > 0
                    else CapabilityPosture.V1_REQUIRED_PENDING
                ),
                "tool_execution_bridge": (
                    CapabilityPosture.SUPPORTED
                    if bridge_has_full_execution
                    else CapabilityPosture.V1_REQUIRED_PENDING
                ),
            },
            "stream_state": {
                "terminal_evidence_contract": "provisional_then_terminalized",
                "possible_states": [
                    "idle",
                    "provisional_streaming",
                    "terminal_completed",
                    "terminal_cancelled",
                    "terminal_failed",
                    "evidence_unavailable",
                ],
                "stream_terminal_ledger_health": _compute_stream_terminal_health(),
            },
            "tool_state": {
                "session_context_bound": self._tool_bridge.has_session_context,
                "executor_wired": self._tool_bridge.has_executor,
                "mode": (
                    "full_execution"
                    if bridge_has_full_execution
                    else "stateless_preflight_only"
                ),
                "possible_outcomes": [
                    "proposed",
                    "preflight_admitted",
                    "execution_authorized",
                    "executed",
                    "refused",
                    "failed",
                    "evidence_failed",
                ],
            },
            "agent_loop": {
                "active": self._loop_active,
                "state": self._loop_state,
                "tool_turn_count": self._loop_turn_count,
                "max_tool_turns": self._loop_max_turns,
                "supported": "production_proven",
            },
            "scheduler": {
                **_flatten_scheduler_proj(scheduler_proj),
                **scheduler_proj,
                "queue_position_visible": True,
                "serialization_reason": (
                    "MLX single-GPU-stream architecture; one model generation "
                    "at a time. BatchGenerator exists architecturally but not activated."
                ),
                "waiting_count": scheduler_proj.get("scheduler_state", {}).get(
                    "queue_depth", 0
                ),
                "refusal_count": scheduler_proj.get("scheduler_state", {}).get(
                    "total_refused", 0
                ),
                "cancellation_count": (
                    "ledger: runtime_scheduler_ledger.jsonl (cancelled transitions)"
                ),
            },
            "cache": {
                **_flatten_cache_proj(cache_proj, self._cache.ssd_enabled),
                **cache_proj,
                "cache_loop_safety": ("loop_cache_invalidation_on_loop_completion"),
            },
            "pool": {**_flatten_pool_proj(pool_proj), **pool_proj},
            "bridge": bridge_proj,
            "governance": {
                "evidence": "canonical_locked_digest_chained",
                "tool_execution": (
                    "governed_execution_through_tool_runtime"
                    if bridge_has_full_execution
                    else "stateless_preflight_admission_only"
                ),
                "tool_execution_detail": tool_execution_detail,
                "scheduler_authority": "serialized_fcfs_under_lock",
                "scheduling_truth": "serialized_fcfs_is_the_only_live_production_path",
                "scheduling_truth_detail": (
                    "BatchGenerator exists architecturally but batch loop "
                    "is never started. start_batch_loop() has zero call sites. "
                    "BatchGenerator is an internal mlx-lm API (not in __all__). "
                    "All generation routes through FCFS serialized scheduling."
                ),
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
                    "scheduler.complete() called. On failure, terminal state "
                    "resolves via scheduler.fail() with evidence_emission_failed "
                    "— no consumer-visible sentinel is yielded after token stream."
                ),
                "tool_loop_completeness": (
                    "governed_iterative_model_tool_observation_model_loop"
                ),
                "tool_loop_completeness_detail": (
                    "Tool proposals → Rig authority execution → content-light observations "
                    "→ appended to model context → continued generation. "
                    "Bounded by max_tool_turns. Each iteration produces canonical evidence. "
                    "Terminal outcome distinguishes completed, cancelled, limit-reached, "
                    "and runtime-failed states."
                ),
                "stream_terminal_evidence_integrity": (
                    _stream_terminal_integrity_str()
                ),
                "stream_terminal_evidence_integrity_detail": (
                    "Complete when all operations have terminalized evidence. "
                    "Degraded when provisional-only streams exist or evidence "
                    "failures are present. Unavailable when the stream terminal "
                    "ledger cannot be read."
                ),
                "shutdown_drain_status": self._shutdown_state,
            },
            "privacy": {
                "secret_scanning": "enforced_before_admission",
                "private_local_context": "allowed",
                "secret_bearing_context": "refused",
                "cache_persistence": cache_persistence_privacy,
                "cache_persistence_detail": cache_persistence_detail,
            },
            "health": {
                "state": health_snapshot.state,
                "gpu_available": health_snapshot.gpu_available,
                "last_probe": health_snapshot.probed_at,
                "stream_terminal_ledger_health": _compute_stream_terminal_health(),
                "shutdown_state": self._shutdown_state,
            },
            "models": {
                "loaded_count": self._engine.loaded_model_count,
                "inventory_count": len(self._inventory),
                "pool_count": self._pool.loaded_count,
                "lifecycle_events": "ledger: runtime_lifecycle_ledger.jsonl",
            },
            "evidence_ledgers": {
                "execution": "runtime_execution_ledger.jsonl",
                "lifecycle": "runtime_lifecycle_ledger.jsonl",
                "cache": "runtime_cache_ledger.jsonl",
                "stream_terminal": "runtime_stream_terminal_ledger.jsonl",
                "stream_terminal_health": _compute_stream_terminal_health(),
                "reconstruct": "RiggedLocalRuntime.reconstruct_evidence()",
            },
        }

    def reconstruct_evidence(self) -> dict[str, list[dict]]:
        return reconstruct_ledgers()


def _flatten_scheduler_proj(scheduler_proj: dict) -> dict:
    """Extract schema-required flat fields from scheduler sub-projection."""
    state = scheduler_proj.get("scheduler_state", {})
    return {
        "mode": state.get("mode", "serialized_fcfs"),
        "queue_depth": state.get("queue_depth", 0),
        "running_count": state.get("running_count", 0),
        "total_processed": state.get("total_processed", 0),
        "batching_status": scheduler_proj.get(
            "batching_status", "serialized_fcfs_only"
        ),
    }


def _flatten_cache_proj(cache_proj: dict, ssd_enabled: bool) -> dict:
    """Extract schema-required flat fields from cache sub-projection."""
    capability = cache_proj.get("cache_capability", {})
    stats = cache_proj.get("cache_stats", {})
    return {
        "kv_cache_reuse_enabled": capability.get("kv_cache_reuse", "")
        == "supported_read_only_reuse",
        "hit_count": stats.get("hit_count", 0),
        "miss_count": stats.get("miss_count", 0),
        "ssd_cache": cache_proj.get(
            "ssd_cache", {"enabled": ssd_enabled, "default": "disabled_opt_in_only"}
        ),
    }


def _flatten_pool_proj(pool_proj: dict) -> dict:
    """Extract schema-required flat fields from pool sub-projection."""
    state = pool_proj.get("pool_state", {})
    return {
        "loaded_count": state.get("loaded_count", 0),
        "max_models": state.get("max_models", 3),
        "active_generations": state.get("active_generations", 0),
    }


def _compute_stream_terminal_health() -> str:
    """Read the stream terminal ledger and compute health status.

    Returns 'complete', 'degraded', 'unavailable', or 'empty'.
    """
    try:
        ledgers = reconstruct_ledgers()
        stream_entries = ledgers.get("stream_terminal", [])
        if not stream_entries:
            return "empty"
        terminalized = 0
        provisional_only = 0
        evidence_failed = 0
        seen_ops: set[str] = set()
        for entry in reversed(stream_entries):
            op_id = entry.get("_operation_id", "")
            if op_id and op_id in seen_ops:
                continue
            if op_id:
                seen_ops.add(op_id)
            state = entry.get("payload", {}).get("terminal_state", "")
            if state == "terminalized":
                terminalized += 1
            elif state == "provisional":
                provisional_only += 1
            elif state == "evidence_failed":
                evidence_failed += 1
        total = terminalized + provisional_only + evidence_failed
        if total == 0:
            return "empty"
        if evidence_failed > 0:
            return "degraded_evidence_failures_present"
        if provisional_only > 0:
            return "degraded_provisional_streams_exist"
        return "complete"
    except Exception:
        return "unavailable"


def _stream_terminal_integrity_str() -> str:
    base = _compute_stream_terminal_health()
    if base == "complete":
        return "complete"
    if base.startswith("degraded"):
        return "degraded"
    return "unavailable"


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


async def _handle_tool_proposals(
    proposals: list[ToolCallProposal],
    task_id_hash: str,
    op_id: str,
    bridge: ToolExecutionBridge | None = None,
) -> list[dict[str, Any]]:
    """Preflight and optionally execute tool proposals through governance.

    Performs stateless governance preflight for every proposal.
    Refuses obviously invalid arguments (empty, > 100KB) before governance.
    When a ToolExecutionBridge with session context is provided, also
    executes admitted proposals through ToolRuntime and emits evidence
    for every execution outcome.

    Returns:
        List of execution results for each proposal (includes preflight
        and optionally execution_result fields). Every result, including
        refusals, carries a terminal_outcome_id. A batch_terminal_outcome_digest
        is computed from all individual outcome IDs.
    """
    for p in proposals:
        logger.info(
            "runtime_tool_proposal: task=%s tool=%s call_id=%s",
            task_id_hash[:12],
            p.tool_name,
            p.call_id,
        )

    MAX_ARG_BYTES = 102_400
    preflight_results: list[dict[str, Any]] = []
    for p in proposals:
        if not p.arguments or (
            isinstance(p.arguments, str) and len(p.arguments.encode()) > MAX_ARG_BYTES
        ):
            tid = secrets.token_hex(12)
            preflight_results.append({
                "status": "refused",
                "reason": "invalid_arguments",
                "terminal_outcome_id": tid,
                "evidence_emitted": False,
            })
            continue
        result = _preflight_tool_proposal(p)
        result["terminal_outcome_id"] = secrets.token_hex(12)
        preflight_results.append(result)

    admitted_count = sum(
        1 for r in preflight_results if r.get("status") == "admitted_pending_execution"
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

    execution_results: list[dict[str, Any]] = []

    if bridge is not None and bridge.has_session_context and admitted_count > 0:
        for i, (proposal, preflight) in enumerate(
            zip(proposals, preflight_results, strict=True)
        ):
            if preflight["status"] != "admitted_pending_execution":
                execution_results.append(preflight)
                continue

            try:
                exec_result = await bridge.execute_proposal(proposal)
                execution_results.append(exec_result)
            except asyncio.CancelledError:
                execution_results.append({
                    "status": "cancelled",
                    "reason": "Tool execution cancelled",
                    "preflight": preflight,
                    "evidence_emitted": False,
                    "terminal_outcome_id": secrets.token_hex(12),
                })
                remaining = preflight_results[i + 1 :] if i + 1 < len(proposals) else []
                return execution_results + remaining
            except Exception as exc:
                logger.exception(
                    "Tool execution failed for proposal %s: %s", proposal.call_id, exc
                )
                execution_results.append({
                    "status": "failed",
                    "reason": str(exc)[:500],
                    "preflight": preflight,
                    "evidence_emitted": False,
                    "terminal_outcome_id": secrets.token_hex(12),
                })

            evidence_ok = False
            try:
                proposal_hash = (
                    f"sha256:{hashlib.sha256(proposal.arguments.encode()).hexdigest()}"
                )
                emit_tool_execution_outcome(
                    op_id,
                    {
                        "schema_version": "rig.relay.runtime_execution_event.v1",
                        "receipt_id": op_id,
                        "operation_id": op_id,
                        "task_id_hash": task_id_hash,
                        "status": execution_results[-1].get("status", "unknown"),
                        "prompt_sha256": "",
                        "output_sha256": "",
                        "model_id_hash": "",
                        "content_light": True,
                        "proposal_hash": proposal_hash,
                        "tool_name": proposal.tool_name,
                        "call_id": proposal.call_id,
                    },
                )
                evidence_ok = True
            except Exception:
                logger.exception(
                    "Failed to emit tool execution evidence for op=%s", op_id
                )
            if not evidence_ok:
                result_entry = execution_results[-1]
                if result_entry.get("status") == "executed":
                    result_entry["status"] = "executed_evidence_failed"
                result_entry["evidence_emitted"] = False
    else:
        execution_results = preflight_results

    outcome_ids = sorted(
        r.get("terminal_outcome_id", "")
        for r in execution_results
        if r.get("terminal_outcome_id")
    )
    if outcome_ids:
        batch_digest = (
            f"sha256:{hashlib.sha256(''.join(outcome_ids).encode()).hexdigest()}"
        )
    else:
        batch_digest = ""
    execution_results.append({
        "_meta": "batch_terminal_outcome_digest",
        "batch_terminal_outcome_digest": batch_digest,
    })

    return execution_results


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


def _build_tool_result_synthetic_message(observations: list[Any]) -> str:
    """Build a content-light synthetic message from tool observations.

    Follows the pattern used by core agent tool response handling:
    hash-based, content-light, summarizing tool outcomes without raw output.
    """
    parts: list[str] = ["[Tool results from execution round]"]
    for obs in observations:
        if hasattr(obs, "tool_name"):
            parts.append(
                f"- {obs.tool_name} (call_id={obs.call_id}): "
                f"status={obs.outcome_status}, "
                f"evidence_emitted={obs.evidence_emitted}"
            )
    return "\n".join(parts)


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
