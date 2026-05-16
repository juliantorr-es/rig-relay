from __future__ import annotations

from typing import Any

import pytest

from rig_relay.core.tools.base import BaseToolState, InvokeContext
from rig_relay.core.tools.builtins.validate import Validate
from rig_relay.core.tools.builtins.validate_models import (
    ValidateArgs,
    ValidateToolConfig,
)
from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.store import InMemoryTraceStore


@pytest.mark.asyncio
async def test_validate_profile_emits_trace_span():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    ctx = InvokeContext(tool_call_id="v1", trace_recorder=recorder)
    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    result: Any = None
    async for item in tool.run(ValidateArgs(profile="quick"), ctx=ctx):
        result = item
    assert result is not None

    span_start = [e for e in store.events if e["event_kind"] == "span.start"]
    span_end = [e for e in store.events if e["event_kind"] == "span.end"]
    assert len(span_start) >= 1
    assert len(span_end) >= 1
    assert span_start[0]["name"] == "validate.profile"
    assert span_start[0]["attributes"]["profile"] == "quick"


@pytest.mark.asyncio
async def test_disabled_tracing_preserves_validate_behavior():
    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    result: Any = None
    async for item in tool.run(ValidateArgs(profile="quick")):
        result = item
    assert result is not None


@pytest.mark.asyncio
async def test_validate_state_transitions_emit_events():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    ctx = InvokeContext(tool_call_id="v2", trace_recorder=recorder)
    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    async for item in tool.run(ValidateArgs(profile="quick"), ctx=ctx):
        pass

    transitions = [
        e for e in store.events if e.get("name") == "validate.state.transition"
    ]
    assert len(transitions) >= 1, "Expected at least one state transition event"
    for t in transitions:
        attrs = t.get("attributes", {})
        assert "profile.state.from" in attrs
        assert "profile.state.to" in attrs
        assert "profile.event" in attrs


@pytest.mark.asyncio
async def test_unknown_profile_refused_with_trace():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    ctx = InvokeContext(tool_call_id="v3", trace_recorder=recorder)
    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    result: Any = None
    async for item in tool.run(ValidateArgs(profile="nonexistent_xyz"), ctx=ctx):
        result = item
    assert result is not None

    span_end = [e for e in store.events if e["event_kind"] == "span.end"]
    assert len(span_end) >= 1
    assert span_end[0]["status"] == "error"


@pytest.mark.asyncio
async def test_validate_trace_has_no_raw_cwd():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    ctx = InvokeContext(tool_call_id="v4", trace_recorder=recorder)
    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    async for item in tool.run(ValidateArgs(profile="quick"), ctx=ctx):
        pass

    for event in store.events:
        attrs = event.get("attributes", {})
        for key in attrs:
            val = str(attrs[key])
            assert "/Users/" not in val, (
                f"Raw path leaked in {event['name']}: {key}={val}"
            )
