"""ConversationRuntime Phase 3 loop ownership transfer tests — remaining loop cases."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from rig_relay.core.conversation_runtime import ConversationRuntime


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class ToolBatchAdapter:
    """Adapter that yields one tool call, then runs tool batch, then completes."""

    def __init__(self):
        self.middleware_calls = 0
        self.llm_turn_calls = 0
        self.tool_batch_calls = 0
        self.turn_outcomes = []
        self._phase = 0  # 0=first LLM (tool call), 1=second LLM (assistant)

    def get_turn(self):
        t = MagicMock()
        t.advance = MagicMock()
        return t

    def get_turn_id(self): return "t1"
    def mark_turn_outcome(self, o, r): self.turn_outcomes.append((o, r))
    def persist_turn_state(self): pass

    def middleware_before_turn(self, ctx):
        self.middleware_calls += 1
        r = MagicMock()
        r.action = "CONTINUE"
        return r, []

    def reset_hooks(self): pass

    def build_context_envelope(self, r): return MagicMock()
    def set_context_envelope(self, e): pass

    async def stream_llm_turn(self):
        self.llm_turn_calls += 1
        e = MagicMock()
        if self._phase == 0:
            e.type = "tool_call"
        else:
            e.type = "assistant"
        yield e
        self._phase += 1

    def is_user_cancellation_event(self, e): return False
    async def stream_hooks_post_turn(self):
        if False:
            yield

    def is_hook_user_message(self, e): return False
    def inject_hook_message(self, m): pass

    def last_message_has_no_tool_calls(self):
        return self._phase >= 2  # first turn is tool call, second is assistant

    async def execute_tool_batch(self):
        self.tool_batch_calls += 1
        if False:
            yield

    def check_max_turns(self): return None


class HookRetryAdapter:
    """Adapter that completes, but a hook injects a retry message."""

    def __init__(self):
        self.middleware_calls = 0
        self.llm_turn_calls = 0
        self.hook_injected = False
        self.turn_outcomes = []

    def get_turn(self):
        t = MagicMock()
        t.advance = MagicMock()
        return t

    def get_turn_id(self): return "t1"
    def mark_turn_outcome(self, o, r): self.turn_outcomes.append((o, r))
    def persist_turn_state(self): pass

    def middleware_before_turn(self, ctx):
        self.middleware_calls += 1
        r = MagicMock()
        r.action = "CONTINUE"
        return r, []

    def reset_hooks(self): pass
    def build_context_envelope(self, r): return MagicMock()
    def set_context_envelope(self, e): pass

    async def stream_llm_turn(self):
        self.llm_turn_calls += 1
        e = MagicMock()
        e.type = "assistant"
        yield e

    def is_user_cancellation_event(self, e): return False

    async def stream_hooks_post_turn(self):
        if not self.hook_injected:
            self.hook_injected = True
            hm = MagicMock()
            hm.content = "retry message"
            yield hm

    def is_hook_user_message(self, e): return self.hook_injected and not self.llm_turn_calls > 2

    def inject_hook_message(self, m): pass
    def last_message_has_no_tool_calls(self): return True

    async def execute_tool_batch(self):
        if False:
            yield

    def check_max_turns(self): return None


class TestRemainingLoopCases:
    def test_loop_runs_tool_batch(self):
        cr = ConversationRuntime()
        adapter = ToolBatchAdapter()

        async def _run():
            async for _event in cr.execute_turn_loop(adapter):
                pass

        _run_async(_run())
        assert adapter.tool_batch_calls >= 1
        assert adapter.llm_turn_calls >= 2

    def test_loop_retries_on_hook_user_message(self):
        cr = ConversationRuntime()
        adapter = HookRetryAdapter()

        async def _run():
            async for _event in cr.execute_turn_loop(adapter):
                pass

        _run_async(_run())
        assert adapter.llm_turn_calls >= 2
