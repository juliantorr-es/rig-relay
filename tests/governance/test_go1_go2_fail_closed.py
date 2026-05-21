from __future__ import annotations

from collections.abc import AsyncGenerator
import logging
from typing import Any, cast
from unittest.mock import MagicMock, patch

from pydantic import BaseModel
import pytest

from rig_relay.core.agent_loop import _COUNCIL_MUTATION_TOOLS, AgentLoop
from rig_relay.core.telemetry.tool_contract import ToolMutationClass
from rig_relay.core.tool_runtime_models import (
    RefusalCode,
    ToolRuntimeExecutionMode,
    ToolRuntimeRequest,
    ToolRuntimeStatus,
)
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
)
from rig_relay.core.types import ToolStreamEvent
from tests.conftest import build_test_vibe_config


class _ReadOnlyToolArgs(BaseModel):
    pass


class _ReadOnlyToolResult(BaseModel):
    pass


class _ReadOnlyToolState(BaseToolState):
    pass


class ReadOnlyTool(
    BaseTool[_ReadOnlyToolArgs, _ReadOnlyToolResult, BaseToolConfig, _ReadOnlyToolState]
):
    mutation_class = ToolMutationClass.READ_ONLY

    @classmethod
    def get_name(cls) -> str:
        return "readonly_tool"

    async def run(
        self, args: _ReadOnlyToolArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | _ReadOnlyToolResult, None]:
        yield _ReadOnlyToolResult()
        return  # pragma: no cover — never reached in these tests


class _MutationToolArgs(BaseModel):
    pass


class _MutationToolResult(BaseModel):
    pass


class _MutationToolState(BaseToolState):
    pass


class MutationTool(
    BaseTool[_MutationToolArgs, _MutationToolResult, BaseToolConfig, _MutationToolState]
):
    mutation_class = ToolMutationClass.MUTATES_GIT_STATE

    @classmethod
    def get_name(cls) -> str:
        return "mutation_tool"

    async def run(
        self, args: _MutationToolArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | _MutationToolResult, None]:
        yield _MutationToolResult()
        return  # pragma: no cover — never reached in these tests


def _build_agent_with_tools(
    *tool_classes: type[BaseTool],
    override_providers: list[Any] | None = None,
    approval_callback: Any = None,
) -> AgentLoop:
    """Build an AgentLoop with custom tool classes registered."""
    config = build_test_vibe_config()
    if override_providers is not None:
        config.providers = override_providers
    agent = AgentLoop(
        config=config, agent_name="default", defer_heavy_init=True, headless=True
    )
    for tc in tool_classes:
        agent.tool_manager._available[tc.get_name()] = tc
    if approval_callback is not None:
        agent.approval_callback = approval_callback
    return agent


def _make_mutation_request(
    tool_name: str = "mutation_tool", **kwargs: Any
) -> ToolRuntimeRequest:
    defaults: dict[str, Any] = {
        "tool_name": tool_name,
        "tool_call_id": "test-cid-1",
        "execution_mode": ToolRuntimeExecutionMode.MUTATION_EXECUTION,
        "session_id": "test-session",
        "turn_id": "test-turn",
    }
    defaults.update(kwargs)
    return ToolRuntimeRequest(**defaults)


def _make_readonly_request(
    tool_name: str = "readonly_tool", **kwargs: Any
) -> ToolRuntimeRequest:
    defaults: dict[str, Any] = {
        "tool_name": tool_name,
        "tool_call_id": "test-cid-2",
        "execution_mode": ToolRuntimeExecutionMode.READ_ONLY,
        "session_id": "test-session",
        "turn_id": "test-turn",
    }
    defaults.update(kwargs)
    return ToolRuntimeRequest(**defaults)


def _mock_council_tool_class() -> type[BaseTool]:
    tc = cast(type[BaseTool], MagicMock())
    name = next(iter(_COUNCIL_MUTATION_TOOLS))
    tc.__name__ = name  # type: ignore[attr-defined]
    return tc


# ────────────────────────────────────────────────────────────────
# GO-1: Permission / Approval / Patch Gate fail-closed
# ────────────────────────────────────────────────────────────────


