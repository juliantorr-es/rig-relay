from __future__ import annotations

from typing import TYPE_CHECKING, Any

_COUNCIL_MUTATION_TOOLS = frozenset({
    "BashTool",
    "WriteFileTool",
    "SearchReplaceTool",
    "CheckpointTool",
})

if TYPE_CHECKING:
    from rig_relay.core.agent_loop import AgentLoop
    from rig_relay.core.tools.base import BaseTool


class CouncilGate:
    """Pre-mutation council consultation gate.

    Checks capability gate and multi-provider availability before
    allowing mutation tool execution. Fail-closed: unknown tools,
    blocked gates, missing providers, and consultation errors all
    result in REVIEW or BLOCK rather than ALLOW.
    """

    __slots__ = ("_loop",)

    def __init__(self, *, loop: AgentLoop) -> None:
        self._loop: AgentLoop = loop

    def _get_telemetry_client(self) -> Any | None:
        return getattr(self._loop, "telemetry_client", None)

    async def consult(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_class: type[BaseTool] | None,
    ) -> str:
        """Return ALLOW, BLOCK, or REVIEW. Never ALLOW on failure."""
        loop = self._loop
        turn_id = getattr(loop, "_current_user_message_id", None)
        tc = self._get_telemetry_client()

        if tool_class is None:
            from rig_relay.core.logger import logger

            logger.warning(
                "governance.degraded: reason=council_unknown_tool session=%s turn=%s",
                loop.session_id,
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
                    loop.session_id,
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
                loop.session_id,
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

        configured_providers = [p.name for p in getattr(loop.config, "providers", [])]
        if len(configured_providers) <= 1:
            from rig_relay.core.logger import logger

            logger.warning(
                "governance.degraded: reason=council_single_provider session=%s turn=%s",
                loop.session_id,
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

            context_summary = f"Tool: {tool_name}. Turn: {loop._current_user_message_id or 'unknown'}."
            receipt = await consult_council_before_mutation(
                tool_name=tool_name,
                tool_args=tool_args,
                context_summary=context_summary,
                providers=configured_providers,
                redaction="standard",
            )
            return determine_council_recommendation(receipt)
        except Exception as exc:
            from rig_relay.core.logger import logger

            logger.warning(
                "governance.degraded: reason=council_consultation_failed session=%s turn=%s error=%s",
                loop.session_id,
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
