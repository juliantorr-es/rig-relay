"""ConversationRuntime Phase 3 loop ownership transfer tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from rig_relay.core.conversation_runtime import ConversationRuntime

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class FakeAdapter:
    def __init__(self) -> None:
        self.middleware_calls = 0
        self.context_build_calls = 0
        self.llm_turn_calls = 0
        self.hooks_calls = 0
        self.tool_batch_calls = 0
        self.turn_outcomes: list[tuple[Any, str]] = []
        self.middleware_action = "CONTINUE"
        self._cancelled = False
        self._tool_call_mode = False
        self._hook_retry: Any | None = None
        self._max_turns: int | None = None

    def get_turn(self) -> Any:
        turn = MagicMock()
        turn.advance = MagicMock()
        return turn

    def get_turn_id(self) -> str:
        return "turn-001"

    def mark_turn_outcome(self, outcome: Any, reason: str) -> None:
        self.turn_outcomes.append((outcome, reason))

    def persist_turn_state(self) -> None:
        pass

    async def middleware_before_turn(
        self, ctx: dict[str, str]
    ) -> tuple[Any, list[Any]]:
        self.middleware_calls += 1
        result = MagicMock()
        result.action = self.middleware_action
        return result, []

    def reset_hooks(self) -> None:
        pass

    async def build_context_envelope(self, request: Any | None) -> Any | None:
        self.context_build_calls += 1
        envelope = MagicMock()
        envelope.envelope_id = "env-001"
        envelope.section_count = 3
        return envelope

    def set_context_envelope(self, receipt: Any) -> None:
        pass

    async def stream_llm_turn(self):
        self.llm_turn_calls += 1
        if self._cancelled:
            event = MagicMock()
            event.type = "cancellation"
            yield event
        elif self._tool_call_mode:
            event = MagicMock()
            event.type = "tool_call"
            yield event
        else:
            event = MagicMock()
            event.type = "assistant"
            yield event

    def is_user_cancellation_event(self, event: Any) -> bool:
        return getattr(event, "type", "") == "cancellation"

    async def stream_hooks_post_turn(self):
        self.hooks_calls += 1
        if self._hook_retry:
            yield self._hook_retry

    def is_hook_user_message(self, event: Any) -> bool:
        return self._hook_retry is not None and event is self._hook_retry

    def inject_hook_message(self, hook_message: Any) -> None:
        self._hook_retry = None

    def last_message_has_no_tool_calls(self) -> bool:
        return not self._tool_call_mode

    def get_turn_batch_result(self):
        from rig_relay.core.conversation_runtime.models import TurnBatchResult

        if self._tool_call_mode:
            return TurnBatchResult(pending_batch=[object()], assistant_is_final=False)
        return TurnBatchResult(pending_batch=None, assistant_is_final=True)

    async def execute_tool_batch(self):
        self.tool_batch_calls += 1
        self._tool_call_mode = False
        if False:
            yield

    def check_max_turns(self) -> int | None:
        return self._max_turns


class TestExecuteTurnLoopOwnership:
    def test_loop_completes_normal_path(self) -> None:
        cr = ConversationRuntime()
        adapter = FakeAdapter()

        async def _run():
            async for _event in cr.execute_turn_loop(adapter):
                pass

        _run_async(_run())
        assert adapter.middleware_calls >= 1
        assert adapter.context_build_calls == 1
        assert adapter.llm_turn_calls >= 1
        assert len(adapter.turn_outcomes) >= 1

    def test_loop_stops_on_middleware_stop(self) -> None:
        cr = ConversationRuntime()
        adapter = FakeAdapter()
        adapter.middleware_action = "STOP"

        async def _run():
            async for _event in cr.execute_turn_loop(adapter):
                pass

        _run_async(_run())
        assert adapter.middleware_calls == 1
        assert adapter.llm_turn_calls == 0

    def test_loop_stops_on_cancellation(self) -> None:
        cr = ConversationRuntime()
        adapter = FakeAdapter()
        adapter._cancelled = True

        async def _run():
            async for _event in cr.execute_turn_loop(adapter):
                pass

        _run_async(_run())
        assert len(adapter.turn_outcomes) >= 1

    def test_loop_runs_tool_batch(self) -> None:
        cr = ConversationRuntime()
        adapter = FakeAdapter()
        adapter._tool_call_mode = True

        async def _run():
            async for _event in cr.execute_turn_loop(adapter):
                pass

        _run_async(_run())
        assert adapter.tool_batch_calls >= 1

    def test_loop_retries_on_hook_user_message(self) -> None:
        cr = ConversationRuntime()
        adapter = FakeAdapter()
        adapter._hook_retry = MagicMock()
        adapter._hook_retry.content = "retry message"

        async def _run():
            async for _event in cr.execute_turn_loop(adapter):
                pass

        _run_async(_run())
        assert adapter.hooks_calls >= 1
        assert adapter.llm_turn_calls >= 2

    def test_loop_fails_on_budget_exceeded(self) -> None:
        cr = ConversationRuntime()
        adapter = FakeAdapter()
        adapter._max_turns = 0
        adapter._tool_call_mode = False

        async def _run():
            async for _event in cr.execute_turn_loop(adapter):
                pass

        _run_async(_run())
        assert any(str(o) == "llm_error" for o, _r in adapter.turn_outcomes) or any(
            "budget" in str(r).lower() for _o, r in adapter.turn_outcomes
        )

    def test_loop_propagates_exception(self) -> None:
        cr = ConversationRuntime()

        class BrokenAdapter(FakeAdapter):
            async def stream_llm_turn(self):
                raise ValueError("simulated LLM failure")
                yield

        adapter = BrokenAdapter()

        with pytest.raises(ValueError, match="simulated LLM failure"):

            async def _run():
                async for _event in cr.execute_turn_loop(adapter):
                    pass

            _run_async(_run())


class TestAgentLoopDelegatesToConversationRuntime:
    def test_conversation_loop_calls_execute_turn_loop(self) -> None:
        source = (_REPO_ROOT / "rig_relay" / "core" / "agent_loop.py").read_text()
        assert "execute_turn_loop(" in source

    def test_conversation_loop_builds_adapter(self) -> None:
        source = (_REPO_ROOT / "rig_relay" / "core" / "agent_loop.py").read_text()
        assert "_build_loop_adapter" in source

    def test_adapter_class_exists(self) -> None:
        source = (
            _REPO_ROOT / "rig_relay" / "core" / "conversation_loop_adapter.py"
        ).read_text()
        assert "class _ConversationLoopAdapter" in source

    def test_execute_turn_loop_exists(self) -> None:
        source = (
            _REPO_ROOT / "rig_relay" / "core" / "conversation_runtime" / "runtime.py"
        ).read_text()
        assert "async def execute_turn_loop" in source
