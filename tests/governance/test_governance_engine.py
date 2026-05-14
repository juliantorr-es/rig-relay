"""Tests for GovernanceEngine — pure governance gate evaluation."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from rig_relay.governance.decisions import (
    AllowedIntent,
    BlockedIntent,
    DecisionReason,
    GateDecision,
    GovernanceDecisionKind,
    GovernanceReasonSeverity,
)
from rig_relay.governance.governance_engine import GovernanceEngine
from rig_relay.runtime.models import (
    RuntimeCapabilityKind,
    RuntimeProviderStatus,
    RuntimeProviderTrustTier,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class TestGovernanceDecisionKind:
    """StrEnum stability and serialization."""

    def test_enum_values_are_stable_strings(self) -> None:
        assert GovernanceDecisionKind.ALLOWED.value == "allowed"
        assert GovernanceDecisionKind.BLOCKED.value == "blocked"
        assert GovernanceDecisionKind.REQUIRES_REVIEW.value == "requires_review"
        assert GovernanceDecisionKind.NOT_APPLICABLE.value == "not_applicable"

    def test_enum_serializes_as_string(self) -> None:
        data = json.dumps({"d": GovernanceDecisionKind.BLOCKED})
        assert '"blocked"' in data


class TestGovernanceReasonSeverity:
    """StrEnum stability and serialization."""

    def test_enum_values_are_stable_strings(self) -> None:
        assert GovernanceReasonSeverity.INFO.value == "info"
        assert GovernanceReasonSeverity.WARNING.value == "warning"
        assert GovernanceReasonSeverity.ERROR.value == "error"
        assert GovernanceReasonSeverity.CRITICAL.value == "critical"

    def test_enum_serializes_as_string(self) -> None:
        data = json.dumps({"s": GovernanceReasonSeverity.ERROR})
        assert '"error"' in data


class TestDecisionReason:
    """DecisionReason model validation."""

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            DecisionReason.model_validate({"code": "c", "message": "m", "extra": "x"})

    def test_default_severity_is_info(self) -> None:
        r = DecisionReason(code="c", message="m")
        assert r.severity == GovernanceReasonSeverity.INFO

    def test_accepts_all_valid_severities(self) -> None:
        for sv in GovernanceReasonSeverity:
            r = DecisionReason(code="c", message="m", severity=sv)
            assert r.severity == sv

    def test_requires_code_and_message(self) -> None:
        with pytest.raises(ValidationError):
            DecisionReason.model_validate({"code": "c"})
        with pytest.raises(ValidationError):
            DecisionReason.model_validate({"message": "m"})


class TestBlockedIntent:
    """BlockedIntent model validation."""

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            BlockedIntent.model_validate({
                "intent_id": "i",
                "reason": "r",
                "extra": "x",
            })

    def test_code_is_optional(self) -> None:
        b = BlockedIntent(intent_id="i", reason="r")
        assert b.code is None

    def test_requires_intent_id_and_reason(self) -> None:
        with pytest.raises(ValidationError):
            BlockedIntent.model_validate({"intent_id": "i"})
        with pytest.raises(ValidationError):
            BlockedIntent.model_validate({"reason": "r"})


class TestAllowedIntent:
    """AllowedIntent model validation."""

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            AllowedIntent.model_validate({
                "intent_id": "i",
                "reason": "r",
                "extra": "x",
            })

    def test_reason_is_optional(self) -> None:
        a = AllowedIntent(intent_id="i")
        assert a.reason is None

    def test_requires_intent_id(self) -> None:
        with pytest.raises(ValidationError):
            AllowedIntent.model_validate({"reason": "r"})


class TestGateDecision:
    """GateDecision model validation."""

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            GateDecision.model_validate({
                "decision": "allowed",
                "gate": "test",
                "extra": "x",
            })

    def test_default_schema_version(self) -> None:
        d = GateDecision(decision=GovernanceDecisionKind.ALLOWED, gate="test")
        assert d.schema_version == "rig.relay.governance_decision.v1"

    def test_workspace_id_is_optional(self) -> None:
        d = GateDecision(decision=GovernanceDecisionKind.ALLOWED, gate="test")
        assert d.workspace_id is None

    def test_serializes_to_json(self) -> None:
        d = GateDecision(decision=GovernanceDecisionKind.ALLOWED, gate="test")
        data = json.loads(d.model_dump_json())
        assert data["decision"] == "allowed"
        assert data["gate"] == "test"

    def test_no_forbidden_raw_fields(self) -> None:
        d = GateDecision(decision=GovernanceDecisionKind.ALLOWED, gate="test")
        dump = d.model_dump(mode="json")
        assert "content" not in dump
        assert "stdout" not in dump
        assert "stderr" not in dump
        assert "diff" not in dump
        assert "output" not in dump

    def test_reasons_and_intents_default_to_empty_lists(self) -> None:
        d = GateDecision(decision=GovernanceDecisionKind.ALLOWED, gate="test")
        assert d.reasons == []
        assert d.allowed_intents == []
        assert d.blocked_intents == []


class TestGovernanceEngine:
    """GovernanceEngine.evaluate_action_legality behavior."""

    def test_allowed_for_safe_read_only_intent(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.read_file",
            intent_kind="read_only",
            requested_capabilities=[RuntimeCapabilityKind.FILE_READ],
        )
        assert result.decision == GovernanceDecisionKind.ALLOWED

    def test_allowed_read_only_includes_allowed_intent(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.read_file",
            intent_kind="read_only",
            requested_capabilities=[RuntimeCapabilityKind.FILE_READ],
        )
        assert len(result.allowed_intents) == 1
        assert result.allowed_intents[0].intent_id == "intent.read_file"

    def test_blocked_for_blocked_provider_trust_tier(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.execute",
            intent_kind="execution",
            requested_capabilities=[RuntimeCapabilityKind.SHELL_PROPOSAL],
            provider_trust_tier=RuntimeProviderTrustTier.BLOCKED,
        )
        assert result.decision == GovernanceDecisionKind.BLOCKED

    def test_blocked_includes_reason_for_blocked_tier(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.execute",
            intent_kind="execution",
            requested_capabilities=[RuntimeCapabilityKind.SHELL_PROPOSAL],
            provider_trust_tier=RuntimeProviderTrustTier.BLOCKED,
        )
        assert any(r.code == "provider_trust_tier_blocked" for r in result.reasons)

    def test_blocked_for_unavailable_provider_status_with_execution_cap(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.execute",
            intent_kind="execution",
            requested_capabilities=[RuntimeCapabilityKind.SHELL_PROPOSAL],
            provider_status=RuntimeProviderStatus.UNAVAILABLE,
        )
        assert result.decision == GovernanceDecisionKind.BLOCKED

    def test_blocked_for_error_provider_status_with_execution_cap(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.execute",
            intent_kind="execution",
            requested_capabilities=[RuntimeCapabilityKind.SHELL_PROPOSAL],
            provider_status=RuntimeProviderStatus.ERROR,
        )
        assert result.decision == GovernanceDecisionKind.BLOCKED

    def test_not_blocked_for_unavailable_provider_with_read_cap(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.read",
            intent_kind="read_only",
            requested_capabilities=[RuntimeCapabilityKind.FILE_READ],
            provider_status=RuntimeProviderStatus.UNAVAILABLE,
        )
        assert result.decision != GovernanceDecisionKind.BLOCKED

    def test_requires_review_for_mutation_without_allow_mutation(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.write",
            intent_kind="mutation",
            requested_capabilities=[RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
        )
        assert result.decision == GovernanceDecisionKind.REQUIRES_REVIEW

    def test_requires_review_includes_reason_for_mutation(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.write",
            intent_kind="mutation",
            requested_capabilities=[RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
        )
        assert any(r.code == "mutation_requires_review" for r in result.reasons)

    def test_allows_mutation_when_allow_mutation_true(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.write",
            intent_kind="mutation",
            requested_capabilities=[RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
            allow_mutation=True,
        )
        assert result.decision == GovernanceDecisionKind.ALLOWED

    def test_requires_review_for_network_without_allow_network(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.fetch",
            intent_kind="network",
            requested_capabilities=[RuntimeCapabilityKind.NETWORK_FETCH_PROPOSAL],
        )
        assert result.decision == GovernanceDecisionKind.REQUIRES_REVIEW

    def test_requires_review_includes_reason_for_network(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.fetch",
            intent_kind="network",
            requested_capabilities=[RuntimeCapabilityKind.NETWORK_FETCH_PROPOSAL],
        )
        assert any(r.code == "network_requires_review" for r in result.reasons)

    def test_allows_network_when_allow_network_true(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.fetch",
            intent_kind="network",
            requested_capabilities=[RuntimeCapabilityKind.NETWORK_FETCH_PROPOSAL],
            allow_network=True,
        )
        assert result.decision == GovernanceDecisionKind.ALLOWED

    def test_blocked_when_dirty_policy_not_satisfied(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.write",
            intent_kind="mutation",
            requested_capabilities=[RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
            dirty_policy_satisfied=False,
        )
        assert result.decision == GovernanceDecisionKind.BLOCKED

    def test_blocked_dirty_policy_includes_reason(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.write",
            intent_kind="mutation",
            requested_capabilities=[RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
            dirty_policy_satisfied=False,
        )
        assert any(r.code == "dirty_policy_violated" for r in result.reasons)

    def test_not_applicable_for_no_capabilities_no_intent_kind(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1", intent_id="intent.unknown"
        )
        assert result.decision == GovernanceDecisionKind.NOT_APPLICABLE

    def test_not_applicable_includes_reason(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1", intent_id="intent.unknown"
        )
        assert any(r.code == "no_requested_capabilities" for r in result.reasons)

    def test_blocked_when_multiple_checks_fail(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.execute",
            intent_kind="execution",
            requested_capabilities=[RuntimeCapabilityKind.SHELL_PROPOSAL],
            provider_trust_tier=RuntimeProviderTrustTier.BLOCKED,
            dirty_policy_satisfied=False,
        )
        assert result.decision == GovernanceDecisionKind.BLOCKED
        assert len(result.reasons) >= 2

    def test_pure_no_side_effects(self) -> None:
        """Calling evaluate_action_legality does not mutate external state."""
        import os
        import tempfile

        before_files = set(os.listdir(tempfile.gettempdir()))
        GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.read",
            intent_kind="read_only",
            requested_capabilities=[RuntimeCapabilityKind.FILE_READ],
        )
        after_files = set(os.listdir(tempfile.gettempdir()))
        assert before_files == after_files

    def test_blocked_intent_includes_reason_code(self) -> None:
        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.write",
            intent_kind="mutation",
            requested_capabilities=[RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
            dirty_policy_satisfied=False,
        )
        assert len(result.blocked_intents) >= 1
        assert result.blocked_intents[0].code is not None


class TestGovernanceEngineSchema:
    """Schema validation for GateDecision model dumps."""

    _SCHEMA_PATH = (
        _PROJECT_ROOT
        / "docs"
        / "schemas"
        / "rig.relay.governance_decision.v1.schema.json"
    )

    def test_schema_validates_allowed_decision(self) -> None:
        import json

        import jsonschema

        with open(self._SCHEMA_PATH) as f:
            schema = json.load(f)

        d = GateDecision(decision=GovernanceDecisionKind.ALLOWED, gate="test")
        dump = json.loads(d.model_dump_json())
        jsonschema.validate(dump, schema)

    def test_schema_validates_blocked_decision_with_reasons(self) -> None:
        import json

        import jsonschema

        with open(self._SCHEMA_PATH) as f:
            schema = json.load(f)

        result = GovernanceEngine.evaluate_action_legality(
            workspace_id="ws1",
            intent_id="intent.execute",
            intent_kind="execution",
            requested_capabilities=[RuntimeCapabilityKind.SHELL_PROPOSAL],
            provider_trust_tier=RuntimeProviderTrustTier.BLOCKED,
            dirty_policy_satisfied=False,
        )
        dump = json.loads(result.model_dump_json())
        jsonschema.validate(dump, schema)

    def test_schema_rejects_unknown_top_level_fields(self) -> None:
        import json

        import jsonschema

        with open(self._SCHEMA_PATH) as f:
            schema = json.load(f)

        bad = {
            "decision": "allowed",
            "gate": "test",
            "unknown_field": "should be rejected",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)
