"""SubagentRuntime ToolRuntime adoption — readiness proof tests.

Proves the production path passes tool_runtime= and routes through
ToolRuntime.execute_one() rather than legacy direct tool execution.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestTaskProductionWiring:
    def test_task_py_passes_tool_runtime_to_subagent_runtime(self) -> None:
        task_path = _REPO_ROOT / "rig_relay" / "core" / "tools" / "builtins" / "task.py"
        source = task_path.read_text()
        assert 'tool_runtime=getattr(ctx, "tool_runtime", None)' in source, (
            "task.py must pass ctx.tool_runtime to SubagentRuntime constructor"
        )

    def test_subagent_runtime_constructor_accepts_tool_runtime(self) -> None:
        runtime_path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = runtime_path.read_text()
        assert "tool_runtime: Any | None = None" in source, (
            "SubagentRuntime constructor must accept tool_runtime= parameter"
        )

    def test_governed_path_uses_execute_one(self) -> None:
        runtime_path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = runtime_path.read_text()
        assert "execute_and_format(" in source, (
            "Governed path must call execute_and_format() which calls ToolRuntime.execute_one()"
        )

    def test_tool_execution_mode_set_to_tool_runtime_when_provided(self) -> None:
        runtime_path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = runtime_path.read_text()
        assert (
            '"tool_runtime" if tool_runtime is None else "tool_runtime"' not in source
        )
        assert "self._tool_execution_mode" in source, (
            "SubagentRuntime must track tool_execution_mode for evidence metadata"
        )

    def test_no_legacy_direct_as_default(self) -> None:
        runtime_path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = runtime_path.read_text()
        assert (
            "fallback only when no ToolRuntime" in source
            or "explicit opt-in only" in source
        ), "Legacy direct path must be explicitly marked as fallback-only"


class TestToolAdapterEnvelopePassthrough:
    def test_subagent_tool_result_carries_envelope_fields(self) -> None:
        adapter_path = (
            _REPO_ROOT / "rig_relay" / "core" / "subagents" / "tool_adapter.py"
        )
        source = adapter_path.read_text()
        assert "supervisor_result_envelope_id" in source, (
            "SubagentToolResult must carry supervisor envelope id"
        )
        assert "supervisor_result_envelope_sha256" in source, (
            "SubagentToolResult must carry supervisor envelope sha256"
        )
        assert "supervisor_result_classification" in source, (
            "SubagentToolResult must carry supervisor classification"
        )

    def test_execute_and_format_extracts_envelope_from_tool_runtime_result(
        self,
    ) -> None:
        adapter_path = (
            _REPO_ROOT / "rig_relay" / "core" / "subagents" / "tool_adapter.py"
        )
        source = adapter_path.read_text()
        assert "result.supervisor_result_envelope_id" in source
        assert "result.supervisor_result_envelope_sha256" in source
        assert "result.supervisor_result_classification" in source
