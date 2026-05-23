from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from rig_relay.core.tool_executor.adapter_builder import ToolRuntimeAdapterBuilder
from rig_relay.core.tool_executor.concurrency import ToolConcurrencyManager
from rig_relay.core.tool_executor.context import ToolSessionContext, ToolTurnContext
from rig_relay.core.tool_executor.council_gate import CouncilGate
from rig_relay.core.tool_runtime_models import (
    ToolRuntimeExecutionMode,
    ToolRuntimeRequest,
    ToolRuntimeStatus,
)
from rig_relay.core.utils import (
    TOOL_ERROR_TAG,
    CancellationReason,
    get_user_cancellation_message,
)

if TYPE_CHECKING:
    from rig_relay.core.llm.format import ResolvedToolCall
    from rig_relay.core.types import ToolResultEvent, ToolStreamEvent


class ToolExecutor:
    """Orchestrates single-tool and concurrent tool execution.

    Composes adapter_builder, council_gate, and concurrency manager.
    Receives all runtime state via ToolSessionContext (session-scoped)
    and ToolTurnContext (per-batch) — no reach-through to AgentLoop internals.
    """

    __slots__ = (
        "_session_ctx",
        "_turn_ctx",
        "adapter_builder",
        "council_gate",
        "concurrency",
    )

    def __init__(
        self,
        *,
        session_ctx: ToolSessionContext,
        adapter_builder: ToolRuntimeAdapterBuilder,
        council_gate: CouncilGate,
        concurrency: ToolConcurrencyManager,
    ) -> None:
        self._session_ctx = session_ctx
        self._turn_ctx: ToolTurnContext | None = None
        self.adapter_builder = adapter_builder
        self.council_gate = council_gate
        self.concurrency = concurrency

    async def execute_one_tool(
        self, tool_call: ResolvedToolCall
    ) -> AsyncGenerator[ToolResultEvent | ToolStreamEvent]:
        """Execute a single tool call with span, council gating, and result adaptation."""
        session_ctx = self._session_ctx
        turn_ctx = self._turn_ctx
        assert turn_ctx is not None, "ToolTurnContext not set for batch execution"
        assert session_ctx.trace_runtime is not None, (
            "ToolSessionContext.trace_runtime not set"
        )
        assert session_ctx.tool_manager is not None, (
            "ToolSessionContext.tool_manager not set"
        )
        assert session_ctx.rewind_manager is not None, (
            "ToolSessionContext.rewind_manager not set"
        )
        assert session_ctx.result_sink is not None, (
            "ToolSessionContext.result_sink not set"
        )

        async with session_ctx.trace_runtime.tool_span(
            tool_name=tool_call.tool_name,
            call_id=tool_call.call_id,
            arguments=tool_call.validated_args.model_dump_json(),
        ) as span:
            runtime = self.adapter_builder.build_tool_runtime()
            tn = tool_call.tool_name
            cid = tool_call.call_id

            exec_mode = ToolRuntimeExecutionMode.UNKNOWN
            if tool_call.tool_class is not None:
                mut_cls = getattr(tool_call.tool_class, "mutation_class", None)
                if mut_cls is not None:
                    mut_str = (
                        str(mut_cls.value)
                        if hasattr(mut_cls, "value")
                        else str(mut_cls)
                    )
                    if "execution" in mut_str.lower():
                        exec_mode = ToolRuntimeExecutionMode.MUTATION_EXECUTION
                    elif "proposal" in mut_str.lower():
                        exec_mode = ToolRuntimeExecutionMode.MUTATION_PROPOSAL
                else:
                    exec_mode = ToolRuntimeExecutionMode.READ_ONLY

            try:
                session_ctx.tool_manager.get(tn)
            except Exception as exc:
                yield self._tool_failure_event(
                    tool_call, f"Error getting tool '{tn}': {exc}", span=span
                )
                return

            request = ToolRuntimeRequest(
                tool_name=tn,
                tool_args=tool_call.args_dict,
                tool_call_id=cid,
                turn_id=turn_ctx.user_message_id,
                session_id=session_ctx.session_id,
                execution_mode=exec_mode,
                bypass_permissions=turn_ctx.bypass_permissions,
            )

            try:
                of_interest = session_ctx.tool_manager.get(tn)
                snapshot = of_interest.get_file_snapshot(tool_call.validated_args)
                if snapshot is not None:
                    session_ctx.rewind_manager.add_snapshot(snapshot)
            except Exception:
                pass

            recommendation = await self.council_gate.consult(
                tn, tool_call.args_dict, tool_call.tool_class, turn_ctx
            )
            if recommendation == "BLOCK":
                turn = turn_ctx.current_turn
                if turn is not None:
                    turn.tool_skip_count += 1
                from rig_relay.core.types import ToolResultEvent as TRE

                yield TRE(
                    tool_name=tn,
                    tool_class=tool_call.tool_class,
                    skipped=True,
                    skip_reason="Council consultation blocked this mutation",
                    cancelled=False,
                    tool_call_id=cid,
                )
                return
            if recommendation == "REVIEW" and session_ctx.approval_callback is not None:
                from rig_relay.core.types import ApprovalResponse

                response, feedback = await session_ctx.approval_callback(
                    tn, tool_call.validated_args, cid, []
                )
                if response != ApprovalResponse.YES:
                    turn = turn_ctx.current_turn
                    if turn is not None:
                        turn.tool_skip_count += 1
                    from rig_relay.core.types import ToolResultEvent as TRE

                    yield TRE(
                        tool_name=tn,
                        tool_class=tool_call.tool_class,
                        skipped=True,
                        skip_reason=feedback or "Council review not approved by user",
                        cancelled=False,
                        tool_call_id=cid,
                    )
                    return

            try:
                result = await runtime.execute_one(request)
            except asyncio.CancelledError:
                cancel = str(
                    get_user_cancellation_message(CancellationReason.TOOL_INTERRUPTED)
                )
                turn = turn_ctx.current_turn
                if turn is not None:
                    turn.tool_failure_count += 1
                yield self._tool_failure_event(
                    tool_call, cancel, None, cancelled=True, span=span
                )
                raise

            turn = turn_ctx.current_turn
            if turn is not None and result.duration_ms is not None:
                turn.tool_total_duration_ms += result.duration_ms

            match result.status:
                case ToolRuntimeStatus.CACHED:
                    from rig_relay.core.types import ToolResultEvent as TRE

                    cached_event = TRE(
                        tool_name=tn,
                        tool_class=tool_call.tool_class,
                        result=result.provider_tool_response,
                        cached=True,
                        tool_call_id=cid,
                    )
                    if turn is not None:
                        turn.tool_success_count += 1
                    session_ctx.result_sink.record(result)
                    yield cached_event

                case ToolRuntimeStatus.COMPLETED | ToolRuntimeStatus.DEGRADED:
                    for ev in result.tool_events:
                        yield ev

                    response_model = result.provider_tool_response
                    duration_sec = (
                        result.duration_ms / 1000 if result.duration_ms else 0
                    )

                    text = ""
                    result_dict: dict[str, Any] = {}
                    if response_model is not None and hasattr(
                        response_model, "model_dump"
                    ):
                        result_dict = response_model.model_dump()
                        text = "\n".join(f"{k}: {v}" for k, v in result_dict.items())
                        try:
                            of_interest = session_ctx.tool_manager.get(tn)
                            extra = of_interest.get_result_extra(response_model)
                            if extra:
                                text += "\n\n" + extra
                        except Exception:
                            pass

                    if session_ctx.handle_tool_response is not None:
                        session_ctx.handle_tool_response(
                            tool_call=tool_call,
                            text=text,
                            status="success",
                            result=result_dict,
                            span=span,
                            duration_ms=duration_sec * 1000,
                        )

                    from rig_relay.core.types import ToolResultEvent as TRE

                    yield TRE(
                        tool_name=tn,
                        tool_class=tool_call.tool_class,
                        result=response_model,
                        cancelled=(
                            getattr(response_model, "cancelled", False)
                            if response_model is not None
                            else False
                        ),
                        duration=duration_sec,
                        tool_call_id=cid,
                    )
                    if turn is not None:
                        turn.tool_success_count += 1
                    session_ctx.result_sink.record(result)

                case ToolRuntimeStatus.REFUSED:
                    refusal = result.refusal
                    reason_text = (
                        refusal.message if refusal else "Tool execution refused"
                    )
                    from rig_relay.core.types import ToolResultEvent as TRE

                    skip_event = TRE(
                        tool_name=tn,
                        tool_class=tool_call.tool_class,
                        skipped=True,
                        skip_reason=reason_text,
                        cancelled=False,
                        tool_call_id=cid,
                    )
                    if turn is not None:
                        turn.tool_skip_count += 1
                    yield skip_event
                    if session_ctx.handle_tool_response is not None:
                        session_ctx.handle_tool_response(
                            tool_call=tool_call,
                            text=reason_text,
                            status="skipped",
                            span=span,
                        )
                    session_ctx.result_sink.record(result)

                case ToolRuntimeStatus.FAILED:
                    error_msg = (
                        f"<{TOOL_ERROR_TAG}>{tn} failed: "
                        f"{result.error_message or ''}</{TOOL_ERROR_TAG}>"
                    )
                    if turn is not None:
                        turn.tool_failure_count += 1
                    yield self._tool_failure_event(
                        tool_call, error_msg, None, span=span
                    )
                    session_ctx.result_sink.record(result)

                case _:
                    error_msg = (
                        f"<{TOOL_ERROR_TAG}>{tn}: unknown status "
                        f"{result.status}</{TOOL_ERROR_TAG}>"
                    )
                    if turn is not None:
                        turn.tool_failure_count += 1
                    yield self._tool_failure_event(
                        tool_call, error_msg, None, span=span
                    )

    def _tool_failure_event(
        self,
        tool_call: ResolvedToolCall,
        error_msg: str,
        decision: Any = None,
        cancelled: bool = False,
        span: Any = None,
    ) -> Any:
        session_ctx = self._session_ctx
        if session_ctx.handle_tool_response is not None:
            session_ctx.handle_tool_response(
                tool_call=tool_call, text=error_msg, status="failure", span=span
            )
        from rig_relay.core.types import ToolResultEvent

        return ToolResultEvent(
            tool_name=tool_call.tool_name,
            tool_class=tool_call.tool_class,
            error=error_msg,
            cancelled=cancelled,
            tool_call_id=tool_call.call_id,
        )

    async def execute_batch(
        self, resolved: Any, turn_ctx: ToolTurnContext
    ) -> AsyncGenerator[Any]:
        """Execute the full tool batch: failed events, tool-call events,
        concurrent execution, and passive auto-GC.
        """
        session_ctx = self._session_ctx
        self._turn_ctx = turn_ctx
        self.adapter_builder.set_turn_context(turn_ctx)
        try:
            for failed in resolved.failed_calls:
                error_msg = (
                    f"<{TOOL_ERROR_TAG}>{failed.tool_name}: {failed.error}"
                    f"</{TOOL_ERROR_TAG}>"
                )
                from rig_relay.core.types import ToolResultEvent

                yield ToolResultEvent(
                    tool_name=failed.tool_name,
                    tool_class=None,
                    error=error_msg,
                    tool_call_id=failed.call_id,
                )
                if session_ctx.stats is not None:
                    session_ctx.stats.tool_calls_failed += 1

            if not resolved.tool_calls:
                return

            for tc in resolved.tool_calls:
                from rig_relay.core.types import ToolCallEvent as TCE

                yield TCE(
                    tool_name=tc.tool_name,
                    tool_class=tc.tool_class,
                    args=tc.validated_args,
                    tool_call_id=tc.call_id,
                )

            async for event in self.execute_concurrently(resolved.tool_calls):
                yield event

            from rig_relay.core._auto_gc import maybe_auto_gc

            assert session_ctx.workspace_root is not None, (
                "ToolSessionContext.workspace_root not set"
            )
            await maybe_auto_gc(
                session_ctx.config, session_ctx.workspace_root, session_ctx.stats
            )
        finally:
            self._turn_ctx = None
            self.adapter_builder.clear_turn_context()

    async def execute_concurrently(
        self, tool_calls: list[ResolvedToolCall]
    ) -> AsyncGenerator[ToolResultEvent | ToolStreamEvent]:
        """Execute multiple tool calls concurrently, yielding events as they arrive."""
        async for event in self.concurrency.execute_concurrently(
            tool_calls, self.execute_one_tool
        ):
            yield event
