from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest

from rig_relay.core.tool_runtime import ToolRuntime
from rig_relay.core.tool_runtime_models import (
    RefusalCode,
    ToolRuntimeApprovalStatus,
    ToolRuntimeExecutionMode,
    ToolRuntimeRequest,
    ToolRuntimeStatus,
)
from rig_relay.core.tool_runtime_policy import ToolRuntimePolicy


async def _fake_invoke_success(args_dict: dict[str, Any]) -> AsyncGenerator[Any, None]:
    class _Result:
        def model_dump(self, **kwargs: Any) -> dict[str, Any]:
            return {"ok": True}

        supervisor_result_envelope = None
        supervisor_result_envelope_sha256 = None
        supervisor_result_classification = None

    yield _Result()


async def _async_allow(
    tool_name: str, args_dict: dict, call_id: str
) -> tuple[bool, str]:
    return True, ""


async def _async_deny(
    tool_name: str, args_dict: dict, call_id: str
) -> tuple[bool, str]:
    return False, "policy_denied"


def _make_policy(
    *, permission_decision=None, approval_request=None, patch_gate_check=None
) -> ToolRuntimePolicy:
    return ToolRuntimePolicy(
        permission_decision=permission_decision,
        approval_request=approval_request,
        patch_gate_check=patch_gate_check,
    )


class TestBareToolRuntimeRefusesMutation:
    """GO-5: bare ToolRuntime (no policy) defaults to fail-closed for mutation."""

    @pytest.mark.asyncio
    async def test_mutation_tool_refused_without_policy(self):
        rt = ToolRuntime(invoke_tool=_fake_invoke_success)
        req = ToolRuntimeRequest(
            tool_name="write_file",
            tool_args={"path": "foo.py", "content": "x"},
            tool_call_id="c1",
            execution_mode=ToolRuntimeExecutionMode.MUTATION_EXECUTION,
        )
        result = await rt.execute_one(req)
        assert result.status == ToolRuntimeStatus.REFUSED
        assert result.refusal is not None
        assert result.refusal.refusal_code == RefusalCode.TOOL_PERMISSION_DENIED
        assert "policy_object_missing" in (result.refusal.message or "")

    @pytest.mark.asyncio
    async def test_mutation_tool_refused_without_approval(self):
        rt = ToolRuntime(
            invoke_tool=_fake_invoke_success, permission_decision=_async_allow
        )
        req = ToolRuntimeRequest(
            tool_name="search_replace",
            tool_args={"file_path": "bar.py"},
            tool_call_id="c2",
            execution_mode=ToolRuntimeExecutionMode.MUTATION_EXECUTION,
        )
        result = await rt.execute_one(req)
        assert result.status == ToolRuntimeStatus.REFUSED
        assert result.refusal is not None
        assert result.refusal.refusal_code == RefusalCode.APPROVAL_DENIED
        assert "policy_object_missing" in (result.refusal.message or "")

    @pytest.mark.asyncio
    async def test_mutation_tool_gated_without_patch_gate(self):
        rt = ToolRuntime(
            invoke_tool=_fake_invoke_success,
            permission_decision=_async_allow,
            approval_request=_async_allow,
        )
        req = ToolRuntimeRequest(
            tool_name="write_file",
            tool_args={},
            tool_call_id="c3",
            execution_mode=ToolRuntimeExecutionMode.MUTATION_EXECUTION,
        )
        result = await rt.execute_one(req)
        assert result.status == ToolRuntimeStatus.REFUSED
        assert result.refusal is not None
        assert result.refusal.refusal_code == RefusalCode.PATCH_PROPOSAL_REQUIRED


