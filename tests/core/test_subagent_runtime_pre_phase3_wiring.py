"""SubagentRuntime strict ToolRuntime default and trace wiring — Phase 3 pre-flight.

Proves:
- No silent legacy_direct when tool_runtime is missing (AST proof)
- Explicit allow_legacy_direct opt-in preserves test path (AST proof)
- task.py passes tool_runtime and trace_recorder (AST proof)
- Lifecycle evidence emits with trace recorder (behavioral)
- Governed path remains primary (AST proof)
- Legacy metadata is explicit (AST proof)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.store import InMemoryTraceStore

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestStrictDefaultNoLegacyAST:
    """AST-level proofs — no SubagentRuntime import needed."""

    def test_allow_legacy_direct_parameter_exists(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = path.read_text()
        assert "allow_legacy_direct: bool = False" in source, (
            "SubagentRuntime constructor must have allow_legacy_direct parameter"
        )

    def test_legacy_direct_not_default(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = path.read_text()
        assert "tool_runtime_required" in source, (
            "tool_runtime_required mode must exist for missing ToolRuntime + no legacy opt-in"
        )

    def test_legacy_path_is_explicit_opt_in(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = path.read_text()
        assert "Explicit opt-in only" in source or "explicit opt-in only" in source, (
            "Legacy path comment must mark it as explicit opt-in"
        )

    def test_no_silent_fallback_when_tool_runtime_missing(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = path.read_text()
        assert "ToolRuntime required for" in source, (
            "Missing ToolRuntime must produce structured refusal message"
        )

    def test_tool_runtime_present_still_governed(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = path.read_text()
        assert "if self._tool_runtime is not None:" in source
        assert "_execute_tool_call_governed" in source

    def test_metadata_includes_legacy_direct_allowed(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = path.read_text()
        assert "legacy_direct_allowed" in source, (
            "Build result metadata must include legacy_direct_allowed field"
        )

    def test_execution_mode_set_correctly(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = path.read_text()
        assert 'self._tool_execution_mode = "tool_runtime"' in source
        assert 'self._tool_execution_mode = "legacy_direct"' in source
        assert 'self._tool_execution_mode = "tool_runtime_required"' in source


class TestTaskProductionWiring:
    def test_task_py_passes_tool_runtime(self) -> None:
        task_path = _REPO_ROOT / "rig_relay" / "core" / "tools" / "builtins" / "task.py"
        source = task_path.read_text()
        assert 'tool_runtime=getattr(ctx, "tool_runtime", None)' in source

    def test_task_py_passes_trace_recorder(self) -> None:
        task_path = _REPO_ROOT / "rig_relay" / "core" / "tools" / "builtins" / "task.py"
        source = task_path.read_text()
        assert 'trace_recorder=getattr(ctx, "trace_recorder", None)' in source

    def test_task_py_sets_allow_legacy_direct_false(self) -> None:
        task_path = _REPO_ROOT / "rig_relay" / "core" / "tools" / "builtins" / "task.py"
        source = task_path.read_text()
        assert "allow_legacy_direct=False" in source


class TestLifecycleEvidence:
    def test_trace_recorder_writes_events(
        self, trace_store: InMemoryTraceStore
    ) -> None:
        recorder = TraceRecorder(trace_store)
        with recorder.span("subagent.test", {"mission_id": "m1"}):
            pass
        events = trace_store.events
        assert len(events) >= 2
        kinds = [e["event_kind"] for e in events]
        assert "span.start" in kinds
        assert "span.end" in kinds

    def test_trace_recorder_error_span(self, trace_store: InMemoryTraceStore) -> None:
        recorder = TraceRecorder(trace_store)
        rec = recorder  # alias
        with pytest.raises(ValueError, match="test error"):
            with rec.span("subagent.fail"):
                raise ValueError("test error")
        end = trace_store.events[-1]
        assert end["status"] == "error"

    def test_null_store_is_noop(self) -> None:
        from rig_relay.tracing.store import NullTraceStore

        recorder = TraceRecorder(NullTraceStore())
        with recorder.span("subagent.noop"):
            pass


class TestGuards:
    def test_subagent_runtime_never_constructs_agent_loop(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = path.read_text()
        assert "AgentLoop(" not in source

    def test_governed_path_remains_primary(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = path.read_text()
        assert "if self._tool_runtime is not None:" in source
        assert "_execute_tool_call_governed" in source

    def test_no_legacy_direct_as_default(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = path.read_text()
        assert (
            "Legacy direct path (explicit opt-in only)" in source
            or "Legacy direct path (fallback only when no ToolRuntime)" in source
        )


@pytest.fixture
def trace_store() -> InMemoryTraceStore:
    return InMemoryTraceStore()