class TestGO1PermissionFailClosed:
    @pytest.mark.asyncio
    async def test_permission_exception_returns_refusal_for_mutation(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When permission_decision's _should_execute_tool throws,
        mutation tools must receive (False, 'permission_unavailable').
        """
        agent = _build_agent_with_tools(MutationTool)
        rt = agent._get_tool_runtime()
        orig_get = agent.tool_manager.get

        def _failing_get(name: str) -> BaseTool:
            if name == "mutation_tool":
                raise RuntimeError("simulated governance crash")
            return orig_get(name)

        with patch.object(agent.tool_manager, "get", side_effect=_failing_get):
            permitted, reason = await rt._permission_decision(
                "mutation_tool", {}, "test-cid-1"
            )

        assert permitted is False, f"Expected refusal, got allowed. Reason: {reason}"
        assert reason == "permission_unavailable"

    @pytest.mark.asyncio
    async def test_permission_exception_allows_read_only(self) -> None:
        """When permission_decision throws, read-only tools should still be
        allowed so the agent can continue reading files.
        """
        agent = _build_agent_with_tools(ReadOnlyTool)
        rt = agent._get_tool_runtime()
        orig_get = agent.tool_manager.get

        def _failing_get(name: str) -> BaseTool:
            if name == "readonly_tool":
                raise RuntimeError("simulated governance crash")
            return orig_get(name)

        with patch.object(agent.tool_manager, "get", side_effect=_failing_get):
            permitted, reason = await rt._permission_decision(
                "readonly_tool", {}, "test-cid-2"
            )

        assert permitted is True, (
            f"Expected read-only tool allowed during degradation. Reason: {reason}"
        )

    @pytest.mark.asyncio
    async def test_permission_degraded_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Degraded permission_decision must emit a governance.degraded log line."""
        agent = _build_agent_with_tools(MutationTool)
        rt = agent._get_tool_runtime()
        agent.session_id = "sess-g1"
        agent._current_user_message_id = "turn-g1"

        def _failing_get(name: str) -> BaseTool:
            raise RuntimeError("governance down")

        with patch.object(agent.tool_manager, "get", side_effect=_failing_get):
            with caplog.at_level(logging.WARNING):
                await rt._permission_decision("mutation_tool", {}, "test-inv-id")

        assert any(
            "governance.degraded" in r.message
            and "permission_unavailable" in r.message
            and "sess-g1" in r.message
            and "turn-g1" in r.message
            and "test-inv-id" in r.message
            for r in caplog.records
        ), "Missing governance.degraded warning log"


class TestGO1ApprovalFailClosed:
    @pytest.mark.asyncio
    async def test_approval_exception_returns_refusal_for_mutation(self) -> None:
        """When approval_request throws, mutation tools must be refused."""

        async def _always_approve(*args: Any, **kwargs: Any) -> Any:
            return True, ""

        agent = _build_agent_with_tools(MutationTool, approval_callback=_always_approve)
        rt = agent._get_tool_runtime()
        orig_get = agent.tool_manager.get

        def _failing_get(name: str) -> BaseTool:
            if name == "mutation_tool":
                raise RuntimeError("simulated approval crash")
            return orig_get(name)

        with patch.object(agent.tool_manager, "get", side_effect=_failing_get):
            approved, reason = await rt._approval_request(
                "mutation_tool", {}, "test-cid-1"
            )

        assert approved is False, (
            f"Expected approval refusal, got allowed. Reason: {reason}"
        )
        assert reason == "approval_unavailable"

    @pytest.mark.asyncio
    async def test_approval_exception_allows_read_only(self) -> None:
        """When approval throws, read-only tools should still be allowed."""

        async def _always_approve(*args: Any, **kwargs: Any) -> Any:
            return True, ""

        agent = _build_agent_with_tools(ReadOnlyTool, approval_callback=_always_approve)
        rt = agent._get_tool_runtime()
        orig_get = agent.tool_manager.get

        def _failing_get(name: str) -> BaseTool:
            if name == "readonly_tool":
                raise RuntimeError("simulated approval crash")
            return orig_get(name)

        with patch.object(agent.tool_manager, "get", side_effect=_failing_get):
            approved, reason = await rt._approval_request(
                "readonly_tool", {}, "test-cid-2"
            )

        assert approved is True, f"Expected read-only tool allowed. Reason: {reason}"

    @pytest.mark.asyncio
    async def test_approval_no_callback_returns_true(self) -> None:
        """When approval_callback is None, approval always returns True
        (governance unavailable but no callback to enforce).
        """
        agent = _build_agent_with_tools(MutationTool, approval_callback=None)
        rt = agent._get_tool_runtime()
        result = await rt._approval_request("any_tool", {}, "any-cid")
        assert result == (True, "")


class TestGO1PatchGateFailClosed:
    def test_patch_gate_exception_returns_degraded_string(self) -> None:
        """When patch_gate_check's tool_manager.get throws, it must return
        'patch_gate_unavailable' (a truthy string) so the ToolRuntime
        sees a non-None result and refuses the mutation.
        """
        agent = _build_agent_with_tools(MutationTool)
        rt = agent._get_tool_runtime()

        request = _make_mutation_request()
        with patch.object(
            agent.tool_manager, "get", side_effect=RuntimeError("patch gate crash")
        ):
            gating = rt._patch_gate_check(request, None)

        assert gating is not None, "Expected non-None degraded gating result"
        assert gating == "patch_gate_unavailable", (
            f"Expected 'patch_gate_unavailable', got {gating!r}"
        )

    def test_patch_gate_none_ref_returns_none(self) -> None:
        """When tool_call_ref is None, patch_gate_check should return None
        (nothing to gate).
        """
        agent = _build_agent_with_tools()
        rt = agent._get_tool_runtime()
        gating = rt._patch_gate_check(None, None)
        assert gating is None


# ────────────────────────────────────────────────────────────────
# GO-2: Council consultation fail-closed
# ────────────────────────────────────────────────────────────────


class TestGO2CouncilFailClosed:
    @pytest.mark.asyncio
    async def test_tool_class_none_returns_review(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        agent = _build_agent_with_tools()
        agent.session_id = "sess-g2-1"

        with caplog.at_level(logging.WARNING):
            result = await agent._consult_council_before_mutation(
                "unknown_tool", {}, None
            )

        assert result == "REVIEW", f"Expected REVIEW, got {result}"
        assert any(
            "governance.degraded" in r.message and "council_unknown_tool" in r.message
            for r in caplog.records
        ), "Missing governance.degraded warning for unknown tool"

    @pytest.mark.asyncio
    async def test_non_mutation_tool_returns_allow(self) -> None:
        agent = _build_agent_with_tools(ReadOnlyTool)

        result = await agent._consult_council_before_mutation(
            "readonly_tool", {}, ReadOnlyTool
        )
        assert result == "ALLOW", f"Expected ALLOW for non-mutation tool, got {result}"

    @pytest.mark.asyncio
    async def test_gate_not_allowed_returns_block(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        agent = _build_agent_with_tools()
        agent.session_id = "sess-g2-gb"
        mock_tc = _mock_council_tool_class()

        mock_gate = MagicMock()
        mock_gate.is_allowed.return_value = (False, "council blocked by policy")

        with (
            patch(
                "rig_relay.governance.service_state.get_capability_gate",
                return_value=mock_gate,
            ),
            caplog.at_level(logging.WARNING),
        ):
            result = await agent._consult_council_before_mutation("bash", {}, mock_tc)

        assert result == "BLOCK", f"Expected BLOCK, got {result}"
        assert any(
            "governance.degraded" in r.message and "council_gate_blocked" in r.message
            for r in caplog.records
        ), "Missing warning for council gate blocked"

    @pytest.mark.asyncio
    async def test_gate_exception_returns_block(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        agent = _build_agent_with_tools()
        agent.session_id = "sess-g2-ge"
        mock_tc = _mock_council_tool_class()

        with (
            patch(
                "rig_relay.governance.service_state.get_capability_gate",
                side_effect=RuntimeError("gate engine unavailable"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            result = await agent._consult_council_before_mutation("bash", {}, mock_tc)

        assert result == "BLOCK", f"Expected BLOCK on gate exception, got {result}"
        assert any(
            "governance.degraded" in r.message
            and "council_gate_unavailable" in r.message
            for r in caplog.records
        ), "Missing warning for gate unavailable"

    @pytest.mark.asyncio
    async def test_single_provider_returns_review(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        agent = _build_agent_with_tools()
        agent.config.providers = [MagicMock(name="solo-provider")]
        agent.session_id = "sess-g2-sp"
        mock_tc = _mock_council_tool_class()

        mock_gate = MagicMock()
        mock_gate.is_allowed.return_value = (True, "")

        with (
            patch(
                "rig_relay.governance.service_state.get_capability_gate",
                return_value=mock_gate,
            ),
            caplog.at_level(logging.WARNING),
        ):
            result = await agent._consult_council_before_mutation("bash", {}, mock_tc)

        assert result == "REVIEW", f"Expected REVIEW for single provider, got {result}"
        assert any(
            "governance.degraded" in r.message
            and "council_single_provider" in r.message
            for r in caplog.records
        ), "Missing warning for single provider"

    @pytest.mark.asyncio
    async def test_consultation_exception_returns_review(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        agent = _build_agent_with_tools()
        agent.session_id = "sess-g2-cf"
        agent.config.providers = [
            MagicMock(name="provider-a"),
            MagicMock(name="provider-b"),
        ]
        mock_tc = _mock_council_tool_class()

        mock_gate = MagicMock()
        mock_gate.is_allowed.return_value = (True, "")

        with (
            patch(
                "rig_relay.governance.service_state.get_capability_gate",
                return_value=mock_gate,
            ),
            patch(
                "rig_relay.core.agent_loop.consult_council_before_mutation",
                side_effect=RuntimeError("council RPC timeout"),
                create=True,
            ),
            caplog.at_level(logging.WARNING),
        ):
            result = await agent._consult_council_before_mutation("bash", {}, mock_tc)

        assert result == "REVIEW", (
            f"Expected REVIEW on consultation failure, got {result}"
        )
        assert any(
            "governance.degraded" in r.message
            and "council_consultation_failed" in r.message
            for r in caplog.records
        ), "Missing warning for consultation failure"


# ────────────────────────────────────────────────────────────────
# Integration: tool execution with degraded governance
# ────────────────────────────────────────────────────────────────


class TestToolRuntimeIntegration:
    @pytest.mark.asyncio
    async def test_mutation_execution_refused_when_permission_degraded(self) -> None:
        agent = _build_agent_with_tools(MutationTool)
        rt = agent._get_tool_runtime()

        async def _fake_invoke(args: dict) -> AsyncGenerator[Any, None]:
            yield _MutationToolResult()
            return

        rt._invoke_tool = _fake_invoke  # type: ignore[assignment]

        async def _failing_permission(tn: str, ad: dict, cid: str) -> tuple[bool, str]:
            return False, "permission_unavailable"

        rt._permission_decision = _failing_permission  # type: ignore[assignment]

        request = _make_mutation_request()
        result = await rt.execute_one(request)

        assert result.status == ToolRuntimeStatus.REFUSED
        assert result.refusal is not None
        assert result.refusal.refusal_code == RefusalCode.TOOL_PERMISSION_DENIED

    @pytest.mark.asyncio
    async def test_read_only_execution_allowed_when_permission_degraded(self) -> None:
        agent = _build_agent_with_tools(ReadOnlyTool, MutationTool)
        rt = agent._get_tool_runtime()

        async def _fake_invoke(args: dict) -> AsyncGenerator[Any, None]:
            yield _ReadOnlyToolResult()
            return

        rt._invoke_tool = _fake_invoke  # type: ignore[assignment]

        async def _degraded_permission(tn: str, ad: dict, cid: str) -> tuple[bool, str]:
            if tn == "readonly_tool":
                return True, ""
            return False, "permission_unavailable"

        rt._permission_decision = _degraded_permission  # type: ignore[assignment]

        request = _make_readonly_request()
        result = await rt.execute_one(request)

        assert result.status in (
            ToolRuntimeStatus.COMPLETED,
            ToolRuntimeStatus.CACHED,
        ), f"Expected read-only tool to complete, got {result.status}"

    @pytest.mark.asyncio
    async def test_patch_gate_degraded_refuses_mutation(self) -> None:
        agent = _build_agent_with_tools(MutationTool)
        rt = agent._get_tool_runtime()

        async def _fake_invoke(args: dict) -> AsyncGenerator[Any, None]:
            yield _MutationToolResult()
            return

        rt._invoke_tool = _fake_invoke  # type: ignore[assignment]

        async def _allow_permission(tn: str, ad: dict, cid: str) -> tuple[bool, str]:
            return True, ""

        rt._permission_decision = _allow_permission  # type: ignore[assignment]

        async def _allow_approval(tn: str, ad: dict, cid: str) -> tuple[bool, str]:
            return True, ""

        rt._approval_request = _allow_approval  # type: ignore[assignment]

        rt._patch_gate_check = lambda tc, ti: "patch_gate_unavailable"

        request = _make_mutation_request()
        result = await rt.execute_one(request)

        assert result.status == ToolRuntimeStatus.REFUSED
        assert result.refusal is not None
        assert result.refusal.refusal_code == RefusalCode.PATCH_PROPOSAL_REQUIRED
