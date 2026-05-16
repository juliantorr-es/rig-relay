from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.core.tools.base import BaseToolState, InvokeContext
from rig_relay.core.tools.builtins.coordination import (
    Coordination,
    CoordinationArgs,
    CoordinationToolConfig,
)
from tests.mock.utils import collect_result


@pytest.fixture
def tool(tmp_path: Path) -> Coordination:
    return Coordination(
        config_getter=lambda: CoordinationToolConfig(
            store_root=tmp_path / "coordination"
        ),
        state=BaseToolState(),
    )


@pytest.mark.asyncio
async def test_claim_task_and_publish_artifact(
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
async def test_reserve_paths_and_read_projection(
    tool: Coordination, tmp_path: Path
) -> None:
    claim = await collect_result(
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
    assert claim.response["allowed"] is True

    projection = await collect_result(
        tool.run(
            CoordinationArgs(action="read_state_projection"),
            InvokeContext(tool_call_id="tool-call", session_dir=tmp_path),
        )
    )
    payload = projection.response
    assert payload["active_path_reservations"]