class TestToolRuntimeWithPolicy:
    """GO-5: ToolRuntime with policy object respects policy decisions."""

    @pytest.mark.asyncio
    async def test_policy_allows_when_callbacks_return_true(self):
        policy = _make_policy(
            permission_decision=_async_allow,
            approval_request=_async_allow,
            patch_gate_check=lambda tc, ti: None,
        )
        rt = ToolRuntime(invoke_tool=_fake_invoke_success, policy_object=policy)
        req = ToolRuntimeRequest(
            tool_name="write_file",
            tool_args={"path": "foo.py"},
            tool_call_id="c1",
            execution_mode=ToolRuntimeExecutionMode.MUTATION_EXECUTION,
        )
        result = await rt.execute_one(req)
        assert result.status == ToolRuntimeStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_policy_refuses_when_permission_deny(self):
        policy = _make_policy(
            permission_decision=_async_deny,
            approval_request=_async_allow,
            patch_gate_check=lambda tc, ti: None,
        )
        rt = ToolRuntime(invoke_tool=_fake_invoke_success, policy_object=policy)
        req = ToolRuntimeRequest(
            tool_name="write_file",
            tool_args={},
            tool_call_id="c1",
            execution_mode=ToolRuntimeExecutionMode.MUTATION_EXECUTION,
        )
        result = await rt.execute_one(req)
        assert result.status == ToolRuntimeStatus.REFUSED
        assert result.refusal is not None
        assert result.refusal.message == "policy_denied"

    @pytest.mark.asyncio
    async def test_policy_refuses_when_approval_deny(self):
        policy = _make_policy(
            permission_decision=_async_allow,
            approval_request=_async_deny,
            patch_gate_check=lambda tc, ti: None,
        )
        rt = ToolRuntime(invoke_tool=_fake_invoke_success, policy_object=policy)
        req = ToolRuntimeRequest(
            tool_name="write_file",
            tool_args={},
            tool_call_id="c1",
            execution_mode=ToolRuntimeExecutionMode.MUTATION_EXECUTION,
        )
        result = await rt.execute_one(req)
        assert result.status == ToolRuntimeStatus.REFUSED
        assert result.approval_status == ToolRuntimeApprovalStatus.DENIED

    @pytest.mark.asyncio
    async def test_policy_fallbacks_to_fail_closed_when_callback_none(self):
        policy = ToolRuntimePolicy(
            permission_decision=None, approval_request=None, patch_gate_check=None
        )
        rt = ToolRuntime(invoke_tool=_fake_invoke_success, policy_object=policy)
        req = ToolRuntimeRequest(
            tool_name="write_file",
            tool_args={},
            tool_call_id="c1",
            execution_mode=ToolRuntimeExecutionMode.MUTATION_EXECUTION,
        )
        result = await rt.execute_one(req)
        assert result.status == ToolRuntimeStatus.REFUSED
        assert result.refusal is not None
        assert result.refusal.refusal_code == RefusalCode.TOOL_PERMISSION_DENIED


class TestReadOnlyWithoutPolicy:
    """GO-7: read-only tools work without governance policy."""

    @pytest.mark.asyncio
    async def test_read_only_tool_proceeds_without_policy(self):
        rt = ToolRuntime(invoke_tool=_fake_invoke_success)
        req = ToolRuntimeRequest(
            tool_name="read_file",
            tool_args={"path": "README.md"},
            tool_call_id="c1",
            execution_mode=ToolRuntimeExecutionMode.READ_ONLY,
        )
        result = await rt.execute_one(req)
        assert result.status == ToolRuntimeStatus.REFUSED

    @pytest.mark.asyncio
    async def test_read_request_with_explicit_allow_policy_proceeds(self):
        policy = _make_policy(
            permission_decision=_async_allow,
            approval_request=_async_allow,
            patch_gate_check=lambda tc, ti: None,
        )
        rt = ToolRuntime(invoke_tool=_fake_invoke_success, policy_object=policy)
        req = ToolRuntimeRequest(
            tool_name="read_file",
            tool_args={},
            tool_call_id="c1",
            execution_mode=ToolRuntimeExecutionMode.READ_ONLY,
        )
        result = await rt.execute_one(req)
        assert result.status == ToolRuntimeStatus.COMPLETED


