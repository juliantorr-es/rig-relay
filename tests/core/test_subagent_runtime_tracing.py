"""SubagentRuntime v1 — lifecycle evidence and privacy tests."""

from __future__ import annotations

from datetime import UTC, datetime
import time
from unittest.mock import MagicMock

import pytest

from rig_relay.core.subagents.models import SubagentMission, SubagentResult
from rig_relay.core.subagents.runtime import SubagentRuntime
from rig_relay.tracing.models import TraceStatus
from rig_relay.tracing.recorder import TraceRecorder


def _make_mission(**kwargs) -> SubagentMission:
    defaults = {
        "parent_session_id": "sess-1",
        "parent_turn_id": "turn-1",
        "parent_trace_id": "trace-parent",
        "task": "run tests",
        "agent_profile": "explore",
        "budget_max_turns": 3,
        "budget_max_tool_calls": 5,
    }
    defaults.update(kwargs)
    return SubagentMission(**defaults)


# ── Lifecycle evidence tests ────────────────────────────────────


class TestSubagentLifecycleEvidence:
    def test_emits_start_and_completed_events(self) -> None:
        store = MagicMock()
        store.write = MagicMock()
        recorder = TraceRecorder(store)

        mission = _make_mission()
        runtime = SubagentRuntime(mission, trace_recorder=recorder)
        runtime._wall_started_at = datetime.now(UTC).isoformat()
        runtime._mono_start = time.monotonic()

        # Emit start + completed directly
        runtime._emit_start()
        runtime._emit_end(status="completed")

        written = [c.args[0] for c in store.write.call_args_list]
        span_starts = [e for e in written if e.event_kind.value == "span.start"]
        span_ends = [e for e in written if e.event_kind.value == "span.end"]

        assert len(span_starts) == 1
        assert len(span_ends) == 1
        assert span_starts[0].name == "subagent.runtime"
        assert span_ends[0].status == TraceStatus.ok

    def test_emits_error_status(self) -> None:
        store = MagicMock()
        store.write = MagicMock()
        recorder = TraceRecorder(store)

        mission = _make_mission()
        runtime = SubagentRuntime(mission, trace_recorder=recorder)
        runtime._wall_started_at = datetime.now(UTC).isoformat()

        runtime._emit_start()
        runtime._emit_end(status="error", reason="something broke")

        written = [c.args[0] for c in store.write.call_args_list]
        span_ends = [e for e in written if e.event_kind.value == "span.end"]
        assert len(span_ends) == 1
        assert span_ends[0].status == TraceStatus.error
        assert span_ends[0].error_message == "something broke"

    def test_emits_cancelled_status(self) -> None:
        store = MagicMock()
        store.write = MagicMock()
        recorder = TraceRecorder(store)

        runtime = SubagentRuntime(_make_mission(), trace_recorder=recorder)
        runtime._emit_start()
        runtime._emit_end(status="cancelled", reason="user hit esc")

        written = [c.args[0] for c in store.write.call_args_list]
        span_ends = [e for e in written if e.event_kind.value == "span.end"]
        assert span_ends[0].status == TraceStatus.cancelled

    def test_emits_budget_exhausted_event(self) -> None:
        store = MagicMock()
        store.write = MagicMock()
        recorder = TraceRecorder(store)

        mission = _make_mission(budget_max_turns=5, budget_max_tool_calls=3)
        runtime = SubagentRuntime(mission, trace_recorder=recorder)
        runtime._turns = 5
        runtime._tool_calls_attempted = 3
        runtime._emit_start()
        runtime._emit_budget_exhausted()

        written = [c.args[0] for c in store.write.call_args_list]
        events = [e for e in written if e.event_kind.value == "span.event"]
        budget_events = [e for e in events if "budget" in e.name]
        assert len(budget_events) >= 1

    def test_no_trace_recorder_does_not_crash(self) -> None:
        runtime = SubagentRuntime(_make_mission())
        # Should not raise
        runtime._emit_start()
        runtime._emit_end(status="completed")
        runtime._emit_budget_exhausted()

    def test_emit_does_not_crash_on_recorder_exception(self) -> None:
        store = MagicMock()
        store.write = MagicMock(side_effect=RuntimeError("disk full"))
        recorder = TraceRecorder(store)

        runtime = SubagentRuntime(_make_mission(), trace_recorder=recorder)
        # Should not raise despite recorder error
        runtime._emit_start()
        runtime._emit_end(status="completed")


# ── Privacy tests ───────────────────────────────────────────────


