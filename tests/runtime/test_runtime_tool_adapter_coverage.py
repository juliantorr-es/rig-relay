"""Coverage tests for runtime tool adapter edge cases: non-match, unsupported tools, linkage fields.

Tests are isolated and never mutate files outside temp directories.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolIntent, RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionRunner,
    RuntimeToolExecutionStatus,
)

# ── Helpers (mirror test_runtime_tool_invocation_execution) ────────────


def _resolved_context(**overrides: object) -> RuntimeContext:
    kwargs: dict[str, object] = {
        "session_id": "sess-001",
        "task_id": "task-001",
        "lane_id": "lane-001",
        "workspace_id": "ws-001",
        "worktree_path": "/tmp/worktrees/ws-001",
        "repo_root": "/tmp/repo",
        "dirty_policy": "preserve_existing",
    }
    kwargs.update(overrides)
    return RuntimeContext(**kwargs)  # type: ignore[arg-type]


def _resolved(
    status: str = "resolved", **overrides: object
) -> RuntimeContextResolution:
    kwargs: dict[str, object] = {
        "status": status,
        "context": _resolved_context() if status == "resolved" else None,
    }
    if status == "blocked":
        kwargs["error_kind"] = "session_required"
        kwargs["refusal_reason"] = "session_id is required"
    kwargs.update(overrides)
    return RuntimeContextResolution(**kwargs)  # type: ignore[arg-type]


def _intent(
    tool_name: RuntimeToolName = RuntimeToolName.VALIDATE, **overrides: object
) -> RuntimeToolIntent:
    kwargs: dict[str, object] = {
        "intent_id": "intent-001",
        "tool_name": tool_name,
        "payload": {},
    }
    kwargs.update(overrides)
    return RuntimeToolIntent(**kwargs)  # type: ignore[arg-type]


def _make_repo(tmp_path: Path, name: str = "repo") -> Path:
    """Create a minimal git repo with a pyproject.toml at repo root."""
    repo = tmp_path / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'test'\nversion = '0.1.0'\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo, capture_output=True, check=True
    )
    return repo


# ── SearchReplace non-match status variants ────────────────────────────


class TestSearchReplaceNonMatch:
    """Tests for search_replace non-match status variants through the adapter."""

    @pytest.mark.asyncio
    async def test_no_match_returns_completed(self, tmp_path: Path) -> None:
        """Search text not found returns COMPLETED with tool_status='no_match'."""
        target = tmp_path / "test.py"
        target.write_text("original\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": (
                    "<<<<<<< SEARCH\nnonexistent_text_xyz\n=======\nreplacement\n>>>>>>> REPLACE"
                ),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_status == "no_match"
        assert target.read_text(encoding="utf-8") == "original\n"

    @pytest.mark.asyncio
    async def test_ambiguous_match_returns_completed(self, tmp_path: Path) -> None:
        """Duplicate SEARCH text with allow_multiple=False returns COMPLETED."""
        target = tmp_path / "test.py"
        target.write_text("repeat\nother\nrepeat\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": (
                    "<<<<<<< SEARCH\nrepeat\n=======\nchanged\n>>>>>>> REPLACE"
                ),
                "allow_multiple": False,
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_status == "ambiguous_match"

    @pytest.mark.asyncio
    async def test_count_mismatch_returns_completed(self, tmp_path: Path) -> None:
        """expected_replacements mismatch returns COMPLETED with count_mismatch."""
        target = tmp_path / "test.py"
        target.write_text("hello\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": ("<<<<<<< SEARCH\nhello\n=======\nworld\n>>>>>>> REPLACE"),
                "expected_replacements": 3,
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_status == "count_mismatch"


# ── SearchReplace unsupported tool routing ─────────────────────────────


class TestSearchReplaceUnsupportedTool:
    """Tests that execute_search_replace refuses non-search_replace tools."""

    @pytest.mark.asyncio
    async def test_write_file_refused(self) -> None:
        """write_file through search_replace returns REFUSED with unsupported_tool."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.WRITE_FILE)
        resolution = _resolved()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"
        assert "write_file" in (result.refusal_reason or "")

    @pytest.mark.asyncio
    async def test_validate_refused(self) -> None:
        """validate through search_replace returns REFUSED with unsupported_tool."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.VALIDATE)
        resolution = _resolved()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"
        assert "validate" in (result.refusal_reason or "")

    @pytest.mark.asyncio
    async def test_bash_legacy_refused(self) -> None:
        """bash_legacy through search_replace returns REFUSED with unsupported_tool."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.BASH_LEGACY)
        resolution = _resolved()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"
        assert "bash_legacy" in (result.refusal_reason or "")


# ── Validate unsupported tool routing ──────────────────────────────────


class TestValidateUnsupportedTool:
    """Tests that execute_validate refuses non-validate tools."""

    @pytest.mark.asyncio
    async def test_bash_legacy_refused(self) -> None:
        """bash_legacy through validate returns REFUSED with unsupported_tool."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.BASH_LEGACY)
        resolution = _resolved()
        result = await runner.execute_validate(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"
        assert "bash_legacy" in (result.refusal_reason or "")


# ── Linkage field population ───────────────────────────────────────────


class TestLinkageFields:
    """Tests that linkage fields (intent_id, tool_name, invocation_id) are populated."""

    @pytest.mark.asyncio
    async def test_validate_linkage_fields_populated(self, tmp_path: Path) -> None:
        """Completed validate populates intent_id, tool_name, invocation_id."""
        repo = _make_repo(tmp_path)
        ctx = _resolved_context(worktree_path=str(repo), repo_root=str(repo))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_validate(intent, resolution)
        assert result.intent_id == "intent-001"
        assert result.tool_name == "validate"
        assert result.invocation_id is not None
        assert len(result.invocation_id) > 0

    @pytest.mark.asyncio
    async def test_search_replace_linkage_fields_populated(
        self, tmp_path: Path
    ) -> None:
        """Completed search_replace populates intent_id, tool_name, invocation_id."""
        target = tmp_path / "test.py"
        target.write_text("abc\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": ("<<<<<<< SEARCH\nabc\n=======\ndef\n>>>>>>> REPLACE"),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.intent_id == "intent-001"
        assert result.tool_name == "search_replace"
        assert result.invocation_id is not None
        assert len(result.invocation_id) > 0
