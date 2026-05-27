"""RiggedInferenceScheduler — governed request scheduler for local inference.

Two operating modes:
  1. BatchGenerator mode (when mlx-lm BatchGenerator is available):
     Continuous batching via BatchGenerator.insert() / next_generated().
     Multiple requests can be in-flight simultaneously.
  2. FCFS fallback (when BatchGenerator unavailable):
     Serialized first-come-first-served scheduling.

Exposes truthful capability status. Batching metrics in build_projection().

OMLX-informed: BatchGenerator wrapping pattern, UUID-based request tracking
(vLLM-style waiting->running->finished lifecycle). Apache 2.0.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import queue as _sync_queue
import secrets
import threading
import time
from typing import Any

from rig_relay.core.logger import logger
from rig_relay.local_inference.runtime._evidence import emit_scheduler_event
from rig_relay.local_inference.runtime._models import (
    BatchingStatus,
    LocalInferenceResponse,
    TaskKind,
)

_HAS_BATCH_GENERATOR = False
try:
    from mlx_lm.generate import BatchGenerator as _BatchGenerator

    _HAS_BATCH_GENERATOR = True
except ImportError:
    _BatchGenerator = None  # type: ignore[assignment]


class RequestState:
    QUEUED = "queued"
    PREFILLING = "prefilling"
    GENERATING = "generating"
    RUNNING = "running"
    COMPLETED = "completed"
    REFUSED = "refused"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class ScheduledRequest:
    operation_id: str
    task_kind: TaskKind
    messages: list[dict] = field(default_factory=list)
    model_id_hash: str = ""
    max_tokens: int = 4096
    tokenized_prompt: list[list[int]] = field(default_factory=list)
    cache: list | None = None
    state: str = RequestState.QUEUED
    response: LocalInferenceResponse | None = None
    error: str = ""
    evidence_digest: str = ""
    queued_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    consumer_queue: _sync_queue.Queue | None = field(default=None, repr=False)


class RiggedInferenceScheduler:
    """FCFS request scheduler with stateful operation lifecycle.

    Used as fallback when BatchGenerator is unavailable.
    """

    def __init__(self, max_concurrent: int = 1) -> None:
        self._queue: list[ScheduledRequest] = []
        self._running: dict[str, ScheduledRequest] = {}
        self._completed: list[ScheduledRequest] = []
        self._max_concurrent = max_concurrent
        self._lock = asyncio.Lock()
        self._total_processed: int = 0
        self._total_refused: int = 0

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    @property
    def running_count(self) -> int:
        return len(self._running)

    @property
    def total_processed(self) -> int:
        return self._total_processed

    @property
    def batching_status(self) -> str:
        return "serialized_fallback"

    async def enqueue(
        self,
        task_kind: TaskKind,
        messages: list[dict],
        model_id_hash: str = "",
        max_tokens: int = 4096,
    ) -> ScheduledRequest:
        op_id = _make_op_id()
        req = ScheduledRequest(
            operation_id=op_id,
            task_kind=task_kind,
            messages=messages,
            model_id_hash=model_id_hash,
            max_tokens=max_tokens,
            queued_at=_now_iso(),
        )
        async with self._lock:
            self._queue.append(req)
            logger.debug("scheduler: enqueued op=%s depth=%d", op_id, len(self._queue))
        return req

    async def admit_next(self) -> ScheduledRequest | None:
        async with self._lock:
            if not self._queue:
                return None
            if len(self._running) >= self._max_concurrent:
                return None
            req = self._queue.pop(0)
            from_state = req.state
            req.state = RequestState.RUNNING
            req.started_at = _now_iso()
            self._running[req.operation_id] = req
            self._emit_transition(req, "admitted", from_state, RequestState.RUNNING)
            return req

    async def complete(self, op_id: str, response: LocalInferenceResponse) -> None:
        async with self._lock:
            req = self._running.pop(op_id, None)
            if req is None:
                return
            from_state = req.state
            req.state = RequestState.COMPLETED
            req.response = response
            req.completed_at = _now_iso()
            self._completed.append(req)
            self._total_processed += 1
            self._emit_transition(req, "completed", from_state, RequestState.COMPLETED)

    async def fail(self, op_id: str, error: str) -> None:
        async with self._lock:
            req = self._running.pop(op_id, None)
            if req is None:
                return
            from_state = req.state
            req.state = RequestState.FAILED
            req.error = error
            req.completed_at = _now_iso()
            self._completed.append(req)
            self._emit_transition(req, "failed", from_state, RequestState.FAILED)

    async def cancel(self, op_id: str) -> bool:
        async with self._lock:
            req = self._running.pop(op_id, None)
            if req is None:
                for i, r in enumerate(self._queue):
                    if r.operation_id == op_id:
                        from_state = r.state
                        r.state = RequestState.CANCELLED
                        r.completed_at = _now_iso()
                        self._queue.pop(i)
                        self._completed.append(r)
                        self._emit_transition(
                            r, "cancelled", from_state, RequestState.CANCELLED
                        )
                        return True
                return False
            from_state = req.state
            req.state = RequestState.CANCELLED
            req.completed_at = _now_iso()
            self._completed.append(req)
            self._total_processed += 1
            self._emit_transition(req, "cancelled", from_state, RequestState.CANCELLED)
            return True

    async def refuse(self, op_id: str, reason: str) -> None:
        async with self._lock:
            for i, r in enumerate(self._queue):
                if r.operation_id == op_id:
                    from_state = r.state
                    r.state = RequestState.REFUSED
                    r.error = reason
                    r.completed_at = _now_iso()
                    self._queue.pop(i)
                    self._completed.append(r)
                    self._total_refused += 1
                    self._emit_transition(
                        r, "refused", from_state, RequestState.REFUSED
                    )
                    return

    def _emit_transition(
        self, req: ScheduledRequest, event_type: str, from_state: str, to_state: str
    ) -> None:
        try:
            emit_scheduler_event(
                req.operation_id,
                event_type,
                {
                    "schema_version": "rig.relay.runtime_scheduler_event.v1",
                    "operation_id": req.operation_id,
                    "transition": event_type,
                    "from_state": from_state,
                    "to_state": to_state,
                    "content_light": True,
                },
            )
        except Exception:
            logger.exception(
                "scheduler: evidence emission failed for op=%s", req.operation_id
            )

    def build_projection(self) -> dict:
        return {
            "scheduler_state": {
                "mode": "serialized_fallback",
                "max_concurrent": self._max_concurrent,
                "queue_depth": len(self._queue),
                "running_count": len(self._running),
                "total_processed": self._total_processed,
                "total_refused": self._total_refused,
            },
            "batching_status": self.batching_status,
            "batching_details": (
                "Continuous batching pending. mlx-lm BatchGenerator API "
                "present in installed version but requires scheduler engine "
                "integration with external prefill + multi-request decode. "
                "See OMLX scheduler.py for reference architecture."
            ),
        }


class RiggedBatchScheduler:
    """Continuous batching scheduler wrapping mlx-lm BatchGenerator.

    When BatchGenerator is available, multiple requests can be in-flight
    simultaneously via prefill/decoding batching. Falls back to serialized
    FCFS when BatchGenerator is unavailable or model is not provided.

    Architecture inspired by OMLX scheduler.py (vLLM-style waiting→running→
    finished lifecycle with continuous batching). Apache 2.0.
    """

    def __init__(
        self,
        model: Any = None,
        tokenizer: Any = None,
        max_concurrent: int = 32,
        completion_batch_size: int = 32,
        prefill_batch_size: int = 8,
    ) -> None:
        self._fallback = RiggedInferenceScheduler(max_concurrent=1)
        self._batch_gen: object | None = None
        self._model = model
        self._tokenizer = tokenizer
        self._max_batch_size = max_concurrent
        self._completion_batch_size = completion_batch_size
        self._prefill_batch_size = prefill_batch_size
        self._uid_to_op: dict[str, str] = {}
        self._op_to_uid: dict[str, str] = {}
        self._consumer_queues: dict[str, _sync_queue.Queue] = {}
        self._accumulated: dict[str, list[str]] = {}
        self._pending: list[ScheduledRequest] = []
        self._active: bool = False
        self._loop_thread: threading.Thread | None = None
        self._loop_running: threading.Event = threading.Event()
        self._lock = threading.Lock()
        self._total_processed: int = 0
        self._total_refused: int = 0
        self._completed_sequences: int = 0
        self._batch_status: BatchingStatus = (
            BatchingStatus.ACTIVE
            if _HAS_BATCH_GENERATOR and model is not None
            else BatchingStatus.FALLBACK_SERIALIZED
        )
        self._tokens_generated: int = 0
        self._generation_start_time: float = 0.0

    @property
    def batching_status(self) -> str:
        return self._batch_status.value

    @property
    def queue_depth(self) -> int:
        return len(self._pending)

    @property
    def running_count(self) -> int:
        return len(self._uid_to_op)

    @property
    def total_processed(self) -> int:
        return self._total_processed

    def set_model(self, model: Any, tokenizer: Any) -> None:
        self._model = model
        self._tokenizer = tokenizer
        if _HAS_BATCH_GENERATOR and model is not None:
            self._batch_status = BatchingStatus.ACTIVE
            self._init_batch_generator()
        else:
            self._batch_status = BatchingStatus.FALLBACK_SERIALIZED

    def _init_batch_generator(self) -> None:
        if self._model is None or self._tokenizer is None:
            return
        if not _HAS_BATCH_GENERATOR:
            return
        try:
            from mlx_lm.generate import BatchGenerator as BG

            self._batch_gen = BG(
                self._model,
                completion_batch_size=self._completion_batch_size,
                prefill_batch_size=self._prefill_batch_size,
            )
            self._batch_status = BatchingStatus.ACTIVE
            logger.info(
                "RiggedBatchScheduler: BatchGenerator initialized "
                "(completion_batch=%d, prefill_batch=%d)",
                self._completion_batch_size,
                self._prefill_batch_size,
            )
        except Exception as e:
            logger.warning(
                "RiggedBatchScheduler: BatchGenerator init failed: %s — "
                "falling back to serialized FCFS",
                e,
            )
            self._batch_status = BatchingStatus.FALLBACK_SERIALIZED

    async def enqueue(
        self,
        task_kind: TaskKind,
        messages: list[dict],
        model_id_hash: str = "",
        max_tokens: int = 4096,
        tokenized_prompt: list[list[int]] | None = None,
        cache: list | None = None,
    ) -> ScheduledRequest:
        if self._batch_status != BatchingStatus.ACTIVE:
            return await self._fallback.enqueue(
                task_kind, messages, model_id_hash, max_tokens
            )

        op_id = _make_op_id()
        cq: _sync_queue.Queue = _sync_queue.Queue()
        req = ScheduledRequest(
            operation_id=op_id,
            task_kind=task_kind,
            messages=messages,
            model_id_hash=model_id_hash,
            max_tokens=max_tokens,
            tokenized_prompt=tokenized_prompt or [],
            cache=cache,
            queued_at=_now_iso(),
            state=RequestState.QUEUED,
            consumer_queue=cq,
        )
        with self._lock:
            self._pending.append(req)
            self._consumer_queues[op_id] = cq
            self._accumulated[op_id] = []
            logger.debug(
                "batch_scheduler: enqueued op=%s pending=%d", op_id, len(self._pending)
            )
        return req

    async def admit_next(self) -> ScheduledRequest | None:
        if self._batch_status != BatchingStatus.ACTIVE:
            return await self._fallback.admit_next()
        with self._lock:
            if self._pending:
                req = self._pending[0]
                req.state = RequestState.GENERATING
                return req
        return None

    async def complete(self, op_id: str, response: LocalInferenceResponse) -> None:
        if self._batch_status != BatchingStatus.ACTIVE:
            await self._fallback.complete(op_id, response)
            return
        with self._lock:
            self._uid_to_op.pop(op_id, None)
            self._op_to_uid.pop(op_id, None)
            self._consumer_queues.pop(op_id, None)
            self._accumulated.pop(op_id, None)
            self._total_processed += 1
            self._completed_sequences += 1
        try:
            emit_scheduler_event(
                op_id,
                "completed",
                {
                    "schema_version": "rig.relay.runtime_scheduler_event.v1",
                    "operation_id": op_id,
                    "transition": "completed",
                    "from_state": RequestState.GENERATING,
                    "to_state": RequestState.COMPLETED,
                    "content_light": True,
                },
            )
        except Exception:
            logger.exception("Failed to emit scheduler event for op=%s", op_id)

    async def fail(self, op_id: str, error: str) -> None:
        if self._batch_status != BatchingStatus.ACTIVE:
            await self._fallback.fail(op_id, error)
            return
        with self._lock:
            self._consumer_queues.pop(op_id, None)
            self._accumulated.pop(op_id, None)
            self._uid_to_op.pop(op_id, None)
            self._op_to_uid.pop(op_id, None)
        try:
            emit_scheduler_event(
                op_id,
                "failed",
                {
                    "schema_version": "rig.relay.runtime_scheduler_event.v1",
                    "operation_id": op_id,
                    "transition": "failed",
                    "from_state": RequestState.FAILED,
                    "to_state": RequestState.FAILED,
                    "content_light": True,
                },
            )
        except Exception:
            logger.exception("Failed to emit scheduler event for op=%s", op_id)

    async def cancel(self, op_id: str) -> bool:
        if self._batch_status != BatchingStatus.ACTIVE:
            return await self._fallback.cancel(op_id)
        with self._lock:
            cq = self._consumer_queues.pop(op_id, None)
            self._accumulated.pop(op_id, None)
            self._uid_to_op.pop(op_id, None)
            self._op_to_uid.pop(op_id, None)
            self._pending = [r for r in self._pending if r.operation_id != op_id]
            if cq is not None:
                cq.put(("cancelled", None))
        try:
            emit_scheduler_event(
                op_id,
                "cancelled",
                {
                    "schema_version": "rig.relay.runtime_scheduler_event.v1",
                    "operation_id": op_id,
                    "transition": "cancelled",
                    "from_state": RequestState.CANCELLED,
                    "to_state": RequestState.CANCELLED,
                    "content_light": True,
                },
            )
        except Exception:
            logger.exception("Failed to emit scheduler event for op=%s", op_id)
        return cq is not None

    async def refuse(self, op_id: str, reason: str) -> None:
        if self._batch_status != BatchingStatus.ACTIVE:
            await self._fallback.refuse(op_id, reason)
            return
        with self._lock:
            self._pending = [r for r in self._pending if r.operation_id != op_id]
            self._total_refused += 1
        try:
            emit_scheduler_event(
                op_id,
                "refused",
                {
                    "schema_version": "rig.relay.runtime_scheduler_event.v1",
                    "operation_id": op_id,
                    "transition": "refused",
                    "from_state": RequestState.REFUSED,
                    "to_state": RequestState.REFUSED,
                    "content_light": True,
                },
            )
        except Exception:
            logger.exception("Failed to emit scheduler event for op=%s", op_id)

    def get_consumer_queue(self, op_id: str) -> _sync_queue.Queue | None:
        with self._lock:
            return self._consumer_queues.get(op_id)

    def _insert_pending_requests(self) -> None:
        """Insert pending requests up to batch size into the BatchGenerator."""
        with self._lock:
            remaining_slots = self._max_batch_size - len(self._uid_to_op)
            if remaining_slots <= 0 or not self._pending:
                return

            to_insert = self._pending[:remaining_slots]
            self._pending = self._pending[remaining_slots:]

        for req in to_insert:
            try:
                tokens = req.tokenized_prompt
                if not tokens and req.messages and self._tokenizer is not None:
                    from rig_relay.local_inference.runtime._engine import (
                        _build_prompt_using_chat_template,
                    )

                    prompt_text = _build_prompt_using_chat_template(
                        req.messages, self._tokenizer
                    )
                    tokens = [self._tokenizer.encode(prompt_text)]
                if not tokens:
                    tokens = [[0]] if req.messages else [[]]

                caches: list | None = [req.cache] if req.cache else None
                uids = self._batch_gen.insert(  # type: ignore[union-attr]
                    tokens, max_tokens=[req.max_tokens], caches=caches
                )
                with self._lock:
                    for uid in uids:
                        uid_str = str(uid)
                        self._uid_to_op[uid_str] = req.operation_id
                        self._op_to_uid[req.operation_id] = uid_str
                    req.state = RequestState.GENERATING
                    cq = self._consumer_queues.get(req.operation_id)
                    if cq is None:
                        for uid in uids:
                            self._uid_to_op.pop(str(uid), None)
                        self._op_to_uid.pop(req.operation_id, None)
                        continue
                logger.debug(
                    "batch_scheduler: inserted op=%s uids=%s",
                    req.operation_id,
                    [str(u) for u in uids],
                )
            except Exception as e:
                logger.error(
                    "batch_scheduler: insert error for %s: %s", req.operation_id, e
                )
                with self._lock:
                    cq = self._consumer_queues.get(req.operation_id)
                if cq:
                    cq.put(("error", str(e)))

    def _process_generated_tokens(self) -> None:
        """Poll BatchGenerator.next_generated() and route tokens to consumers."""
        try:
            for uid, token_text, finish_reason, token_count in (
                self._batch_gen.next_generated()  # type: ignore[union-attr]
            ):
                uid_str = str(uid)
                full_text: str = ""
                with self._lock:
                    op_id = self._uid_to_op.get(uid_str)
                    if op_id is None:
                        continue
                    cq = self._consumer_queues.get(op_id)
                    if cq is None:
                        continue

                    self._accumulated.setdefault(op_id, []).append(str(token_text))
                    self._tokens_generated += 1

                    if finish_reason is not None:
                        full_text = "".join(self._accumulated.pop(op_id, []))
                    else:
                        cq = self._consumer_queues.get(op_id)
                if cq is not None:
                    if finish_reason is not None:
                        cq.put((
                            "done",
                            {
                                "content": full_text,
                                "finish_reason": finish_reason,
                                "token_count": token_count,
                            },
                        ))
                    else:
                        cq.put(("token", str(token_text)))
        except Exception as e:
            if self._loop_running.is_set():
                logger.error("batch_scheduler: next_generated error: %s", e)

    def _batch_loop(self) -> None:
        """Synchronous batch processing loop running in a dedicated thread."""
        if self._batch_gen is None:
            return

        self._generation_start_time = time.monotonic()
        sleep_interval = 0.005

        while self._loop_running.is_set() or self._pending or self._uid_to_op:
            self._insert_pending_requests()
            self._process_generated_tokens()
            time.sleep(sleep_interval)

    def start_batch_loop(self) -> None:
        if self._batch_gen is None:
            return
        self._loop_running.set()
        self._loop_thread = threading.Thread(
            target=self._batch_loop, daemon=True, name="tachikoma_batch_loop"
        )
        self._loop_thread.start()
        logger.info("RiggedBatchScheduler: batch loop started")

    def stop_batch_loop(self) -> None:
        self._loop_running.clear()
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=5.0)
        if self._batch_gen is not None:
            try:
                self._batch_gen.close()  # type: ignore[union-attr]
            except Exception:
                pass
        self._batch_gen = None
        logger.info("RiggedBatchScheduler: batch loop stopped")

    def build_projection(self) -> dict:
        elapsed = max(time.monotonic() - self._generation_start_time, 0.001)
        tps = self._tokens_generated / elapsed if elapsed > 0 else 0.0

        base: dict = {
            "scheduler_state": {
                "mode": self._batch_status.value,
                "max_concurrent": self._max_batch_size,
                "queue_depth": len(self._pending),
                "running_count": len(self._uid_to_op),
                "total_processed": self._total_processed,
                "total_refused": self._total_refused,
            },
            "batching_status": self._batch_status.value,
            "batching_enabled": _HAS_BATCH_GENERATOR,
        }

        if self._batch_status == BatchingStatus.ACTIVE:
            base["batching_details"] = (
                f"Continuous batching active via mlx-lm BatchGenerator. "
                f"Completion batch_size={self._completion_batch_size}, "
                f"Prefill batch_size={self._prefill_batch_size}. "
                f"Active sequences={len(self._uid_to_op)}, "
                f"Completed sequences={self._completed_sequences}. "
                f"Throughput: {tps:.1f} tokens/sec."
            )
            base["batching_metrics"] = {
                "completion_batch_size": self._completion_batch_size,
                "prefill_batch_size": self._prefill_batch_size,
                "active_sequences": len(self._uid_to_op),
                "completed_sequences": self._completed_sequences,
                "tokens_generated": self._tokens_generated,
                "throughput_tokens_per_sec": round(tps, 1),
            }
        else:
            base["batching_details"] = "Continuous batching not active. " + (
                "BatchGenerator not available in installed mlx-lm version."
                if not _HAS_BATCH_GENERATOR
                else "Model or tokenizer not provided — using serialized FCFS."
            )

        return base


def _make_op_id() -> str:
    return f"op_{_now_compact()}_{secrets.token_hex(6)}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _now_compact() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")
