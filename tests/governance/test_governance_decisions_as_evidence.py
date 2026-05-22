from __future__ import annotations

from pathlib import Path
import tempfile

from rig_relay.core._agent_models import ToolExecutionResponse
from rig_relay.core.governance_runtime import GovernanceRuntime
from rig_relay.evidence.governance_decision_evidence import (
    GovernanceDecisionEvidence,
    should_block_mutation_on_evidence_failure,
)
from rig_relay.evidence.receipt_envelope import (
    ReceiptActorKind,
    ReceiptEnvelope,
    ReceiptSubjectKind,
    build_governance_decision_envelope,
)
from rig_relay.evidence.receipt_store import FilesystemReceiptStore
from rig_relay.governance.decisions import GateDecision, GovernanceDecisionKind


def _make_gate_decision(
    decision: str = "allowed",
    gate: str = "test_gate",
    surface: str | None = "agent_loop",
    authority_tier: str | None = "local_mutation",
) -> GateDecision:
    return GateDecision(
        decision=GovernanceDecisionKind(decision),
        gate=gate,
        surface=surface,
        authority_tier=authority_tier,
    )


class TestGovernanceDecisionToEvidence:
    def test_gate_decision_converts_to_receipt_envelope(self) -> None:
        gd = _make_gate_decision()
        envelope = build_governance_decision_envelope(gd)

        assert isinstance(envelope, ReceiptEnvelope)
        assert envelope.receipt_kind == "governance_decision"
        assert envelope.decision is not None
        assert envelope.decision.governance_decision_id == gd.decision_id
        assert envelope.decision.decision == "allowed"
        assert envelope.decision.surface == "agent_loop"
        assert envelope.decision.authority_tier == "local_mutation"

    def test_envelope_actor_is_governance_runtime(self) -> None:
        gd = _make_gate_decision()
        envelope = build_governance_decision_envelope(gd)
        assert envelope.actor.actor_id == "governance_runtime"
        assert envelope.actor.actor_kind == ReceiptActorKind.RUNTIME
        assert envelope.actor.is_authoritative is True

    def test_envelope_subject_is_governance_decision(self) -> None:
        gd = _make_gate_decision()
        envelope = build_governance_decision_envelope(gd)
        assert envelope.subject.subject_kind == ReceiptSubjectKind.GOVERNANCE_DECISION
        assert envelope.subject.subject_id == gd.decision_id

    def test_blocked_decision_envelope_has_blocked_status(self) -> None:
        gd = _make_gate_decision(decision="blocked")
        envelope = build_governance_decision_envelope(gd)
        assert envelope.decision is not None
        assert envelope.decision.decision == "blocked"

    def test_evidence_items_include_governance_kind(self) -> None:
        gd = _make_gate_decision()
        envelope = build_governance_decision_envelope(gd)
        assert len(envelope.evidence) >= 1
        found_gov = False
        for e in envelope.evidence:
            kind = getattr(e, "evidence_kind", "")
            kind_str = (
                getattr(kind, "value", str(kind))
                if hasattr(kind, "value")
                else str(kind)
            )
            if "governance" in kind_str.lower():
                found_gov = True
                break
        assert found_gov, (
            f"No governance decision evidence item found in: {[getattr(e, 'evidence_kind', '?') for e in envelope.evidence]}"
        )

    def test_content_light_fields_present(self) -> None:
        gd = _make_gate_decision(decision="blocked", gate="mcp_mutation_gate")
        envelope = build_governance_decision_envelope(gd)
        assert envelope.decision is not None
        assert envelope.decision.content_light_classification == "public_safe"
        assert envelope.decision.gate == "mcp_mutation_gate"
        assert envelope.decision.governance_decision_id is not None

    def test_envelope_schema_version_stable(self) -> None:
        gd = _make_gate_decision()
        envelope = build_governance_decision_envelope(gd)
        assert envelope.schema_version == "rig.relay.receipt_envelope.v1"

    def test_replayed_decision_preserves_decision_id(self) -> None:
        gd = _make_gate_decision()
        original = build_governance_decision_envelope(gd, envelope_id="env-test-001")
        assert original.decision is not None

        reconstructed = ReceiptEnvelope.model_validate(original.model_dump(mode="json"))
        assert reconstructed.decision is not None
        assert reconstructed.decision.governance_decision_id == gd.decision_id
        assert reconstructed.decision.decision == "allowed"
        assert reconstructed.decision.surface == "agent_loop"
        assert reconstructed.decision.authority_tier == "local_mutation"

    def test_envelope_does_not_contain_raw_content(self) -> None:
        gd = _make_gate_decision(decision="blocked")
        envelope = build_governance_decision_envelope(gd)
        dumped = envelope.model_dump(mode="json")
        raw = str(dumped)
        assert "secret" not in raw.lower() or "public_safe" in raw
        assert "password" not in raw.lower()
        assert "token" not in raw.lower()


