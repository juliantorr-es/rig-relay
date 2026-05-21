from __future__ import annotations

from typing import Any

import pytest

from rig_relay.core.tool_runtime import ToolRuntime
from rig_relay.core.tool_runtime_models import ToolRuntimeRequest, ToolRuntimeStatus
from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.store import InMemoryTraceStore


async def _fake_invoke(args_dict: dict[str, Any]) -> Any:
    from pydantic import BaseModel

    class _FakeResult(BaseModel):
        result: str = "ok"

    yield _FakeResult()


async def _fake_allow() -> tuple[bool, str]:
    return True, ""


def _fake_cache_check(tool_name: str, args: dict) -> tuple[bool, Any]:
    return False, None


def _fake_cache_store(tool_name: str, args: dict, result: dict) -> None:
    pass


@pytest.mark.asyncio
async def test_completed_execution_emits_trace_span():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    runtime = ToolRuntime(
        invoke_tool=_fake_invoke,
        cache_check=_fake_cache_check,
        cache_store=_fake_cache_store,
        permission_decision=lambda t, a, c: _fake_allow(),
        approval_request=lambda t, a, c: _fake_allow(),
        patch_gate_check=lambda tc, ti: None,
        trace_recorder=recorder,
    )
    result = await runtime.execute_one(
        ToolRuntimeRequest(tool_name="test_tool", tool_args={"x": 1}, tool_call_id="c1")
    )
    assert result.status == ToolRuntimeStatus.COMPLETED

    span_start = [e for e in store.events if e["event_kind"] == "span.start"]
    span_end = [e for e in store.events if e["event_kind"] == "span.end"]
    assert len(span_start) >= 1
    assert len(span_end) >= 1
    assert span_start[0]["name"] == "tool_runtime.execute_one"
    assert span_start[0]["attributes"]["tool.name"] == "test_tool"
    assert span_end[0]["status"] == "ok"


@pytest.mark.asyncio
async def test_refused_execution_emits_trace_span():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)

    async def deny(tool_name: str, args: dict, call_id: str) -> tuple[bool, str]:
        return False, "Permission denied"

    runtime = ToolRuntime(
        invoke_tool=_fake_invoke,
        cache_check=_fake_cache_check,
        cache_store=_fake_cache_store,
        permission_decision=deny,
        approval_request=lambda t, a, c: _fake_allow(),
        patch_gate_check=lambda tc, ti: None,
        trace_recorder=recorder,
    )
    result = await runtime.execute_one(
        ToolRuntimeRequest(tool_name="refused_tool", tool_args={}, tool_call_id="c2")
    )
    assert result.status == ToolRuntimeStatus.REFUSED

    span_start = [e for e in store.events if e["event_kind"] == "span.start"]
    [e for e in store.events if e["event_kind"] == "span.end"]
    assert len(span_start) >= 1
    assert span_start[0]["name"] == "tool_runtime.execute_one"
    assert span_start[0]["attributes"]["tool.name"] == "refused_tool"


@pytest.mark.asyncio
async def test_disabled_tracing_does_not_fail_execution():
    runtime = ToolRuntime(
        invoke_tool=_fake_invoke,
        cache_check=_fake_cache_check,
        permission_decision=lambda t, a, c: _fake_allow(),
        approval_request=lambda t, a, c: _fake_allow(),
        patch_gate_check=lambda tc, ti: None,
        trace_recorder=None,
    )
    result = await runtime.execute_one(
        ToolRuntimeRequest(tool_name="no_trace_tool", tool_args={}, tool_call_id="c3")
    )
    assert result.status == ToolRuntimeStatus.COMPLETED


@pytest.mark.asyncio
async def test_cached_result_emits_hit_event():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)

    def cache_hit(tool_name: str, args: dict) -> tuple[bool, Any]:
        return True, {"cached": True}

    runtime = ToolRuntime(
        invoke_tool=_fake_invoke,
        cache_check=cache_hit,
        cache_store=_fake_cache_store,
        permission_decision=lambda t, a, c: _fake_allow(),
        approval_request=lambda t, a, c: _fake_allow(),
        patch_gate_check=lambda tc, ti: None,
        trace_recorder=recorder,
    )
    result = await runtime.execute_one(
        ToolRuntimeRequest(tool_name="cached_tool", tool_args={}, tool_call_id="c4")
    )
    assert result.status == ToolRuntimeStatus.CACHED

    cache_events = [e for e in store.events if e["name"] == "tool_runtime.cache_check"]
    assert len(cache_events) >= 1
    assert cache_events[0]["attributes"]["cache.hit"] is True


@pytest.mark.asyncio
async def test_tool_args_are_not_in_trace():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    runtime = ToolRuntime(
        invoke_tool=_fake_invoke,
        cache_check=_fake_cache_check,
        cache_store=_fake_cache_store,
        permission_decision=lambda t, a, c: _fake_allow(),
        approval_request=lambda t, a, c: _fake_allow(),
        patch_gate_check=lambda tc, ti: None,
        trace_recorder=recorder,
    )
    await runtime.execute_one(
        ToolRuntimeRequest(
            tool_name="secret_tool",
            tool_args={"api_key": "sk-secret-value", "token": "abc123"},
            tool_call_id="c5",
        )
    )
    for event in store.events:
        attrs = event.get("attributes", {})
        for key in attrs:
            val = str(attrs[key])
            assert "sk-secret" not in val
            assert "abc123" not in val
