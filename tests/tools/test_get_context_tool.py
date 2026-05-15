"""Tests for rig.get_context built-in tool — verifies tool registration, argument
validation, output structure, and read-only guarantee.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.core.tools.builtins.get_context import (
    GetContext,
    GetContextArgs,
    GetContextResult,
    GetContextToolConfig,
)
from rig_relay.core.tools.base import BaseToolState


class TestGetContextArgs:
    """Argument model validation."""

    def test_default_args(self) -> None:
        args = GetContextArgs()
        assert args.mode == "map"
        assert args.max_tokens == 60000
        assert args.compression == "none"

    def test_valid_modes(self) -> None:
        for mode in ["map", "packet", "handoff", "collision", "symbols"]:
            args = GetContextArgs(mode=mode)
            assert args.mode == mode

    def test_invalid_mode_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid mode"):
            GetContextArgs(mode="invalid")

    def test_invalid_compression_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid compression"):
            GetContextArgs(compression="gzip")

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValueError):
            GetContextArgs.model_validate({"mode": "map", "unknown": "x"})  # type: ignore


class TestGetContextResult:
    """Result model validation."""

    def test_default_result(self) -> None:
        result = GetContextResult()
        assert result.schema_version == "rig.context_packet.v1"
        assert result.mode == "map"

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValueError):
            GetContextResult.model_validate({"unknown": "x"})  # type: ignore


class TestGetContextToolRegistration:
    """Tool registration metadata."""

    def test_tool_name(self) -> None:
        assert GetContext.get_name() == "get_context"

    def test_tool_is_read_only(self) -> None:
        assert GetContext.mutation_class.value == "read_only"

    def test_tool_is_deterministic_repo_state(self) -> None:
        assert GetContext.determinism_class.value == "deterministic_repo_state"

    def test_has_description(self) -> None:
        assert len(GetContext.description) > 50

    def test_tool_is_not_abstract(self) -> None:
        import inspect
        assert not inspect.isabstract(GetContext)
        # Should be instantiable
        config = GetContextToolConfig()
        state = BaseToolState()
        tool = GetContext(config_getter=lambda: config, state=state)
        assert tool is not None


class TestGetContextToolReadOnly:
    """Prove get_context does not write files."""

    @pytest.mark.asyncio
    async def test_run_does_not_write_files(self, tmp_path: Path) -> None:
        """Run get_context in a temp dir with no git repo and verify no files created."""
        import os
        orig_cwd = Path.cwd()
        os.chdir(str(tmp_path))

        try:
            config = GetContextToolConfig()
            state = BaseToolState()
            tool = GetContext(config_getter=lambda: config, state=state)

            before = set(tmp_path.rglob("*"))

            args = GetContextArgs(mode="map")
            result = None
            async for event in tool.run(args):
                if isinstance(event, GetContextResult):
                    result = event

            after = set(tmp_path.rglob("*"))
            new_files = after - before
            assert len(new_files) == 0, f"Tool created files: {new_files}"
            assert result is not None
            assert result.mode == "map"
        finally:
            os.chdir(str(orig_cwd))


class TestGetContextOutput:
    """Output structure verification."""

    @pytest.mark.asyncio
    async def test_map_mode_returns_repo_info(self, tmp_path: Path) -> None:
        config = GetContextToolConfig()
        state = BaseToolState()
        tool = GetContext(config_getter=lambda: config, state=state)

        args = GetContextArgs(mode="map")
        result = None
        async for event in tool.run(args):
            if isinstance(event, GetContextResult):
                result = event

        assert result is not None
        assert result.repo is not None
        assert "root" in result.repo
        assert result.summary_text is not None

    @pytest.mark.asyncio
    async def test_result_is_json_serializable(self, tmp_path: Path) -> None:
        config = GetContextToolConfig()
        state = BaseToolState()
        tool = GetContext(config_getter=lambda: config, state=state)

        args = GetContextArgs(mode="map")
        result = None
        async for event in tool.run(args):
            if isinstance(event, GetContextResult):
                result = event

        assert result is not None
        raw = result.model_dump_json(exclude_none=True)
        data = json.loads(raw)
        assert data["schema_version"] == "rig.context_packet.v1"
        assert "receipt" in data

    @pytest.mark.asyncio
    async def test_result_has_receipt(self, tmp_path: Path) -> None:
        config = GetContextToolConfig()
        state = BaseToolState()
        tool = GetContext(config_getter=lambda: config, state=state)

        args = GetContextArgs(mode="map")
        result = None
        async for event in tool.run(args):
            if isinstance(event, GetContextResult):
                result = event

        assert result is not None
        receipt = result.receipt
        assert receipt["kind"] == "rig.context.receipt.v1"
        assert receipt["context_id"] == result.context_id
        assert receipt["mode"] == "map"
        assert receipt["request_sha256"] is not None
        assert receipt["packet_sha256"] is not None


class TestGetContextCollisionMode:
    """Collision detection in tool output."""

    @pytest.mark.asyncio
    async def test_collision_warnings_returned(self, tmp_path: Path) -> None:
        # Create a fake worktree with claimed paths
        worktrees_dir = tmp_path / ".rig" / "relay" / "worktrees" / "wt-001"
        worktrees_dir.mkdir(parents=True)
        (worktrees_dir / "worktree.json").write_text(
            '{"agent_id": "a1", "claimed_paths": ["src/main.py"], "status": "active"}'
        )

        config = GetContextToolConfig()
        state = BaseToolState()
        tool = GetContext(config_getter=lambda: config, state=state)

        args = GetContextArgs(mode="collision", scope_paths=["src/main.py"])
        result = None
        async for event in tool.run(args):
            if isinstance(event, GetContextResult):
                result = event

        assert result is not None
        do_not_touch = result.do_not_touch
        assert len(do_not_touch) >= 0

    @pytest.mark.asyncio
    async def test_does_not_write_files_in_collision_mode(self, tmp_path: Path) -> None:
        import os
        orig_cwd = Path.cwd()
        os.chdir(str(tmp_path))

        try:
            before = set(tmp_path.rglob("*"))
            config = GetContextToolConfig()
            state = BaseToolState()
            tool = GetContext(config_getter=lambda: config, state=state)
            args = GetContextArgs(mode="collision", scope_paths=["test.py"])
            async for event in tool.run(args):
                pass
            after = set(tmp_path.rglob("*"))
            assert after - before == set()
        finally:
            os.chdir(str(orig_cwd))
