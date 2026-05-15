"""ToolRuntime — governed tool execution boundary.

ToolRuntime owns the policy for tool execution: cache lookup,
permission enforcement, approval dispatch, patch proposal gating,
tool invocation, result classification, receipt emission, cache
storage, and context observation.

AgentLoop remains the turn conductor. It builds a
ToolRuntimeRequest, calls ToolRuntime.execute_one(), receives a
structured ToolRuntimeResult, adapts events, and records telemetry.

Graceful degradation is first-class: failures, refusals, cache
unavailability, receipt unavailability, and timeouts all produce
typed ToolRuntimeResult values.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from rig_relay.core.logger import logger
from rig_relay.core.tool_runtime_models import (
    RefusalCode,
    ToolRuntimeApprovalStatus,
    ToolRuntimeCacheStatus,
    ToolRuntimeRefusal,
    ToolRuntimeRequest,
    ToolRuntimeResult,
    ToolRuntimeStatus,
)
from rig_relay.core.tools.base import ToolPermissionError

# ── Callback signatures for dependency injection ──────────────────────


InvokeToolFn = Callable[[dict[str, Any]], AsyncGenerator[Any, None]]
"""Async generator yielding tool stream events then the final result model."""

CacheCheckFn = Callable[[str, dict[str, Any]], tuple[bool, Any | None]]

CacheStoreFn = Callable[[str, dict[str, Any], dict[str, Any]], None]

PermissionDecisionFn = Callable[[str, dict[str, Any], str], Awaitable[tuple[bool, str]]]
"""Returns (permitted: bool, reason: str). Skip reasons are returned as non-permitted."""

ApprovalRequestFn = Callable[
    [str, dict[str, Any], str], Awaitable[tuple[bool, str]]
]

PatchGateCheckFn = Callable[[Any, Any], Any | None]
"""Returns a gating event if blocked, None if allowed. Takes (tool_call, tool_instance)."""

ExpandArgsFn = Callable[[dict[str, Any]], dict[str, Any]]

ReceiptBuildFn = Callable[[str, Any], Any | None]
"""Returns a receipt model or None. Takes (tool_name, result_model)."""

ReceiptCaptureFn = Callable[[str, str, dict[str, Any]], None]

ContextObserveFn = Callable[[str, str, dict[str, Any], bool], None]

StatsDeltaFn = Callable[[str, int], None]


async def _async_allow() -> tuple[bool, str]:
    return True, ""


class ToolRuntime:
    """Governed tool execution runtime.

    All I/O goes through injected callables. ToolRuntime owns the
    governance sequence:

        cache → permission → approval → patch gate → invoke →
        receipt → cache store → context observation → result

    AgentLoop only builds the request, calls execute_one(), adapts
    the returned events, and records provider telemetry.
    """

    def __init__(
        self,
        *,
        invoke_tool: InvokeToolFn | None = None,
        cache_check: CacheCheckFn | None = None,
        cache_store: CacheStoreFn | None = None,
        permission_decision: PermissionDecisionFn | None = None,
        approval_request: ApprovalRequestFn | None = None,
        patch_gate_check: PatchGateCheckFn | None = None,
        expand_args: ExpandArgsFn | None = None,
        receipt_build: ReceiptBuildFn | None = None,
        receipt_capture: ReceiptCaptureFn | None = None,
        context_observe: ContextObserveFn | None = None,
        stats_delta: StatsDeltaFn | None = None,
    ) -> None:
        self._invoke_tool = invoke_tool or self._default_invoke_tool
        self._cache_check = cache_check or (lambda t, a: (False, None))
        self._cache_store = cache_store or (lambda t, a, r: None)
        self._permission_decision = permission_decision or (
            lambda t, a, c: _async_allow()
        )
        self._approval_request = approval_request or (
            lambda t, a, c: _async_allow()
        )
        self._patch_gate_check = patch_gate_check or (lambda tc, ti: None)
        self._expand_args = expand_args or (lambda a: a)
        self._receipt_build = receipt_build or (lambda tn, rm: None)
        self._receipt_capture = receipt_capture or (lambda s, t, r: None)
        self._context_observe = context_observe or (
            lambda s, tn, a, bp: None
        )
        self._stats_delta = stats_delta or (lambda k, d: None)

    # ── Public API ──────────────────────────────────────────────────

    async def execute_one(
        self, request: ToolRuntimeRequest
    ) -> ToolRuntimeResult:
        """Execute a single tool call with full governance sequencing.

        Owns the entire path: cache → permission → approval →
        patch gate → invoke → receipt → cache store →
        context observation → classified result.

        Returns a structured ToolRuntimeResult. Events produced
        during invocation are collected in ``result.tool_events``
        for AgentLoop to forward.

        Never raises — all failures become FAILED or REFUSED results.
        """
        try:
            return await self._execute_governed(request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "ToolRuntime unexpected error for %s: %s",
                request.tool_name,
                exc,
                exc_info=True,
            )
            return ToolRuntimeResult.failed(
                tool_name=request.tool_name,
                tool_call_id=request.tool_call_id,
                error_kind="unexpected_runtime_error",
                error_message=str(exc)[:500],
                degraded_capabilities=["tool_runtime_internal_error"],
            )

    # ── Internal sequence ───────────────────────────────────────────

    async def _execute_governed(
        self, request: ToolRuntimeRequest
    ) -> ToolRuntimeResult:
        tn = request.tool_name
        cid = request.tool_call_id

        # ── 1. Cache check ──────────────────────────────────────
        hit, cached = self._cache_check(tn, request.tool_args)
        if hit and cached is not None:
            self._stats_delta("tool_calls_succeeded", 1)
            return ToolRuntimeResult.cached_result(
                tool_name=tn, tool_call_id=cid, provider_tool_response=cached
            )

        # ── 2. Permission check ─────────────────────────────────
        if not request.bypass_permissions:
            permitted, reason = await self._permission_decision(
                tn, request.tool_args, cid
            )
            if not permitted:
                self._stats_delta("tool_calls_rejected", 1)
                return ToolRuntimeResult.refused(
                    tool_name=tn,
                    tool_call_id=cid,
                    refusal=ToolRuntimeRefusal(
                        refusal_code=RefusalCode.TOOL_PERMISSION_DENIED,
                        message=reason or f"Permission denied for '{tn}'",
                        recoverable=True,
                        suggested_next_action="Adjust tool permissions or request approval",
                    ),
                    approval_status=ToolRuntimeApprovalStatus.DENIED,
                )

        # ── 3. Approval request ─────────────────────────────────
        approved, reason = await self._approval_request(
            tn, request.tool_args, cid
        )
        if not approved:
            self._stats_delta("tool_calls_rejected", 1)
            return ToolRuntimeResult.refused(
                tool_name=tn,
                tool_call_id=cid,
                refusal=ToolRuntimeRefusal(
                    refusal_code=RefusalCode.APPROVAL_DENIED,
                    message=reason or f"Approval denied for '{tn}'",
                    recoverable=True,
                    suggested_next_action="Request user approval",
                ),
                approval_status=ToolRuntimeApprovalStatus.DENIED,
            )

        # ── 4. Patch gate ───────────────────────────────────────
        gating = self._patch_gate_check(request, None)
        if gating is not None:
            self._stats_delta("tool_calls_rejected", 1)
            return ToolRuntimeResult.refused(
                tool_name=tn,
                tool_call_id=cid,
                refusal=ToolRuntimeRefusal(
                    refusal_code=RefusalCode.PATCH_PROPOSAL_REQUIRED,
                    message="Patch proposal required for mutation tool",
                    recoverable=True,
                    suggested_next_action="Submit a patch proposal instead",
                ),
                approval_status=ToolRuntimeApprovalStatus.NOT_REQUIRED,
            )

        self._stats_delta("tool_calls_agreed", 1)

        # ── 5. Invoke tool ──────────────────────────────────────
        expanded_args = self._expand_args(request.tool_args)
        expanded_args["_tool_runtime_name"] = tn
        expanded_args["_tool_runtime_call_id"] = cid
        tool_events: list[Any] = []
        result_model = None
        start_time = asyncio.get_event_loop().time()

        try:
            async for item in self._invoke_tool(expanded_args):
                if hasattr(item, "model_dump"):
                    result_model = item
                else:
                    tool_events.append(item)
        except asyncio.CancelledError:
            raise
        except ToolPermissionError:
            self._stats_delta("tool_calls_agreed", -1)
            self._stats_delta("tool_calls_rejected", 1)
            return ToolRuntimeResult.refused(
                tool_name=tn,
                tool_call_id=cid,
                refusal=ToolRuntimeRefusal(
                    refusal_code=RefusalCode.TOOL_PERMISSION_DENIED,
                    message=f"ToolPermissionError during '{tn}'",
                    recoverable=False,
                ),
                approval_status=ToolRuntimeApprovalStatus.DENIED,
            )
        except Exception as exc:
            self._stats_delta("tool_calls_failed", 1)
            return ToolRuntimeResult.failed(
                tool_name=tn,
                tool_call_id=cid,
                error_kind="tool_invocation_failed",
                error_message=f"{tn} failed: {exc}"[:500],
                refusal=ToolRuntimeRefusal(
                    refusal_code=RefusalCode.TOOL_INVOCATION_FAILED,
                    message=str(exc)[:200],
                    recoverable=True,
                ),
            )

        duration = asyncio.get_event_loop().time() - start_time

        if result_model is None:
            self._stats_delta("tool_calls_failed", 1)
            return ToolRuntimeResult.failed(
                tool_name=tn,
                tool_call_id=cid,
                error_kind="tool_invocation_failed",
                error_message="Tool did not yield a result",
                refusal=ToolRuntimeRefusal(
                    refusal_code=RefusalCode.TOOL_INVOCATION_FAILED,
                    message="Tool did not yield a result",
                    recoverable=False,
                ),
            )

        # ── 6. Receipt ──────────────────────────────────────────
        try:
            receipt = self._receipt_build(tn, result_model)
            if receipt is not None:
                self._receipt_capture(
                    request.session_id or "",
                    tn,
                    receipt.model_dump(mode="json"),
                )
        except Exception:
            logger.warning("Receipt capture failed for %s", tn, exc_info=True)

        # ── 7. Cache store ──────────────────────────────────────
        cache_status = ToolRuntimeCacheStatus.MISS
        try:
            self._cache_store(
                tn,
                request.tool_args,
                result_model.model_dump(mode="json"),
            )
        except Exception:
            cache_status = ToolRuntimeCacheStatus.WRITE_FAILED

        # ── 8. Context observation ──────────────────────────────
        obs_status = "succeeded"
        try:
            self._context_observe("succeeded", tn, request.tool_args, False)
        except Exception:
            obs_status = "context_observation_failed"

        # ── 9. Classify result ──────────────────────────────────
        self._stats_delta("tool_calls_succeeded", 1)

        degraded: list[str] = []
        if cache_status == ToolRuntimeCacheStatus.WRITE_FAILED:
            degraded.append("cache_write_failed")
        if obs_status == "context_observation_failed":
            degraded.append("context_observation_failed")

        status = (
            ToolRuntimeStatus.DEGRADED
            if degraded
            else ToolRuntimeStatus.COMPLETED
        )

        return ToolRuntimeResult(
            status=status,
            tool_name=tn,
            tool_call_id=cid,
            provider_tool_response=result_model,
            tool_events=tool_events,
            cache_status=cache_status,
            approval_status=ToolRuntimeApprovalStatus.APPROVED,
            context_observation_status=obs_status,
            execution_enabled=True,
            mutation_performed=False,
            degraded_capabilities=degraded,
            duration_ms=duration * 1000,
            receipt_refs=[],
        )

    @staticmethod
    async def _default_invoke_tool(
        args_dict: dict[str, Any],
    ) -> AsyncGenerator[Any, None]:
        if False:
            yield
