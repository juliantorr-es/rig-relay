"""Architecture boundary tests — enforce dependency direction.

AgentLoop and core mixins must not import from outer rings:
desktop, Ralph, scripts, analytics, bash query, or DuckDB.
"""

from __future__ import annotations

import ast
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent.parent.parent / "rig_relay" / "core"

FORBIDDEN_MODULES = (
    "rig_relay.desktop",
    "rig_relay.ralph",
    "rig_relay.scripts",
    "rig_relay.analytics",
    "rig_relay.reports.query",
    "rig_relay.bash.query",
    "duckdb",
)

# Modules that are allowed to import forbidden modules
# (none currently — add explicit exceptions with justification)
ALLOWLIST: dict[str, tuple[str, ...]] = {}


def _find_core_python_files() -> list[Path]:
    return sorted(
        p
        for p in CORE_DIR.rglob("*.py")
        if p.name != "__init__.py" or p.parent == CORE_DIR
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


class TestAgentLoopBoundary:
    def test_agent_loop_does_not_import_desktop(self):
        path = CORE_DIR / "agent_loop.py"
        imports = _imports_in_file(path)
        for imp in imports:
            assert not imp.startswith("rig_relay.desktop"), (
                f"agent_loop.py imports {imp}"
            )

    def test_agent_loop_does_not_import_ralph(self):
        path = CORE_DIR / "agent_loop.py"
        imports = _imports_in_file(path)
        for imp in imports:
            assert not imp.startswith("rig_relay.ralph"), f"agent_loop.py imports {imp}"

    def test_agent_loop_does_not_import_scripts(self):
        path = CORE_DIR / "agent_loop.py"
        imports = _imports_in_file(path)
        for imp in imports:
            assert not imp.startswith("rig_relay.scripts"), (
                f"agent_loop.py imports {imp}"
            )

    def test_agent_loop_does_not_import_duckdb(self):
        path = CORE_DIR / "agent_loop.py"
        imports = _imports_in_file(path)
        for imp in imports:
            assert not imp.startswith("duckdb"), "agent_loop.py imports duckdb"

    def test_agent_loop_does_not_import_analytics_query(self):
        path = CORE_DIR / "agent_loop.py"
        imports = _imports_in_file(path)
        analytics_imports = [i for i in imports if "analytics" in i or "bash" in i]
        assert not analytics_imports, (
            f"agent_loop.py imports analytics/bash modules: {analytics_imports}"
        )


class TestCoreMixinBoundaries:
    def test_mixins_do_not_import_forbidden_modules(self):
        mixin_files = [
            p
            for p in _find_core_python_files()
            if p.name.startswith("_") and p.name.endswith(".py")
        ]
        violations: list[tuple[str, str]] = []
        for path in mixin_files:
            imports = _imports_in_file(path)
            for imp in imports:
                for forbidden in FORBIDDEN_MODULES:
                    if imp.startswith(forbidden):
                        violations.append((path.name, imp))
        assert not violations, f"Core mixins import forbidden modules: {violations}"


class TestRuntimeStateBoundaries:
    def test_runtime_state_does_not_import_forbidden_modules(self):
        path = CORE_DIR / "runtime_state.py"
        imports = _imports_in_file(path)
        for imp in imports:
            for forbidden in FORBIDDEN_MODULES:
                assert not imp.startswith(forbidden), f"runtime_state.py imports {imp}"


class TestConversationTurnBoundaries:
    def test_conversation_turn_does_not_import_forbidden_modules(self):
        path = CORE_DIR / "conversation_turn.py"
        imports = _imports_in_file(path)
        for imp in imports:
            for forbidden in FORBIDDEN_MODULES:
                assert not imp.startswith(forbidden), (
                    f"conversation_turn.py imports {imp}"
                )