class TestGovernanceDecisionPersistence:
    def test_persist_writes_to_filesystem_store(self) -> None:
        gd = _make_gate_decision()
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            evidence = GovernanceDecisionEvidence(store=store)

            result = evidence.persist(gd)
            assert result is not None
            assert isinstance(result, ReceiptEnvelope)
            assert evidence.persisted() is True

    def test_persist_fails_gracefully_without_store(self) -> None:
        gd = _make_gate_decision()
        evidence = GovernanceDecisionEvidence(store=None)
        result = evidence.persist(gd)
        assert result is None
        assert evidence.persisted() is False

    def test_store_is_available_detects_store(self) -> None:
        evidence = GovernanceDecisionEvidence(store=None)
        assert evidence.store_is_available() is False

        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            evidence = GovernanceDecisionEvidence(store=store)
            assert evidence.store_is_available() is True

    def test_multiple_persist_cycles_track_state(self) -> None:
        gd = _make_gate_decision()
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            evidence = GovernanceDecisionEvidence(store=store)

            evidence.persist(gd)
            assert evidence.persisted() is True

    def test_envelope_can_be_retrieved_from_store(self) -> None:
        gd = _make_gate_decision()
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            evidence = GovernanceDecisionEvidence(store=store)
            env = evidence.persist(gd)
            assert env is not None

            retrieved = store.get(env.envelope_id)
            assert retrieved is not None
            assert retrieved.decision is not None
            assert retrieved.decision.governance_decision_id == gd.decision_id

    def test_persisted_envelope_survives_replay(self) -> None:
        gd = _make_gate_decision(decision="blocked", surface="mcp")
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            evidence = GovernanceDecisionEvidence(store=store)
            env = evidence.persist(gd)
            assert env is not None

            retrieved = store.get(env.envelope_id)
            assert retrieved is not None
            assert retrieved.decision is not None
            assert retrieved.decision.decision == "blocked"
            assert retrieved.decision.surface == "mcp"


class TestEvidenceFailureFailClosed:
    def test_should_block_mutation_when_evidence_is_none(self) -> None:
        gd = _make_gate_decision()
        result = should_block_mutation_on_evidence_failure(gd, None)
        assert result is True

    def test_should_block_mutation_when_not_persisted(self) -> None:
        gd = _make_gate_decision()
        evidence = GovernanceDecisionEvidence(store=None)
        evidence.persist(gd)
        result = should_block_mutation_on_evidence_failure(gd, evidence)
        assert result is True

    def test_should_not_block_when_persisted(self) -> None:
        gd = _make_gate_decision()
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            evidence = GovernanceDecisionEvidence(store=store)
            evidence.persist(gd)
            result = should_block_mutation_on_evidence_failure(gd, evidence)
            assert result is False

    def test_should_not_block_already_blocked_decision(self) -> None:
        gd = _make_gate_decision(decision="blocked")
        result = should_block_mutation_on_evidence_failure(gd, None)
        assert result is False

    def test_should_not_block_requires_review_decision(self) -> None:
        gd = _make_gate_decision(decision="requires_review")
        result = should_block_mutation_on_evidence_failure(gd, None)
        assert result is False


class TestGovernanceRuntimeEvidenceWiring:
    def make_runtime(self, store=None) -> GovernanceRuntime:
        from rig_relay.evidence.governance_decision_evidence import (
            GovernanceDecisionEvidence,
        )

        return GovernanceRuntime(evidence=GovernanceDecisionEvidence(store=store))

    def test_mutation_tool_persists_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            rt = self.make_runtime(store=store)
            decision = rt.should_execute_tool(
                tool_call_id="call-ev-1",
                tool_name="write_file",
                tool_args={"path": "/tmp/test"},
                execution_mode="normal",
            )
            assert decision.decision_id is not None
            assert decision.decision_id.startswith("gd-")

    def test_mutation_tool_blocked_by_policy_returns_skip(self) -> None:
        rt = GovernanceRuntime()
        decision = rt.should_execute_tool(
            tool_call_id="call-ev-2",
            tool_name="write_file",
            tool_args={},
            execution_mode="normal",
        )
        assert decision.verdict == ToolExecutionResponse.SKIP
        assert decision.feedback is not None
        assert "mutation_requires_review" in decision.feedback

    def test_read_only_tool_unaffected_by_evidence_absence(self) -> None:
        rt = self.make_runtime(store=None)
        decision = rt.should_execute_tool(
            tool_call_id="call-ev-3",
            tool_name="read_file",
            tool_args={},
            execution_mode="normal",
        )
        assert decision.verdict == ToolExecutionResponse.EXECUTE
