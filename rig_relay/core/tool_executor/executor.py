from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from rig_relay.core.tool_executor.adapter_builder import ToolRuntimeAdapterBuilder
from rig_relay.core.tool_executor.concurrency import ToolConcurrencyManager
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
    from rig_relay.core.agent_loop import AgentLoop
    from rig_relay.core.llm.format import ResolvedToolCall
    from rig_relay.core.types import ToolResultEvent, ToolStreamEvent


class ToolExecutor:
    """Orchestrates single-tool execution and concurrent tool execution.

    Composes ToolRuntimeAdapterBuilder, CouncilGate, and
    ToolConcurrencyManager. Owns the full execution flow from
    request building through result adaptation.

    Replaces AgentLoop._execute_tool_call, _process_one_tool_call,
    _run_tools_concurrently, and _execute_tool_to_queue.
    """

    __slots__ = ("_loop", "adapter_builder", "council_gate", "concurrency")

    def __init__(
        self,
        *,
        loop: AgentLoop,
        adapter_builder: ToolRuntimeAdapterBuilder,
        council_gate: CouncilGate,
        concurrency: ToolConcurrencyManager,
    ) -> None:
        self._loop: AgentLoop = loop
        self.adapter_builder = adapter_builder
        self.council_gate = council_gate
        self.concurrency = concurrency

    async def execute_one_tool(
        self, tool_call: ResolvedToolCall
    ) -> AsyncGenerator[ToolResultEvent | ToolStreamEvent]:
        """Execute a single tool call with span, council gating, and result adaptation."""
        loop = self._loop

        async with loop._trace_runtime.tool_span(
            tool_name=tool_call.tool_name,
            call_id=tool_call.call_id,
            arguments=tool_call.validated_args.model_dump_json(),
        ) as span:
            runtime = self.adapter_builder.build_tool_runtime()
            tn = tool_call.tool_name
            cid = tool_call.call_id

            # ── Build request ───────────────────────────────────────
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
                loop.tool_manager.get(tn)
            except Exception as exc:
                yield loop._tool_failure_event(
                    tool_call, f"Error getting tool '{tn}': {exc}", span=span
                )
                return

            request = ToolRuntimeRequest(
                tool_name=tn,
                tool_args=tool_call.args_dict,
                tool_call_id=cid,
                turn_id=loop._current_user_message_id,
                session_id=loop.session_id,
                execution_mode=exec_mode,
                bypass_permissions=loop.bypass_tool_permissions,
            )

            # ── Rewind snapshot (pre-invocation) ─────────────────────
            try:
                of_interest = loop.tool_manager.get(tn)
                snapshot = of_interest.get_file_snapshot(tool_call.validated_args)
                if snapshot is not None:
                    loop.rewind_manager.add_snapshot(snapshot)
            except Exception:
                pass

            # ── Council consultation (pre-mutation) ──────────────────
            recommendation = await self.council_gate.consult(
                tn, tool_call.args_dict, tool_call.tool_class
            )
            if recommendation == "BLOCK":
                turn = getattr(loop, "_current_turn", None)
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
            if recommendation == "REVIEW" and loop.approval_callback is not None:
                from rig_relay.core.types import ApprovalResponse

                response, feedback = await loop.approval_callback(
                    tn, tool_call.validated_args, cid, []
                )
                if response != ApprovalResponse.YES:
                    turn = getattr(loop, "_current_turn", None)
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

            # ── Governed execution ───────────────────────────────────
            try:
                result = await runtime.execute_one(request)
            except asyncio.CancelledError:
                cancel = str(
                    get_user_cancellation_message(CancellationReason.TOOL_INTERRUPTED)
                )
                turn = getattr(loop, "_current_turn", None)
                if turn is not None:
                    turn.tool_failure_count += 1
                yield loop._tool_failure_event(
                    tool_call, cancel, None, cancelled=True, span=span
                )
                raise

            # ── Adapt result ─────────────────────────────────────────
            turn = getattr(loop, "_current_turn", None)
            if turn is not None:
                if result.duration_ms is not None:
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
                    loop._tool_result_sink.record(result)
                    yield cached_event
                    return

                case ToolRuntimeStatus.COMPLETED | ToolRuntimeStatus.DEGRADED:
                    for ev in result.tool_events:
                        yield ev

                    response_model = result.provider_tool_response
                    duration_sec = (
                        result.duration_ms / 1000 if result.duration_ms else 0
                    )

                    if response_model is not None and hasattr(
                        response_model, "model_dump"
                    ):
                        result_dict = response_model.model_dump()
                        text = "\n".join(f"{k}: {v}" for k, v in result_dict.items())
                        try:
                            of_interest = loop.tool_manager.get(tn)
                            extra = of_interest.get_result_extra(response_model)
                            if extra:
                                text += "\n\n" + extra
                        except Exception:
                            pass

                        loop._handle_tool_response(
                            tool_call,
                            text,
                            "success",
                            None,
                            result_dict,
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
                    loop._tool_result_sink.record(result)
                    return

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
                    loop._handle_tool_response(
                        tool_call, reason_text, "skipped", None, span=span
                    )
                    loop._tool_result_sink.record(result)
                    return

                case ToolRuntimeStatus.FAILED:
                    error_msg = (
                        f"<{TOOL_ERROR_TAG}>{tn} failed: "
                        f"{result.error_message or ''}</{TOOL_ERROR_TAG}>"
                    )
                    if turn is not None:
                        turn.tool_failure_count += 1
                    yield loop._tool_failure_event(
                        tool_call, error_msg, None, span=span
                    )
                    loop._tool_result_sink.record(result)
                    return

                case _:
                    error_msg = (
                        f"<{TOOL_ERROR_TAG}>{tn}: unknown status "
                        f"{result.status}</{TOOL_ERROR_TAG}>"
                    )
                    if turn is not None:
                        turn.tool_failure_count += 1
                    yield loop._tool_failure_event(
                        tool_call, error_msg, None, span=span
                    )

    async def execute_batch(self, resolved: Any) -> AsyncGenerator[Any]:
        """Execute the full tool batch: failed events, tool-call events, concurrent
        execution, and passive auto-GC.

        Delegates failed-tool-event emission to the AgentLoop's
        ``_emit_failed_tool_events`` and concurrent execution to
        ``execute_concurrently``.  After all tools finish, runs passive GC
        via ``maybe_auto_gc`` if the storage budget is over threshold.
        """
        loop = self._loop

        async for event in loop._emit_failed_tool_events(resolved.failed_calls):
            yield event

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

        await maybe_auto_gc(loop.config, loop._workspace_root, loop.stats)

    async def execute_concurrently(
        self, tool_calls: list[ResolvedToolCall]
    ) -> AsyncGenerator[ToolResultEvent | ToolStreamEvent]:
        """Execute multiple tool calls concurrently, yielding events as they arrive."""
        async for event in self.concurrency.execute_concurrently(
            tool_calls, self.execute_one_tool
        ):
            yield event