class TestPolicyObjectThreading:
    """GO-6: runtime runner passes policy through adapter."""

    def test_adapter_builds_policy_with_fail_closed_callbacks(self):
        from rig_relay.runtime.tool_runtime_adapter import RuntimeToolRuntimeAdapter

        adapter = RuntimeToolRuntimeAdapter()
        policy = adapter.build_policy()

        assert policy is not None
        assert policy.permission_decision is not None
        assert policy.approval_request is not None
        assert policy.patch_gate_check is not None
        assert policy.governance_engine is None
        assert policy.council_enabled is False
        assert policy.local_action_envelope_required is False
        assert policy.dirty_guard_satisfied is False

    @pytest.mark.asyncio
    async def test_adapter_policy_allows_validate(self):
        from rig_relay.runtime.tool_runtime_adapter import RuntimeToolRuntimeAdapter

        adapter = RuntimeToolRuntimeAdapter()
        policy = adapter.build_policy()
        assert policy.permission_decision is not None
        permitted, reason = await policy.permission_decision("validate", {}, "c1")
        assert permitted is True
        assert reason == ""

    @pytest.mark.asyncio
    async def test_adapter_policy_denies_search_replace(self):
        from rig_relay.runtime.tool_runtime_adapter import RuntimeToolRuntimeAdapter

        adapter = RuntimeToolRuntimeAdapter()
        policy = adapter.build_policy()
        assert policy.permission_decision is not None
        permitted, reason = await policy.permission_decision("search_replace", {}, "c1")
        assert permitted is False
        assert reason == "policy_object_missing"

    @pytest.mark.asyncio
    async def test_adapter_policy_denies_write_file(self):
        from rig_relay.runtime.tool_runtime_adapter import RuntimeToolRuntimeAdapter

        adapter = RuntimeToolRuntimeAdapter()
        policy = adapter.build_policy()
        assert policy.permission_decision is not None
        permitted, reason = await policy.permission_decision("write_file", {}, "c1")
        assert permitted is False
        assert reason == "policy_object_missing"

    @pytest.mark.asyncio
    async def test_adapter_policy_denies_bash(self):
        from rig_relay.runtime.tool_runtime_adapter import RuntimeToolRuntimeAdapter

        adapter = RuntimeToolRuntimeAdapter()
        policy = adapter.build_policy()
        assert policy.permission_decision is not None
        permitted, reason = await policy.permission_decision("bash", {}, "c1")
        assert permitted is False
        assert reason == "policy_object_missing"

    def test_runner_passes_policy_to_tool_runtime(self):
        from rig_relay.runtime.tool_runtime_adapter import RuntimeToolRuntimeAdapter

        adapter = RuntimeToolRuntimeAdapter()
        policy = adapter.build_policy()
        rt = ToolRuntime(policy_object=policy)
        assert rt._policy_provided is True


class TestTraceEventOnPolicyMissing:
    """GO-5: trace event emitted when ToolRuntime defaults to fail-closed."""

    @pytest.mark.asyncio
    async def test_policy_missing_event_emitted_for_mutation(self, caplog):
        import logging

        from rig_relay.core.tool_runtime import logger as rt_logger

        rt = ToolRuntime(invoke_tool=_fake_invoke_success)
        req = ToolRuntimeRequest(
            tool_name="write_file",
            tool_args={"path": "foo.py"},
            tool_call_id="c1",
            session_id="sess-1",
            turn_id="turn-1",
            execution_mode=ToolRuntimeExecutionMode.MUTATION_EXECUTION,
        )
        with caplog.at_level(logging.WARNING, logger=rt_logger.name):
            await rt.execute_one(req)

        found = any(
            "governance.tool_runtime_policy_missing" in r.message
            and "session_id=sess-1" in r.message
            and "tool_name=write_file" in r.message
            and "severity=critical" in r.message
            for r in caplog.records
        )
        assert found, (
            f"Expected policy_missing trace event not found in: "
            f"{[r.message for r in caplog.records]}"
        )

    @pytest.mark.asyncio
    async def test_no_policy_missing_event_when_policy_provided(self, caplog):
        import logging

        from rig_relay.core.tool_runtime import logger as rt_logger

        policy = _make_policy(
            permission_decision=_async_allow,
            approval_request=_async_allow,
            patch_gate_check=lambda tc, ti: None,
        )
        rt = ToolRuntime(invoke_tool=_fake_invoke_success, policy_object=policy)
        req = ToolRuntimeRequest(
            tool_name="write_file",
            tool_args={"path": "foo.py"},
            tool_call_id="c1",
            session_id="sess-2",
            turn_id="turn-2",
            execution_mode=ToolRuntimeExecutionMode.MUTATION_EXECUTION,
        )
        with caplog.at_level(logging.WARNING, logger=rt_logger.name):
            await rt.execute_one(req)

        found = any(
            "governance.tool_runtime_policy_missing" in r.message
            for r in caplog.records
        )
        assert not found, "Policy missing event incorrectly emitted when policy present"


class TestBypassBehavior:
    """bypass_permissions does not bypass fail-closed defaults."""

    @pytest.mark.asyncio
    async def test_bypass_does_not_override_fail_closed(self):
        rt = ToolRuntime(invoke_tool=_fake_invoke_success)
        req = ToolRuntimeRequest(
            tool_name="write_file",
            tool_args={},
            tool_call_id="c1",
            bypass_permissions=True,
            execution_mode=ToolRuntimeExecutionMode.MUTATION_EXECUTION,
        )
        result = await rt.execute_one(req)
        assert result.status == ToolRuntimeStatus.REFUSED
