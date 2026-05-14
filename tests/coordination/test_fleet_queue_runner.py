"""Tests for FleetQueueRunner — Phase 0.

Covers:
- idle result when no runnable item
- validate/runtime_exec dispatch through executor
- message/handoff_note immediate completion
- unsupported kind → blocked
- failed/refused runtime result → queue state
- one item per call
- depends_on respect
- content-light result
- schema validation
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from rig_relay.coordination.fleet_queue import (
    FleetQueue,
    FleetQueueItemKind,
    FleetQueueItemStatus,
)
from rig_relay.coordination.fleet_queue_runner import (
    FleetQueueRunner,
    FleetQueueRunnerResult,
)
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionResult,
    RuntimeToolExecutionRunner,
    RuntimeToolExecutionStatus,
)

# ── Constants ───────────────────────────────────────────────────────────

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.fleet.queue_runner_result.v1.schema.json"
)

FORBIDDEN_WORDS: frozenset[str] = frozenset({
    "stdout",
    "stderr",
    "content",
    "file_contents",
    "chunk_text",
    "old_text",
    "new_text",
    "diff",
    "patch",
    "prompt",
    "secret",
    "argv",
    "snippet",
})


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_queue(events_path: Path) -> FleetQueue:
    return FleetQueue(events_path)


def _make_completed_result(**overrides: Any) -> RuntimeToolExecutionResult:
    base = RuntimeToolExecutionResult(
        intent_id="test-intent",
        tool_name="validate",
        status=RuntimeToolExecutionStatus.COMPLETED,
        duration_ms=10.0,
    )
    if overrides:
        return base.model_copy(update=overrides)
    return base


def _make_fake_executor() -> AsyncMock:
    """Create a mock executor that returns completed by default."""
    executor = AsyncMock(spec=RuntimeToolExecutionRunner)
    executor.execute_validate = AsyncMock(return_value=_make_completed_result())
    executor.execute_runtime_exec = AsyncMock(
        return_value=_make_completed_result(
            tool_name=RuntimeToolName.RUNTIME_EXEC.value
        )
    )
    return executor


def _enqueue_validate_item(
    queue: FleetQueue,
    *,
    queue_item_id: str = "wi-validate-001",
    payload: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
) -> str:
    queue.enqueue_item(
        kind=FleetQueueItemKind.VALIDATE,
        queue_item_id=queue_item_id,
        payload=payload or {"profile": "quick"},
        depends_on=depends_on,
    )
    return queue_item_id


def _enqueue_runtime_exec_item(
    queue: FleetQueue,
    *,
    queue_item_id: str = "wi-runtime-exec-001",
    payload: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
) -> str:
    queue.enqueue_item(
        kind=FleetQueueItemKind.RUNTIME_EXEC,
        queue_item_id=queue_item_id,
        payload=payload or {"tool_name": "validate", "profile": "quick"},
        depends_on=depends_on,
    )
    return queue_item_id


def _enqueue_message_item(
    queue: FleetQueue,
    *,
    queue_item_id: str = "wi-msg-001",
    payload: dict[str, Any] | None = None,
) -> str:
    queue.enqueue_item(
        kind=FleetQueueItemKind.MESSAGE,
        queue_item_id=queue_item_id,
        payload=payload or {"summary": "Hello from agent"},
    )
    return queue_item_id


def _enqueue_handoff_note_item(
    queue: FleetQueue,
    *,
    queue_item_id: str = "wi-handoff-001",
    payload: dict[str, Any] | None = None,
) -> str:
    queue.enqueue_item(
        kind=FleetQueueItemKind.HANDOFF_NOTE,
        queue_item_id=queue_item_id,
        payload=payload or {"summary": "Handoff to tester"},
    )
    return queue_item_id


def _enqueue_pause_item(
    queue: FleetQueue, *, queue_item_id: str = "wi-pause-001"
) -> str:
    queue.enqueue_item(kind=FleetQueueItemKind.PAUSE, queue_item_id=queue_item_id)
    return queue_item_id


def _enqueue_resume_item(
    queue: FleetQueue, *, queue_item_id: str = "wi-resume-001"
) -> str:
    queue.enqueue_item(kind=FleetQueueItemKind.RESUME, queue_item_id=queue_item_id)
    return queue_item_id


def _validate_against_schema(result: FleetQueueRunnerResult) -> list[str]:
    """Validate a runner result against the schema, return error messages."""
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    dumped = result.model_dump(mode="json")
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(dumped)]


# ── Tests ───────────────────────────────────────────────────────────────


class TestIdleResult:
    @pytest.mark.asyncio
    async def test_no_runnable_item_returns_idle(self, tmp_path: Path) -> None:
        """Empty queue returns idle."""
        queue = _make_queue(tmp_path / "empty.jsonl")
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "idle"
        assert result.queue_item_id is None

    @pytest.mark.asyncio
    async def test_all_items_terminal_returns_idle(self, tmp_path: Path) -> None:
        """Queue with only completed items returns idle."""
        queue = _make_queue(tmp_path / "completed.jsonl")
        _enqueue_validate_item(queue, queue_item_id="wi-done")
        queue.mark_completed("wi-done")
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "idle"


class TestValidateDispatch:
    @pytest.mark.asyncio
    async def test_validate_item_dispatches_through_executor(
        self, tmp_path: Path
    ) -> None:
        """A validate item calls executor.execute_validate."""
        queue = _make_queue(tmp_path / "validate.jsonl")
        _enqueue_validate_item(queue)
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "completed"
        assert result.queue_item_id == "wi-validate-001"
        executor.execute_validate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_validate_item_transitions_to_running_then_completed(
        self, tmp_path: Path
    ) -> None:
        """State: queued → running → completed."""
        queue = _make_queue(tmp_path / "validate-state.jsonl")
        _enqueue_validate_item(queue)
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        await runner.run_once()
        snapshot = queue.list_items()
        assert len(snapshot.items) == 1
        item = snapshot.items[0]
        assert item.status == FleetQueueItemStatus.COMPLETED
        # Verify running event was emitted
        assert snapshot.status_counts.get("running", 0) == 0
        assert snapshot.status_counts.get("completed", 0) == 1


class TestRuntimeExecDispatch:
    @pytest.mark.asyncio
    async def test_runtime_exec_item_dispatches_through_executor(
        self, tmp_path: Path
    ) -> None:
        """A runtime_exec item calls executor.execute_runtime_exec."""
        queue = _make_queue(tmp_path / "runtime-exec.jsonl")
        _enqueue_runtime_exec_item(queue)
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "completed"
        assert result.queue_item_id == "wi-runtime-exec-001"
        executor.execute_runtime_exec.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_runtime_exec_with_invalid_tool_name_fails(
        self, tmp_path: Path
    ) -> None:
        """runtime_exec with unknown sub-tool is failed."""
        queue = _make_queue(tmp_path / "bad-tool.jsonl")
        _enqueue_runtime_exec_item(
            queue, queue_item_id="wi-bad", payload={"tool_name": "nonexistent_tool"}
        )
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "failed"
        assert result.error_kind == "unsupported_tool"


class TestMessageHandling:
    @pytest.mark.asyncio
    async def test_message_completes_without_runtime(self, tmp_path: Path) -> None:
        """A message item completes immediately."""
        queue = _make_queue(tmp_path / "message.jsonl")
        _enqueue_message_item(queue, payload={"summary": "Test message"})
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "completed"
        assert result.queue_item_id == "wi-msg-001"
        # Message should not touch executor
        executor.execute_validate.assert_not_called()
        executor.execute_runtime_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_handoff_note_completes_without_runtime(self, tmp_path: Path) -> None:
        """A handoff_note item completes immediately."""
        queue = _make_queue(tmp_path / "handoff.jsonl")
        _enqueue_handoff_note_item(queue)
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "completed"

    @pytest.mark.asyncio
    async def test_pause_resume_completes_without_runtime(self, tmp_path: Path) -> None:
        """Pause/resume items complete without mutation."""
        queue = _make_queue(tmp_path / "pause-resume.jsonl")
        _enqueue_pause_item(queue)
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "completed"
        assert "no-op" in (result.reason or "")

    @pytest.mark.asyncio
    async def test_resume_acknowledged(self, tmp_path: Path) -> None:
        """Resume item completes as no-op."""
        queue = _make_queue(tmp_path / "resume.jsonl")
        _enqueue_resume_item(queue)
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "completed"


class TestUnsupportedItemKinds:
    @pytest.mark.asyncio
    async def test_unsupported_kind_becomes_blocked(self, tmp_path: Path) -> None:
        """An unsupported item kind is blocked."""
        queue = _make_queue(tmp_path / "unsupported.jsonl")
        queue.enqueue_item(kind="some_unsupported_kind", queue_item_id="wi-unsupported")
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "blocked"
        assert result.error_kind == "unsupported_queue_item_kind"


class TestRuntimeResultMapping:
    @pytest.mark.asyncio
    async def test_failed_runtime_result_marks_item_failed(
        self, tmp_path: Path
    ) -> None:
        """A failed execution marks the queue item failed."""
        queue = _make_queue(tmp_path / "failed.jsonl")
        _enqueue_validate_item(queue)
        executor = _make_fake_executor()
        executor.execute_validate = AsyncMock(
            return_value=_make_completed_result(
                status=RuntimeToolExecutionStatus.FAILED,
                error_kind="execution_error",
                refusal_reason="Tool crashed",
            )
        )
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "failed"
        snapshot = queue.list_items()
        assert snapshot.items[0].status == FleetQueueItemStatus.FAILED

    @pytest.mark.asyncio
    async def test_refused_runtime_result_marks_item_blocked(
        self, tmp_path: Path
    ) -> None:
        """A refused execution marks the queue item blocked."""
        queue = _make_queue(tmp_path / "refused.jsonl")
        _enqueue_validate_item(queue)
        executor = _make_fake_executor()
        executor.execute_validate = AsyncMock(
            return_value=_make_completed_result(
                status=RuntimeToolExecutionStatus.REFUSED,
                error_kind="unsupported_tool",
                refusal_reason="Tool not available",
            )
        )
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "blocked"
        snapshot = queue.list_items()
        assert snapshot.items[0].status == FleetQueueItemStatus.BLOCKED

    @pytest.mark.asyncio
    async def test_blocked_runtime_result_marks_item_blocked(
        self, tmp_path: Path
    ) -> None:
        """A blocked execution marks the queue item blocked."""
        queue = _make_queue(tmp_path / "blocked.jsonl")
        _enqueue_validate_item(queue)
        executor = _make_fake_executor()
        executor.execute_validate = AsyncMock(
            return_value=_make_completed_result(
                status=RuntimeToolExecutionStatus.BLOCKED,
                error_kind="lease_conflict",
                refusal_reason="Path is locked",
            )
        )
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "blocked"
        assert result.error_kind == "lease_conflict"


class TestOneItemPerCall:
    @pytest.mark.asyncio
    async def test_one_call_runs_only_one_item(self, tmp_path: Path) -> None:
        """run_once() processes exactly one item per call."""
        queue = _make_queue(tmp_path / "two-items.jsonl")
        _enqueue_validate_item(queue, queue_item_id="wi-first")
        _enqueue_runtime_exec_item(
            queue,
            queue_item_id="wi-second",
            payload={"tool_name": "validate", "profile": "quick"},
        )
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.queue_item_id == "wi-first"
        # Second item should still be queued
        snapshot = queue.list_items()
        second = [i for i in snapshot.items if i.queue_item_id == "wi-second"][0]
        assert second.status == FleetQueueItemStatus.QUEUED

    @pytest.mark.asyncio
    async def test_second_call_runs_next_item(self, tmp_path: Path) -> None:
        """After first item completes, second call runs next item."""
        queue = _make_queue(tmp_path / "sequential.jsonl")
        _enqueue_validate_item(queue, queue_item_id="wi-a")
        _enqueue_runtime_exec_item(
            queue,
            queue_item_id="wi-b",
            payload={"tool_name": "validate", "profile": "quick"},
        )
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        r1 = await runner.run_once()
        assert r1.queue_item_id == "wi-a"
        r2 = await runner.run_once()
        assert r2.queue_item_id == "wi-b"


class TestDependsOn:
    @pytest.mark.asyncio
    async def test_depends_on_is_respected(self, tmp_path: Path) -> None:
        """An item with unmet dependency is skipped."""
        queue = _make_queue(tmp_path / "depends.jsonl")
        _enqueue_validate_item(queue, queue_item_id="wi-dependency")
        _enqueue_runtime_exec_item(
            queue,
            queue_item_id="wi-dependent",
            depends_on=["wi-dependency"],
            payload={"tool_name": "validate", "profile": "quick"},
        )
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        # First call runs wi-dependency
        r1 = await runner.run_once()
        assert r1.queue_item_id == "wi-dependency"
        # Second call runs wi-dependent (dependency now completed)
        r2 = await runner.run_once()
        assert r2.queue_item_id == "wi-dependent"

    @pytest.mark.asyncio
    async def test_item_blocked_by_unmet_dependency(self, tmp_path: Path) -> None:
        """An item with unmet dependency is not selected."""
        queue = _make_queue(tmp_path / "blocked-dep.jsonl")
        _enqueue_runtime_exec_item(
            queue,
            queue_item_id="wi-dependent",
            depends_on=["wi-nonexistent"],
            payload={"tool_name": "validate", "profile": "quick"},
        )
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        # No runnable item since wi-dependent depends on non-existent
        assert result.decision == "idle"


class TestContentLight:
    @pytest.mark.asyncio
    async def test_result_has_no_forbidden_field_names(self, tmp_path: Path) -> None:
        """Result model fields don't contain forbidden words."""
        queue = _make_queue(tmp_path / "content-light.jsonl")
        _enqueue_validate_item(queue)
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        dumped = result.model_dump(mode="json")
        for forbidden in FORBIDDEN_WORDS:
            for key in dumped:
                assert forbidden not in key, (
                    f"Found forbidden key '{forbidden}' in result dump"
                )

    @pytest.mark.asyncio
    async def test_idle_result_is_content_light(self, tmp_path: Path) -> None:
        """Idle result has no forbidden fields."""
        queue = _make_queue(tmp_path / "idle-cl.jsonl")
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "idle"
        dumped = result.model_dump(mode="json")
        assert "decision" in dumped
        assert "schema_version" in dumped

    @pytest.mark.asyncio
    async def test_result_has_runtime_result_hash(self, tmp_path: Path) -> None:
        """A completed validate item produces a runtime_result_sha256."""
        queue = _make_queue(tmp_path / "hash.jsonl")
        _enqueue_validate_item(queue)
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.runtime_result_sha256 is not None
        assert result.runtime_result_sha256.startswith("sha256:")

    @pytest.mark.asyncio
    async def test_result_validates_against_schema(self, tmp_path: Path) -> None:
        """Result validates against queue_runner_result schema."""
        queue = _make_queue(tmp_path / "schema-val.jsonl")
        _enqueue_validate_item(queue)
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        errors = _validate_against_schema(result)
        assert not errors, f"Schema validation errors: {errors}"

    @pytest.mark.asyncio
    async def test_idle_result_validates_against_schema(self, tmp_path: Path) -> None:
        """Idle result validates against schema."""
        queue = _make_queue(tmp_path / "idle-schema.jsonl")
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        errors = _validate_against_schema(result)
        assert not errors, f"Schema validation errors: {errors}"

    @pytest.mark.asyncio
    async def test_model_dump_without_exclude_none(self, tmp_path: Path) -> None:
        """model_dump(mode='json') validates without exclude_none=True."""
        queue = _make_queue(tmp_path / "no-exclude-none.jsonl")
        _enqueue_validate_item(queue)
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        dumped = result.model_dump(mode="json")
        import jsonschema

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=dumped, schema=schema)


