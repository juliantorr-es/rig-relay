"""Integration tests for the TUI queue runner bridge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from rig_relay.coordination.fleet_queue import FleetQueue
from rig_relay.coordination.fleet_queue_runner import FleetQueueRunnerResult
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionResult,
    RuntimeToolExecutionRunner,
    RuntimeToolExecutionStatus,
)
from vibe.cli.textual_ui.rig_console.queue_runner import QueueRunnerBridge


class TestQueueRunnerBridgeMissingRoots:
    def test_none_roots_blocked(self) -> None:
        bridge = QueueRunnerBridge(None, None)
        assert bridge.can_run() is False

    @pytest.mark.asyncio
    async def test_run_next_without_roots_returns_blocked(self) -> None:
        bridge = QueueRunnerBridge(None, None)
        result = await bridge.run_next()
        assert result.decision == "blocked"
        assert result.error_kind == "missing_runner_roots"

    def test_enqueue_validate_without_roots_returns_blocked(self) -> None:
        bridge = QueueRunnerBridge(None, None)
        result = bridge.enqueue_validate()
        assert result.decision == "blocked"


class TestQueueRunnerBridgeEnqueueValidate:
    def test_enqueue_creates_validate_item(self, tmp_path: Path) -> None:
        queue_root = tmp_path / "coordination"
        (queue_root / "queue").mkdir(parents=True)
        executor = MagicMock(spec=RuntimeToolExecutionRunner)
        bridge = QueueRunnerBridge(queue_root, executor)
        result = bridge.enqueue_validate()
        assert result.decision == "completed"
        queue = FleetQueue(queue_root / "queue" / "events.jsonl")
        snap = queue.list_items()
        assert snap.total_count == 1
        assert snap.items[0].kind == "validate"

    def test_enqueue_with_paths(self, tmp_path: Path) -> None:
        queue_root = tmp_path / "coordination"
        (queue_root / "queue").mkdir(parents=True)
        executor = MagicMock(spec=RuntimeToolExecutionRunner)
        bridge = QueueRunnerBridge(queue_root, executor)
        bridge.enqueue_validate(changed_paths=["src/main.py"])
        queue = FleetQueue(queue_root / "queue" / "events.jsonl")
        snap = queue.list_items()
        assert snap.total_count == 1

    def test_snapshot_counts_after_enqueue(self, tmp_path: Path) -> None:
        queue_root = tmp_path / "coordination"
        (queue_root / "queue").mkdir(parents=True)
        executor = MagicMock(spec=RuntimeToolExecutionRunner)
        bridge = QueueRunnerBridge(queue_root, executor)
        assert bridge.snapshot_counts() == {}
        bridge.enqueue_validate()
        counts = bridge.snapshot_counts()
        assert counts.get("queued", 0) >= 1


class TestQueueRunnerBridgeRunNext:
    @pytest.mark.asyncio
    async def test_run_next_processes_one_item(self, tmp_path: Path) -> None:
        coord_root = tmp_path / "coordination"
        (coord_root / "queue").mkdir(parents=True)
        executor = MagicMock(spec=RuntimeToolExecutionRunner)
        executor.execute_runtime_exec = AsyncMock(
            return_value=RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.COMPLETED,
                intent_id="test-intent",
                tool_name="validate",
            )
        )
        bridge = QueueRunnerBridge(coord_root, executor)
        bridge.enqueue_validate()
        result = await bridge.run_next()
        assert result.decision == "completed"
        queue = FleetQueue(coord_root / "queue" / "events.jsonl")
        snap = queue.list_items()
        assert snap.status_counts.get("queued", 0) == 0
        assert snap.status_counts.get("completed", 0) == 1
        executor.execute_runtime_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_next_idle_when_no_runnable(self, tmp_path: Path) -> None:
        queue_root = tmp_path / "coordination"
        (queue_root / "queue").mkdir(parents=True)
        executor = MagicMock(spec=RuntimeToolExecutionRunner)
        bridge = QueueRunnerBridge(queue_root, executor)
        result = await bridge.run_next()
        assert result.decision == "idle"

    @pytest.mark.asyncio
    async def test_run_next_only_one_item(self, tmp_path: Path) -> None:
        coord_root = tmp_path / "coordination"
        (coord_root / "queue").mkdir(parents=True)
        executor = MagicMock(spec=RuntimeToolExecutionRunner)
        executor.execute_runtime_exec = AsyncMock(
            return_value=RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.COMPLETED,
                intent_id="test-intent",
                tool_name="validate",
            )
        )
        bridge = QueueRunnerBridge(coord_root, executor)
        bridge.enqueue_validate()
        bridge.enqueue_validate()
        result1 = await bridge.run_next()
        assert result1.decision == "completed"
        queue = FleetQueue(coord_root / "queue" / "events.jsonl")
        snap = queue.list_items()
        assert snap.status_counts.get("completed", 0) == 1
        assert snap.status_counts.get("queued", 0) == 1

    @pytest.mark.asyncio
    async def test_run_next_failure_visible(self, tmp_path: Path) -> None:
        coord_root = tmp_path / "coordination"
        (coord_root / "queue").mkdir(parents=True)
        executor = MagicMock(spec=RuntimeToolExecutionRunner)
        executor.execute_runtime_exec = AsyncMock(
            side_effect=RuntimeError("execution error")
        )
        bridge = QueueRunnerBridge(coord_root, executor)
        bridge.enqueue_validate()
        result = await bridge.run_next()
        assert result.decision == "failed"
        assert result.error_kind == "execution_error"

    @pytest.mark.asyncio
    async def test_run_next_validate_routes_through_runtime_exec(
        self, tmp_path: Path
    ) -> None:
        coord_root = tmp_path / "coordination"
        (coord_root / "queue").mkdir(parents=True)
        executor = MagicMock(spec=RuntimeToolExecutionRunner)
        executor.execute_runtime_exec = AsyncMock(
            return_value=RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.COMPLETED,
                intent_id="test-intent",
                tool_name="validate",
            )
        )
        bridge = QueueRunnerBridge(coord_root, executor)
        bridge.enqueue_validate()
        result = await bridge.run_next()
        assert result.decision == "completed"
        executor.execute_runtime_exec.assert_called_once()


class TestQueueRunnerBridgeContentLight:
    _FORBIDDEN = (
        "stdout",
        "stderr",
        "content",
        "file_contents",
        "diff",
        "patch",
        "prompt",
        "secret",
        "argv",
        "snippet",
    )

    def test_result_no_forbidden_fields(self) -> None:
        result = FleetQueueRunnerResult(decision="completed", reason="done")
        data = result.model_dump()
        text = str(data).lower()
        assert not any(f in text for f in self._FORBIDDEN)


class TestNoDirectToolCalls:
    @pytest.mark.asyncio
    async def test_only_fleet_queue_runner_path_used(self, tmp_path: Path) -> None:
        coord_root = tmp_path / "coordination"
        (coord_root / "queue").mkdir(parents=True)
        executor = MagicMock(spec=RuntimeToolExecutionRunner)
        executor.execute_runtime_exec = AsyncMock(
            return_value=RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.COMPLETED,
                intent_id="test-intent",
                tool_name="validate",
            )
        )
        bridge = QueueRunnerBridge(coord_root, executor)
        bridge.enqueue_validate()
        result = await bridge.run_next()
        assert result.decision == "completed"
        executor.execute_runtime_exec.assert_called_once()
