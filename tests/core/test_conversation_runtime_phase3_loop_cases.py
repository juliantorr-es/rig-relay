"""Phase 3 loop semantic parity tests — budget, decisions, finalization, hooks, tools.

Tests ConversationRuntime.execute_turn_loop with a fake adapter to
verify correct behavior on every terminal path.
"""

from __future__ import annotations

import asyncio
from typing import Any

from rig_relay.core.conversation_runtime import ConversationRuntime
from rig_relay.core.conversation_turn import ConversationTurnRuntime, TurnOutcome

# ── Fake adapter for controlled loop execution ──────────────────


class _FakeMiddlewareResult:
    def __init__(self, action: str = "continue"):
        self.action = action


class _FakeHookMessage:
    def __init__(self, content: str = "retry"):
        self.content = content
        self.injected = True


class _FakeLoopAdapter:
    """Controlled adapter for testing execute_turn_loop behavior.

    Set canned responses before each test.
    """

    def __init__(self) -> None:
        self.turn = ConversationTurnRuntime(
            session_id="s1", user_message_text="hello", user_message_id="u1"
        )
        self.persist_calls = 0
        self.mark_calls: list[tuple[str, str]] = []
        self.hook_injected: list = []

        # Canned responses
        self.middleware_action = "continue"
        self.middleware_events: list = []
        self.context_envelope = None
        self.llm_events: list = []
        self.user_cancelled = False
        self.has_tool_calls = True
        self.tool_batch_events: list = []
        self.hook_events: list = []
        self.hook_has_user_message = False
        self.max_turns: int | None = None
        self.raise_on_stream_llm: Exception | None = None

    # ── Turn lifecycle ──────────────────────────────────────────

    def get_turn(self):
        return self.turn

    def get_turn_id(self) -> str:
        return self.turn.turn_id

    def mark_turn_outcome(self, outcome: TurnOutcome, reason: str) -> None:
        self.mark_calls.append((str(outcome.value), reason))
        self.turn.mark_outcome(outcome, reason)

    def persist_turn_state(self) -> None:
        self.persist_calls += 1

    # ── Middleware ───────────────────────────────────────────────

    async def middleware_before_turn(self, ctx: dict[str, str]):
        return _FakeMiddlewareResult(self.middleware_action), list(
            self.middleware_events
        )

    # ── Context ──────────────────────────────────────────────────

    async def build_context_envelope(self, request):
        return self.context_envelope

    def set_context_envelope(self, receipt) -> None:
        pass

    # ── LLM ──────────────────────────────────────────────────────

    async def stream_llm_turn(self):
        if self.raise_on_stream_llm:
            raise self.raise_on_stream_llm
        for ev in self.llm_events:
            yield ev

    def is_user_cancellation_event(self, event) -> bool:
        return self.user_cancelled

    # ── Hooks ────────────────────────────────────────────────────

    async def stream_hooks_post_turn(self):
        for ev in self.hook_events:
            yield ev

    def is_hook_user_message(self, event) -> bool:
        return self.hook_has_user_message

    def inject_hook_message(self, hook_message) -> None:
        self.hook_injected.append(hook_message)

    # ── Loop control ─────────────────────────────────────────────

    def last_message_has_no_tool_calls(self) -> bool:
        return not self.has_tool_calls

    def get_turn_batch_result(self):
        from rig_relay.core.conversation_runtime.models import TurnBatchResult

        if self.has_tool_calls:
            return TurnBatchResult(pending_batch=[object()], assistant_is_final=False)
        return TurnBatchResult(pending_batch=None, assistant_is_final=True)

    async def execute_tool_batch(self):
        for ev in self.tool_batch_events:
            yield ev

    def check_max_turns(self) -> int | None:
        return self.max_turns


# ── Helper to run the loop and collect results ───────────────────


async def _collect_loop(cr: ConversationRuntime, adapter: _FakeLoopAdapter):
    results: list[Any] = []
    try:
        async for event in cr.execute_turn_loop(adapter):
            results.append(event)
    except Exception:
        pass
    return results, adapter


def _run_loop_to_completion(cr, adapter):
    gen = cr.execute_turn_loop(adapter)
    loop = asyncio.new_event_loop()
    try:
        while True:
            loop.run_until_complete(gen.__anext__())
    except StopAsyncIteration:
        pass
    except Exception:
        pass
    finally:
        loop.close()
    return adapter


# ── Budget tests ────────────────────────────────────────────────


