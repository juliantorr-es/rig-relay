"""AgentLoop helper functions and decorators."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from http import HTTPStatus
import inspect
from typing import TYPE_CHECKING, Any

from rig_relay.core.llm.exceptions import BackendError

if TYPE_CHECKING:
    from rig_relay.core.agent_loop import AgentLoop


def _should_raise_rate_limit_error(e: Exception) -> bool:
    return isinstance(e, BackendError) and e.status == HTTPStatus.TOO_MANY_REQUESTS


def _is_context_too_long_error(e: Exception) -> bool:
    if isinstance(e, BackendError):
        return e.is_context_too_long
    if isinstance(e, RuntimeError) and isinstance(e.__cause__, BackendError):
        return e.__cause__.is_context_too_long
    return False


def _is_non_retryable_error(e: BaseException) -> bool:
    """Detect Temporal-style non_retryable flag without importing temporalio."""
    seen: set[int] = set()
    current: BaseException | None = e
    while current is not None and id(current) not in seen:
        if getattr(current, "non_retryable", False):
            return True
        seen.add(id(current))
        current = current.__cause__
    return False


def requires_init(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that awaits deferred initialization before executing the method."""
    if inspect.isasyncgenfunction(fn):

        @wraps(fn)
        async def gen_wrapper(self: AgentLoop, *args: Any, **kwargs: Any) -> Any:
            await self.wait_until_ready()
            agen = fn(self, *args, **kwargs)
            sent: Any = None
            try:
                while True:
                    sent = yield await agen.asend(sent)
            except StopAsyncIteration:
                return
            finally:
                await agen.aclose()

        return gen_wrapper

    @wraps(fn)
    async def wrapper(self: AgentLoop, *args: Any, **kwargs: Any) -> Any:
        await self.wait_until_ready()
        return await fn(self, *args, **kwargs)

    return wrapper
