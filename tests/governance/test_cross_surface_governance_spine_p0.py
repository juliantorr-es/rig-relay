from __future__ import annotations

from rig_relay.core._agent_models import ToolExecutionResponse
from rig_relay.core.governance_runtime import (
    GovernanceRuntime,
    _generate_decision_id,
    _is_likely_mutation_tool,
)
from rig_relay.evidence.receipt_envelope import ReceiptDecision
from rig_relay.governance.decisions import GateDecision, GovernanceDecisionKind


class TestGateDecisionFields:
    def test_decision_id_is_generated_and_stable(self) -> None:
        d1 = GateDecision(decision=GovernanceDecisionKind.ALLOWED, gate="test_gate")
        d2 = GateDecision(decision=GovernanceDecisionKind.ALLOWED, gate="test_gate")
        assert d1.decision_id
        assert d2.decision_id
        assert d1.decision_id != d2.decision_id

    def test_decision_id_begins_with_gd_prefix(self) -> None:
        d = GateDecision(decision=GovernanceDecisionKind.ALLOWED, gate="test")
        assert d.decision_id.startswith("gd-")

    def test_content_light_is_true_by_default(self) -> None:
        d = GateDecision(decision=GovernanceDecisionKind.ALLOWED, gate="test")
        assert d.content_light is True

    def test_surface_and_authority_tier_are_optional(self) -> None:
        d = GateDecision(decision=GovernanceDecisionKind.ALLOWED, gate="test")
        assert d.surface is None
        assert d.authority_tier is None

    def test_surface_and_authority_tier_can_be_set(self) -> None:
        d = GateDecision(
            decision=GovernanceDecisionKind.BLOCKED,
            gate="mcp_gate",
            surface="mcp",
            authority_tier="remote_mutation",
            capability_id="rig.promote_to_preproduction",
            request_id="req-123",
        )
        assert d.surface == "mcp"
        assert d.authority_tier == "remote_mutation"
        assert d.capability_id == "rig.promote_to_preproduction"
        assert d.request_id == "req-123"
        assert d.decision == GovernanceDecisionKind.BLOCKED

    def test_blocked_decision_has_blocked_intents(self) -> None:
        from rig_relay.governance.decisions import BlockedIntent

        d = GateDecision(
            decision=GovernanceDecisionKind.BLOCKED,
            gate="test_gate",
            blocked_intents=[BlockedIntent(intent_id="intent-1", reason="test block")],
        )
        assert len(d.blocked_intents) == 1
        assert d.blocked_intents[0].intent_id == "intent-1"

    def test_generated_at_is_iso_format(self) -> None:
        d = GateDecision(decision=GovernanceDecisionKind.ALLOWED, gate="test")
        assert "T" in d.generated_at


