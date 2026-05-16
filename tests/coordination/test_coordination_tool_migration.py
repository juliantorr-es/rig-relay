from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.coordination.tool import execute_coordination_action
from rig_relay.core.tools.base import BaseToolState, InvokeContext
from rig_relay.core.tools.builtins.coordination import (
    Coordination,
    CoordinationArgs,
    CoordinationToolConfig,
)
from tests.mock.utils import collect_result


def test_relay_native_tool_executor_imports(tmp_path: Path) -> None:
    result = execute_coordination_action(
        store_root=tmp_path / "coordination",
        action_data={
            "action": "register_session",
            "session_id": "session-a",
            "status": "active",
        },
    )
    assert result.action == "register_session"
    assert result.response["session_id"] == "session-a"


@pytest.fixture
def tool(tmp_path: Path) -> Coordination:
    return Coordination(
        config_getter=lambda: CoordinationToolConfig(
            store_root=tmp_path / "coordination"
        ),
        state=BaseToolState(),
    )


@pytest.mark.asyncio
async def test_legacy_coordination_tool_runs(
    tool: Coordination, tmp_path: Path
) -> None:
    result = await collect_result(
        tool.run(
            CoordinationArgs(
                action="claim_task",
                session_id="session-a",
                task_id="task-a",
                claim_kind="implementation",
                ttl_seconds=120,
                scope={"allowed_paths": ["vibe/core/tools/builtins/task.py"]},
            ),
            InvokeContext(tool_call_id="tool-call", session_dir=tmp_path),
        )
    )

    payload = result.response
    assert payload["allowed"] is True
    assert payload["claim"]["task_id"] == "task-a"


@pytest.mark.asyncio
async def test_legacy_coordination_tool_preserves_event_shape(
    tool: Coordination, tmp_path: Path
) -> None:
    await collect_result(
        tool.run(
            CoordinationArgs(
                action="reserve_paths",
                session_id="session-a",
                task_id="task-a",
                mode="write",
                paths=["vibe/core/tools/builtins/task.py"],
                ttl_seconds=120,
            ),
            InvokeContext(tool_call_id="tool-call", session_dir=tmp_path),
        )
    )

    events_path = tmp_path / "coordination" / "events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["event_name"] == "coord.path.reserved"
    assert events[-1]["event_hash"].startswith("sha256:")
    assert "payload" in events[-1]
