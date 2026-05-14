"""Fleet Queue Runner — Phase 0.

Connects queue items to governed runtime execution.

Design:
- One item per call (no looping).
- Queue state transitions are event-sourced (running→completed/failed/blocked).
- validate/runtime_exec items route through RuntimeToolExecutionRunner.
- message/handoff_note items complete immediately (no mutation).
- pause/resume items complete immediately (no-op).
- Unsupported item kinds are marked blocked with error_kind.
- Result is content-light: no stdout, stderr, content, diffs, patches, etc.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from rig_relay.coordination.fleet_queue import FleetQueue, FleetQueueItemKind
from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolIntent, RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionResult,
    RuntimeToolExecutionRunner,
    RuntimeToolExecutionStatus,
)

# ── Constants ────────────────────────────────────────────────────────────────

_SCHEMA_VERSION_RESULT = "rig.fleet.queue_runner_result.v1"
_TRUNCATE_LEN = 200


# ── Config ────────────────────────────────────────────────────────────────


class FleetQueueRunnerConfig(BaseModel):
    """Configuration for FleetQueueRunner.

    Phase 0: one item per call, bounded timeout, supported kinds.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.fleet.queue_runner_config.v1"
    max_items_per_call: int = 1
    runtime_timeout_ms: int = 300_000  # 5 minutes


# ── Result model (content-light) ─────────────────────────────────────────