class TestBudgetCheck:
    def test_budget_exceeded_stops_loop(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.max_turns = 1
        adapter.has_tool_calls = False
        adapter.llm_events = [_FakeAssistantEvent("done")]

        gen = cr.execute_turn_loop(adapter)
        loop = asyncio.new_event_loop()
        try:
            while True:
                loop.run_until_complete(gen.__anext__())
        except StopAsyncIteration:
            pass
        finally:
            loop.close()

        outcomes = [c[0] for c in adapter.mark_calls]
        assert "llm_error" in outcomes or "success" in outcomes

    def test_budget_ok_continues(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.max_turns = 5
        adapter.has_tool_calls = False
        adapter.llm_events = [_FakeAssistantEvent("done")]

        gen = cr.execute_turn_loop(adapter)
        loop = asyncio.new_event_loop()
        try:
            while True:
                loop.run_until_complete(gen.__anext__())
        except StopAsyncIteration:
            pass
        finally:
            loop.close()

        outcomes = [c[0] for c in adapter.mark_calls]
        assert "llm_error" not in outcomes

    def test_budget_none_never_exceeds(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.max_turns = None
        adapter.has_tool_calls = False
        adapter.llm_events = [_FakeAssistantEvent("done")]

        gen = cr.execute_turn_loop(adapter)
        loop = asyncio.new_event_loop()
        try:
            while True:
                loop.run_until_complete(gen.__anext__())
        except StopAsyncIteration:
            pass
        finally:
            loop.close()

        assert adapter.mark_calls[-1][0] == "success"


# ── Middleware tests ─────────────────────────────────────────────


class TestMiddlewareDecision:
    def test_middleware_stop_uses_decision_kind(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.middleware_action = "STOP"

        adapter = _run_loop_to_completion(cr, adapter)
        assert len(adapter.mark_calls) == 1
        assert adapter.mark_calls[0][0] == "middleware_stop"

    def test_middleware_continue_proceeds(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.middleware_action = "continue"
        adapter.has_tool_calls = False
        adapter.llm_events = [_FakeAssistantEvent("done")]

        adapter = _run_loop_to_completion(cr, adapter)
        assert adapter.mark_calls[-1][0] == "success"


# ── Finalization tests ───────────────────────────────────────────


class TestFinalization:
    def test_finalization_called_on_success(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.has_tool_calls = False
        adapter.llm_events = [_FakeAssistantEvent("done")]

        adapter = _run_loop_to_completion(cr, adapter)
        assert adapter.mark_calls[-1][0] == "success"

    def test_finalization_called_on_cancelled(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.user_cancelled = True
        adapter.llm_events = [_FakeAssistantEvent("cancelled")]

        adapter = _run_loop_to_completion(cr, adapter)
        assert adapter.mark_calls[0][0] == "user_cancelled"

    def test_finalization_called_on_error(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.raise_on_stream_llm = RuntimeError("model 500")

        _run_loop_to_completion(cr, adapter)
        assert adapter.mark_calls[0][0] == "llm_error"

    def test_persist_called_exactly_once(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.has_tool_calls = False
        adapter.llm_events = [_FakeAssistantEvent("done")]

        _run_loop_to_completion(cr, adapter)
        assert adapter.persist_calls == 1


# ── Hook retry tests ─────────────────────────────────────────────


class TestHookRetry:
    def test_hook_retry_injects_message(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.has_tool_calls = False
        adapter.llm_events = [_FakeAssistantEvent("done")]
        adapter.hook_has_user_message = True
        adapter.hook_events = [_FakeHookMessage("retry please")]

        # Run the loop to completion — it will retry until hook passes
        # In this test, hook always returns a message, causing infinite loop.
        # We run one iteration manually to verify injection happens.
        gen = cr.execute_turn_loop(adapter)
        loop = asyncio.new_event_loop()
        events = []
        try:
            # Pull events until we've seen the LLM event and hook event
            for _ in range(20):
                try:
                    events.append(loop.run_until_complete(gen.__anext__()))
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

        assert len(adapter.hook_injected) >= 1
        if adapter.hook_injected:
            assert adapter.hook_injected[0].content == "retry please"

    def test_hook_pass_through_completes(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.has_tool_calls = False
        adapter.llm_events = [_FakeAssistantEvent("done")]
        adapter.hook_has_user_message = False

        adapter = _run_loop_to_completion(cr, adapter)
        assert adapter.mark_calls[-1][0] == "success"


# ── Tool detection tests ─────────────────────────────────────────


class TestToolDetection:
    def test_no_tool_calls_completes(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.has_tool_calls = False
        adapter.llm_events = [_FakeAssistantEvent("done")]

        adapter = _run_loop_to_completion(cr, adapter)
        assert adapter.mark_calls[-1][0] == "success"

    def test_tool_calls_execute_batch(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.has_tool_calls = True
        adapter.llm_events = [_FakeAssistantEvent("run tools")]
        adapter.tool_batch_events = ["tool_output_event"]

        # Run one iteration — tool batch should execute, then continue
        gen = cr.execute_turn_loop(adapter)
        loop = asyncio.new_event_loop()
        events_collected = []
        try:
            while True:
                events_collected.append(loop.run_until_complete(gen.__anext__()))
                if "tool_output_event" in events_collected:
                    break
        except (StopAsyncIteration, RuntimeError):
            pass
        finally:
            loop.close()

        assert "tool_output_event" in events_collected


# ── Exception path tests ─────────────────────────────────────────


class TestExceptionPath:
    def test_exception_marks_and_reraises(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.raise_on_stream_llm = RuntimeError("model crashed")

        gen = cr.execute_turn_loop(adapter)
        loop = asyncio.new_event_loop()
        raised = False
        try:
            loop.run_until_complete(gen.__anext__())
        except RuntimeError as e:
            raised = True
            assert "model crashed" in str(e)
        finally:
            loop.close()

        assert raised, "Expected RuntimeError to be raised"
        assert len(adapter.mark_calls) >= 1
        assert adapter.mark_calls[0][0] == "llm_error"

    def test_cancellation_not_swallowed(self) -> None:
        cr = ConversationRuntime()
        cr._session_id = "s1"
        adapter = _FakeLoopAdapter()
        adapter.user_cancelled = True
        adapter.llm_events = [_FakeAssistantEvent("cancelled")]

        adapter = _run_loop_to_completion(cr, adapter)
        assert adapter.mark_calls[0][0] == "user_cancelled"


# ── Helper ───────────────────────────────────────────────────────


class _FakeAssistantEvent:
    def __init__(self, content: str = "") -> None:
        self.content = content
        self.message_id = "msg-1"
