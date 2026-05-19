from __future__ import annotations

import inspect
from pathlib import Path
import re

from rig_relay.core.agent_loop import AgentLoop
from rig_relay.core.conversation_runtime.models import ConversationRuntimeStatus
from rig_relay.core.conversation_turn import ConversationTurnRuntime
from rig_relay.core.runtime_state import AgentRuntimeState
from rig_relay.core.subagents.models import SubagentMission, SubagentResult
from rig_relay.core.subagents.runtime import SubagentRuntime
from rig_relay.core.tool_runtime_models import ToolRuntimeRequest, ToolRuntimeResult
from rig_relay.runtime.execution_budgets import AgentExecutionBudgets
from rig_relay.runtime.execution_request import ExecutionRequest
from rig_relay.runtime.models import RuntimeInvocationStatus
from rig_relay.runtime.supervisor import RuntimeSupervisor
from rig_relay.runtime.tool_invocation_execution import RuntimeToolExecutionResult


def _module_source_lines(module_path: str) -> list[str]:
    p = Path(__file__).parent.parent.parent / module_path
    return p.read_text().splitlines()


def test_runtime_supervisor_has_taskgroup_or_registry() -> None:
    supervisor_init = inspect.signature(RuntimeSupervisor.__init__)

    assert any("heartbeat" in p.name for p in supervisor_init.parameters.values()), (
        "RuntimeSupervisor should have heartbeat/stall parameters"
    )

    assert any("stall" in p.name for p in supervisor_init.parameters.values()), (
        "RuntimeSupervisor should have stall detection parameters"
    )

    source = inspect.getsource(RuntimeSupervisor)
    assert "asyncio.create_task" in source, (
        "RuntimeSupervisor should use asyncio.create_task for structured task management"
    )
    assert "drain_tasks" in source, (
        "RuntimeSupervisor should track drain tasks list for lifecycle management"
    )


def test_subagent_lifecycle_states_are_defined() -> None:
    assert hasattr(RuntimeInvocationStatus, "PENDING")
    assert hasattr(RuntimeInvocationStatus, "STARTING")
    assert hasattr(RuntimeInvocationStatus, "RUNNING")
    assert hasattr(RuntimeInvocationStatus, "SUCCEEDED")
    assert hasattr(RuntimeInvocationStatus, "FAILED")
    assert hasattr(RuntimeInvocationStatus, "TIMED_OUT")
    assert hasattr(RuntimeInvocationStatus, "CANCELLED")

    assert hasattr(ConversationRuntimeStatus, "NOT_STARTED")
    assert hasattr(ConversationRuntimeStatus, "RUNNING")
    assert hasattr(ConversationRuntimeStatus, "COMPLETED")
    assert hasattr(ConversationRuntimeStatus, "FAILED")
    assert hasattr(ConversationRuntimeStatus, "CANCELLED")

    execute_source = inspect.getsource(SubagentRuntime.execute)
    assert "status=" in execute_source
    assert '"completed"' in execute_source or "'completed'" in execute_source
    assert '"cancelled"' in execute_source or "'cancelled'" in execute_source


def test_agent_loop_has_stall_detection() -> None:
    supervisor_params = inspect.signature(RuntimeSupervisor.__init__).parameters

    assert "stall_warning_after_ms" in supervisor_params, (
        "RuntimeSupervisor should accept stall_warning_after_ms"
    )
    assert "stall_check_interval_ms" in supervisor_params, (
        "RuntimeSupervisor should accept stall_check_interval_ms"
    )
    assert "terminate_on_stall" in supervisor_params, (
        "RuntimeSupervisor should accept terminate_on_stall"
    )

    supervisor_source = inspect.getsource(RuntimeSupervisor.execute)
    assert "STALL_DETECTED" in supervisor_source, (
        "RuntimeSupervisor should emit STALL_DETECTED warning on stall"
    )

    budgets = AgentExecutionBudgets()
    assert budgets.agent_loop_max_total_runtime_seconds > 0, (
        "AgentExecutionBudgets should define max total runtime"
    )

    assert "budget_max_seconds" in SubagentMission.model_fields or hasattr(
        SubagentMission, "timeout_seconds"
    ), "SubagentMission should have budget_max_seconds field"


