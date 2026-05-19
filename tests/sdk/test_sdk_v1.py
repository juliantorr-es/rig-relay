"""SDK v1 — schema validation, client behavior, and import hygiene tests."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.sdk import (
    RigClient,
    RigRefusal,
    RigRunResult,
    RigStatus,
    RigTransportBudgets,
    RigVerdict,
    get_sdk_status,
)

R = Path(__file__).resolve().parent.parent.parent
S = R / "docs" / "schemas"


def _load(name: str) -> dict:
    return json.loads((S / name).read_text(encoding="utf-8"))


def _v(instance, name):
    jsonschema.validate(instance, _load(name))


class TestSDKV1:
    def test_status_validates(self):
        _v(RigStatus().to_dict(), "rig.relay.sdk.status.v1.schema.json")

    def test_run_result_validates(self):
        r = RigRunResult("op1", "mcp_read_only", RigVerdict.COMPLETED, "t1")
        _v(r.to_dict(), "rig.relay.sdk.run_result.v1.schema.json")

    def test_refusal_validates(self):
        r = RigRefusal("mut_refused", "reason", "cap1", "t1")
        _v(r.to_dict(), "rig.relay.sdk.refusal.v1.schema.json")

    def test_unknown_capability_refused(self):
        d = RigClient().evaluate_capability("unknown")
        assert d.verdict == RigVerdict.REFUSED
        assert d.refusal_code == "unknown_capability"

    def test_mutation_refused_by_default(self):
        d = RigClient().evaluate_capability("mcp.mutation")
        assert d.verdict == RigVerdict.REFUSED

    def test_mcp_read_only_bridge_receipt(self):
        r = RigClient().run_mcp_read_only("rig.current_mission", "t2")
        assert r.verdict == RigVerdict.COMPLETED
        assert r.trace_id == "t2"

    def test_trace_context_preserved(self):
        c = RigClient(trace_id="pt-123")
        assert c.status().trace_support is True
        r = c.run_mcp_read_only("rig.current_mission", "pt-123")
        assert r.trace_id == "pt-123"

    def test_no_desktop_provider_imports(self):
        sd = R / "rig_relay" / "sdk"
        forbidden = ("rig_relay.desktop", "rig_relay.identity", "rig_relay.providers")
        for f in sorted(sd.glob("*.py")):
            src = f.read_text()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for fb in forbidden:
                        assert not node.module.startswith(fb), (
                            f"{f.name} imports {node.module}"
                        )

    def test_get_sdk_status(self):
        s = get_sdk_status()
        assert s.provider_id == "rig_sdk"
        assert s.mcp_available is True

    @pytest.mark.asyncio
    async def test_run_mcp_read_only_returns_completed_for_tier0_tool(self):
        c = RigClient(trace_id="t0-test")
        r = await c.async_run_mcp_read_only("rig.current_mission", "t0-test")
        assert r.verdict == RigVerdict.COMPLETED
        assert r.trace_id == "t0-test"

    @pytest.mark.asyncio
    async def test_run_mcp_read_only_refuses_tier4_tool(self):
        c = RigClient(trace_id="t4-test")
        r = await c.async_run_mcp_read_only("rig.request_user_approval", "t4-test")
        assert r.verdict == RigVerdict.REFUSED
        assert r.refusal_code == "mutation_refused"

    @pytest.mark.asyncio
    async def test_list_mcp_tools_returns_tool_list(self):
        c = RigClient()
        r = await c.async_list_mcp_tools("t-list")
        assert r.verdict == RigVerdict.COMPLETED
        assert r.operation_kind == "list_mcp_tools"

    @pytest.mark.asyncio
    async def test_list_mcp_resources_returns_resource_list(self):
        c = RigClient()
        r = await c.async_list_mcp_resources("t-res")
        assert r.verdict == RigVerdict.COMPLETED
        assert r.operation_kind == "list_mcp_resources"

    @pytest.mark.asyncio
    async def test_list_mcp_prompts_returns_prompt_list(self):
        c = RigClient()
        r = await c.async_list_mcp_prompts("t-pr")
        assert r.verdict == RigVerdict.COMPLETED
        assert r.operation_kind == "list_mcp_prompts"

    def test_send_a2a_local_task_delegates_task(self):
        r = RigClient().send_a2a_local_task("task-1", "agent-builder", "t-a2a")
        assert r.verdict == RigVerdict.COMPLETED
        assert r.operation_kind == "a2a_local_task"

    def test_transport_budgets_model_defaults(self):
        b = RigTransportBudgets()
        assert b.max_request_bytes == 65536
        assert b.max_response_bytes == 65536
        assert b.max_pending_requests == 64
        assert b.content_light is True
        c = RigClient()
        assert c.budgets.max_concurrent_sessions == 8
        assert c.budgets.request_timeout_seconds == 30

    def test_sdk_trace_id_propagated_across_protocols(self):
        c = RigClient(trace_id="pt-cross")
        mr = c.run_mcp_read_only("rig.current_mission", "pt-cross")
        assert mr.trace_id == "pt-cross"
        ar = c.start_acp_session("pt-cross")
        assert ar.trace_id == "pt-cross"
        a2a = c.send_a2a_local_task("t-1", "agent-1", "pt-cross")
        assert a2a.trace_id == "pt-cross"
