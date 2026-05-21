from __future__ import annotations

from typing import TYPE_CHECKING, Any

_COUNCIL_MUTATION_TOOLS = frozenset({
    "BashTool",
    "WriteFileTool",
    "SearchReplaceTool",
    "CheckpointTool",
})

if TYPE_CHECKING:
    from rig_relay.core.tool_executor.context import ToolExecutionContext
    from rig_relay.core.tools.base import BaseTool


class CouncilGate:
    """Pre-mutation council consultation gate.

    Checks capability gate and multi-provider availability before
    allowing mutation tool execution. Fail-closed: unknown tools,
    blocked gates, missing providers, and consultation errors all
    result in REVIEW or BLOCK rather than ALLOW.

    Receives all runtime state via ToolExecutionContext — no
    reach-through to AgentLoop internals.
    """

    __slots__ = ("_ctx",)

    def __init__(self, *, ctx: ToolExecutionContext) -> None:
        self._ctx = ctx

    def _get_telemetry_client(self) -> Any | None:
        return getattr(self._ctx, "telemetry_client", None)

    async def consult(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_class: type[BaseTool] | None,
    ) -> str:
        """Return ALLOW, BLOCK, or REVIEW. Never ALLOW on failure."""
        ctx = self._ctx
        turn_id = ctx.user_message_id
        tc = self._get_telemetry_client()

        if tool_class is None:
            from rig_relay.core.logger import logger

            logger.warning(
                "governance.degraded: reason=council_unknown_tool session=%s turn=%s",
                ctx.session_id,
                turn_id,
            )
            if tc is not None:
                tc.emit_governance_gate_decision(
                    gate="council",
                    decision="review",
                    reason="council_unknown_tool",
                    tool_name=tool_name,
                    severity="warning",
                    turn_id=turn_id or "",
                )
            return "REVIEW"
        if tool_class.__name__ not in _COUNCIL_MUTATION_TOOLS:
            if tc is not None:
                tc.emit_governance_gate_decision(
                    gate="council",
                    decision="allowed",
                    reason="non_mutation_tool",
                    tool_name=tool_name,
                    severity="info",
                    turn_id=turn_id or "",
                )
            return "ALLOW"

        try:
            from rig_relay.governance.service_state import get_capability_gate

            gate = get_capability_gate()
            allowed, _ = gate.is_allowed("council_consult")
            if not allowed:
                from rig_relay.core.logger import logger

                logger.warning(
                    "governance.degraded: reason=council_gate_blocked session=%s turn=%s",
                    ctx.session_id,
                    turn_id,
                )
                if tc is not None:
                    tc.emit_governance_gate_decision(
                        gate="council",
                        decision="blocked",
                        reason="council_gate_blocked",
                        tool_name=tool_name,
                        severity="warning",
                        mutation_intent=True,
                        turn_id=turn_id or "",
                    )
                return "BLOCK"
        except Exception:
            from rig_relay.core.logger import logger

            logger.warning(
                "governance.degraded: reason=council_gate_unavailable session=%s turn=%s",
                ctx.session_id,
                turn_id,
            )
            if tc is not None:
                tc.emit_governance_gate_decision(
                    gate="council",
                    decision="blocked",
                    reason="council_gate_unavailable",
                    tool_name=tool_name,
                    severity="warning",
                    mutation_intent=True,
                    turn_id=turn_id or "",
                )
            return "BLOCK"

        configured_providers = [p.name for p in getattr(ctx.config, "providers", [])]
        if len(configured_providers) <= 1:
            from rig_relay.core.logger import logger

            logger.warning(
                "governance.degraded: reason=council_single_provider session=%s turn=%s",
                ctx.session_id,
                turn_id,
            )
            if tc is not None:
                tc.emit_governance_gate_decision(
                    gate="council",
                    decision="review",
                    reason="council_single_provider",
                    tool_name=tool_name,
                    severity="warning",
                    turn_id=turn_id or "",
                )
            return "REVIEW"

        try:
            from rig_relay.coordination.council_invoker import (
                consult_council_before_mutation,
                determine_council_recommendation,
            )

            context_summary = f"Tool: {tool_name}. Turn: {turn_id or 'unknown'}."
            receipt = await consult_council_before_mutation(
                tool_name=tool_name,
                tool_args=tool_args,
                context_summary=context_summary,
                providers=configured_providers,
                redaction="standard",
            )
            recommendation = determine_council_recommendation(receipt)
            if tc is not None:
                tc.emit_governance_gate_decision(
                    gate="council",
                    decision="allowed" if recommendation == "ALLOW" else "review",
                    reason=f"council_consultation_complete_{recommendation.lower()}",
                    tool_name=tool_name,
                    mutation_intent=True,
                    severity="info",
                    turn_id=turn_id or "",
                )
            return recommendation
        except Exception as exc:
            from rig_relay.core.logger import logger

            logger.warning(
                "governance.degraded: reason=council_consultation_failed session=%s turn=%s error=%s",
                ctx.session_id,
                turn_id,
                exc,
            )
            if tc is not None:
                tc.emit_governance_gate_decision(
                    gate="council",
                    decision="failed_closed",
                    reason="council_consultation_failed",
                    tool_name=tool_name,
                    severity="critical",
                    mutation_intent=True,
                    turn_id=turn_id or "",
                )
            return "REVIEW"