def test_tool_timeout_is_enforced() -> None:
    er_fields = ExecutionRequest.model_fields
    assert "timeout_ms" in er_fields, "ExecutionRequest should have timeout_ms field"
    timeout_field = er_fields["timeout_ms"]
    assert timeout_field.annotation is not None, (
        "ExecutionRequest.timeout_ms should have a type annotation"
    )
    budgets = AgentExecutionBudgets()
    assert budgets.tool_max_runtime_seconds > 0, (
        "AgentExecutionBudgets should define tool_max_runtime_seconds"
    )

    supervisor_source = inspect.getsource(RuntimeSupervisor.execute)
    assert "timeout_ms" in supervisor_source or "timeout_s" in supervisor_source, (
        "RuntimeSupervisor should enforce timeout during execution"
    )


def test_asyncio_primitives_are_not_used_for_os_thread_sync() -> None:
    agent_loop_source = inspect.getsource(AgentLoop.__init__)

    async_locks = re.findall(r"asyncio\.\w*(?:Lock|Semaphore)", agent_loop_source)
    threading_locks = re.findall(r"threading\.\w*(?:Lock|Semaphore)", agent_loop_source)

    assert threading_locks, (
        "AgentLoop init should use threading primitives for deferred init thread safety"
    )

    for lock_match in async_locks:
        for lineno, line in enumerate(agent_loop_source.splitlines(), 1):
            if lock_match in line:
                if "_approval_lock" in line:
                    break
                assert "_approval_lock" in line, (
                    f"Found non-approval async lock/semaphore {lock_match!r} at "
                    f"line {lineno} in AgentLoop init that may indicate "
                    f"thread boundary crossing: {line.strip()}"
                )
                break

    runtime_source = inspect.getsource(RuntimeSupervisor.__init__)
    assert "threading" not in runtime_source or "Lock" not in runtime_source, (
        "RuntimeSupervisor should not require threading primitives"
    )


def test_no_global_mutable_execution_state() -> None:
    core_dir = Path(__file__).parent.parent.parent / "rig_relay" / "core"

    mutable_globals: list[tuple[str, str, int]] = []
    for py_file in sorted(core_dir.rglob("*.py")):
        try:
            source = py_file.read_text()
        except Exception:
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            if re.match(
                r"^[a-z_][a-z0-9_]*\s*=\s*(\[\s*\]|\{\s*\}|dict\(|list\(|set\(|frozenset\(|set\(\))",
                line,
            ):
                varname = line.split("=")[0].strip()
                if varname.startswith("_"):
                    continue
                if varname in {"DEFAULT_CACHE_TTL", "BUILD_ROOT", "TOOL_MAPPER"}:
                    continue
                mutable_globals.append((str(py_file), varname, lineno))

    assert not mutable_globals, (
        f"Found {len(mutable_globals)} module-level mutable dict/list initializations "
        f"in core/: {mutable_globals[:10]}"
    )


def test_shared_state_models_are_pydantic_or_immutable() -> None:
    from pydantic import BaseModel

    def check_model(cls: type, name: str) -> None:
        assert issubclass(cls, BaseModel), (
            f"{name} must be a Pydantic BaseModel for shared state"
        )

    check_model(RuntimeToolExecutionResult, "RuntimeToolExecutionResult")
    check_model(SubagentMission, "SubagentMission")
    check_model(SubagentResult, "SubagentResult")
    check_model(ConversationTurnRuntime, "ConversationTurnRuntime")
    check_model(ToolRuntimeRequest, "ToolRuntimeRequest")
    check_model(ToolRuntimeResult, "ToolRuntimeResult")
    check_model(AgentRuntimeState, "AgentRuntimeState")
    check_model(AgentExecutionBudgets, "AgentExecutionBudgets")
    check_model(ExecutionRequest, "ExecutionRequest")
