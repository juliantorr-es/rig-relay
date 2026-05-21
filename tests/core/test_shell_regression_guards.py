"""Shell regression guards — prove AgentLoop is thin and stays thin.

Enforces dependency boundaries (forbidden imports), delegation
contracts (AgentLoop delegates to runtime modules), and a hard
line-count cap.

pytestmark = [pytest.mark.contract, pytest.mark.integration]
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_LOOP_PATH = REPO_ROOT / "rig_relay" / "core" / "agent_loop.py"

FORBIDDEN_MODULES = (
    "rig_relay.desktop",
    "rig_relay.ralph",
    "rig_relay.scripts",
    "rig_relay.analytics",
    "duckdb",
)


def _imports_in_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


class TestAgentLoopForbiddenImports:
    def test_does_not_import_desktop(self):
        imports = _imports_in_file(AGENT_LOOP_PATH)
        for imp in imports:
            assert not imp.startswith("rig_relay.desktop"), (
                f"agent_loop.py imports {imp}"
            )

    def test_does_not_import_ralph(self):
        imports = _imports_in_file(AGENT_LOOP_PATH)
        for imp in imports:
            assert not imp.startswith("rig_relay.ralph"), f"agent_loop.py imports {imp}"

    def test_does_not_import_analytics(self):
        imports = _imports_in_file(AGENT_LOOP_PATH)
        for imp in imports:
            assert not imp.startswith("rig_relay.analytics"), (
                f"agent_loop.py imports {imp}"
            )

    def test_does_not_import_duckdb(self):
        imports = _imports_in_file(AGENT_LOOP_PATH)
        for imp in imports:
            assert not imp.startswith("duckdb"), f"agent_loop.py imports {imp}"


class TestAgentLoopDelegation:
    def test_delegates_tool_execution(self):
        """AgentLoop._execute_tool_call must delegate to ToolExecutor."""
        imports = _imports_in_file(AGENT_LOOP_PATH)
        assert any("tool_executor" in i for i in imports), (
            "agent_loop.py must import from tool_executor"
        )

    def test_delegates_session_lifecycle(self):
        """AgentLoop.fork/compact/clear_history must delegate to SessionRuntime."""
        imports = _imports_in_file(AGENT_LOOP_PATH)
        assert any("session_runtime" in i for i in imports), (
            "agent_loop.py must import from session_runtime"
        )

    def test_delegates_governance(self):
        """AgentLoop._should_execute_tool/_ask_approval must delegate to GovernanceRuntime."""
        imports = _imports_in_file(AGENT_LOOP_PATH)
        assert any("governance_runtime" in i for i in imports), (
            "agent_loop.py must import from governance_runtime"
        )

    def test_delegates_trace(self):
        """AgentLoop._act must use TraceRuntime.agent_span."""
        imports = _imports_in_file(AGENT_LOOP_PATH)
        assert any("trace_runtime" in i for i in imports), (
            "agent_loop.py must import from trace_runtime"
        )


class TestAgentLoopLineCount:
    def test_under_1000_lines(self):
        lines = len(AGENT_LOOP_PATH.read_text().split("\n"))
        assert lines < 1000, f"AgentLoop is {lines} lines — should be under 1000"
