from __future__ import annotations

from pathlib import Path

import pytest

from tests.mock.utils import collect_result
from vibe.core.tools.base import BaseToolState, InvokeContext
from vibe.core.tools.builtins.session_lifecycle import (
    SessionFinalizeArgs,
    SessionLifecycleFinalize,
    SessionLifecycleFinalizeConfig,
)


@pytest.fixture
def tool(tmp_path: Path) -> SessionLifecycleFinalize:
    return SessionLifecycleFinalize(
        config_getter=lambda: SessionLifecycleFinalizeConfig(), state=BaseToolState()
    )


@pytest.mark.asyncio
async def test_finalize_tool_returns_structured_result(
    tool: SessionLifecycleFinalize, tmp_path: Path
) -> None:
    session_root = tmp_path / ".rig" / "sessions" / "session-tool"
    session_root.mkdir(parents=True, exist_ok=True)
    (session_root / "intent_events.jsonl").write_text(
        '{"ok": true}\n', encoding="utf-8"
    )
    result = await collect_result(
        tool.run(
            SessionFinalizeArgs(
                session_id="session-tool",
                sessions_root=session_root,
                allow_compaction=True,
                allow_prune=False,
                write_receipt=True,
            ),
            InvokeContext(tool_call_id="tool-call", session_dir=session_root),
        )
    )
    assert result.session_id == "session-tool"
    assert result.scanned_files >= 1
    assert result.receipt_path is not None
    assert result.status in {"ok", "partial", "refused"}