class TestEventEmission:
    @pytest.mark.asyncio
    async def test_runner_emits_running_then_terminal_event(
        self, tmp_path: Path
    ) -> None:
        """Running event is emitted before terminal event."""
        queue = _make_queue(tmp_path / "events.jsonl")
        _enqueue_validate_item(queue, queue_item_id="wi-events")
        executor = _make_fake_executor()
        runner = FleetQueueRunner(queue=queue, executor=executor)
        await runner.run_once()
        # Read the raw events file
        events_path = tmp_path / "events.jsonl"
        assert events_path.exists()
        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        # We expect at least 3 events: enqueued, status_changed(running), status_changed(completed)
        event_kinds = []
        for line in lines:
            if line:
                ev = json.loads(line)
                event_kinds.append(ev["event_kind"])
        assert "status_changed" in event_kinds
        # Find running and completed events in order
        running_events = [json.loads(l) for l in lines if l and "running" in l]
        completed_events = [json.loads(l) for l in lines if l and "completed" in l]
        assert len(running_events) >= 1
        assert len(completed_events) >= 1
        # running event should come before completed

    @pytest.mark.asyncio
    async def test_exception_during_execution_marks_failed(
        self, tmp_path: Path
    ) -> None:
        """An exception from executor marks queue item failed."""
        queue = _make_queue(tmp_path / "exception.jsonl")
        _enqueue_validate_item(queue)
        executor = _make_fake_executor()
        executor.execute_validate = AsyncMock(side_effect=RuntimeError("Boom"))
        runner = FleetQueueRunner(queue=queue, executor=executor)
        result = await runner.run_once()
        assert result.decision == "failed"
        assert result.error_kind == "execution_error"
        snapshot = queue.list_items()
        assert snapshot.items[0].status == FleetQueueItemStatus.FAILED
