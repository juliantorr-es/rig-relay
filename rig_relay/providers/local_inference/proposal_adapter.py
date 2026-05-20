"""Local output proposal adapter — turns model output into governed proposals.

All proposals are blocked by default. Must pass through Rig gates.
Never executes tools/files/shell directly.
"""

from __future__ import annotations

import json
import secrets

from rig_relay.providers.local_inference.models import (
    LocalOutputProposal,
    ProposalActionType,
)


def _new_proposal_id() -> str:
    return f"lop_{secrets.token_hex(8)}"


def classify_and_propose(
    *,
    completion_text: str,
    source_execution_receipt: str = "",
    model_safe_id: str = "",
    prompt_sha256: str = "",
    completion_sha256: str = "",
    now: str | None = None,
) -> LocalOutputProposal:
    action_type = _classify_output(completion_text)

    proposal = LocalOutputProposal(
        proposal_id=_new_proposal_id(),
        source_execution_receipt=source_execution_receipt,
        model_safe_id=model_safe_id,
        prompt_sha256=prompt_sha256,
        completion_sha256=completion_sha256,
        proposed_action_type=action_type.value,
        default_status="blocked_pending_gate",
        raw_output_persisted=False,
        tool_execution_allowed=False,
        file_mutation_allowed=False,
        shell_execution_allowed=False,
    )

    _set_risk_and_gate(proposal)
    return proposal


def _classify_output(text: str) -> ProposalActionType:
    lower = text.lower()
    is_json = False
    try:
        json.loads(text)
        is_json = True
    except (json.JSONDecodeError, ValueError):
        pass

    if not is_json:
        return ProposalActionType.ANSWER_ONLY

    if "tool_calls" in lower or '"tool"' in lower or "function_call" in lower:
        return ProposalActionType.TOOL_CALL_PROPOSAL
    if "write_file" in lower or "patch" in lower or "file_path" in lower:
        return ProposalActionType.FILE_MUTATION_PROPOSAL
    if (
        "bash" in lower
        or "shell" in lower
        or "subprocess" in lower
        or "command" in lower
    ):
        return ProposalActionType.SHELL_COMMAND_PROPOSAL

    return ProposalActionType.ANSWER_ONLY


def _set_risk_and_gate(proposal: LocalOutputProposal) -> None:
    action = ProposalActionType(proposal.proposed_action_type)

    if action == ProposalActionType.ANSWER_ONLY:
        proposal.risk_classification = "low"
        proposal.required_gate = "none"
    elif action == ProposalActionType.TOOL_CALL_PROPOSAL:
        proposal.risk_classification = "high"
        proposal.required_gate = "tool_permission"
        proposal.blocked_reasons.append("tool_execution_requires_gate")
    elif action == ProposalActionType.FILE_MUTATION_PROPOSAL:
        proposal.risk_classification = "critical"
        proposal.required_gate = "patch_gate"
        proposal.blocked_reasons.append("file_mutation_requires_gate")
    elif action == ProposalActionType.SHELL_COMMAND_PROPOSAL:
        proposal.risk_classification = "critical"
        proposal.required_gate = "bash_policy"
        proposal.blocked_reasons.append("shell_execution_requires_gate")
    elif action == ProposalActionType.UNKNOWN_OR_UNSAFE:
        proposal.risk_classification = "critical"
        proposal.blocked_reasons.append("unsafe_output_classification")


__all__ = ["classify_and_propose"]
