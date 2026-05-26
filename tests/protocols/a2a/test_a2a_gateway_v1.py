"""External A2A gateway tests — C3 trust-tier-gated boundary validation."""

from __future__ import annotations

from typing import cast

from rig_relay.protocols.a2a._gateway import (
    A2AGateway,
    GatewayConfig,
    _scan_for_forbidden,
    gateway_admit_mutation,
    refusal_response,
)
from rig_relay.protocols.a2a._governance_bindings import MutationIntent
from rig_relay.protocols.a2a._trust import CapabilityClass, TrustTier


class TestGatewayConfig:
    def test_default_config(self):
        config = GatewayConfig()
        assert config.agent_id == "rig-relay-a2a"
        assert config.local_only is True
        assert config.content_light is True
        assert config.max_artifact_bytes == 65536

    def test_custom_config(self):
        config = GatewayConfig(agent_id="custom-agent", max_task_description_chars=2048)
        assert config.agent_id == "custom-agent"
        assert config.max_task_description_chars == 2048


class TestAgentCard:
    def test_unauthenticated_card_has_only_public_caps(self):
        gw = A2AGateway(trust_tier=TrustTier.EXTERNAL_UNAUTHENTICATED)
        card = gw.build_agent_card()
        caps: list[str] = cast(list[str], card["capabilities"])
        assert "discovery_only" in caps
        assert "mutation_pending_authority" not in caps
        assert "runtime_delegation" not in caps

    def test_authenticated_card_has_evidence(self):
        gw = A2AGateway(trust_tier=TrustTier.EXTERNAL_AUTHENTICATED_A2A)
        card = gw.build_agent_card()
        caps: list[str] = cast(list[str], card["capabilities"])
        assert "proposal_generation" in caps

    def test_card_never_advertises_mutation(self):
        for tier in TrustTier:
            gw = A2AGateway(trust_tier=tier)
            card = gw.build_agent_card()
            caps: list[str] = cast(list[str], card["capabilities"])
            assert "mutation_pending_authority" not in caps, (
                f"Mutation advertised for {tier}"
            )
            assert "runtime_delegation" not in caps, (
                f"Runtime delegation advertised for {tier}"
            )
            assert "github_pending_lane_b" not in caps, (
                f"GitHub cap advertised for {tier}"
            )

    def test_card_includes_governance_extensions(self):
        gw = A2AGateway()
        card = gw.build_agent_card()
        ext: dict[str, object] = cast(dict[str, object], card.get("extensions", {}))
        assert "rig_relay_governance" in ext
        gov: dict[str, object] = cast(dict[str, object], ext["rig_relay_governance"])
        assert gov["mutation_refused"] is True
        assert gov["remote_federation_refused"] is True

    def test_card_schema_version(self):
        gw = A2AGateway()
        card = gw.build_agent_card()
        assert card["schema_version"] == "rig.relay.a2a.agent_card.v1"


class TestCapabilityAdmission:
    def test_discovery_admitted_for_all(self):
        for tier in TrustTier:
            gw = A2AGateway(trust_tier=tier)
            admitted, _ = gw.admit_capability(CapabilityClass.DISCOVERY_ONLY)
            assert admitted

    def test_proposal_admitted_for_authenticated(self):
        gw = A2AGateway(trust_tier=TrustTier.EXTERNAL_AUTHENTICATED_A2A)
        admitted, _ = gw.admit_capability(CapabilityClass.PROPOSAL_GENERATION)
        assert admitted

    def test_proposal_refused_for_unauthenticated(self):
        gw = A2AGateway(trust_tier=TrustTier.EXTERNAL_UNAUTHENTICATED)
        admitted, _ = gw.admit_capability(CapabilityClass.PROPOSAL_GENERATION)
        assert not admitted

    def test_mutation_always_refused_at_gateway(self):
        for tier in TrustTier:
            gw = A2AGateway(trust_tier=tier)
            admitted, reason = gw.admit_capability(
                CapabilityClass.MUTATION_PENDING_AUTHORITY
            )
            assert not admitted, f"Mutation admitted for {tier}"
            assert "not available" in reason

    def test_read_investigation_refused_at_gateway(self):
        gw = A2AGateway(trust_tier=TrustTier.INTERNAL_GOVERNED_AGENT)
        admitted, _ = gw.admit_capability(CapabilityClass.READ_ONLY_INVESTIGATION)
        assert not admitted