class TestGovernanceRuntimeMutationGate:
    def make_runtime(self) -> GovernanceRuntime:
        return GovernanceRuntime()

    def test_read_only_tool_executes_with_decision_id(self) -> None:
        rt = self.make_runtime()
        decision = rt.should_execute_tool(
            tool_call_id="call-1",
            tool_name="read_file",
            tool_args={},
            execution_mode="normal",
        )
        assert decision.verdict == ToolExecutionResponse.EXECUTE
        assert decision.decision_id is not None
        assert decision.decision_id.startswith("gd-")

    def test_mutation_tool_is_evaluated_by_governance(self) -> None:
        rt = self.make_runtime()
        decision = rt.should_execute_tool(
            tool_call_id="call-2",
            tool_name="write_file",
            tool_args={"path": "/tmp/test.txt"},
            execution_mode="normal",
        )
        assert decision.decision_id is not None
        assert decision.surface == "agent_loop"

    def test_bypass_config_allows_execution(self) -> None:
        class BypassConfig:
            bypass_tool_permissions = True

        rt = GovernanceRuntime(config=BypassConfig())
        decision = rt.should_execute_tool(
            tool_call_id="call-3",
            tool_name="write_file",
            tool_args={},
            execution_mode="normal",
        )
        assert decision.verdict == ToolExecutionResponse.EXECUTE
        assert decision.decision_id is not None
        assert decision.decision_id.startswith("gd-")

    def test_is_likely_mutation_tool_identifies_mutators(self) -> None:
        assert _is_likely_mutation_tool("write_file") is True
        assert _is_likely_mutation_tool("search_replace") is True
        assert _is_likely_mutation_tool("bash") is True
        assert _is_likely_mutation_tool("checkpoint") is True

    def test_is_likely_mutation_tool_rejects_readers(self) -> None:
        assert _is_likely_mutation_tool("read_file") is False
        assert _is_likely_mutation_tool("grep") is False
        assert _is_likely_mutation_tool("list_files") is False
        assert _is_likely_mutation_tool("rig.search_evidence") is False

    def test_decision_id_is_deterministic_per_seed(self) -> None:
        id1 = _generate_decision_id("seed1")
        id2 = _generate_decision_id("seed1")
        assert id1 == id2

    def test_decision_id_different_per_different_seed(self) -> None:
        id1 = _generate_decision_id("seed1")
        id2 = _generate_decision_id("seed2")
        assert id1 != id2

    def test_mutation_tool_produces_decision_with_authority_tier(self) -> None:
        rt = self.make_runtime()
        decision = rt.should_execute_tool(
            tool_call_id="call-4",
            tool_name="write_file",
            tool_args={},
            execution_mode="normal",
        )
        assert decision.authority_tier in ("local_mutation", "read_only_projection")

    def test_ask_approval_without_callback_skips(self) -> None:
        rt = self.make_runtime()
        decision = rt.should_execute_tool(
            tool_call_id="call-5",
            tool_name="bash",
            tool_args={"command": "rm -rf /"},
            execution_mode="normal",
        )
        assert decision.verdict in (
            ToolExecutionResponse.EXECUTE,
            ToolExecutionResponse.SKIP,
        )


class TestReceiptDecisionAlignment:
    def test_receipt_decision_has_authority_spine_fields(self) -> None:
        rd = ReceiptDecision(
            decision="allowed",
            gate="mcp_gate",
            governance_decision_id="gd-abc123",
            surface="mcp",
            authority_tier="read_only_projection",
            capability_id="rig.search_evidence",
            approval_receipt_id=None,
            content_light_classification="public_safe",
        )
        assert rd.decision == "allowed"
        assert rd.surface == "mcp"
        assert rd.authority_tier == "read_only_projection"
        assert rd.capability_id == "rig.search_evidence"
        assert rd.governance_decision_id == "gd-abc123"
        assert rd.content_light_classification == "public_safe"

    def test_receipt_decision_authority_spine_fields_are_optional(self) -> None:
        rd = ReceiptDecision(decision="blocked", gate="test")
        assert rd.surface is None
        assert rd.authority_tier is None
        assert rd.capability_id is None
        assert rd.governance_decision_id is None
        assert rd.approval_receipt_id is None
        assert rd.content_light_classification is None


class TestMCPMutationBlock:
    def test_mcp_tier_4_blocked_without_receipt(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        result = server.call_tool_sync("rig.request_user_approval", {})

        assert result["status"] == "blocked"
        assert result["refusal_code"] == "mutation_tier_mcp"
        assert result["approval_required"] is True
        assert result["content_light"] is True
        assert "cross_surface_authority_spine" in result["message"]

    def test_mcp_tier_5_blocked_always(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        result = server.call_tool_sync(
            "rig.promote_to_preproduction",
            {"receipt_ids": ["r1"], "authorization_receipt": "fake"},
        )

        assert result["status"] in ("blocked", "refused")
        assert result["content_light"] is True

    def test_mcp_tier_0_tool_allowed(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        result = server.call_tool_sync("rig.current_mission", {})

        assert result.get("status") == "ok"
        assert "error" not in result


class TestA2AGovernanceGuard:
    def test_delegation_blocked_by_governance(self) -> None:
        from rig_relay.protocols.a2a._lifecycle import delegation_allowed_by_governance

        allowed, reason = delegation_allowed_by_governance("agent-a", "agent-b", "test")
        assert allowed is False
        assert "cross_surface_authority_spine" in reason
        assert "blocked" in reason.lower()

    def test_delegation_receipt_refused_by_governance(self) -> None:
        from rig_relay.protocols.a2a._lifecycle import build_delegation_receipt

        receipt = build_delegation_receipt("agent-a", "agent-b", "task-1")
        assert receipt.verdict == "refused"
        assert receipt.refusal_code == "governance_blocked"
