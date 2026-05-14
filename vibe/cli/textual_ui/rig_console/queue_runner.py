"""TUI Queue Runner Bridge — thin integration between Textual UI and FleetQueueRunner.

This module is the ONLY surface through which the TUI triggers queue item
execution. It enforces the design rule that the TUI must not call raw tools
directly — all executable queued actions route through FleetQueueRunner /
runtime_exec.

Phase 0:
- One item per call (no looping).
- Supported kinds: validate, runtime_exec, message, handoff_note.
- No dedicated write_file/search_replace/bash buttons.
- Missing roots produce safe refusal, never crash.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rig_relay.coordination.fleet_queue import FleetQueue
from rig_relay.coordination.fleet_queue_runner import (
    FleetQueueRunner,
    FleetQueueRunnerConfig,
    FleetQueueRunnerResult,
)
from rig_relay.coordination.fleet_queue import FleetQueueItemKind
from rig_relay.runtime.tool_invocation_execution import RuntimeToolExecutionRunner

_RUNNER_TIMEOUT_MS = 300_000  # 5 minutes


class QueueRunnerBridge:
    """TUI-side bridge that locates queue/executor and runs one item.

    Never blocks the Textual event loop — callers use Textual workers.
    Never writes to ~/.rig/relay.
    Never exposes raw content in results.
    """

    def __init__(self, coordination_root: Path | None, executor: RuntimeToolExecutionRunner | None) -> None:
        self._coordination_root = coordination_root
        self._executor = executor

    def can_run(self) -> bool:
        """Return True if queue and executor are available."""
        return self._coordination_root is not None and self._executor is not None

    def _queue(self) -> FleetQueue | None:
        if self._coordination_root is None:
            return None
        events_path = self._coordination_root / "queue" / "events.jsonl"
        return FleetQueue(events_path)

    async def run_next(self) -> FleetQueueRunnerResult:
        """Run the next eligible queue item.

        Returns idle if no runner, no queue, no runnable item, or executor
        is missing. Never crashes — returns a structured result with
        decision="idle" or decision="blocked".
        """
        if not self.can_run():
            return FleetQueueRunnerResult(
                decision="blocked",
                error_kind="missing_runner_roots",
                reason="Queue runner roots are required",
            )
        assert self._executor is not None
        queue = self._queue()
        if queue is None:
            return FleetQueueRunnerResult(
                decision="blocked",
                error_kind="missing_queue",
                reason="Fleet queue not available",
            )
        runner = FleetQueueRunner(
            queue=queue,
            executor=self._executor,
            config=FleetQueueRunnerConfig(runtime_timeout_ms=_RUNNER_TIMEOUT_MS),
        )
        return await runner.run_once()

    def enqueue_validate(self, changed_paths: list[str] | None = None) -> FleetQueueRunnerResult:
        """Enqueue a validate item. Returns the result synchronously.

        Does not execute the item — only enqueues it.
        """
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
        now = _now_iso()
        queue.enqueue_item(
            kind=FleetQueueItemKind.VALIDATE,
            payload={
                "title": "Validate workspace",
                "summary": "Validate current workspace state",
                "created_at": now,
                "changed_paths": changed_paths or [],
            },
        )
        return FleetQueueRunnerResult(decision="completed", reason="Validate enqueued")

    def snapshot_counts(self) -> dict[str, int]:
        """Return current queue status counts, or empty dict on failure."""
        queue = self._queue()
        if queue is None:
            return {}
        try:
            snapshot = queue.list_items()
            return dict(snapshot.status_counts)
        except Exception:
            return {}


def _now_iso() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


__all__ = ["QueueRunnerBridge"]