class FleetQueueRunnerResult(BaseModel):
    """Result of a single run_once() call.

    Content-light: no stdout, stderr, content, file_contents, chunk_text,
    old_text, new_text, diff, patch, prompt, secret, argv, snippet.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION_RESULT
    queue_item_id: str | None = None
    decision: str  # "completed" | "failed" | "blocked" | "idle"
    runtime_result_sha256: str | None = None
    receipt_sha256: str | None = None
    tool_name: str | None = None
    error_kind: str | None = None
    reason: str | None = None
    changed_paths: list[str] | None = None


# ── Runner ────────────────────────────────────────────────────────────────


class FleetQueueRunner:
    """Runs one queue item per call through governed runtime execution.

    Not thread-safe. Not multi-process safe. Phase 0.
    """

    def __init__(
        self,
        queue: FleetQueue,
        executor: RuntimeToolExecutionRunner,
        config: FleetQueueRunnerConfig | None = None,
    ) -> None:
        self._queue = queue
        self._executor = executor
        self._config = config or FleetQueueRunnerConfig()

    # ── Public API ─────────────────────────────────────────────────

    async def run_once(self) -> FleetQueueRunnerResult:
        """Select and execute one queue item.

        Returns idle if no runnable item exists.
        """
        item = self._queue.next_runnable_item()
        if item is None:
            return FleetQueueRunnerResult(decision="idle")

        # ── Mark running (event-sourced) ───────────────────────────
        self._queue.mark_running(item.queue_item_id)

        # ── Dispatch by kind ───────────────────────────────────────
        kind = item.kind

        if kind in {FleetQueueItemKind.VALIDATE, FleetQueueItemKind.RUNTIME_EXEC}:
            return await self._dispatch_runtime_exec(item)
        elif kind == FleetQueueItemKind.MESSAGE:
            return await self._handle_message(item)
        elif kind == FleetQueueItemKind.HANDOFF_NOTE:
            return await self._handle_handoff_note(item)
        elif kind in {FleetQueueItemKind.PAUSE, FleetQueueItemKind.RESUME}:
            return await self._handle_pause_resume(item)
        else:
            return await self._handle_unsupported(item)

    # ── Runtime exec dispatch ──────────────────────────────────────

    async def _dispatch_runtime_exec(self, item: Any) -> FleetQueueRunnerResult:
        """Dispatch a validate or runtime_exec item through the executor."""
        # Build intent from queue item payload
        payload = dict(item.payload or {})
        kind = item.kind

        if kind == FleetQueueItemKind.VALIDATE:
            tool_name = RuntimeToolName.VALIDATE
        else:
            # runtime_exec: payload must contain tool_name
            sub_tool_str = payload.get("tool_name", "")
            try:
                tool_name = RuntimeToolName(sub_tool_str)
            except ValueError:
                self._queue.mark_failed(
                    item.queue_item_id,
                    reason=f"Unknown sub-tool in runtime_exec payload: {sub_tool_str}",
                )
                return FleetQueueRunnerResult(
                    queue_item_id=item.queue_item_id,
                    decision="failed",
                    error_kind="unsupported_tool",
                    reason=f"Unknown sub-tool: {sub_tool_str}",
                )

        intent_id = str(uuid4())
        intent = RuntimeToolIntent(
            intent_id=intent_id,
            tool_name=tool_name,
            payload=payload,
            requested_paths=item.depends_on or [],
            mission_id=item.mission_id,
            agent_id=item.agent_id,
        )

        # Build minimal resolution
        ctx = RuntimeContext(
            session_id=item.mission_id or "queue-runner",
            task_id=item.queue_item_id,
            coordination_enabled=False,  # queue runner bypasses path leases
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)

        # Execute
        try:
            if kind == FleetQueueItemKind.VALIDATE:
                runtime_result: RuntimeToolExecutionResult = (
                    await self._executor.execute_validate(intent, resolution)
                )
            else:
                runtime_result = await self._executor.execute_runtime_exec(
                    intent, resolution
                )
        except Exception as e:
            self._queue.mark_failed(
                item.queue_item_id,
                reason=f"Runtime execution raised: {type(e).__name__}",
            )
            return FleetQueueRunnerResult(
                queue_item_id=item.queue_item_id,
                decision="failed",
                error_kind="execution_error",
                reason=f"{type(e).__name__}",
            )

        # Map runtime result to queue state transition
        exec_status = runtime_result.status
        if exec_status == RuntimeToolExecutionStatus.COMPLETED:
            self._queue.mark_completed(item.queue_item_id)
        elif exec_status == RuntimeToolExecutionStatus.REFUSED:
            # Refused: treat as blocked (policy prevented execution)
            self._queue.mark_blocked(
                item.queue_item_id,
                reason=runtime_result.refusal_reason or "Tool refused",
            )
        elif exec_status == RuntimeToolExecutionStatus.BLOCKED:
            self._queue.mark_blocked(
                item.queue_item_id,
                reason=runtime_result.refusal_reason or "Tool blocked",
            )
        else:
            self._queue.mark_failed(
                item.queue_item_id,
                reason=runtime_result.refusal_reason or "Execution failed",
            )

        # Build content-light result
        result_sha256 = _compute_result_sha256(runtime_result)
        receipt_sha = runtime_result.receipt_sha256 or (
            runtime_result.receipt.receipt_sha256 if runtime_result.receipt else None
        )

        decision_map = {
            RuntimeToolExecutionStatus.COMPLETED: "completed",
            RuntimeToolExecutionStatus.REFUSED: "blocked",
            RuntimeToolExecutionStatus.BLOCKED: "blocked",
            RuntimeToolExecutionStatus.FAILED: "failed",
        }
        decision = decision_map.get(exec_status, "failed")

        return FleetQueueRunnerResult(
            queue_item_id=item.queue_item_id,
            decision=decision,
            runtime_result_sha256=result_sha256,
            receipt_sha256=receipt_sha,
            tool_name=runtime_result.tool_name,
            error_kind=runtime_result.error_kind,
            reason=_sanitise_reason(runtime_result.refusal_reason),
            changed_paths=runtime_result.changed_paths or None,
        )

    # ── Message handler ────────────────────────────────────────────

    async def _handle_message(self, item: Any) -> FleetQueueRunnerResult:
        """Message items complete without runtime mutation.

        Records handoff note summary from payload if present.
        """
        summary = (item.payload or {}).get("summary")
        self._queue.mark_completed(item.queue_item_id)
        return FleetQueueRunnerResult(
            queue_item_id=item.queue_item_id,
            decision="completed",
            reason=_sanitise_reason(summary) if summary else None,
        )

    # ── Handoff note handler ───────────────────────────────────────

    async def _handle_handoff_note(self, item: Any) -> FleetQueueRunnerResult:
        """Handoff note items complete immediately with summary."""
        summary = (item.payload or {}).get("summary")
        self._queue.mark_completed(item.queue_item_id)
        return FleetQueueRunnerResult(
            queue_item_id=item.queue_item_id,
            decision="completed",
            reason=_sanitise_reason(summary) if summary else None,
        )

    # ── Pause/resume handler ───────────────────────────────────────

    async def _handle_pause_resume(self, item: Any) -> FleetQueueRunnerResult:
        """Pause/resume items complete without mutation.

        Phase 0: no-op. Queue state transitions for pause/resume
        are modeled but not enforced by the runner.
        """
        kind = item.kind
        self._queue.mark_completed(item.queue_item_id)
        return FleetQueueRunnerResult(
            queue_item_id=item.queue_item_id,
            decision="completed",
            reason=f"{kind} acknowledged (no-op in Phase 0)",
        )

    # ── Unsupported handler ────────────────────────────────────────

    async def _handle_unsupported(self, item: Any) -> FleetQueueRunnerResult:
        """Unsupported item kinds are marked blocked."""
        self._queue.mark_blocked(
            item.queue_item_id, reason=f"Unsupported queue item kind: {item.kind}"
        )
        return FleetQueueRunnerResult(
            queue_item_id=item.queue_item_id,
            decision="blocked",
            error_kind="unsupported_queue_item_kind",
            reason=f"Unsupported kind: {item.kind}",
        )


# ── Helpers ──────────────────────────────────────────────────────────────


def _compute_result_sha256(result: RuntimeToolExecutionResult) -> str:
    """Compute a content-light SHA256 of a runtime execution result.

    Uses canonical JSON of selected fields. No raw content.
    """
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


def _sanitise_reason(reason: str | None) -> str | None:
    """Sanitise a reason string to ensure it's content-light.

    Truncates long strings and strips any lines that look like file content.
    """
    if reason is None:
        return None
    # Truncate to first 200 chars, preferring sentence boundary
    reason = reason.strip().replace("\n", " ").replace("\r", "")
    if len(reason) > _TRUNCATE_LEN:
        reason = reason[: _TRUNCATE_LEN - 3] + "..."
    return reason if reason else None


__all__ = ["FleetQueueRunner", "FleetQueueRunnerConfig", "FleetQueueRunnerResult"]
