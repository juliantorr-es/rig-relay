"""A2A governance bindings tests — C1 extension data model validation."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from pydantic import ValidationError
import pytest

from rig_relay.protocols.a2a._governance_bindings import (
    A2AAgentCardExtensions,
    A2AGovernanceBinding,
    CancellationReason,
    ConfidentialityTier,
    ExecutionRisk,
    MutationIntent,
    RefusalReason,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
S = REPO_ROOT / "docs" / "schemas"


def _load(name: str) -> dict:
    return json.loads((S / name).read_text(encoding="utf-8"))


def _v(instance: dict, name: str) -> None:
    jsonschema.validate(instance, _load(name))


class TestGovernanceBindingModel:
    def test_minimal_binding_creates(self):
        binding = A2AGovernanceBinding()
        assert binding.schema_version == "rig.relay.a2a.governance_binding.v1"
        assert binding.confidentiality_tier == ConfidentialityTier.INTERNAL
        assert binding.mutation_intent == MutationIntent.NONE
        assert binding.execution_risk == ExecutionRisk.NONE
        assert binding.content_light is True

    def test_full_binding_fields(self):
        binding = A2AGovernanceBinding(
            mission_id="mission-1",
            lane_id="lane-a",
            parent_task_id="task-parent-1",
            evidence_digest="e" * 64,
            artifact_digest="a" * 64,
            receipt_id="rcpt-1",
            confidentiality_tier=ConfidentialityTier.CONFIDENTIAL,
            mutation_intent=MutationIntent.PROPOSAL_ONLY,
            execution_risk=ExecutionRisk.MEDIUM,
            authorization_dependency="lane_a_validate",
            producer_trust_tier="internal_governed_agent",
            producer_identity_hash="i" * 64,
            causal_predecessor_task_id="task-0",
            causal_predecessor_event_seq=3,
            required_capability_classes=[
                "read_only_investigation",
                "proposal_generation",
            ],
            granted_capability_classes=["proposal_generation"],
        )
        assert binding.mission_id == "mission-1"
        assert binding.mutation_intent == MutationIntent.PROPOSAL_ONLY
        assert binding.execution_risk == ExecutionRisk.MEDIUM
        assert binding.required_capability_classes == [
            "read_only_investigation",
            "proposal_generation",
        ]

    def test_binding_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            A2AGovernanceBinding(unknown_field="bad")  # type: ignore[call-arg]


class TestGovernanceBindingSchema:
    def test_valid_binding_validates(self):
        binding = {
            "schema_version": "rig.relay.a2a.governance_binding.v1",
            "mission_id": "m1",
            "lane_id": "lane-a",
            "parent_task_id": None,
            "evidence_digest": "e" * 64,
            "artifact_digest": "a" * 64,
            "receipt_id": "rcpt-1",
            "confidentiality_tier": "internal",
            "mutation_intent": "none",
            "execution_risk": "low",
            "authorization_dependency": None,
            "producer_trust_tier": "internal_governed_agent",
            "producer_identity_hash": "i" * 64,
            "causal_predecessor_task_id": None,
            "causal_predecessor_event_seq": None,
            "cancellation_reason": None,
            "refusal_reason": None,
            "required_capability_classes": [],
            "granted_capability_classes": [],
            "content_light": True,
        }
        _v(binding, "rig.relay.a2a.governance_binding.v1.schema.json")

    def test_binding_rejects_invalid_confidentiality(self):
        schema = _load("rig.relay.a2a.governance_binding.v1.schema.json")
        binding = {
            "schema_version": "rig.relay.a2a.governance_binding.v1",
            "confidentiality_tier": "ultra_top_secret",
            "mutation_intent": "none",
            "execution_risk": "low",
            "content_light": True,
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(binding, schema)

    def test_binding_rejects_invalid_mutation_intent(self):
        schema = _load("rig.relay.a2a.governance_binding.v1.schema.json")
        binding = {
            "schema_version": "rig.relay.a2a.governance_binding.v1",
            "confidentiality_tier": "internal",
            "mutation_intent": "delete_everything",
            "execution_risk": "low",
            "content_light": True,
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(binding, schema)

    def test_binding_requires_content_light(self):
        schema = _load("rig.relay.a2a.governance_binding.v1.schema.json")
        binding = {
            "schema_version": "rig.relay.a2a.governance_binding.v1",
            "confidentiality_tier": "internal",
            "mutation_intent": "none",
            "execution_risk": "low",
            "content_light": False,
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(binding, schema)


class TestCancellationReasonEnum:
    def test_all_values_are_strings(self):
        for reason in CancellationReason:
            assert isinstance(reason.value, str)
            assert len(reason.value) > 0

    def test_user_requested_exists(self):
        assert CancellationReason.USER_REQUESTED.value == "user_requested"

    def test_governance_refusal_exists(self):
        assert CancellationReason.GOVERNANCE_REFUSAL.value == "governance_refusal"


class TestRefusalReasonEnum:
    def test_capability_mismatch_exists(self):
        assert RefusalReason.CAPABILITY_MISMATCH.value == "capability_mismatch"

    def test_trust_tier_insufficient_exists(self):
        assert RefusalReason.TRUST_TIER_INSUFFICIENT.value == "trust_tier_insufficient"

    def test_mutation_not_authorized_exists(self):
        assert RefusalReason.MUTATION_NOT_AUTHORIZED.value == "mutation_not_authorized"


class TestMutationIntentEnum:
    def test_none_is_default_safe(self):
        assert MutationIntent.NONE.value == "none"

    def test_read_only_distinct_from_none(self):
        assert MutationIntent.READ_ONLY.value != MutationIntent.NONE.value

    def test_scoped_mutation_is_most_permissive(self):
        assert MutationIntent.SCOPED_MUTATION.value == "scoped_mutation"


class TestExecutionRiskEnum:
    def test_none_to_critical_scale(self):
        risks = [
            ExecutionRisk.NONE,
            ExecutionRisk.LOW,
            ExecutionRisk.MEDIUM,
            ExecutionRisk.HIGH,
            ExecutionRisk.CRITICAL,
        ]
        for risk in risks:
            assert isinstance(risk.value, str)


class TestAgentCardExtensions:
    def test_default_trust_tier_is_external_unauthenticated(self):
        ext = A2AAgentCardExtensions()
        assert ext.trust_tier == "external_unauthenticated"

    def test_content_light_default_true(self):
        ext = A2AAgentCardExtensions()
        assert ext.content_light is True

    def test_supported_bindings_modifiable(self):
        ext = A2AAgentCardExtensions(
            rig_relay_version="1.0.0",
            supported_bindings=["jsonrpc", "http"],
            governance_envelope_provided=True,
        )
        assert ext.supported_bindings == ["jsonrpc", "http"]
        assert ext.governance_envelope_provided is True
        assert ext.rig_relay_version == "1.0.0"


class TestConfidentialityTierEnum:
    def test_all_tiers(self):
        tiers = {
            ConfidentialityTier.PUBLIC,
            ConfidentialityTier.INTERNAL,
            ConfidentialityTier.CONFIDENTIAL,
            ConfidentialityTier.RESTRICTED,
        }
        assert len(tiers) == 4

    def test_default_is_not_public(self):
        binding = A2AGovernanceBinding()
        assert binding.confidentiality_tier != ConfidentialityTier.PUBLIC
