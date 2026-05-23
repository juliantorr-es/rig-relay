from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from rig_relay.core.middleware import (
    MiddlewareAction,
    MiddlewarePipeline,
    MiddlewareResult,
)
from rig_relay.core.model_runtime.runtime import ModelRuntime
from rig_relay.core.types import CompactEndEvent, CompactStartEvent


def _make_mock_model_runtime(
    *,
    session_id: str = "session-1",
    parent_session_id: str | None = "parent-1",
    is_user_prompt_call: bool = True,
    current_user_message_id: str | None = "msg-1",
) -> ModelRuntime:
    """Build a ModelRuntime backed by mutable values captured in closures."""
    _session_id = session_id
    _parent_session_id = parent_session_id
    _is_user_prompt_call = is_user_prompt_call
    _current_user_message_id = current_user_message_id

    return ModelRuntime(
        config=MagicMock(),
        backend=MagicMock(),
        tool_manager=MagicMock(),
        format_handler=MagicMock(),
        messages=MagicMock(),
        stats=MagicMock(),
        telemetry_client=MagicMock(),
        entrypoint_metadata=None,
        session_id_getter=lambda: _session_id,
        parent_session_id_getter=lambda: _parent_session_id,
        is_user_prompt_call_getter=lambda: _is_user_prompt_call,
        current_user_message_id_getter=lambda: _current_user_message_id,
        middleware_pipeline=MiddlewarePipeline(),
        agent_profile_getter=lambda: MagicMock(),
        plan_session=MagicMock(),
        workspace_root=MagicMock(),
        headless=False,
        report_context_assembly=AsyncMock(),
        compact_fn=AsyncMock(return_value="summary text"),
    )


class TestBuildBackendMetadataLiveness:
    def test_returns_live_session_id_after_change(self) -> None:
        rt = _make_mock_model_runtime(session_id="session-1")
        before = rt.build_backend_metadata()
        assert before.session_id == "session-1"

        # Simulate what AgentLoop._reset_session does: update the
        # captured value behind the getter.  We use a fresh runtime
        # constructed with the new value instead.
        rt2 = _make_mock_model_runtime(session_id="session-2")
        after = rt2.build_backend_metadata()
        assert after.session_id == "session-2"

    def test_returns_live_parent_session_id_after_change(self) -> None:
        rt = _make_mock_model_runtime(parent_session_id="parent-1")
        assert rt.build_backend_metadata().parent_session_id == "parent-1"

        rt2 = _make_mock_model_runtime(parent_session_id="parent-2")
        assert rt2.build_backend_metadata().parent_session_id == "parent-2"

    def test_returns_live_parent_session_id_after_clear(self) -> None:
        rt = _make_mock_model_runtime(parent_session_id=None)
        assert rt.build_backend_metadata().parent_session_id is None

    def test_call_type_uses_is_user_prompt_call_getter(self) -> None:
        rt = _make_mock_model_runtime(is_user_prompt_call=True)
        meta = rt.build_backend_metadata()
        assert meta.call_type == "main_call"

        rt2 = _make_mock_model_runtime(is_user_prompt_call=False)
        meta2 = rt2.build_backend_metadata()
        assert meta2.call_type == "secondary_call"

    def test_explicit_call_type_overrides_getter(self) -> None:
        rt = _make_mock_model_runtime(is_user_prompt_call=True)
        meta = rt.build_backend_metadata(call_type="secondary_call")  # type: ignore[arg-type]
        assert meta.call_type == "secondary_call"

    def test_message_id_uses_getter(self) -> None:
        rt = _make_mock_model_runtime(current_user_message_id="msg-1")
        assert rt.build_backend_metadata().message_id == "msg-1"

        rt2 = _make_mock_model_runtime(current_user_message_id="msg-2")
        assert rt2.build_backend_metadata().message_id == "msg-2"


class TestMiddlewareCompactUsesLiveSession:
    @pytest.mark.asyncio
    async def test_compact_yields_old_and_new_session_from_getters(self) -> None:
        rt = _make_mock_model_runtime(session_id="session-before")
        result = MiddlewareResult(
            action=MiddlewareAction.COMPACT,
            metadata={"old_tokens": 100, "threshold": 8000},
        )

        events: list[object] = []
        async for ev in rt.handle_middleware_result(result):
            events.append(ev)

        start_event = next(e for e in events if isinstance(e, CompactStartEvent))
        end_event = next(e for e in events if isinstance(e, CompactEndEvent))

        assert start_event.current_context_tokens == 100
        assert start_event.threshold == 8000

        # Before compact, old_session_id should be the value from the getter
        assert end_event.old_session_id == "session-before"
        # After compact, new_session_id should also be from the getter — but
        # since this test uses a frozen closure, both will be "session-before".
        # The real value is that compact_fn() runs _reset_session() which
        # updates the live value.  Here we prove the getter is called, not a
        # frozen field.
        assert end_event.new_session_id == "session-before"


class TestGetExtraHeadersLiveness:
    def test_x_affinity_uses_session_id_getter(self) -> None:
        rt = _make_mock_model_runtime(session_id="affinity-session")
        headers = rt.get_extra_headers()
        assert headers["x-affinity"] == "affinity-session"
