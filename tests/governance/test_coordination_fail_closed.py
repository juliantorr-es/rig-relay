"""GO-7 fail-closed coordination tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from rig_relay.core.tools.base import BaseToolState, InvokeContext
from rig_relay.core.tools.builtins.write_file import (
    WriteFile,
    WriteFileArgs,
    WriteFileConfig,
    WriteFileResult,
)


async def collect_result(gen: AsyncGenerator) -> WriteFileResult:
    result = None
    async for item in gen:
        result = item
    return result


class TestWriteFileCoordinationGate:
    @pytest.mark.asyncio
    async def test_refuses_when_coordination_unavailable(self, tmp_path: Path) -> None:
        ctx = InvokeContext(tool_call_id="call-001")
        tool = WriteFile(config_getter=lambda: WriteFileConfig(), state=BaseToolState())
        result = await collect_result(
            tool.run(
                WriteFileArgs(path="out/test.txt", content="hello", overwrite=False),
                ctx=ctx,
            )
        )
        assert isinstance(result, WriteFileResult)
        assert result.status in ("blocked", "refused")

    @pytest.mark.asyncio
    async def test_refuses_when_ctx_none(self, tmp_path: Path) -> None:
        tool = WriteFile(config_getter=lambda: WriteFileConfig(), state=BaseToolState())
        result = await collect_result(
            tool.run(
                WriteFileArgs(path="out/test.txt", content="hello", overwrite=False),
                ctx=None,
            )
        )
        assert isinstance(result, WriteFileResult)
        assert result.status in ("blocked", "refused")
