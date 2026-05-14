from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.governance.mission_envelope import MissionEnvelope
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


def _mission_envelope() -> MissionEnvelope:
    return MissionEnvelope.model_validate({
        "schema_version": "rig.mission_envelope.v1",
        "mission_id": "mission-2026-05-14-session-finalize",
        "title": "Finalize session with mission linkage",
        "created_at": "2026-05-14T12:00:00+00:00",
        "repo_root": "/Users/user/Developer/GitHub/rig-relay",
        "branch": "main",
        "head": "61b46b8",
        "dirty_summary": {
            "tracked_modified_count": 0,
            "untracked_count": 0,
            "protected_dirty_count": 0,
        },
        "allowed_paths": [],
        "protected_paths": [],
        "instruction_paths": [],
        "acceptance_checks": [],
        "handoff_required": True,
    })


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
                mission_envelope=_mission_envelope(),
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
    assert result.receipt_path is not None
