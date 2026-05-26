"""A2A canonicalization and integrity digest tests — C1 domain model validation."""

from __future__ import annotations

from rig_relay.protocols.a2a._canonical import (
    compute_agent_card_digest,
    compute_digest,
    compute_governance_binding_digest,
    compute_task_card_digest,
    content_integrity_chain,
    dump_canonical_json,
    verify_digest,
)


class TestCanonicalJSON:
    def test_simple_object_deterministic(self):
        a = {"b": 1, "a": 2}
        b = {"a": 2, "b": 1}
        assert dump_canonical_json(a) == dump_canonical_json(b)

    def test_nested_object_deterministic(self):
        a = {"outer": {"b": 1, "a": 2}}
        b = {"outer": {"a": 2, "b": 1}}
        assert dump_canonical_json(a) == dump_canonical_json(b)

    def test_array_order_preserved(self):
        a = [3, 1, 2]
        b = [1, 2, 3]
        assert dump_canonical_json(a) != dump_canonical_json(b)

    def test_unicode_handling(self):
        obj = {"name": "café"}
        result = dump_canonical_json(obj)
        assert "café" in result.decode("utf-8")

    def test_no_trailing_whitespace(self):
        result = dump_canonical_json({"a": 1})
        text = result.decode("utf-8")
        assert not text.endswith(" ")
        assert not text.endswith("\n")


class TestDigestComputation:
    def test_compute_digest_returns_hex_string(self):
        digest = compute_digest({"test": "value"})
        assert isinstance(digest, str)
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_compute_digest_deterministic(self):
        d1 = compute_digest({"a": 1, "b": 2})
        d2 = compute_digest({"b": 2, "a": 1})
        assert d1 == d2

    def test_compute_digest_differs_for_different_content(self):
        d1 = compute_digest({"a": 1})
        d2 = compute_digest({"a": 2})
        assert d1 != d2


class TestAgentCardDigest:
    def test_agent_card_digest_stable_across_generation(self):
        card1 = {
            "schema_version": "rig.relay.a2a.agent_card.v1",
            "agent_id": "agent-1",
            "name": "Test",
            "description": "desc",
            "capabilities": ["read"],
            "supported_task_types": ["explore"],
            "local_only": True,
            "remote_federation_supported": False,
            "content_light": True,
            "generated_at": "2026-01-01T00:00:00Z",
        }
        card2 = {**card1, "generated_at": "2026-06-01T12:00:00Z"}
        assert compute_agent_card_digest(card1) == compute_agent_card_digest(card2)

    def test_agent_card_digest_differs_for_different_capabilities(self):
        card1 = {
            "schema_version": "rig.relay.a2a.agent_card.v1",
            "agent_id": "agent-1",
            "name": "Test",
            "description": "desc",
            "capabilities": ["read"],
            "supported_task_types": [],
            "local_only": True,
            "remote_federation_supported": False,
            "content_light": True,
            "generated_at": "2026-01-01T00:00:00Z",
        }
        card2 = {**card1, "capabilities": ["read", "write"]}
        assert compute_agent_card_digest(card1) != compute_agent_card_digest(card2)


class TestTaskCardDigest:
    def test_task_card_digest_stable_across_updates(self):
        card1 = {
            "schema_version": "rig.relay.a2a.task_card.v1",
            "task_id": "t1",
            "agent_id": "a1",
            "status": "created",
            "description": "test",
            "input_hash": "",
            "output_hash": "",
            "trace_id": "tr1",
            "messages": [],
            "events": [],
            "seq": 1,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "content_light": True,
            "generated_at": "2026-01-01T00:00:00Z",
            "artifact_refs": [],
            "cancellation_reason": "",
            "refusal_reason": "",
            "trust_tier": "",
            "integrity_digest": "",
        }
        card2 = {
            **card1,
            "updated_at": "2026-06-01T12:00:00Z",
            "generated_at": "2026-06-01T12:00:00Z",
        }
        assert compute_task_card_digest(card1) == compute_task_card_digest(card2)

    def test_task_card_digest_differs_for_status_change(self):
        card1 = {
            "schema_version": "rig.relay.a2a.task_card.v1",
            "task_id": "t1",
            "agent_id": "a1",
            "status": "created",
            "description": "test",
            "trace_id": "tr1",
            "content_light": True,
            "generated_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        card2 = {**card1, "status": "running"}
        assert compute_task_card_digest(card1) != compute_task_card_digest(card2)


class TestGovernanceBindingDigest:
    def test_binding_digest_hex_string(self):
        binding = {
            "schema_version": "rig.relay.a2a.governance_binding.v1",
            "mission_id": "m1",
            "confidentiality_tier": "internal",
            "mutation_intent": "none",
            "execution_risk": "low",
            "content_light": True,
        }
        digest = compute_governance_binding_digest(binding)
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_binding_digest_deterministic(self):
        binding = {
            "schema_version": "rig.relay.a2a.governance_binding.v1",
            "mission_id": "m1",
            "confidentiality_tier": "internal",
            "mutation_intent": "none",
            "execution_risk": "low",
            "content_light": True,
        }
        assert compute_governance_binding_digest(
            binding
        ) == compute_governance_binding_digest(binding)


class TestVerifyDigest:
    def test_verify_matching_digest(self):
        obj = {"key": "value"}
        digest = compute_digest(obj)
        assert verify_digest(obj, digest)

    def test_verify_mismatching_digest(self):
        obj = {"key": "value"}
        assert not verify_digest(obj, "0" * 64)

    def test_verify_tampered_object(self):
        obj1 = {"key": "value"}
        obj2 = {"key": "tampered"}
        digest1 = compute_digest(obj1)
        assert not verify_digest(obj2, digest1)


class TestIntegrityChain:
    def test_chain_deterministic(self):
        c1 = content_integrity_chain("aaa", "bbb", "ccc")
        c2 = content_integrity_chain("aaa", "bbb", "ccc")
        assert c1 == c2

    def test_chain_order_matters(self):
        c1 = content_integrity_chain("aaa", "bbb")
        c2 = content_integrity_chain("bbb", "aaa")
        assert c1 != c2

    def test_chain_single_digest(self):
        result = content_integrity_chain("aaa")
        assert isinstance(result, str)
        assert len(result) == 64

    def test_chain_empty(self):
        result = content_integrity_chain()
        assert isinstance(result, str)
        assert len(result) == 64
