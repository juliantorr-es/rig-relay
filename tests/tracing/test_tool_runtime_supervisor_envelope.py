from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, cast

from pydantic import BaseModel
import pytest

from rig_relay.core.tool_runtime import ToolRuntime
from rig_relay.core.tool_runtime_models import ToolRuntimeRequest
from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.store import InMemoryTraceStore


class _FakeResultWithEnvelope(BaseModel):
    status: str = "success"
    supervisor_result_envelope: dict[str, Any] = {
        "result_id": "sha256:trace-envelope",
        "classification": "timed_out",
    }
    supervisor_result_envelope_sha256: str = "sha256:trace-envelope"
    supervisor_result_classification: str = "timed_out"


async def _fake_invoke(_args_dict: dict[str, Any]) -> AsyncGenerator[Any, None]:
    if False:
        yield None
    yield _FakeResultWithEnvelope()


async def _allow(*_args: Any) -> tuple[bool, str]:
    return True, ""


@pytest.mark.asyncio
async def test_tool_runtime_span_uses_supervisor_envelope_classification() -> None:
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    runtime = ToolRuntime(
        invoke_tool=_fake_invoke,
        cache_check=lambda _tool_name, _args: (False, None),
        cache_store=lambda t, a, r: None,
        permission_decision=lambda t, a, c: _allow(),
        approval_request=lambda t, a, c: _allow(),
        trace_recorder=recorder,
    )

    result = await runtime.execute_one(
        ToolRuntimeRequest(
            tool_name="bash", tool_args={"command": "sleep 1"}, tool_call_id="c1"
        )
    )

    assert result.supervisor_result_classification == "timed_out"
    span_start = [e for e in store.events if e["event_kind"] == "span.start"]
    span_end = [e for e in store.events if e["event_kind"] == "span.end"]
    assert span_start[0]["name"] == "tool_runtime.execute_one"
    span_end_event = cast(dict[str, Any], span_end[0])
    assert span_end_event["status"] == "timed_out"
    attributes = cast(dict[str, Any], span_end_event["attributes"])
    assert attributes["tool.supervisor_result_classification"] == "timed_out"
    assert attributes["tool.supervisor_result_envelope_id"] == "sha256:trace-envelope"
