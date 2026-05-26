"""ACP-to-A2A control projection tests — C5 adapter validation."""

from __future__ import annotations

from rig_relay.protocols.a2a._acp_adapter import (
    ACPA2ACapabilityStatus,
    build_acp_a2a_capability_map,
    build_acp_a2a_observation,
    inspect_a2a_capability,
    validate_acp_task_request,
)
from rig_relay.protocols.a2a._trust import TrustTier


class TestCapabilityMap:
    def test_map_returns_all_capabilities(self):
        entries = build_acp_a2a_capability_map()
        assert len(entries) == 10
        caps = {e.capability for e in entries}
        assert "discovery_only" in caps
        assert "mutation_pending_authority" in caps

    def test_discovery_is_available_for_acp(self):
        entries = build_acp_a2a_capability_map()
        discovery = next(e for e in entries if e.capability == "discovery_only")
        assert discovery.status == ACPA2ACapabilityStatus.AVAILABLE

    def test_proposal_is_available_for_acp(self):
        entries = build_acp_a2a_capability_map()
        proposal = next(e for e in entries if e.capability == "proposal_generation")
        assert proposal.status == ACPA2ACapabilityStatus.AVAILABLE

    def test_mutation_requires_authorization(self):
        entries = build_acp_a2a_capability_map()
        mutation = next(
            e for e in entries if e.capability == "mutation_pending_authority"
        )
        assert mutation.status == ACPA2ACapabilityStatus.REQUIRES_AUTHORIZATION
        assert mutation.authorization_dependency == "lane_a_authority"

    def test_github_requires_lane_b(self):
        entries = build_acp_a2a_capability_map()
        github = next(e for e in entries if e.capability == "github_pending_lane_b")
        assert github.status == ACPA2ACapabilityStatus.REQUIRES_AUTHORIZATION
        assert github.authorization_dependency == "lane_b_authority"

    def test_runtime_delegation_requires_authorization(self):
        entries = build_acp_a2a_capability_map()
        delegation = next(e for e in entries if e.capability == "runtime_delegation")
        assert delegation.status == ACPA2ACapabilityStatus.REQUIRES_AUTHORIZATION

    def test_map_uses_acp_trust_tier(self):
        entries = build_acp_a2a_capability_map()
        for e in entries:
            assert e.trust_tier == "acp_originated"

    def test_external_tier_has_more_refusals(self):
        external_entries = build_acp_a2a_capability_map(
            trust_tier=TrustTier.EXTERNAL_UNAUTHENTICATED
        )
        refused = sum(
            1 for e in external_entries if e.status == ACPA2ACapabilityStatus.REFUSED
        )
        assert refused > 1


class TestCapabilityInspection:
    def test_inspect_known_available(self):
        result = inspect_a2a_capability("discovery_only")
        assert result.status == ACPA2ACapabilityStatus.AVAILABLE

    def test_inspect_unknown_capability(self):
        result = inspect_a2a_capability("teleportation")
        assert result.status == ACPA2ACapabilityStatus.NOT_IMPLEMENTED
        assert "Unknown" in result.refusal_reason

    def test_inspect_mutation_refused_for_unauthenticated(self):
        result = inspect_a2a_capability(
            "mutation_pending_authority", trust_tier=TrustTier.EXTERNAL_UNAUTHENTICATED
        )
        assert result.status == ACPA2ACapabilityStatus.REFUSED
        assert result.refusal_reason != ""


class TestTaskRequestValidation:
    def test_safe_proposal_accepted(self):
        valid, result = validate_acp_task_request("Plan a refactoring")
        assert valid
        assert result["status"] == "accepted"
        assert result["mutation_refused"] is True

    def test_mutation_request_refused(self):
        valid, result = validate_acp_task_request(
            "Fix the bug", required_capability="mutation_pending_authority"
        )
        assert not valid
        assert result["refusal_code"] == "requires_authorization"

    def test_github_request_refused(self):
        valid, result = validate_acp_task_request(
            "Push to main", required_capability="github_pending_lane_b"
        )
        assert not valid
        assert result["refusal_code"] == "lane_b_authority_required"

    def test_validation_request_refused(self):
        valid, result = validate_acp_task_request(
            "Run tests", required_capability="validation_pending_lane_a"
        )
        assert not valid
        assert result["refusal_code"] == "lane_a_authority_required"

    def test_unknown_capability_refused(self):
        valid, result = validate_acp_task_request(
            "Do stuff", required_capability="impossible"
        )
        assert not valid
        assert result["refusal_code"] == "unknown_capability"

    def test_secret_content_refused(self):
        valid, result = validate_acp_task_request("Use api_key: sk-abc to call API")
        assert not valid
        assert result["refusal_code"] == "validation_failed"


class TestObservation:
    def test_observation_is_content_light(self):
        obs = build_acp_a2a_observation(
            task_id="t1",
            status="running",
            messages_count=3,
            artifacts_count=1,
            trust_tier="acp_originated",
        )
        assert obs["task_id"] == "t1"
        assert obs["messages_count"] == 3
        assert obs["content_light"] is True
        assert "raw_message" not in obs
        assert "raw_artifact" not in obs
        assert "prompt" not in obs

    def test_observation_no_raw_content(self):
        obs = build_acp_a2a_observation("t1", "completed", 0, 0)
        serialized = str(obs)
        assert "secret" not in serialized
        assert "api_key" not in serialized
