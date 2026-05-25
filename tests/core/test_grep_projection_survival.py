from __future__ import annotations

import pytest

from rig_relay.core.telemetry.tool_contract import ToolMutationClass
from rig_relay.core.tool_runtime_models import ToolRuntimeResult, ToolRuntimeStatus
from rig_relay.core.tools._agent_outcome import derive_agent_outcome
from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.grep import Grep, GrepArgs, GrepToolConfig


@pytest.mark.asyncio
async def test_grep_no_match_survives_projection(tmp_path, monkeypatch):
    """grep no_match: error_kind=None, valid result survives agent outcome projection."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test.py").write_text("x = 1\n")

    tool = Grep(config_getter=lambda: GrepToolConfig(), state=BaseToolState())
    result = None
    async for r in tool.run(GrepArgs(pattern="nomatch", path="."), ctx=None):
        result = r
    assert result is not None
    assert result.match_count == 0
    assert result.error_kind is None  # no_match is NOT an error

    # Verify it survives projection
    runtime_result = ToolRuntimeResult(
        status=ToolRuntimeStatus.COMPLETED,
        tool_name="grep",
        tool_call_id="test_grep_proj",
        provider_tool_response=result,
    )
    outcome = derive_agent_outcome(runtime_result, ToolMutationClass.READ_ONLY)
    assert outcome.status == "completed"
    # error_kind from the tool result should be None (no_match)
    assert outcome.error_kind is None


@pytest.mark.asyncio
async def test_grep_invalid_pattern_survives_projection(tmp_path, monkeypatch):
    """grep invalid pattern: error_kind survives projection."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test.py").write_text("x = 1\n")

    tool = Grep(config_getter=lambda: GrepToolConfig(), state=BaseToolState())
    result = None
    async for r in tool.run(GrepArgs(pattern="", path="."), ctx=None):
        result = r
    assert result is not None
    assert result.error_kind == "invalid_pattern"

    runtime_result = ToolRuntimeResult(
        status=ToolRuntimeStatus.FAILED,
        tool_name="grep",
        tool_call_id="test_grep_inv",
        error_kind=result.error_kind,
        provider_tool_response=result,
    )
    outcome = derive_agent_outcome(runtime_result, ToolMutationClass.READ_ONLY)
    assert outcome.error_kind == "invalid_pattern"
