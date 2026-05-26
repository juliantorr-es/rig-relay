"""Cross-boundary security and conformance tests — C6 closure validation."""

from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from rig_relay.protocols.a2a._conformance import (
    Boundary,
    CrossBoundaryRule,
    build_cross_boundary_assertions,
    build_future_handoff_contracts,
    build_trust_matrix,
    mutation_permitted_for_boundary,
    verify_all_assertions,
)
from rig_relay.protocols.a2a._gateway import A2AGateway
from rig_relay.protocols.a2a._internal_fabric import A2AInternalFabric
from rig_relay.protocols.a2a._trust import CapabilityClass, TrustTier


class TestCrossBoundaryAssertions:
    def test_all_assertions_verified(self):
        assertions = build_cross_boundary_assertions()
        all_ok, verified, total = verify_all_assertions(assertions)
        assert all_ok, f"{total - verified}/{total} assertions unverified"
        assert total == 12

    def test_same_models_rule_present(self):
        assertions = build_cross_boundary_assertions()
        rules = {a.rule for a in assertions}
        assert CrossBoundaryRule.SAME_CANONICAL_MODELS in rules

    def test_different_trust_rule_present(self):
        assertions = build_cross_boundary_assertions()
        rules = {a.rule for a in assertions}
        assert CrossBoundaryRule.DIFFERENT_TRUST_POLICY in rules

    def test_content_light_universal_rule_present(self):
        assertions = build_cross_boundary_assertions()
        rules = {a.rule for a in assertions}
        assert CrossBoundaryRule.CONTENT_LIGHT_UNIVERSAL in rules

    def test_fail_closed_rule_present(self):
        assertions = build_cross_boundary_assertions()
        rules = {a.rule for a in assertions}
        assert CrossBoundaryRule.FAIL_CLOSED in rules

    def test_no_trust_upgrade_rule_present(self):
        assertions = build_cross_boundary_assertions()
        rules = {a.rule for a in assertions}
        assert CrossBoundaryRule.NO_TRUST_UPGRADE in rules

    def test_no_execution_rule_present(self):
        assertions = build_cross_boundary_assertions()
        rules = {a.rule for a in assertions}
        assert CrossBoundaryRule.NO_EXECUTION in rules


class TestTrustMatrix:
    def test_matrix_covers_all_boundaries(self):
        matrix = build_trust_matrix()
        boundaries = {e.origin for e in matrix}
        for b in Boundary:
            assert b in boundaries, f"Boundary {b} missing from trust matrix"

    def test_internal_governed_can_mutate(self):
        matrix = build_trust_matrix()
        entry = next(
            e
            for e in matrix
            if e.origin == Boundary.INTERNAL_FABRIC
            and e.trust_tier == TrustTier.INTERNAL_GOVERNED_AGENT
        )
        assert entry.can_mutate is True
        assert entry.can_delegate is True

    def test_internal_subagent_cannot_mutate(self):
        matrix = build_trust_matrix()
        entry = next(
            e for e in matrix if e.trust_tier == TrustTier.INTERNAL_SUBAGENT_WORKER
        )
        assert entry.can_mutate is False

    def test_external_unauthenticated_cannot_do_anything(self):
        matrix = build_trust_matrix()
        entry = next(
            e for e in matrix if e.trust_tier == TrustTier.EXTERNAL_UNAUTHENTICATED
        )
        assert entry.can_propose is False
        assert entry.can_read_evidence is False
        assert entry.can_mutate is False
        assert entry.can_delegate is False

    def test_external_authenticated_cannot_mutate(self):
        matrix = build_trust_matrix()
        entry = next(
            e for e in matrix if e.trust_tier == TrustTier.EXTERNAL_AUTHENTICATED_A2A
        )
        assert entry.can_mutate is False
        assert entry.can_delegate is False
        assert entry.can_propose is True

    def test_acp_originated_cannot_mutate(self):
        matrix = build_trust_matrix()
        entry = next(e for e in matrix if e.trust_tier == TrustTier.ACP_ORIGINATED)
        assert entry.can_mutate is False
        assert entry.can_propose is True

    def test_all_entries_enforce_content_light(self):
        for entry in build_trust_matrix():
            assert entry.content_light_enforced is True

    def test_all_entries_enforce_mutation_gated(self):
        for entry in build_trust_matrix():
            assert entry.mutation_gated is True


