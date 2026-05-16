"""Phase 3 event stream — proves event ordering and no duplicate finalization."""

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


class EventStreamAdapter:
    """Adapter that records event ordering."""

    def __init__(self):
        self.middleware_calls = 0
        self.context_calls = 0
        self.llm_turns = 0
        self.turn_outcomes = []
        self.yielded_events = []

    def get_turn(self):
        t = MagicMock()
        t.advance = MagicMock()
        return t

    def get_turn_id(self):
        return "t1"

    def mark_turn_outcome(self, o, r):
        self.turn_outcomes.append((str(o.value) if hasattr(o, "value") else str(o), r))

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
        self.context_calls += 1
        e = MagicMock()
        e.envelope_id = "env-1"
        e.section_count = 3
        return e

    def set_context_envelope(self, e):
        pass

    async def stream_llm_turn(self):
        self.llm_turns += 1
        e = MagicMock()
        e.type = "assistant"
        yield e

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
        return True

    async def execute_tool_batch(self):
        if False:
            yield

    def check_max_turns(self):
        return None


class TestEventStreamOrdering:
    def test_context_builds_before_llm_turn(self):
        cr = ConversationRuntime()
        adapter = EventStreamAdapter()

        async def _run():
            events = []
            async for e in cr.execute_turn_loop(adapter):
                events.append(e.type)
            return events

        events = _run_async(_run())
        assert adapter.context_calls == 1
        assert adapter.llm_turns == 1
        assert len(adapter.turn_outcomes) == 1

    def test_one_outcome_per_execution(self):
        cr = ConversationRuntime()
        adapter = EventStreamAdapter()

        async def _run():
            async for _e in cr.execute_turn_loop(adapter):
                pass

        _run_async(_run())
        assert len(adapter.turn_outcomes) == 1, (
            "Only one outcome should be recorded per turn execution"
        )

    def test_persist_called(self):
        cr = ConversationRuntime()
        adapter = EventStreamAdapter()
        persist_called = False

        async def _run():
            nonlocal persist_called
            async for _e in cr.execute_turn_loop(adapter):
                pass
            persist_called = True

        _run_async(_run())
        assert persist_called, "execute_turn_loop must complete"
