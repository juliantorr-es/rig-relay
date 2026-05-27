"""RiggedInferenceScheduler — governed request scheduler for local inference.

FCFS admission policy with typed operation state transitions:
  queued → running → completed / refused / cancelled / failed

Exposes truthful capability status. Currently FCFS serialized execution.
Batching status: batching_pending_dependency_or_api_support.
The scheduler owns request admission, cancellation, evidence, and lifecycle.

OMLX-informed: scheduler.py architecture (vLLM-style waiting→running→finished,
FCFS admission, abort_request, step() lifecycle). Apache 2.0.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import secrets

from rig_relay.core.logger import logger
from rig_relay.local_inference.runtime._models import LocalInferenceResponse, TaskKind


class RequestState:
    QUEUED = "queued"
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
    state: str = RequestState.QUEUED
    response: LocalInferenceResponse | None = None
    error: str = ""
    evidence_digest: str = ""
    queued_at: str = ""
    started_at: str = ""
    completed_at: str = ""


class RiggedInferenceScheduler:
    """FCFS request scheduler with stateful operation lifecycle.

    Future: continuous batching when supported by installed MLX APIs.
    Current: serialized FCFS with truthful status reporting.
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
            req.state = RequestState.RUNNING
            req.started_at = _now_iso()
            self._running[req.operation_id] = req
            return req

    async def complete(self, op_id: str, response: LocalInferenceResponse) -> None:
        async with self._lock:
            req = self._running.pop(op_id, None)
            if req is None:
                return
            req.state = RequestState.COMPLETED
            req.response = response
            req.completed_at = _now_iso()
            self._completed.append(req)
            self._total_processed += 1

    async def fail(self, op_id: str, error: str) -> None:
        async with self._lock:
            req = self._running.pop(op_id, None)
            if req is None:
                return
            req.state = RequestState.FAILED
            req.error = error
            req.completed_at = _now_iso()
            self._completed.append(req)

    async def cancel(self, op_id: str) -> bool:
        async with self._lock:
            req = self._running.pop(op_id, None)
            if req is None:
                for i, r in enumerate(self._queue):
                    if r.operation_id == op_id:
                        r.state = RequestState.CANCELLED
                        r.completed_at = _now_iso()
                        self._queue.pop(i)
                        self._completed.append(r)
                        return True
                return False
            req.state = RequestState.CANCELLED
            req.completed_at = _now_iso()
            self._completed.append(req)
            self._total_processed += 1
            return True

    async def refuse(self, op_id: str, reason: str) -> None:
        async with self._lock:
            for i, r in enumerate(self._queue):
                if r.operation_id == op_id:
                    r.state = RequestState.REFUSED
                    r.error = reason
                    r.completed_at = _now_iso()
                    self._queue.pop(i)
                    self._completed.append(r)
                    self._total_refused += 1
                    return

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


def _make_op_id() -> str:
    return f"op_{_now_compact()}_{secrets.token_hex(6)}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _now_compact() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")
