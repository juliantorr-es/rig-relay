"""TUI Queue Runner Bridge — thin integration between Textual UI and queue execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.coordination.fleet_queue import FleetQueue, FleetQueueItemKind
from rig_relay.coordination.fleet_queue_runner import FleetQueueRunnerResult
from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolIntent, RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionResult,
    RuntimeToolExecutionRunner,
    RuntimeToolExecutionStatus,
)
from vibe.cli.textual_ui.rig_console.actions import build_validate_runtime_exec_intent


class QueueRunnerBridge:
    """TUI-side bridge that locates queue/executor and runs one item."""

    def __init__(
        self,
        coordination_root: Path | None,
        executor: RuntimeToolExecutionRunner | None,
    ) -> None:
        self._coordination_root = coordination_root
        self._executor = executor

    def can_run(self) -> bool:
        return self._coordination_root is not None and self._executor is not None

    def _queue(self) -> FleetQueue | None:
        if self._coordination_root is None:
            return None
        return FleetQueue(self._coordination_root / "queue" / "events.jsonl")

    async def run_next(self) -> FleetQueueRunnerResult:
        if not self.can_run():
            result = FleetQueueRunnerResult(
                decision="blocked",
                error_kind="missing_runner_roots",
                reason="Queue runner roots are required",
            )
        else:
            queue = self._queue()
            if queue is None:
                result = FleetQueueRunnerResult(
                    decision="blocked",
                    error_kind="missing_queue",
                    reason="Fleet queue not available",
                )
            else:
                item = queue.next_runnable_item()
                if item is None:
                    result = FleetQueueRunnerResult(decision="idle")
                else:
                    queue.mark_running(item.queue_item_id)
                    if item.kind == FleetQueueItemKind.VALIDATE:
                        result = await self._run_validate_item(queue, item)
                    elif item.kind == FleetQueueItemKind.RUNTIME_EXEC:
                        result = await self._run_runtime_exec_item(queue, item)
                    elif item.kind in {
                        FleetQueueItemKind.MESSAGE,
                        FleetQueueItemKind.HANDOFF_NOTE,
                    }:
                        queue.mark_completed(item.queue_item_id)
                        result = FleetQueueRunnerResult(
                            queue_item_id=item.queue_item_id,
                            decision="completed",
                            reason="done",
                        )
                    elif item.kind in {
                        FleetQueueItemKind.PAUSE,
                        FleetQueueItemKind.RESUME,
                    }:
                        queue.mark_completed(item.queue_item_id)
                        result = FleetQueueRunnerResult(
                            queue_item_id=item.queue_item_id,
                            decision="completed",
                            reason="noop",
                        )
                    else:
                        queue.mark_blocked(
                            item.queue_item_id, reason="Unsupported queue item kind"
                        )
                        result = FleetQueueRunnerResult(
                            queue_item_id=item.queue_item_id,
                            decision="blocked",
                            error_kind="unsupported_kind",
                            reason="Unsupported queue item kind",
                        )
        return result

    def enqueue_validate(
        self, changed_paths: list[str] | None = None
    ) -> FleetQueueRunnerResult:
        if not self.can_run():
            queue = self._queue()
            if queue is None:
                return FleetQueueRunnerResult(
                    decision="blocked",
                    error_kind="missing_queue",
                    reason="Cannot enqueue validate: fleet queue not available",
                )
        queue = self._queue()
        if queue is None:
            return FleetQueueRunnerResult(
                decision="blocked",
                error_kind="missing_queue",
                reason="Cannot enqueue validate: fleet queue not available",
            )
        queue.enqueue_item(
            kind=FleetQueueItemKind.VALIDATE,
            payload={
                "title": "Validate workspace",
                "summary": "Validate current workspace state",
                "created_at": _now_iso(),
                "changed_paths": changed_paths or [],
            },
        )
        return FleetQueueRunnerResult(decision="completed", reason="Validate enqueued")

    def snapshot_counts(self) -> dict[str, int]:
        queue = self._queue()
        if queue is None:
            return {}
        try:
            snapshot = queue.list_items()
            return dict(snapshot.status_counts)
        except Exception:
            return {}

    async def _run_validate_item(
        self, queue: FleetQueue, item: Any
    ) -> FleetQueueRunnerResult:
        assert self._executor is not None
        payload = dict(item.payload or {})
        changed_paths = [path for path in payload.get("changed_paths", []) if path]
        intent = build_validate_runtime_exec_intent(
            intent_id=item.queue_item_id, changed_paths=changed_paths or None
        )
        try:
            result = await self._executor.execute_runtime_exec(
                intent, self._resolution(item.queue_item_id, item.mission_id)
            )
        except Exception as exc:
            queue.mark_failed(item.queue_item_id, reason=type(exc).__name__)
            return FleetQueueRunnerResult(
                queue_item_id=item.queue_item_id,
                decision="failed",
                error_kind="execution_error",
                reason=type(exc).__name__,
            )
        return self._finalize_runtime_result(queue, item.queue_item_id, result)

    async def _run_runtime_exec_item(
        self, queue: FleetQueue, item: Any
    ) -> FleetQueueRunnerResult:
        assert self._executor is not None
        payload = dict(item.payload or {})
        tool_name = payload.get("tool_name", "")
        try:
            RuntimeToolName(tool_name)
        except ValueError:
            queue.mark_blocked(item.queue_item_id, reason="Unknown runtime_exec tool")
            return FleetQueueRunnerResult(
                queue_item_id=item.queue_item_id,
                decision="blocked",
                error_kind="unsupported_tool",
                reason="Unknown runtime_exec tool",
            )
        intent = RuntimeToolIntent(
            intent_id=item.queue_item_id,
            tool_name=RuntimeToolName.RUNTIME_EXEC,
            payload=payload,
            requested_paths=item.depends_on or [],
            mission_id=item.mission_id,
            agent_id=item.agent_id,
        )
        try:
            result = await self._executor.execute_runtime_exec(
                intent, self._resolution(item.queue_item_id, item.mission_id)
            )
        except Exception as exc:
            queue.mark_failed(item.queue_item_id, reason=type(exc).__name__)
            return FleetQueueRunnerResult(
                queue_item_id=item.queue_item_id,
                decision="failed",
                error_kind="execution_error",
                reason=type(exc).__name__,
            )
        return self._finalize_runtime_result(queue, item.queue_item_id, result)

    def _finalize_runtime_result(
        self, queue: FleetQueue, queue_item_id: str, result: RuntimeToolExecutionResult
    ) -> FleetQueueRunnerResult:
        if result.status == RuntimeToolExecutionStatus.COMPLETED:
            queue.mark_completed(queue_item_id)
            decision = "completed"
            reason = result.refusal_reason or result.error_kind or "completed"
        elif result.status == RuntimeToolExecutionStatus.BLOCKED:
            queue.mark_blocked(
                queue_item_id, reason=result.refusal_reason or "Tool blocked"
            )
            decision = "blocked"
            reason = result.refusal_reason or result.error_kind or "blocked"
        elif result.status == RuntimeToolExecutionStatus.REFUSED:
            queue.mark_blocked(
                queue_item_id, reason=result.refusal_reason or "Tool refused"
            )
            decision = "blocked"
            reason = result.refusal_reason or result.error_kind or "refused"
        else:
            queue.mark_failed(
                queue_item_id, reason=result.refusal_reason or "Execution failed"
            )
            decision = "failed"
            reason = result.refusal_reason or result.error_kind or "failed"
        return FleetQueueRunnerResult(
            queue_item_id=queue_item_id,
            decision=decision,
            runtime_result_sha256=_compute_result_sha256(result),
            receipt_sha256=result.receipt_sha256,
            tool_name=result.tool_name,
            error_kind=result.error_kind,
            reason=reason,
            changed_paths=result.changed_paths or None,
        )

    def _resolution(
        self, queue_item_id: str, mission_id: str | None
    ) -> RuntimeContextResolution:
        ctx = RuntimeContext(
            session_id=mission_id or "queue-runner",
            task_id=queue_item_id,
            coordination_enabled=False,
        )
        return RuntimeContextResolution(status="resolved", context=ctx)


def _compute_result_sha256(result: RuntimeToolExecutionResult) -> str:
    raw = result.model_dump(
        mode="json",
        include={
            "status",
            "tool_name",
            "error_kind",
            "duration_ms",
            "envelope_schema_valid",
            "changed_paths",
        },
    )
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


__all__ = ["QueueRunnerBridge"]
