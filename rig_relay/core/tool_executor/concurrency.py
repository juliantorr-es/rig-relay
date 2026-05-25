from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
import contextlib
from typing import Any


class ToolConcurrencyManager:
    """Run tool calls concurrently via asyncio.Queue with cancellation propagation.

    Replaces AgentLoop._run_tools_concurrently and _execute_tool_to_queue.
    """

    __slots__ = ()

    def __init__(self) -> None:
        pass

    async def execute_concurrently(
        self,
        tool_calls: list[Any],
        execute_one: Callable[[Any], AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        queue: asyncio.Queue[Any] = asyncio.Queue()

        async def _run_one_and_queue(tc: Any) -> None:
            async for event in execute_one(tc):
                await queue.put(event)

        tasks = [asyncio.create_task(_run_one_and_queue(tc)) for tc in tool_calls]

        async def _signal_when_all_done() -> None:
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, Exception) and not isinstance(
                        r, asyncio.CancelledError
                    ):
                        # Surface non-cancellation child-task exceptions
                        # through the queue so the consumer can react.
                        # ToolObservationDeliveryError must abort the batch.
                        await queue.put(r)
            finally:
                await queue.put(None)

        monitor = asyncio.create_task(_signal_when_all_done())

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                if isinstance(event, Exception):
                    raise event
                yield event
        except GeneratorExit:
            for t in tasks:
                if not t.done():
                    t.cancel()
            raise
        except asyncio.CancelledError:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            if not monitor.done():
                monitor.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await monitor