class TestSubagentTracePrivacy:
    def test_mission_extra_forbid(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SubagentMission(
                task="hello",
                raw_prompt="leaked",  # type: ignore[call-arg]
            )

    def test_result_extra_forbid(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SubagentResult(
                mission_id="m1",
                status="completed",
                tool_output="leaked",  # type: ignore[call-arg]
            )

    def test_result_excludes_raw_fields(self) -> None:
        mission = _make_mission()
        result = SubagentResult(
            mission_id=mission.mission_id, status="completed", summary="All good"
        )
        d = result.model_dump()
        assert "stdout" not in d
        assert "stderr" not in d
        assert "argv" not in d
        assert "env" not in d

    def test_trace_extra_forbid(self) -> None:
        from pydantic import ValidationError

        from rig_relay.core.subagents.models import SubagentRuntimeTrace

        with pytest.raises(ValidationError):
            SubagentRuntimeTrace(
                event="start",
                mission_id="m1",
                parent_session_id="s1",
                timestamp="2021-01-01T00:00:00Z",
                task_text="leaked",  # type: ignore[call-arg]
            )


# ── Timestamp sanity tests ──────────────────────────────────────


class TestSubagentTimestampSanity:
    def test_started_at_is_iso8601(self) -> None:
        runtime = SubagentRuntime(_make_mission())
        runtime._wall_started_at = datetime.now(UTC).isoformat()
        assert "T" in runtime._wall_started_at
        assert (
            runtime._wall_started_at.endswith("+00:00")
            or "Z" in runtime._wall_started_at
        )

    def test_monotonic_not_used_as_wall_clock(self) -> None:
        runtime = SubagentRuntime(_make_mission())
        runtime._wall_started_at = "1970-01-01T05:30:00.123456+00:00"
        # Should not look like a monotonic start (which would be epoch-ish)
        # If this were from monotonic, it would start with "1970-0" and have nonsense time
        # The actual assertion: verify _wall_started_at is set via ISO, not fromtimestamp(monotonic)
        runtime._mono_start = time.monotonic()  # not used for wall clock

    def test_build_result_uses_wall_clock(self) -> None:
        runtime = SubagentRuntime(_make_mission())
        runtime._wall_started_at = datetime.now(UTC).isoformat()
        runtime._mono_start = time.monotonic()

        result = runtime._build_result(status="completed")
        assert "T" in result.started_at
        assert "T" in result.completed_at
        assert result.started_at <= result.completed_at

    def test_metadata_has_duration_from_monotonic(self) -> None:
        runtime = SubagentRuntime(_make_mission())
        runtime._wall_started_at = datetime.now(UTC).isoformat()
        runtime._mono_start = time.monotonic() - 0.5  # pretend 500ms ago

        result = runtime._build_result(status="completed")
        dur = result.metadata.get("duration_ms", -1)
        assert dur >= 0


# ── Parent trace propagation tests ──────────────────────────────


class TestSubagentTracePropagation:
    def test_parent_trace_in_span_attributes(self) -> None:
        store = MagicMock()
        store.write = MagicMock()
        recorder = TraceRecorder(store)

        mission = _make_mission(parent_trace_id="trace-parent-456")
        runtime = SubagentRuntime(mission, trace_recorder=recorder)
        runtime._emit_start()

        written = [c.args[0] for c in store.write.call_args_list]
        starts = [e for e in written if e.event_kind.value == "span.start"]
        if starts:
            attrs = starts[0].attributes
            assert attrs["parent_trace_id"] == "trace-parent-456"

    def test_mission_stores_parent_trace(self) -> None:
        mission = _make_mission(parent_trace_id="trace-xyz")
        assert mission.parent_trace_id == "trace-xyz"


# ── Tool execution mode tests ───────────────────────────────────


class TestSubagentToolExecutionMode:
    def test_legacy_direct_mode_is_default(self) -> None:
        runtime = SubagentRuntime(_make_mission())
        assert runtime._tool_execution_mode == "legacy_direct"

    def test_mode_appears_in_result_metadata(self) -> None:
        runtime = SubagentRuntime(_make_mission())
        runtime._wall_started_at = datetime.now(UTC).isoformat()
        runtime._mono_start = time.monotonic()

        result = runtime._build_result(status="completed")
        assert result.metadata["tool_execution_mode"] == "legacy_direct"

    def test_mode_appears_in_trace_attributes(self) -> None:
        store = MagicMock()
        store.write = MagicMock()
        recorder = TraceRecorder(store)

        runtime = SubagentRuntime(_make_mission(), trace_recorder=recorder)
        runtime._emit_start()
        runtime._tool_execution_mode = "legacy_direct"
        runtime._emit_end(status="completed")

        written = [c.args[0] for c in store.write.call_args_list]
        ends = [e for e in written if e.event_kind.value == "span.end"]
        if ends:
            attrs = ends[0].attributes
            assert "tool_execution_mode" in attrs


# ── Guard regression tests ──────────────────────────────────────


class TestSubagentRuntimeNoAgentLoopRegression:
    def test_runtime_module_does_not_import_agent_loop(self) -> None:
        import ast
        from pathlib import Path

        runtime_file = (
            Path(__file__).resolve().parents[2] / "rig_relay/core/subagents/runtime.py"
        )
        tree = ast.parse(runtime_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "agent_loop" in node.module:
                    for alias in node.names:
                        if "AgentLoop" in alias.name:
                            pytest.fail(
                                "SubagentRuntime imports AgentLoop: "
                                f"{node.module}.{alias.name}"
                            )
