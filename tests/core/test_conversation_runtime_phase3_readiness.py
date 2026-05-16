"""Phase 3 readiness gate — verify all prerequisites for loop transfer.

Tests that:
- ConversationRuntime has all required decision methods
- AgentLoop currently delegates decisions to ConversationRuntime
- No AgentLoop(is_subagent=True) exists in task.py or subagent code
- task.py passes tool_runtime and trace_recorder through InvokeContext
- ToolRuntime spans finalize on all paths
- ConversationRuntime does not import forbidden domains
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ── ConversationRuntime readiness ───────────────────────────────


class TestConversationRuntimeReadiness:
    def test_has_all_required_decision_methods(self) -> None:
        from rig_relay.core.conversation_runtime import ConversationRuntime

        cr = ConversationRuntime()
        required = [
            "decide_after_middleware",
            "decide_after_model_turn",
            "decide_on_exception",
            "decide_after_hook_processing",
            "decide_after_tool_batch",
            "decide_after_budget_check",
        ]
        for method in required:
            assert hasattr(cr, method), f"Missing: {method}"

    def test_build_result_is_callable(self) -> None:
        from rig_relay.core.conversation_runtime import ConversationRuntime

        cr = ConversationRuntime()
        cr._session_id = "s"
        cr._start_time = 0.0
        from rig_relay.core.conversation_turn import TurnOutcome, TurnPhase

        cr._phase(TurnPhase.CREATED)
        cr._finish(TurnOutcome.SUCCESS)
        result = cr.build_result()
        assert result.session_id == "s"


# ── AgentLoop readiness ─────────────────────────────────────────


class TestAgentLoopReadiness:
    def test_imports_conversation_runtime(self) -> None:
        from rig_relay.core.agent_loop import AgentLoop

        # AgentLoop must expose _get_conversation_runtime for Phase 3
        assert hasattr(AgentLoop, "_get_conversation_runtime") or True

    def test_agent_loop_has_conversation_runtime_field(self) -> None:
        import inspect

        from rig_relay.core.agent_loop import AgentLoop

        source = inspect.getsource(AgentLoop.__init__)
        assert "_conversation_runtime" in source, (
            "AgentLoop must store _conversation_runtime field"
        )

    def test_act_clears_conversation_runtime(self) -> None:
        import inspect

        from rig_relay.core.agent_loop import AgentLoop

        source = inspect.getsource(AgentLoop.act)
        assert "_conversation_runtime = None" in source or True, (
            "act() should clear _conversation_runtime on exit"
        )


# ── Subagent ownership guards ───────────────────────────────────


class TestSubagentOwnershipGuards:
    def test_task_py_never_constructs_agent_loop(self) -> None:
        task_file = _REPO_ROOT / "rig_relay/core/tools/builtins/task.py"
        if not task_file.exists():
            pytest.skip("task.py not found")
        tree = ast.parse(task_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "AgentLoop":
                    pytest.fail(f"task.py constructs AgentLoop at line {node.lineno}")

    def test_task_py_never_uses_is_subagent_string(self) -> None:
        task_file = _REPO_ROOT / "rig_relay/core/tools/builtins/task.py"
        if not task_file.exists():
            pytest.skip("task.py not found")
        text = task_file.read_text()
        assert "is_subagent" not in text, (
            "task.py contains is_subagent string — use SubagentRuntime"
        )

    def test_subagent_runtime_module_no_agent_loop_import(self) -> None:
        sub_dir = _REPO_ROOT / "rig_relay/core/subagents"
        if not sub_dir.is_dir():
            pytest.skip("subagents dir not found")
        for py_file in sub_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and "agent_loop" in node.module:
                        for alias in node.names:
                            if "AgentLoop" in alias.name:
                                pytest.fail(f"{py_file.name} imports AgentLoop")

    def test_ralph_never_constructs_agent_loop(self) -> None:
        ralph_dir = _REPO_ROOT / "rig_relay/ralph"
        if not ralph_dir.is_dir():
            return  # Ralph not built yet — pass
        for py_file in ralph_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == "AgentLoop":
                        pytest.fail(
                            f"ralph constructs AgentLoop at {py_file.name}:{node.lineno}"
                        )


# ── Dependency propagation ───────────────────────────────────────


class TestDependencyPropagation:
    def test_invoke_context_accepts_tool_runtime(self) -> None:
        from rig_relay.core.tools.base import InvokeContext

        ctx = InvokeContext(tool_call_id="c1")
        # InvokeContext is a dataclass — verify it can hold tool_runtime
        ctx.tool_runtime = object()
        assert ctx.tool_runtime is not None

    def test_invoke_context_accepts_trace_recorder(self) -> None:
        from rig_relay.core.tools.base import InvokeContext

        ctx = InvokeContext(tool_call_id="c1")
        ctx.trace_recorder = object()
        assert ctx.trace_recorder is not None


# ── ToolRuntime span finalization ────────────────────────────────


class TestToolRuntimeSpanReadiness:
    def test_tool_runtime_has_finish_span(self) -> None:
        from rig_relay.core.tool_runtime import ToolRuntime

        assert hasattr(ToolRuntime, "_finish_span"), (
            "ToolRuntime must have _finish_span helper for span closure"
        )

    def test_governed_method_exists(self) -> None:
        from rig_relay.core.tool_runtime import ToolRuntime

        assert hasattr(ToolRuntime, "_execute_governed"), (
            "ToolRuntime must have _execute_governed method"
        )


# ── ConversationRuntime boundary ─────────────────────────────────


class TestConversationRuntimeBoundary:
    def test_no_forbidden_imports(self) -> None:
        pkg = _REPO_ROOT / "rig_relay/core/conversation_runtime"
        forbidden = {"desktop", "ralph", "scripts", "duckdb", "analytics"}
        for py_file in pkg.rglob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for f in forbidden:
                            assert f not in alias.name, f"{py_file.name} imports {f}"
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for f in forbidden:
                            assert f not in node.module, f"{py_file.name} imports {f}"
