"""A2A trust tier and capability class tests — C1 domain model validation."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.protocols.a2a._trust import (
    AgentTrustProfile,
    CapabilityClass,
    TrustTier,
    authenticated_capability_subset,
    capabilities_for_tier,
    capability_admitted,
    mutation_capability_admitted,
    public_capability_subset,
    PUBLIC_CAPABILITIES,
    MUTATION_CAPABILITIES,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
S = REPO_ROOT / "docs" / "schemas"


def _load(name: str) -> dict:
    return json.loads((S / name).read_text(encoding="utf-8"))


def _v(instance: dict, name: str) -> None:
    jsonschema.validate(instance, _load(name))


class TestTrustTier:
    def test_internal_governed_agent_has_all_caps(self):
        caps = capabilities_for_tier(TrustTier.INTERNAL_GOVERNED_AGENT)
        assert CapabilityClass.MUTATION_PENDING_AUTHORITY in caps
        assert CapabilityClass.RUNTIME_DELEGATION in caps
        assert CapabilityClass.DISCOVERY_ONLY in caps

    def test_external_unauthenticated_only_discovery(self):
        caps = capabilities_for_tier(TrustTier.EXTERNAL_UNAUTHENTICATED)
        assert caps == {CapabilityClass.DISCOVERY_ONLY}

    def test_external_authenticated_can_propose(self):
        caps = capabilities_for_tier(TrustTier.EXTERNAL_AUTHENTICATED_A2A)
        assert CapabilityClass.PROPOSAL_GENERATION in caps
        assert CapabilityClass.EVIDENCE_VERIFICATION in caps
        assert CapabilityClass.MUTATION_PENDING_AUTHORITY not in caps

    def test_internal_subagent_cannot_mutate(self):
        caps = capabilities_for_tier(TrustTier.INTERNAL_SUBAGENT_WORKER)
        assert CapabilityClass.MUTATION_PENDING_AUTHORITY not in caps
        assert CapabilityClass.GITHUB_PENDING_LANE_B not in caps
        assert CapabilityClass.RUNTIME_DELEGATION not in caps
        assert CapabilityClass.PROPOSAL_GENERATION in caps

    def test_acp_originated_can_read_and_propose(self):
        caps = capabilities_for_tier(TrustTier.ACP_ORIGINATED)
        assert CapabilityClass.READ_ONLY_INVESTIGATION in caps
        assert CapabilityClass.PROPOSAL_GENERATION in caps
        assert CapabilityClass.MUTATION_PENDING_AUTHORITY not in caps

    def test_external_provider_adapter_cannot_mutate(self):
        caps = capabilities_for_tier(TrustTier.EXTERNAL_PROVIDER_ADAPTER)
        assert CapabilityClass.MUTATION_PENDING_AUTHORITY not in caps
        assert CapabilityClass.GITHUB_PENDING_LANE_B not in caps
        assert CapabilityClass.PROPOSAL_GENERATION in caps


class TestCapabilityAdmission:
    def test_discovery_admitted_for_all_tiers(self):
        for tier in TrustTier:
            admitted, _ = capability_admitted(tier, CapabilityClass.DISCOVERY_ONLY)
            assert admitted, f"DISCOVERY_ONLY should be admitted for {tier}"

    def test_mutation_refused_for_external_tiers(self):
        external_tiers = [
            TrustTier.EXTERNAL_UNAUTHENTICATED,
            TrustTier.EXTERNAL_AUTHENTICATED_A2A,
            TrustTier.EXTERNAL_PROVIDER_ADAPTER,
        ]
        for tier in external_tiers:
            admitted, reason = capability_admitted(
                tier, CapabilityClass.MUTATION_PENDING_AUTHORITY
            )
            assert not admitted, (
                f"MUTATION_PENDING_AUTHORITY should be refused for {tier}"
            )
            assert reason != ""

    def test_mutation_admitted_for_governed_agent(self):
        admitted, _ = capability_admitted(
            TrustTier.INTERNAL_GOVERNED_AGENT,
            CapabilityClass.MUTATION_PENDING_AUTHORITY,
        )
        assert admitted

    def test_refusal_reason_includes_capability_and_tier(self):
        _, reason = capability_admitted(
            TrustTier.EXTERNAL_UNAUTHENTICATED, CapabilityClass.PROPOSAL_GENERATION
        )
        assert "not admitted" in reason
        assert TrustTier.EXTERNAL_UNAUTHENTICATED.value in reason


class TestPublicCapabilitySubset:
    def test_public_subset_is_pure_discovery_for_unauthenticated(self):
        caps = public_capability_subset(TrustTier.EXTERNAL_UNAUTHENTICATED)
        assert caps == {CapabilityClass.DISCOVERY_ONLY}

    def test_public_subset_includes_proposal_for_authenticated(self):
        caps = public_capability_subset(TrustTier.EXTERNAL_AUTHENTICATED_A2A)
        assert CapabilityClass.PROPOSAL_GENERATION in caps
        assert CapabilityClass.MUTATION_PENDING_AUTHORITY not in caps

    def test_public_subset_excludes_mutation(self):
        assert not (PUBLIC_CAPABILITIES & MUTATION_CAPABILITIES)

    def test_authenticated_subset_includes_evidence(self):
        caps = authenticated_capability_subset(TrustTier.EXTERNAL_AUTHENTICATED_A2A)
        assert CapabilityClass.EVIDENCE_VERIFICATION in caps
        assert CapabilityClass.DISCOVERY_ONLY in caps


class TestMutationAdmission:
    def test_internal_governed_agent_can_mutate(self):
        assert mutation_capability_admitted(TrustTier.INTERNAL_GOVERNED_AGENT)

    def test_subagent_cannot_mutate(self):
        assert not mutation_capability_admitted(TrustTier.INTERNAL_SUBAGENT_WORKER)

    def test_external_cannot_mutate(self):
        for tier in [
            TrustTier.EXTERNAL_UNAUTHENTICATED,
            TrustTier.EXTERNAL_AUTHENTICATED_A2A,
            TrustTier.EXTERNAL_PROVIDER_ADAPTER,
        ]:
            assert not mutation_capability_admitted(tier)

    def test_acp_cannot_mutate(self):
        assert not mutation_capability_admitted(TrustTier.ACP_ORIGINATED)


class TestTrustProfileSchema:
    def test_profile_validates(self):
        profile = {
            "schema_version": "rig.relay.a2a.trust_tier.v1",
            "trust_tier": "internal_governed_agent",
            "agent_id": "agent-1",
            "identity_proof_hash": "a" * 64,
            "granted_capabilities": ["discovery_only", "proposal_generation"],
            "mutation_admitted": True,
            "public_capabilities": ["discovery_only"],
            "authenticated_capabilities": ["discovery_only", "proposal_generation"],
            "content_light": True,
            "generated_at": "2026-01-01T00:00:00Z",
        }
        _v(profile, "rig.relay.a2a.trust_tier.v1.schema.json")

    def test_profile_rejects_missing_tier(self):
        schema = _load("rig.relay.a2a.trust_tier.v1.schema.json")
        profile = {
            "schema_version": "rig.relay.a2a.trust_tier.v1",
            "agent_id": "agent-1",
            "content_light": True,
            "generated_at": "2026-01-01T00:00:00Z",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(profile, schema)

    def test_profile_rejects_invalid_tier(self):
        schema = _load("rig.relay.a2a.trust_tier.v1.schema.json")
        profile = {
            "schema_version": "rig.relay.a2a.trust_tier.v1",
            "trust_tier": "super_admin",
            "agent_id": "agent-1",
            "content_light": True,
            "generated_at": "2026-01-01T00:00:00Z",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(profile, schema)

    def test_agent_trust_profile_model(self):
        profile = AgentTrustProfile(
            trust_tier=TrustTier.INTERNAL_GOVERNED_AGENT,
            agent_id="test-agent",
            identity_proof_hash="a" * 64,
            granted_capabilities=[
                CapabilityClass.DISCOVERY_ONLY,
                CapabilityClass.PROPOSAL_GENERATION,
            ],
        )
        assert profile.trust_tier == TrustTier.INTERNAL_GOVERNED_AGENT
        assert profile.content_light is True


class TestCapabilityEnumValues:
    def test_all_capabilities_have_enum_values(self):
        for cap in CapabilityClass:
            assert isinstance(cap.value, str)
            assert len(cap.value) > 0

    def test_public_capabilities_are_concrete(self):
        for cap in PUBLIC_CAPABILITIES:
            assert isinstance(cap, CapabilityClass)

    def test_mutation_capabilities_are_concrete(self):
        for cap in MUTATION_CAPABILITIES:
            assert isinstance(cap, CapabilityClass)


class TestTierConsistency:
    def test_all_tiers_covered_in_permissions(self):
        from rig_relay.protocols.a2a._trust import _CAPABILITY_PERMISSIONS

        for tier in TrustTier:
            assert tier in _CAPABILITY_PERMISSIONS, (
                f"{tier} missing from permission map"
            )

    def test_no_tier_has_empty_capabilities(self):
        for tier in TrustTier:
            caps = capabilities_for_tier(tier)
            assert len(caps) > 0, f"{tier} has no capabilities"

    def test_discovery_is_universal(self):
        for tier in TrustTier:
            caps = capabilities_for_tier(tier)
            assert CapabilityClass.DISCOVERY_ONLY in caps, (
                f"{tier} missing DISCOVERY_ONLY"
            )
