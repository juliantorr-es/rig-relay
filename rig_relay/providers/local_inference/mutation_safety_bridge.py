from __future__ import annotations

from typing import Any

from rig_relay.governance.service_state import CapabilityGate, get_capability_gate
from rig_relay.providers.local_inference.models import (
    LocalOutputProposal,
    ProposalActionType,
)

_GATE_MAP: dict[str, str] = {
    "tool_permission": "local_inference_tool_proposal",
    "patch_gate": "local_inference_file_mutation",
    "bash_policy": "local_inference_shell_execution",
}


def _intent_is_registered(intent: str, gate: CapabilityGate) -> bool:
    return (
        intent in gate.SENSITIVE_CAPABILITIES
        or intent in gate.ACP_COMMAND_CAPABILITIES
        or intent in gate.MUTATION_TOOL_CAPABILITIES
        or intent in gate.ALWAYS_ALLOWED
    )


def evaluate_proposal_safety(*, proposal: LocalOutputProposal) -> dict[str, Any]:
    action = ProposalActionType(proposal.proposed_action_type)
    gate = get_capability_gate()
    blocked_reasons: list[str] = list(proposal.blocked_reasons)

    mutation_allowed = False
    tool_execution_allowed = False
    file_mutation_allowed = False
    shell_execution_allowed = False

    intent = _GATE_MAP.get(proposal.required_gate)
    if intent is None:
        if proposal.required_gate == "none":
            return {
                "proposal_id": proposal.proposal_id,
                "proposed_action_type": proposal.proposed_action_type,
                "required_gate": proposal.required_gate,
                "gate_available": False,
                "gate_status": "allowed",
                "mutation_allowed": False,
                "tool_execution_allowed": False,
                "file_mutation_allowed": False,
                "shell_execution_allowed": False,
                "blocked_reasons": blocked_reasons,
            }
        return {
            "proposal_id": proposal.proposal_id,
            "proposed_action_type": proposal.proposed_action_type,
            "required_gate": proposal.required_gate,
            "gate_available": False,
            "gate_status": "unknown",
            "mutation_allowed": False,
            "tool_execution_allowed": False,
            "file_mutation_allowed": False,
            "shell_execution_allowed": False,
            "blocked_reasons": blocked_reasons + ["gate_not_registered"],
        }

    gate_available = _intent_is_registered(intent, gate)
    allowed, reason = gate.is_allowed(intent)

    if not gate_available:
        gate_status = "unknown"
        if "gate_not_registered" not in blocked_reasons:
            blocked_reasons.append("gate_not_registered")
        if reason and reason not in blocked_reasons:
            blocked_reasons.append(reason)
    elif allowed:
        gate_status = "allowed"
    else:
        gate_status = "blocked"
        if reason and reason not in blocked_reasons:
            blocked_reasons.append(reason)

    if action != ProposalActionType.ANSWER_ONLY:
        if "mutation_blocked_by_default" not in blocked_reasons:
            blocked_reasons.append("mutation_blocked_by_default")

    return {
        "proposal_id": proposal.proposal_id,
        "proposed_action_type": proposal.proposed_action_type,
        "required_gate": proposal.required_gate,
        "gate_available": gate_available,
        "gate_status": gate_status,
        "mutation_allowed": mutation_allowed,
        "tool_execution_allowed": tool_execution_allowed,
        "file_mutation_allowed": file_mutation_allowed,
        "shell_execution_allowed": shell_execution_allowed,
        "blocked_reasons": blocked_reasons,
    }


__all__ = ["evaluate_proposal_safety"]