class TestTaskValidation:
    def test_safe_description_passes(self):
        gw = A2AGateway()
        valid, reason = gw.validate_task_request("Plan a refactoring of utils.py")
        assert valid
        assert reason == ""

    def test_oversized_description_refused(self):
        gw = A2AGateway()
        long_desc = "x" * 5000
        valid, reason = gw.validate_task_request(long_desc)
        assert not valid
        assert "exceeds" in reason

    def test_description_with_secret_refused(self):
        gw = A2AGateway()
        valid, reason = gw.validate_task_request("Use api_key: sk-abc123 to call API")
        assert not valid
        assert "forbidden" in reason

    def test_unsupported_capability_refused(self):
        gw = A2AGateway()
        valid, reason = gw.validate_task_request(
            "Fix the bug",
            required_capabilities=[CapabilityClass.MUTATION_PENDING_AUTHORITY],
        )
        assert not valid
        assert "not available" in reason


class TestTrustTierUpdate:
    def test_set_trust_tier_upgrades_capabilities(self):
        gw = A2AGateway(trust_tier=TrustTier.EXTERNAL_UNAUTHENTICATED)
        assert not gw.admit_capability(CapabilityClass.PROPOSAL_GENERATION)[0]
        gw.set_trust_tier(TrustTier.EXTERNAL_AUTHENTICATED_A2A)
        assert gw.admit_capability(CapabilityClass.PROPOSAL_GENERATION)[0]


class TestGovernanceBinding:
    def test_external_task_binding_is_proposal_only(self):
        gw = A2AGateway()
        binding = gw.build_governance_binding_for_external_task(
            "task-1", "Plan something"
        )
        assert binding.mutation_intent == MutationIntent.PROPOSAL_ONLY
        assert binding.mission_id is None
        assert binding.lane_id is None

    def test_binding_carries_trust_tier(self):
        gw = A2AGateway(trust_tier=TrustTier.EXTERNAL_AUTHENTICATED_A2A)
        binding = gw.build_governance_binding_for_external_task("t1", "desc")
        assert binding.producer_trust_tier == "external_authenticated_a2a"


class TestMutationAdmission:
    def test_all_mutation_intents_refused(self):
        for intent in MutationIntent:
            if intent == MutationIntent.NONE:
                admitted, _ = gateway_admit_mutation(
                    TrustTier.INTERNAL_GOVERNED_AGENT, intent
                )
                assert admitted
            else:
                admitted, reason = gateway_admit_mutation(
                    TrustTier.INTERNAL_GOVERNED_AGENT, intent
                )
                assert not admitted, f"{intent} should be refused"
                assert "proposal-only" in reason

    def test_external_always_refused(self):
        admitted, reason = gateway_admit_mutation(
            TrustTier.EXTERNAL_AUTHENTICATED_A2A, MutationIntent.SCOPED_MUTATION
        )
        assert not admitted


class TestRefusalResponse:
    def test_refusal_response_structure(self):
        resp = refusal_response("Not allowed", code="cap_mismatch", task_id="t1")
        assert resp["status"] == "refused"
        assert resp["refusal_code"] == "cap_mismatch"
        assert resp["task_id"] == "t1"
        assert resp["content_light"] is True

    def test_refusal_without_task_id(self):
        resp = refusal_response("No")
        assert resp["task_id"] == ""


class TestForbiddenScan:
    def test_detects_api_key(self):
        assert "api_key" in _scan_for_forbidden("my api_key is abc")

    def test_clean_text_passes(self):
        assert _scan_for_forbidden("do a refactoring") == []

    def test_detects_token(self):
        assert "token" in _scan_for_forbidden("use token for auth")

    def test_case_insensitive(self):
        assert "secret" in _scan_for_forbidden("my SECRET key")
