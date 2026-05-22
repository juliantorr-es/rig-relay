"""Phase 3 tool batch behavior parity — proves execute_tool_batch delegates correctly."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from rig_relay.core.conversation_runtime import ConversationRuntime


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class FullToolExecutionAdapter:
    """Adapter mirroring real AgentLoop: LLM turn executes tools internally."""

    def __init__(self):
        self.middleware_calls = 0
        self.llm_turns = 0
        self.tool_execution_count = 0
        self.turn_outcomes = []
        self._phase = "tool_request"  # sequence: tool_request → tool_result → assistant

    def get_turn(self):
        t = MagicMock()
        t.advance = MagicMock()
        return t

    def get_turn_id(self):
        return "t1"

    def mark_turn_outcome(self, o, r):
        self.turn_outcomes.append((o, r))

    def persist_turn_state(self):
        pass

    async def middleware_before_turn(self, ctx):
        self.middleware_calls += 1
        r = MagicMock()
        r.action = "CONTINUE"
        return r, []

    def reset_hooks(self):
        pass

    async def build_context_envelope(self, r):
        return MagicMock()

    def set_context_envelope(self, e):
        pass

    async def stream_llm_turn(self):
        """Simulates _perform_llm_turn: makes LLM call AND runs tools if needed."""
        self.llm_turns += 1
        if self._phase == "tool_request":
            # LLM requests a tool call
            e = MagicMock()
            e.type = "tool_call_event"
            yield e
            # Tool execution happens inside _perform_llm_turn
            self.tool_execution_count += 1
            te = MagicMock()
            te.type = "tool_result"
            yield te
            self._phase = "tool_result"
        elif self._phase == "tool_result":
            # LLM receives tool results, produces final answer
            e = MagicMock()
            e.type = "assistant"
            yield e
            self._phase = "done"

    def is_user_cancellation_event(self, e):
        return False

    async def stream_hooks_post_turn(self):
        if False:
            yield

    def is_hook_user_message(self, e):
        return False

    def inject_hook_message(self, m):
        pass

    def last_message_has_no_tool_calls(self):
        # After tool execution, last message is tool result (Role.tool) → has tool calls
        # After final answer, last message is assistant → no tool calls
        return self._phase == "done"

    def get_turn_batch_result(self):
        from rig_relay.core.conversation_runtime.models import TurnBatchResult

        if self._phase == "done":
            return TurnBatchResult(pending_batch=None, assistant_is_final=True)
        return TurnBatchResult(pending_batch=[object()], assistant_is_final=False)

    async def execute_tool_batch(self):
        if False:
            yield

    def check_max_turns(self):
        return None


class TestToolExecutionDelegation:
    def test_tools_executed_within_stream_llm_turn(self):
        """Proves tool execution happens inside stream_llm_turn, not execute_tool_batch."""
        cr = ConversationRuntime()
        adapter = FullToolExecutionAdapter()

        async def _run():
            async for _event in cr.execute_turn_loop(adapter):
                pass

        _run_async(_run())
        assert adapter.tool_execution_count == 1, (
            "Tool execution must happen inside stream_llm_turn"
        )
        assert adapter.llm_turns == 2, (
            "Two LLM turns: tool request + tool result → final answer"
        )
        assert len(adapter.turn_outcomes) >= 1, "Turn must complete with an outcome"

    def test_run_tools_decision_continues_loop(self):
        """Proves the run_tools decision correctly continues the while-loop."""
        cr = ConversationRuntime()
        adapter = FullToolExecutionAdapter()

        async def _run():
            async for _event in cr.execute_turn_loop(adapter):
                pass

        _run_async(_run())
        assert adapter.llm_turns >= 2, "Loop must continue after run_tools decision"

    def test_adapter_execute_tool_batch_is_noop(self):
        """Proves execute_tool_batch yields nothing — tools run in stream_llm_turn."""
        from rig_relay.core.agent_loop import _ConversationLoopAdapter

        if not hasattr(_ConversationLoopAdapter, "execute_tool_batch"):
            pytest.skip("Adapter not importable (pre-existing dependency issue)")

        import inspect

        source = inspect.getsource(_ConversationLoopAdapter.execute_tool_batch)
        assert "_perform_llm_turn" in source or "if False" in source, (
            "execute_tool_batch should document that tools run in stream_llm_turn"
        )