class TestMutationPermission:
    def test_internal_governed_mutation_permitted(self):
        permitted, _ = mutation_permitted_for_boundary(
            Boundary.INTERNAL_FABRIC, TrustTier.INTERNAL_GOVERNED_AGENT
        )
        assert permitted

    def test_external_mutation_refused(self):
        permitted, reason = mutation_permitted_for_boundary(
            Boundary.EXTERNAL_GATEWAY, TrustTier.EXTERNAL_AUTHENTICATED_A2A
        )
        assert not permitted
        assert "not permitted" in reason

    def test_acp_mutation_refused(self):
        permitted, _ = mutation_permitted_for_boundary(
            Boundary.ACP_PROJECTION, TrustTier.ACP_ORIGINATED
        )
        assert not permitted


class TestFutureHandoffContracts:
    def test_all_contracts_not_implemented(self):
        contracts = build_future_handoff_contracts()
        for c in contracts:
            assert c.status == "not_implemented", (
                f"{c.consumer_name} should not be implemented"
            )

    def test_contracts_cover_known_consumers(self):
        contracts = build_future_handoff_contracts()
        names = {c.consumer_name for c in contracts}
        assert "AgentLoop" in names
        assert "Ralph" in names
        assert "Fleet Orchestrator" in names
        assert "Subagent Spawner" in names
        assert "External Provider Adapter" in names

    def test_each_contract_has_integration_seam(self):
        for c in build_future_handoff_contracts():
            assert c.integration_seam, f"{c.consumer_name} has no integration seam"
            assert c.precondition, f"{c.consumer_name} has no precondition"

    def test_contracts_require_appropriate_tiers(self):
        contracts = build_future_handoff_contracts()
        agent_loop = next(c for c in contracts if c.consumer_name == "AgentLoop")
        assert agent_loop.required_trust_tier == TrustTier.INTERNAL_GOVERNED_AGENT


class TestEndToEndInternalThenExternal:
    """Prove the same canonical task shape works across boundaries."""

    def test_internal_task_then_external_inspection(self):
        # Internal fabric creates a task
        with tempfile.TemporaryDirectory() as tmp:
            fabric = A2AInternalFabric(root=Path(tmp))
            task = fabric.create_task(
                agent_id="agent-1",
                description="Refactor utils.py",
                trust_tier=TrustTier.INTERNAL_GOVERNED_AGENT,
            )
            fabric.submit_task(task.task_id)

            # External gateway inspects (can only see proposal capability)
            gw = A2AGateway(trust_tier=TrustTier.EXTERNAL_AUTHENTICATED_A2A)
            admitted, _ = gw.admit_capability(CapabilityClass.PROPOSAL_GENERATION)
            assert admitted
            mutation_admitted, _ = gw.admit_capability(
                CapabilityClass.MUTATION_PENDING_AUTHORITY
            )
            assert not mutation_admitted

    def test_external_proposal_internal_execution_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            fabric = A2AInternalFabric(root=Path(tmp))

            # External gateway validates a proposal
            gw = A2AGateway(trust_tier=TrustTier.EXTERNAL_AUTHENTICATED_A2A)
            valid, _ = gw.validate_task_request("Propose a refactoring")
            assert valid

            # Internal fabric creates the task (simulating gateway→fabric)
            task = fabric.create_task(
                agent_id="external-client",
                description="Propose a refactoring",
                trust_tier=TrustTier.EXTERNAL_AUTHENTICATED_A2A,
            )
            assert task.status.value == "created"
            assert task.trust_tier == TrustTier.EXTERNAL_AUTHENTICATED_A2A


class TestConfidentialityBoundary:
    def test_secret_blocked_at_internal_fabric(self):
        with tempfile.TemporaryDirectory() as tmp:
            fabric = A2AInternalFabric(root=Path(tmp))
            with pytest.raises(ValueError, match="forbidden content"):
                fabric.create_task(agent_id="a1", description="Task with api_key: abc")

    def test_secret_blocked_at_external_gateway(self):
        gw = A2AGateway()
        valid, reason = gw.validate_task_request("Use token: xyz for API")
        assert not valid
        assert "forbidden" in reason

    def test_clean_content_passes_all_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            fabric = A2AInternalFabric(root=Path(tmp))
            task = fabric.create_task(
                agent_id="a1", description="Plan a refactoring of the auth module"
            )
            assert task is not None

            gw = A2AGateway()
            valid, _ = gw.validate_task_request("Plan a refactoring")
            assert valid
