from __future__ import annotations

import pytest

from rig_relay.governance.service_state import (
    CapabilityGate,
    ProfileStore,
    set_profile_store_override,
)
from rig_relay.providers.local_inference.models import (
    LocalOutputProposal,
    ProposalActionType,
)
from rig_relay.providers.local_inference.mutation_safety_bridge import (
    evaluate_proposal_safety,
)


def _make_proposal(
    action_type: ProposalActionType,
    blocked_reasons: list[str] | None = None,
    required_gate: str | None = None,
) -> LocalOutputProposal:
    gates: dict[ProposalActionType, str] = {
        ProposalActionType.ANSWER_ONLY: "none",
        ProposalActionType.TOOL_CALL_PROPOSAL: "tool_permission",
        ProposalActionType.FILE_MUTATION_PROPOSAL: "patch_gate",
        ProposalActionType.SHELL_COMMAND_PROPOSAL: "bash_policy",
        ProposalActionType.UNKNOWN_OR_UNSAFE: "",
    }
    gate = required_gate if required_gate is not None else gates[action_type]
    return LocalOutputProposal(
        proposal_id=f"test_{action_type.value}",
        proposed_action_type=action_type.value,
        required_gate=gate,
        blocked_reasons=blocked_reasons or [],
    )


class TestAnswerOnlyProposal:
    def test_answer_only_is_always_safe(self) -> None:
        proposal = _make_proposal(ProposalActionType.ANSWER_ONLY)
        result = evaluate_proposal_safety(proposal=proposal)
        assert result["gate_status"] == "allowed"
        assert result["mutation_allowed"] is False
        assert result["tool_execution_allowed"] is False
        assert result["file_mutation_allowed"] is False
        assert result["shell_execution_allowed"] is False


class TestToolCallProposal:
    def test_tool_call_proposal_requires_gate(self) -> None:
        proposal = _make_proposal(ProposalActionType.TOOL_CALL_PROPOSAL)
        result = evaluate_proposal_safety(proposal=proposal)
        assert result["gate_available"] is True
        assert result["mutation_allowed"] is False
        assert result["tool_execution_allowed"] is False
        assert "mutation_blocked_by_default" in result["blocked_reasons"]

    def test_tool_call_proposal_gate_is_registered(self) -> None:
        proposal = _make_proposal(ProposalActionType.TOOL_CALL_PROPOSAL)
        result = evaluate_proposal_safety(proposal=proposal)
        assert result["gate_available"] is True


class TestFileMutationProposal:
    def test_file_mutation_proposal_requires_gate(self) -> None:
        proposal = _make_proposal(ProposalActionType.FILE_MUTATION_PROPOSAL)
        result = evaluate_proposal_safety(proposal=proposal)
        assert result["gate_available"] is True
        assert result["mutation_allowed"] is False
        assert result["file_mutation_allowed"] is False
        assert "mutation_blocked_by_default" in result["blocked_reasons"]


class TestShellProposal:
    def test_shell_proposal_requires_gate(self) -> None:
        proposal = _make_proposal(ProposalActionType.SHELL_COMMAND_PROPOSAL)
        result = evaluate_proposal_safety(proposal=proposal)
        assert result["gate_available"] is True
        assert result["mutation_allowed"] is False
        assert result["shell_execution_allowed"] is False
        assert "mutation_blocked_by_default" in result["blocked_reasons"]


class TestUnknownGate:
    def test_unknown_gate_produces_blocked(self) -> None:
        proposal = _make_proposal(
            ProposalActionType.UNKNOWN_OR_UNSAFE, required_gate="nonexistent_gate"
        )
        result = evaluate_proposal_safety(proposal=proposal)
        assert result["gate_available"] is False
        assert result["gate_status"] == "unknown"
        assert "gate_not_registered" in result["blocked_reasons"]


class TestAllProposalsMutationFalse:
    def test_answer_only_mutation_false(self) -> None:
        proposal = _make_proposal(ProposalActionType.ANSWER_ONLY)
        result = evaluate_proposal_safety(proposal=proposal)
        assert result["mutation_allowed"] is False

    def test_tool_call_mutation_false(self) -> None:
        proposal = _make_proposal(ProposalActionType.TOOL_CALL_PROPOSAL)
        result = evaluate_proposal_safety(proposal=proposal)
        assert result["mutation_allowed"] is False

    def test_file_mutation_mutation_false(self) -> None:
        proposal = _make_proposal(ProposalActionType.FILE_MUTATION_PROPOSAL)
        result = evaluate_proposal_safety(proposal=proposal)
        assert result["mutation_allowed"] is False

    def test_shell_mutation_false(self) -> None:
        proposal = _make_proposal(ProposalActionType.SHELL_COMMAND_PROPOSAL)
        result = evaluate_proposal_safety(proposal=proposal)
        assert result["mutation_allowed"] is False


class TestIntegrationProfileUnlock:
    def test_sensitive_capabilities_in_gate(self) -> None:
        assert "local_inference_tool_proposal" in CapabilityGate.SENSITIVE_CAPABILITIES
        assert "local_inference_file_mutation" in CapabilityGate.SENSITIVE_CAPABILITIES
        assert (
            "local_inference_shell_execution" in CapabilityGate.SENSITIVE_CAPABILITIES
        )

    def test_tool_proposal_blocked_when_profile_locked(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        profile_root = tmp_path_factory.mktemp("test_locked_profile")
        store = ProfileStore(root=profile_root)
        store.create_first_launch_profile()
        store.lock()
        set_profile_store_override(store)
        try:
            proposal = _make_proposal(ProposalActionType.TOOL_CALL_PROPOSAL)
            result = evaluate_proposal_safety(proposal=proposal)
            assert result["gate_status"] == "blocked"
            assert result["mutation_allowed"] is False
        finally:
            set_profile_store_override(None)

    def test_file_mutation_blocked_when_profile_locked(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        profile_root = tmp_path_factory.mktemp("test_locked_profile")
        store = ProfileStore(root=profile_root)
        store.create_first_launch_profile()
        store.lock()
        set_profile_store_override(store)
        try:
            proposal = _make_proposal(ProposalActionType.FILE_MUTATION_PROPOSAL)
            result = evaluate_proposal_safety(proposal=proposal)
            assert result["gate_status"] == "blocked"
            assert result["mutation_allowed"] is False
        finally:
            set_profile_store_override(None)

    def test_shell_blocked_when_profile_locked(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        profile_root = tmp_path_factory.mktemp("test_locked_profile")
        store = ProfileStore(root=profile_root)
        store.create_first_launch_profile()
        store.lock()
        set_profile_store_override(store)
        try:
            proposal = _make_proposal(ProposalActionType.SHELL_COMMAND_PROPOSAL)
            result = evaluate_proposal_safety(proposal=proposal)
            assert result["gate_status"] == "blocked"
            assert result["mutation_allowed"] is False
        finally:
            set_profile_store_override(None)
