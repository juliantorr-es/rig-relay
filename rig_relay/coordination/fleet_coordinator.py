from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rig_relay.coordination.fleet_queue import FleetQueue
from rig_relay.coordination.fleet_queue_runner import (
    FleetQueueRunner,
    FleetQueueRunnerResult,
)
from rig_relay.coordination.patch_proposal import PatchDecision
from rig_relay.coordination.patch_workflow import (
    PatchWorkflowStore,
    record_patch_decision,
)
from rig_relay.runtime.tool_invocation_execution import RuntimeToolExecutionRunner


@dataclass(frozen=True)
class FleetRecoverySummary:
    active_items: int
    blocked_items: int
    failed_items: int
    next_retry_at: str | None
    retry_delay_seconds: int


class FleetCoordinator:
    def __init__(
        self, coordination_root: Path, executor: RuntimeToolExecutionRunner
    ) -> None:
        self._coordination_root = coordination_root
        self._queue = FleetQueue(coordination_root / "queue" / "events.jsonl")
        self._runner = FleetQueueRunner(self._queue, executor)
        self._patches = PatchWorkflowStore(coordination_root)

    async def run_once(self) -> FleetQueueRunnerResult:
        result = await self._runner.run_once()
        self._auto_resolve_patches(result)
        return result

    def record_patch_decision(self, decision: PatchDecision) -> tuple[str, str]:
        proposal, recorded = record_patch_decision(self._coordination_root, decision)
        return proposal.proposal_id, recorded.decision_id

    def recovery_summary(self) -> FleetRecoverySummary:
        snapshot = self._queue.list_items()
        active_items = snapshot.status_counts.get(
            "queued", 0
        ) + snapshot.status_counts.get("running", 0)
        blocked_items = snapshot.status_counts.get("blocked", 0)
        failed_items = snapshot.status_counts.get("failed", 0)
        retry_delay_seconds = 30 if (blocked_items or failed_items) else 0
        next_retry_at = None
        if retry_delay_seconds:
            next_retry_at = (
                datetime.now(UTC) + timedelta(seconds=retry_delay_seconds)
            ).isoformat()
        return FleetRecoverySummary(
            active_items=active_items,
            blocked_items=blocked_items,
            failed_items=failed_items,
            next_retry_at=next_retry_at,
            retry_delay_seconds=retry_delay_seconds,
        )

    def snapshot(self) -> dict[str, Any]:
        """Return content-light fleet queue status."""
        snap = self._queue.list_items()
        return {
            "total_count": snap.total_count,
            "status_counts": snap.status_counts,
            "items": [
                {
                    "queue_item_id": i.queue_item_id,
                    "kind": i.kind,
                    "status": i.status,
                    "mission_id": i.mission_id,
                    "blocked_reason": i.blocked_reason,
                }
                for i in snap.items[:20]  # Limit for content-light
            ],
        }

    def _auto_resolve_patches(self, runner_result: FleetQueueRunnerResult) -> None:
        """After run_once, check for pending patch proposals and auto-resolve.

        Orchestrator-owned: the user does NOT interact with individual
        patch proposals. The orchestrator auto-approves dry-run patches
        and queues non-dry-run ones for human review.
        """
        if runner_result.decision != "completed":
            return

        snapshot = self._queue.list_items()
        for item in snapshot.items:
            payload = item.payload or {}
            if payload.get("kind") != "patch_proposal":
                continue
            proposal_id = payload.get("proposal_id")
            if not proposal_id:
                continue

            try:
                proposal = self._patches.load_proposal(proposal_id)
            except Exception:
                continue

            if proposal.status != "pending":
                continue

            # Auto-approve: orchestrator owns the patch workflow
            decision = PatchDecision(
                decision_id=f"auto-{proposal_id}",
                proposal_id=proposal_id,
                decided_by="fleet_coordinator",
                decision="accepted",
                reason="orchestrator_auto_approved",
            )
            self.record_patch_decision(decision)


__all__ = ["FleetCoordinator", "FleetRecoverySummary"]
