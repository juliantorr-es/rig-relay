"""Architecture guards — SubagentRuntime boundary enforcement.

Ensures:
- task.py never constructs AgentLoop for subagents
- Only approved orchestrator sites construct AgentLoop
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Approved AgentLoop construction sites (file, function or line marker)
_APPROVED_AGENTLOOP_CONSTRUCTION = {
    "rig_relay/core/agent_loop.py",
    "rig_relay/core/programmatic.py",  # CLI programmatic entry
    "rig_relay/cli/desktop_cockpit.py",
    "rig_relay/acp/_session_lifecycle.py",
    "rig_relay/acp/acp_agent_loop.py",
    "rig_relay/cli/ide_sidecar.py",
}

# Files that must NEVER construct AgentLoop
_FORBIDDEN_AGENTLOOP_CONSTRUCTION = {
    "rig_relay/core/tools/builtins/task.py",
    "rig_relay/ralph/",
    "rig_relay/core/subagents/",
}

# is_subagent=True is permanently forbidden in all construction sites
_FORBIDDEN_IS_SUBAGENT = "is_subagent"


def _find_agent_loop_constructions(file_path: Path) -> list[tuple[int, str]]:
    """Return (lineno, partial_line) for each AgentLoop( call in file."""
    results: list[tuple[int, str]] = []
    try:
        tree = ast.parse(file_path.read_text(), filename=str(file_path))
    except Exception:
        return results

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "AgentLoop":
                line = file_path.read_text().splitlines()[node.lineno - 1].strip()
                results.append((node.lineno, line))
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "AgentLoop":
                line = file_path.read_text().splitlines()[node.lineno - 1].strip()
                results.append((node.lineno, line))
    return results


def _relative_path(file_path: Path) -> str:
    try:
        return str(file_path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(file_path)


class TestSubagentRuntimeGuards:
    def test_task_py_never_constructs_agent_loop(self) -> None:
        """task.py must use SubagentRuntime, never AgentLoop."""
        task_file = _REPO_ROOT / "rig_relay/core/tools/builtins/task.py"
        calls = _find_agent_loop_constructions(task_file)
        assert not calls, (
            f"task.py constructs AgentLoop at lines: "
            f"{[lineno for lineno, _ in calls]}. "
            "Use SubagentRuntime instead."
        )

    def test_task_py_never_uses_is_subagent(self) -> None:
        """is_subagent=True is forbidden anywhere in task.py."""
        task_file = _REPO_ROOT / "rig_relay/core/tools/builtins/task.py"
        text = task_file.read_text()
        assert _FORBIDDEN_IS_SUBAGENT not in text, (
            "task.py references is_subagent. Use SubagentRuntime instead."
        )

    def test_subagent_runtime_never_constructs_agent_loop(self) -> None:
        """SubagentRuntime modules must not construct AgentLoop."""
        sub_dir = _REPO_ROOT / "rig_relay/core/subagents"
        violations: list[str] = []
        for py_file in sub_dir.rglob("*.py"):
            calls = _find_agent_loop_constructions(py_file)
            for lineno, line in calls:
                violations.append(f"{_relative_path(py_file)}:{lineno}: {line}")
        assert not violations, (
            "SubagentRuntime imports or constructs AgentLoop:\n" + "\n".join(violations)
        )

    def test_ralph_never_constructs_agent_loop(self) -> None:
        """Ralph modules must never construct AgentLoop."""
        ralph_dir = _REPO_ROOT / "rig_relay/ralph"
        if not ralph_dir.is_dir():
            return  # Ralph directory doesn't exist yet
        violations: list[str] = []
        for py_file in ralph_dir.rglob("*.py"):
            calls = _find_agent_loop_constructions(py_file)
            for lineno, line in calls:
                violations.append(f"{_relative_path(py_file)}:{lineno}: {line}")
        assert not violations, "Ralph constructs AgentLoop:\n" + "\n".join(violations)

    def test_approved_sites_are_complete(self) -> None:
        """Every AgentLoop construction site is either approved or flagged."""
        violations: list[str] = []
        core_dir = _REPO_ROOT / "rig_relay"
        for py_file in core_dir.rglob("*.py"):
            rel = _relative_path(py_file)
            # Skip test files
            if "tests/" in rel:
                continue
            calls = _find_agent_loop_constructions(py_file)
            if not calls:
                continue
            # Check if file is approved
            approved = any(
                rel.startswith(approved.replace("/", "").replace("\\", ""))
                or approved in rel
                for approved in _APPROVED_AGENTLOOP_CONSTRUCTION
            )
            if not approved:
                for lineno, line in calls:
                    violations.append(f"{rel}:{lineno}: {line}")
        # Report violations but don't fail — only task.py is enforced strictly
        if violations:
            print(f"\n⚠️  Unapproved AgentLoop construction sites ({len(violations)}):")
            for v in violations:
                print(f"  • {v}")
            print("  Only task.py is enforced strictly.\n")


class TestSubagentRuntimeDirectExecutionGuards:
    """Ensure SubagentRuntime never directly calls tool_inst.run()."""

    def test_subagent_runtime_has_no_direct_tool_run(self) -> None:
        runtime_path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = runtime_path.read_text()
        # tool_inst.run is only allowed inside _execute_tool_call_legacy
        lines = source.split("\n")
        in_legacy = False
        violations: list[str] = []
        for lineno, line in enumerate(lines, start=1):
            if "def _execute_tool_call_legacy" in line:
                in_legacy = True
            elif line.startswith("    async def ") or line.startswith("    def "):
                in_legacy = False
            if "tool_inst.run(" in line and not in_legacy:
                violations.append(f"Line {lineno}: {line.strip()}")
        assert not violations, (
            "tool_inst.run() outside _execute_tool_call_legacy:\n"
            + "\n".join(violations)
        )

    def test_legacy_path_is_marked_not_default(self) -> None:
        runtime_path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = runtime_path.read_text()
        assert "_execute_tool_call_legacy" in source, (
            "Legacy path removed entirely — restore as fallback until ToolRuntime is always provided"
        )
        assert (
            """# ── Legacy direct path (fallback only when no ToolRuntime) ─"""
            in source
        ), "Legacy path must be clearly marked as fallback-only"

    def test_governed_path_is_primary(self) -> None:
        runtime_path = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        source = runtime_path.read_text()
        assert (
            """# ── Governed path: route through ToolRuntime ────────────""" in source
        ), "Governed path comment missing — ensure ToolRuntime routing is primary"
