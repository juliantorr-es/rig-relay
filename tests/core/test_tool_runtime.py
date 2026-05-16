"""Tests for ToolRuntime — governed tool execution boundary."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from pydantic import BaseModel
import pytest

from rig_relay.core.tool_runtime import ToolRuntime
from rig_relay.core.tool_runtime_models import (
    RefusalCode,
    ToolRuntimeApprovalStatus,
    ToolRuntimeCacheStatus,
    ToolRuntimeExecutionMode,
    ToolRuntimeRequest,
    ToolRuntimeStatus,
)

# ── Test doubles ────────────────────────────────────────────────────


class FakeToolResult(BaseModel):
    output: str = "success"
    count: int = 42


async def _fake_invoke_success(
    args_dict: dict[str, Any],
) -> AsyncGenerator[Any, None]:
    yield FakeToolResult(output="ok", count=1)


async def _fake_invoke_failure(
    args_dict: dict[str, Any],
) -> AsyncGenerator[Any, None]:
    raise RuntimeError("tool crashed")
    yield


async def _fake_invoke_no_result(
    args_dict: dict[str, Any],
) -> AsyncGenerator[Any, None]:
    if False:
        yield


def _cache_hit(
    tool_name: str, args_dict: dict[str, Any]
) -> tuple[bool, Any]:
    if args_dict.get("cached") is True:
        return True, FakeToolResult(output="from_cache")
    return False, None


def _cache_miss(
    tool_name: str, args_dict: dict[str, Any]
) -> tuple[bool, Any]:
    return False, None


async def _permission_denied_async(
    tool_name: str, args_dict: dict[str, Any], call_id: str
) -> tuple[bool, str]:
    return False, "not allowed"


async def _permission_allowed_async(
    tool_name: str, args_dict: dict[str, Any], call_id: str
) -> tuple[bool, str]:
    return True, ""


async def _approval_denied(
    tool_name: str, args_dict: dict[str, Any], call_id: str
) -> tuple[bool, str]:
    return False, "not today"


async def _approval_allowed(
    tool_name: str, args_dict: dict[str, Any], call_id: str
) -> tuple[bool, str]:
    return True, ""


# ── Helpers ──────────────────────────────────────────────────────────


def _make_runtime(**overrides: Any) -> ToolRuntime:
    kwargs: dict[str, Any] = dict(
        invoke_tool=_fake_invoke_success,
        cache_check=_cache_miss,
        cache_store=lambda t, a, r: None,
        permission_decision=_permission_allowed_async,
        approval_request=_approval_allowed,
        patch_gate_check=lambda tc, ti: None,
        expand_args=lambda a: a,
        receipt_build=lambda tn, rm: None,
        receipt_capture=lambda s, tn, r: None,
        context_observe=lambda *a, **kw: None,
        stats_delta=lambda k, d: None,
    )
    kwargs.update(overrides)
    return ToolRuntime(**kwargs)


def _request(**overrides: Any) -> ToolRuntimeRequest:
    kwargs: dict[str, Any] = dict(
        tool_name="fake_tool",
        tool_args={"arg1": "val1"},
        tool_call_id="call_1",
        execution_mode=ToolRuntimeExecutionMode.READ_ONLY,
    )
    kwargs.update(overrides)
    return ToolRuntimeRequest(**kwargs)


# ── Tests ────────────────────────────────────────────────────────────


class TestSuccessfulExecution:
    @pytest.mark.asyncio
    async def test_execute_one_returns_completed_on_success(self):
        runtime = _make_runtime()
        result = await runtime.execute_one(_request())
        assert result.status == ToolRuntimeStatus.COMPLETED
        assert result.tool_name == "fake_tool"
        assert result.provider_tool_response is not None

    @pytest.mark.asyncio
    async def test_completed_result_is_json_safe(self):
        import json

        runtime = _make_runtime()
        result = await runtime.execute_one(_request())
        json.dumps(result.to_debug_dict())


class TestCacheBehavior:
    @pytest.mark.asyncio
    async def test_cache_hit_bypasses_invocation(self):
        runtime = _make_runtime(cache_check=_cache_hit)
        result = await runtime.execute_one(
            _request(tool_args={"cached": True})
        )
        assert result.status == ToolRuntimeStatus.CACHED
        assert result.cache_status == ToolRuntimeCacheStatus.HIT
        assert result.cache_hit is True
        assert result.provider_tool_response.output == "from_cache"

    @pytest.mark.asyncio
    async def test_cache_miss_invokes_tool(self):
        runtime = _make_runtime(cache_check=_cache_miss)
        result = await runtime.execute_one(_request())
        assert result.status == ToolRuntimeStatus.COMPLETED
        assert result.cache_status == ToolRuntimeCacheStatus.MISS
        assert result.cache_hit is False


class TestPermissionDenied:
    @pytest.mark.asyncio
    async def test_permission_denied_returns_refused(self):
        runtime = _make_runtime(
            permission_decision=_permission_denied_async
        )
        result = await runtime.execute_one(_request())
        assert result.status == ToolRuntimeStatus.REFUSED
        assert result.refusal is not None
        assert (
            result.refusal.refusal_code == RefusalCode.TOOL_PERMISSION_DENIED
        )

    @pytest.mark.asyncio
    async def test_bypass_overrides_permission_denied(self):
        runtime = _make_runtime(
            permission_decision=_permission_denied_async
        )
        result = await runtime.execute_one(
            _request(bypass_permissions=True)
        )
        assert result.status == ToolRuntimeStatus.COMPLETED


class TestApprovalDenied:
    @pytest.mark.asyncio
    async def test_approval_denied_returns_refused(self):
        runtime = _make_runtime(approval_request=_approval_denied)
        result = await runtime.execute_one(_request())
        assert result.status == ToolRuntimeStatus.REFUSED
        assert result.refusal is not None
        assert result.refusal.refusal_code == RefusalCode.APPROVAL_DENIED
        assert result.approval_status == ToolRuntimeApprovalStatus.DENIED

    @pytest.mark.asyncio
    async def test_approval_allowed_proceeds(self):
        runtime = _make_runtime(approval_request=_approval_allowed)
        result = await runtime.execute_one(_request())
        assert result.status == ToolRuntimeStatus.COMPLETED
        assert (
            result.approval_status == ToolRuntimeApprovalStatus.APPROVED
        )


class TestToolFailure:
    @pytest.mark.asyncio
    async def test_tool_invocation_exception_returns_failed(self):
        runtime = _make_runtime(invoke_tool=_fake_invoke_failure)
        result = await runtime.execute_one(_request())
        assert result.status == ToolRuntimeStatus.FAILED
        assert result.error_kind == "tool_invocation_failed"
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_tool_no_result_returns_failed(self):
        runtime = _make_runtime(invoke_tool=_fake_invoke_no_result)
        result = await runtime.execute_one(_request())
        assert result.status == ToolRuntimeStatus.FAILED
        assert (
            "did not yield" in (result.error_message or "")
        )


class TestDebugSnapshot:
    @pytest.mark.asyncio
    async def test_debug_dict_contains_key_fields(self):
        runtime = _make_runtime()
        result = await runtime.execute_one(_request())
        d = result.to_debug_dict()
        assert d["status"] == "completed"
        assert d["tool_name"] == "fake_tool"
        assert "cache" in d
        assert "approval" in d


class TestArchitectureBoundaries:
    def test_no_forbidden_imports_in_tool_runtime(self):
        import ast
        from pathlib import Path

        forbidden = (
            "rig_relay.desktop",
            "rig_relay.ralph",
            "rig_relay.scripts",
            "rig_relay.analytics",
            "rig_relay.reports.query",
            "rig_relay.bash.query",
            "duckdb",
        )
        path = (
            Path(__file__).resolve().parent.parent.parent
            / "rig_relay"
            / "core"
            / "tool_runtime.py"
        )
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for f in forbidden:
                        assert not alias.name.startswith(
                            f
                        ), f"tool_runtime imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                for f in forbidden:
                    assert not node.module.startswith(
                        f
                    ), f"tool_runtime imports {node.module}"

    def test_no_forbidden_imports_in_models(self):
        import ast
        from pathlib import Path

        forbidden = (
            "rig_relay.desktop",
            "rig_relay.ralph",
            "rig_relay.scripts",
            "rig_relay.analytics",
            "rig_relay.reports.query",
            "rig_relay.bash.query",
            "duckdb",
        )
        path = (
            Path(__file__).resolve().parent.parent.parent
            / "rig_relay"
            / "core"
            / "tool_runtime_models.py"
        )
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for f in forbidden:
                        assert not alias.name.startswith(
                            f
                        ), f"models imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                for f in forbidden:
                    assert not node.module.startswith(
                        f
                    ), f"models imports {node.module}"
