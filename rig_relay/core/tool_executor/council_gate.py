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

    async def consult(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_class: type[BaseTool] | None,
    ) -> str:
        """Return ALLOW, BLOCK, or REVIEW. Never ALLOW on failure."""
        loop = self._loop
        turn_id = getattr(loop, "_current_user_message_id", None)

        if tool_class is None:
            from rig_relay.core.logger import logger

            logger.warning(
                "governance.degraded: reason=council_unknown_tool session=%s turn=%s",
                loop.session_id,
                turn_id,
            )
            return "REVIEW"
        if tool_class.__name__ not in _COUNCIL_MUTATION_TOOLS:
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
                return "BLOCK"
        except Exception:
            from rig_relay.core.logger import logger

            logger.warning(
                "governance.degraded: reason=council_gate_unavailable session=%s turn=%s",
                loop.session_id,
                turn_id,
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
            return "REVIEW"
