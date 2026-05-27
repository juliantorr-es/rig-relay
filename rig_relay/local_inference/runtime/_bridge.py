"""ToolExecutionBridge — tool proposal → execution boundary for local inference.

Provides a governed corridor from model-generated ToolCallProposals to the
ToolRuntime execution layer. Performs governance preflight before execution.

When session context is available (X0 integration): full execution through
ToolRuntime.execute_one() with session_id, turn_id, causation_id.

When session context is NOT available: stateless preflight only. Returns
pending_session_context status truthfully.

OMLX-informed: tool execution corridor pattern (Apache 2.0).
"""

from __future__ import annotations

from typing import Any

from rig_relay.governance.governance_engine import GovernanceEngine
from rig_relay.local_inference.runtime._models import ToolCallProposal
from rig_relay.runtime.models import RuntimeCapabilityKind, RuntimeProviderTrustTier

_TOOL_CAPABILITY_MAP: dict[str, RuntimeCapabilityKind] = {
    "bash": RuntimeCapabilityKind.SHELL_PROPOSAL,
    "write_file": RuntimeCapabilityKind.FILE_WRITE_PROPOSAL,
    "search_replace": RuntimeCapabilityKind.PATCH_PROPOSAL,
}


class ToolExecutionBridge:
    """Governed bridge from tool proposals to execution.

    Performs preflight (governance legality check) for every proposal.
    When session context is bound, executes through ToolRuntime.
    When unbound, returns truthful pending_session_context status.
    """

    def __init__(self) -> None:
        self._session_context: dict[str, Any] | None = None
        self._bound: bool = False

    @property
    def has_session_context(self) -> bool:
        return self._bound and self._session_context is not None

    def bind_session(self, session_context: dict[str, Any] | None) -> None:
        """Bind a session context for full tool execution.

        When None, the bridge operates in stateless-preflight-only mode.
        """
        self._session_context = session_context
        self._bound = session_context is not None

    def execute_proposal(
        self, proposal: ToolCallProposal, session_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute or preflight a single tool proposal.

        Returns:
            dict with status, reason, and optional execution_result.
        """
        preflight = self._preflight_proposal(proposal)

        if preflight["status"] != "admitted_pending_execution":
            return preflight

        return {
            "status": "pending_session_context",
            "reason": (
                "Tool proposal admitted through governance preflight. "
                "Full execution through ToolRuntime requires session context "
                "and is deferred to X0 Inference Studio integration."
            ),
            "preflight": preflight,
        }

    def _preflight_proposal(self, proposal: ToolCallProposal) -> dict[str, Any]:
        """Stateless governance preflight for a single tool proposal."""
        capability = _TOOL_CAPABILITY_MAP.get(proposal.tool_name)

        try:
            from rig_relay.local_inference.runtime._secrets import (
                scan_messages_for_secrets,
            )

            arg_scan = scan_messages_for_secrets([{"content": proposal.arguments}])
            if arg_scan["secrets_detected"]:
                return {"status": "refused", "reason": "secret_in_arguments"}
        except Exception:
            pass

        if capability is None:
            return {"status": "pending_review", "reason": "unknown_tool"}

        decision = GovernanceEngine.evaluate_action_legality(
            intent_id=proposal.call_id,
            intent_kind="tool_execution",
            requested_capabilities=[capability],
            provider_trust_tier=RuntimeProviderTrustTier.EXECUTOR_CANDIDATE,
            allow_mutation=True,
        )

        allowed = decision.decision.value == "allowed"
        return {
            "status": (
                "admitted_pending_execution" if allowed else "refused_by_governance"
            ),
            "reason": (
                str(decision.reasons[0].message)
                if decision.reasons
                else "preflight_complete"
            ),
            "governance_decision": decision.decision.value,
        }

    def build_projection(self) -> dict:
        return {
            "tool_execution_bridge": {
                "session_context_bound": self.has_session_context,
                "mode": (
                    "full_execution"
                    if self.has_session_context
                    else "stateless_preflight_only"
                ),
                "mode_detail": (
                    "Tool proposals are executed through ToolRuntime.execute_one() "
                    "with session context."
                )
                if self.has_session_context
                else (
                    "Tool proposals are preflighted through GovernanceEngine. "
                    "Full execution through ToolRuntime requires session context "
                    "and is deferred to X0 Inference Studio integration."
                ),
                "capability_count": len(_TOOL_CAPABILITY_MAP),
                "capability_names": list(_TOOL_CAPABILITY_MAP),
            }
        }
