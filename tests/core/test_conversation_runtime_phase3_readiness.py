from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

RUNTIME_PATH = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
TASK_PATH = _REPO_ROOT / "rig_relay" / "core" / "tools" / "builtins" / "task.py"
MODELS_PATH = _REPO_ROOT / "rig_relay" / "core" / "tool_runtime_models.py"


class TestPhase3Readiness:
    """Gate checks for ConversationRuntime Phase 3 loop transfer."""

    def test_task_tool_passes_subagent_runtime_kwargs(self) -> None:
        source = TASK_PATH.read_text()
        tree = ast.parse(source)
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "SubagentRuntime":
                    pos = len(node.args)
                    kwargs = {kw.arg: True for kw in node.keywords if kw.arg}
                    calls.append((pos, kwargs))
        assert calls, "task.py must construct SubagentRuntime"
        for pos_count, kwargs in calls:
            assert pos_count >= 1, (
                f"SubagentRuntime must receive at least 1 positional arg (mission), got {pos_count}"
            )
            assert "tool_runtime" in kwargs, (
                "task.py must pass tool_runtime= to SubagentRuntime. "
                "Use ctx.tool_runtime from InvokeContext."
            )

    def test_subagent_runtime_accepts_tool_runtime_and_allow_legacy(self) -> None:
        source = RUNTIME_PATH.read_text()
        assert "tool_runtime" in source
        assert "allow_legacy_direct" not in source or "False" in source, (
            "allow_legacy_direct should default to False or not exist"
        )

    def test_no_agent_loop_subagent_construction(self) -> None:
        source = RUNTIME_PATH.read_text()
        assert "AgentLoop(" not in source, (
            "SubagentRuntime must not construct AgentLoop"
        )
        assert "is_subagent" not in source, (
            "SubagentRuntime must not use is_subagent pattern"
        )

    def test_primary_tool_path_is_governed(self) -> None:
        source = RUNTIME_PATH.read_text()
        assert "_execute_tool_call_governed" in source
        assert "_execute_tool_call_legacy" in source
        assert "tool_runtime.execute_one" in source or "execute_and_format" in source, (
            "SubagentRuntime must use ToolRuntime via adapter"
        )

    def test_toolruntime_envelope_fields_exist(self) -> None:
        source = MODELS_PATH.read_text()
        assert "supervisor_result_envelope_id" in source
        assert "supervisor_result_envelope_sha256" in source
        assert "supervisor_result_classification" in source

    def test_subagent_adapter_preserves_envelope_fields(self) -> None:
        adapter_path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "tool_adapter.py"
        source = adapter_path.read_text()
        assert "supervisor_envelope_id" in source
        assert "supervisor_envelope_sha256" in source
        assert "supervisor_classification" in source

    def test_invoke_context_carries_tool_runtime(self) -> None:
        ctx_path = _REPO_ROOT / "rig_relay" / "core" / "tools" / "base.py"
        source = ctx_path.read_text()
        assert "tool_runtime: Any | None = field(default=None)" in source or "tool_runtime: Any | None" in source, (
            "InvokeContext must carry tool_runtime"
        )

    def test_legacy_direct_not_called_in_governed_path(self) -> None:
        source = RUNTIME_PATH.read_text()
        lines = source.split("\n")
        in_governed = False
        violations = []
        for i, line in enumerate(lines, start=1):
            if "def _execute_tool_call_governed" in line:
                in_governed = True
            elif line.startswith("    async def ") or line.startswith("    def "):
                in_governed = False
            if in_governed and "_execute_tool_call_legacy" in line:
                violations.append(f"Line {i}: {line.strip()}")
        assert not violations, (
            "Governed path must not call legacy method:\n" + "\n".join(violations)
        )

    def test_task_py_never_constructs_agent_loop(self) -> None:
        source = TASK_PATH.read_text()
        assert "AgentLoop(" not in source, "task.py must not construct AgentLoop"
        assert "is_subagent" not in source, "task.py must not use is_subagent"
