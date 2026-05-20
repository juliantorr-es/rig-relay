from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

Handler = Callable[[dict], Awaitable[None]]

_HANDLER_TIMEOUT = 5.0


class EventDispatcher:
    def __init__(self) -> None:
        self._subscriptions: list[tuple[str, Handler]] = []
        self._in_flight: set[str] = set()
        self._pending_tasks: set[asyncio.Task[None]] = set()

    async def publish(self, event: dict) -> None:
        event_id = event.get("event_id", "")
        event_type = event.get("event_type", "")
        if event_id and event_id in self._in_flight:
            return
        if event_id:
            self._in_flight.add(event_id)
        try:
            matching = [
                h for pat, h in self._subscriptions if event_type.startswith(pat)
            ]
            if not matching:
                return
            tasks: list[asyncio.Task[None]] = []
            for handler in matching:
                task = asyncio.create_task(self._run_handler(handler, event))
                tasks.append(task)
                self._pending_tasks.add(task)
            if tasks:
                done, _pending = await asyncio.wait(tasks)
                for t in done:
                    self._pending_tasks.discard(t)
                    if t.exception():
                        pass
        finally:
            if event_id:
                self._in_flight.discard(event_id)

    async def _run_handler(self, handler: Handler, event: dict) -> None:
        try:
            await asyncio.wait_for(handler(event), timeout=_HANDLER_TIMEOUT)
        except TimeoutError:
            pass
        except Exception:
            pass

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self._subscriptions.append((pattern, handler))

    def unsubscribe(self, pattern: str, handler: Handler) -> None:
        self._subscriptions = [
            (p, h)
            for p, h in self._subscriptions
            if not (p == pattern and h is handler)
        ]

    async def drain(self) -> None:
        remaining = list(self._pending_tasks)
        for task in remaining:
            task.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)
        self._pending_tasks.clear()
        self._in_flight.clear()


__all__ = ["EventDispatcher", "Handler"]
