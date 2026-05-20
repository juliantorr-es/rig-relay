from __future__ import annotations

from rig_relay.governance.decisions import GovernanceDecisionKind
from rig_relay.governance.governance_engine import GovernanceEngine
from rig_relay.runtime.models import (
    RuntimeCapabilityKind,
    RuntimeProviderKind,
    RuntimeProviderStatus,
    RuntimeProviderTrustTier,
)
from rig_relay.runtime.supervisor import RuntimeSupervisor


class TestSupervisorGovernanceEngineWired:
    def test_supervisor_has_non_none_governance_engine(self) -> None:
        supervisor = RuntimeSupervisor(governance_engine=GovernanceEngine())
        assert supervisor._governance_engine is not None

    def test_supervisor_without_engine_is_none(self) -> None:
        supervisor = RuntimeSupervisor(governance_engine=None)
        assert supervisor._governance_engine is None

    def test_supervisor_engine_evaluates_and_blocks_dirty_policy(self) -> None:
        supervisor = RuntimeSupervisor(
            governance_engine=GovernanceEngine(),
            dirty_policy_satisfied=False,
            allow_mutation=False,
        )
        assert supervisor._governance_engine is not None
        decision = supervisor._governance_engine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="test",
            intent_kind="runtime_execution",
            requested_capabilities=[RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
            dirty_policy_satisfied=False,
        )
        assert decision.decision == GovernanceDecisionKind.BLOCKED
        assert any(r.code == "dirty_policy_violated" for r in decision.reasons)


class TestGovernanceEngineBlockedProvider:
    def test_blocked_trust_tier_blocks_execution(self) -> None:
        decision = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.execute",
            intent_kind="execution",
            requested_capabilities=[RuntimeCapabilityKind.SHELL_PROPOSAL],
            provider_trust_tier=RuntimeProviderTrustTier.BLOCKED,
        )
        assert decision.decision == GovernanceDecisionKind.BLOCKED
        assert any(r.code == "provider_trust_tier_blocked" for r in decision.reasons)

    def test_blocked_provider_status_blocks_mutation(self) -> None:
        decision = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.execute",
            intent_kind="execution",
            requested_capabilities=[RuntimeCapabilityKind.SHELL_PROPOSAL],
            provider_status=RuntimeProviderStatus.BLOCKED,
        )
        assert decision.decision == GovernanceDecisionKind.BLOCKED
        assert any(
            r.code == "provider_status_blocked_execution" for r in decision.reasons
        )

    def test_available_provider_allows_read_only(self) -> None:
        decision = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.read",
            intent_kind="read_only",
            requested_capabilities=[RuntimeCapabilityKind.FILE_READ],
            provider_trust_tier=RuntimeProviderTrustTier.EXECUTOR_CANDIDATE,
            provider_status=RuntimeProviderStatus.AVAILABLE,
        )
        assert decision.decision == GovernanceDecisionKind.ALLOWED


class TestGovernanceEngineNotApplicable:
    def test_no_capabilities_no_intent_kind_returns_not_applicable(self) -> None:
        decision = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1", intent_id="test"
        )
        assert decision.decision == GovernanceDecisionKind.NOT_APPLICABLE
        assert any(r.code == "no_requested_capabilities" for r in decision.reasons)

    def test_only_intent_id_returns_not_applicable(self) -> None:
        decision = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1", intent_id="unknown_intent"
        )
        assert decision.decision == GovernanceDecisionKind.NOT_APPLICABLE


class TestLocalInferenceProviderGating:
    def test_local_inference_default_trust_tier_is_executor_candidate(self) -> None:
        tier = GovernanceEngine.default_trust_tier_for_provider(
            RuntimeProviderKind.LOCAL_INFERENCE
        )
        assert tier == RuntimeProviderTrustTier.EXECUTOR_CANDIDATE

    def test_local_inference_provider_kind_exists_in_enum(self) -> None:
        assert hasattr(RuntimeProviderKind, "LOCAL_INFERENCE")
        assert RuntimeProviderKind.LOCAL_INFERENCE.value == "local_inference"

    def test_local_inference_with_executor_tier_allows_read_only(self) -> None:
        decision = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.read",
            intent_kind="read_only",
            requested_capabilities=[RuntimeCapabilityKind.FILE_READ],
            provider_trust_tier=RuntimeProviderTrustTier.EXECUTOR_CANDIDATE,
        )
        assert decision.decision == GovernanceDecisionKind.ALLOWED

    def test_local_inference_with_executor_tier_requires_review_for_mutation(
        self,
    ) -> None:
        decision = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.write",
            intent_kind="mutation",
            requested_capabilities=[RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
            provider_trust_tier=RuntimeProviderTrustTier.EXECUTOR_CANDIDATE,
        )
        assert decision.decision == GovernanceDecisionKind.REQUIRES_REVIEW
        assert any(r.code == "mutation_requires_review" for r in decision.reasons)

    def test_unknown_provider_defaults_to_advisory(self) -> None:
        tier = GovernanceEngine.default_trust_tier_for_provider("unknown_provider")
        assert tier == RuntimeProviderTrustTier.ADVISORY


class TestGovernanceContentLight:
    def test_decision_no_raw_output_content(self) -> None:
        decision = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.read",
            intent_kind="read_only",
            requested_capabilities=[RuntimeCapabilityKind.FILE_READ],
        )
        dump = decision.model_dump(mode="json")
        assert "content" not in dump
        assert "stdout" not in dump
        assert "stderr" not in dump
        assert "output" not in dump
        assert "diff" not in dump

    def test_decision_no_secret_keys(self) -> None:
        decision = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.read",
            intent_kind="read_only",
            requested_capabilities=[RuntimeCapabilityKind.FILE_READ],
        )
        dump = decision.model_dump(mode="json")
        dump_str = str(dump)
        assert "api_key" not in dump_str
        assert "token" not in dump_str
        assert "secret" not in dump_str
        assert "password" not in dump_str

    def test_reason_messages_no_raw_file_paths(self) -> None:
        decision = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.write",
            intent_kind="mutation",
            requested_capabilities=[RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
            dirty_policy_satisfied=False,
        )
        for r in decision.reasons:
            assert "/home/" not in r.message
            assert "/Users/" not in r.message


class TestGovernanceEngineProviderDefaultTiers:
    def test_all_known_providers_have_default_tiers(self) -> None:
        for kind in RuntimeProviderKind:
            tier = GovernanceEngine.default_trust_tier_for_provider(kind)
            assert isinstance(tier, RuntimeProviderTrustTier)

    def test_local_inference_different_from_blocked(self) -> None:
        tier = GovernanceEngine.default_trust_tier_for_provider(
            RuntimeProviderKind.LOCAL_INFERENCE
        )
        assert tier != RuntimeProviderTrustTier.BLOCKED

    def test_stub_provider_is_advisory(self) -> None:
        tier = GovernanceEngine.default_trust_tier_for_provider(
            RuntimeProviderKind.STUB
        )
        assert tier == RuntimeProviderTrustTier.ADVISORY

    def test_local_provider_is_executor_candidate(self) -> None:
        tier = GovernanceEngine.default_trust_tier_for_provider(
            RuntimeProviderKind.LOCAL
        )
        assert tier == RuntimeProviderTrustTier.EXECUTOR_CANDIDATE
