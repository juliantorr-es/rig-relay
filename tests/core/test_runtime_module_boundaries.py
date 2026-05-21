"""Runtime module isolation tests — enforce independence between runtime modules.

Each runtime module must stand alone and not import its siblings
or AgentLoop (circular dependency prevention).

pytestmark = [pytest.mark.contract, pytest.mark.integration]
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = REPO_ROOT / "rig_relay" / "core"

RUNTIME_MODULES = {
    "session_runtime": CORE_DIR / "session_runtime.py",
    "governance_runtime": CORE_DIR / "governance_runtime.py",
    "trace_runtime": CORE_DIR / "trace_runtime.py",
    "tool_runtime": CORE_DIR / "tool_runtime.py",
}

TOOL_EXECUTOR_FILES = sorted((CORE_DIR / "tool_executor").rglob("*.py"))


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


def _runtime_imports_in_file(path: Path) -> list[str]:
    """Return module-level imports NOT inside a TYPE_CHECKING block.

    Excludes imports inside `if TYPE_CHECKING:` blocks and imports inside
    function/method bodies (lazy imports for circular-dep breaking).
    """
    tree = ast.parse(path.read_text())
    imports: list[str] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


class TestToolExecutorIsolation:
    def test_tool_executor_does_not_import_session_runtime(self):
        for p in TOOL_EXECUTOR_FILES:
            imports = _imports_in_file(p)
            session_imports = [i for i in imports if "session_runtime" in i]
            assert not session_imports, (
                f"{p.name} imports session_runtime: {session_imports}"
            )

    def test_tool_executor_does_not_import_governance_runtime(self):
        for p in TOOL_EXECUTOR_FILES:
            imports = _imports_in_file(p)
            gov_imports = [i for i in imports if "governance_runtime" in i]
            assert not gov_imports, (
                f"{p.name} imports governance_runtime: {gov_imports}"
            )


class TestSessionRuntimeIsolation:
    def test_session_runtime_does_not_import_governance_runtime(self):
        path = RUNTIME_MODULES["session_runtime"]
        imports = _imports_in_file(path)
        gov_imports = [i for i in imports if "governance_runtime" in i]
        assert not gov_imports, (
            f"session_runtime.py imports governance_runtime: {gov_imports}"
        )

    def test_session_runtime_does_not_import_tool_executor(self):
        path = RUNTIME_MODULES["session_runtime"]
        imports = _imports_in_file(path)
        te_imports = [i for i in imports if "tool_executor" in i]
        assert not te_imports, f"session_runtime.py imports tool_executor: {te_imports}"


class TestGovernanceRuntimeIsolation:
    def test_governance_runtime_does_not_import_tool_executor(self):
        path = RUNTIME_MODULES["governance_runtime"]
        imports = _imports_in_file(path)
        te_imports = [i for i in imports if "tool_executor" in i]
        assert not te_imports, (
            f"governance_runtime.py imports tool_executor: {te_imports}"
        )


class TestTraceRuntimeStandalone:
    def test_trace_runtime_importable_without_agent_loop(self):
        path = RUNTIME_MODULES["trace_runtime"]
        imports = _imports_in_file(path)
        al_imports = [i for i in imports if "agent_loop" in i]
        assert not al_imports, f"trace_runtime.py imports agent_loop: {al_imports}"


class TestNoRuntimeModuleImportsAgentLoop:
    def test_no_runtime_module_imports_agent_loop(self):
        violations: list[tuple[str, str]] = []
        runtime_paths = list(RUNTIME_MODULES.values()) + TOOL_EXECUTOR_FILES
        for p in runtime_paths:
            if not p.exists():
                continue
            imports = _runtime_imports_in_file(p)
            for imp in imports:
                if "agent_loop" in imp:
                    violations.append((p.name, imp))
        assert not violations, (
            f"Runtime modules import agent_loop at module level "
            f"(circular dependency risk): {violations}"
        )


class TestRuntimeModuleForbiddenImports:
    def test_no_runtime_module_imports_forbidden(self):
        forbidden = (
            "rig_relay.desktop",
            "rig_relay.ralph",
            "rig_relay.scripts",
            "rig_relay.analytics",
            "duckdb",
        )
        runtime_paths = list(RUNTIME_MODULES.values()) + TOOL_EXECUTOR_FILES
        violations: list[tuple[str, str, str]] = []
        for p in runtime_paths:
            if not p.exists():
                continue
            imports = _imports_in_file(p)
            for imp in imports:
                for f in forbidden:
                    if imp.startswith(f):
                        violations.append((p.name, imp, f))
        assert not violations, f"Runtime modules import forbidden modules: {violations}"
