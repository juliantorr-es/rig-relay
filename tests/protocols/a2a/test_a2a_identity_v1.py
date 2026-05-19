from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.protocols.a2a._identity import (
    A2ASecurityScheme,
    build_agent_card_with_security,
    build_identity_metadata,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
S = REPO_ROOT / "docs" / "schemas"


def _load(name: str) -> dict:
    return json.loads((S / name).read_text(encoding="utf-8"))


def _v(instance: dict, name: str) -> None:
    jsonschema.validate(instance, _load(name))


class TestA2AIdentityV1:
    def test_security_scheme_none_is_valid(self):
        scheme = A2ASecurityScheme(scheme_type="none")
        d = scheme.to_dict()
        assert d["scheme_type"] == "none"
        assert d["description"] == ""

    def test_agent_card_with_security_schemes_field_present(self):
        card = build_agent_card_with_security(
            agent_id="a1",
            name="Test Agent",
            description="For testing",
            capabilities=["read", "explore"],
        )
        assert "security_schemes" in card
        schemes = card["security_schemes"]
        assert isinstance(schemes, list)
        assert len(schemes) == 1

    def test_agent_card_security_schemes_empty_when_local_only(self):
        card = build_agent_card_with_security(agent_id="a1", name="Test Agent")
        schemes = card["security_schemes"]
        assert isinstance(schemes, list)
        assert len(schemes) == 1
        assert all(
            isinstance(s, dict) and s.get("scheme_type") == "none" for s in schemes
        )

    def test_identity_metadata_is_content_light(self):
        identity = build_identity_metadata("a1")
        d = identity.to_dict()
        assert "agent_id_hash" in d
        assert "identity_proof_hash" in d
        assert d["federation_trust_boundary"] == "none"
        assert "access_token" not in d
        assert "api_key" not in d

    def test_identity_metadata_no_raw_credentials(self):
        identity = build_identity_metadata("agent-with-secret-api-key")
        d = identity.to_dict()
        serialized = json.dumps(d)
        assert "secret" not in serialized
        assert "agent-with-secret-api-key" not in serialized
        agent_hash = d["agent_id_hash"]
        assert isinstance(agent_hash, str)
        assert len(agent_hash) == 64

    def test_federation_trust_boundary_is_none(self):
        identity = build_identity_metadata("a1")
        assert identity.federation_trust_boundary == "none"
        d = identity.to_dict()
        assert d["federation_trust_boundary"] == "none"

    def test_updated_agent_card_schema_validates_with_security_identity(self):
        card = build_agent_card_with_security(
            agent_id="a1",
            name="Test Agent",
            description="For schema validation",
            capabilities=["read", "explore"],
            supported_task_types=["exploration"],
        )
        _v(card, "rig.relay.a2a.agent_card.v1.schema.json")

    def test_agent_card_schema_rejects_without_security_schemes(self):
        schema = _load("rig.relay.a2a.agent_card.v1.schema.json")
        card = {
            "schema_version": "rig.relay.a2a.agent_card.v1",
            "agent_id": "a1",
            "name": "Test",
            "description": "",
            "capabilities": [],
            "supported_task_types": [],
            "local_only": True,
            "remote_federation_supported": False,
            "content_light": True,
            "generated_at": "2026-01-01T00:00:00Z",
            "identity": {
                "agent_id_hash": "0" * 64,
                "identity_proof_hash": "0" * 64,
                "federation_trust_boundary": "none",
            },
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(card, schema)

    def test_agent_card_schema_rejects_without_identity(self):
        schema = _load("rig.relay.a2a.agent_card.v1.schema.json")
        card = {
            "schema_version": "rig.relay.a2a.agent_card.v1",
            "agent_id": "a1",
            "name": "Test",
            "description": "",
            "capabilities": [],
            "supported_task_types": [],
            "local_only": True,
            "remote_federation_supported": False,
            "content_light": True,
            "generated_at": "2026-01-01T00:00:00Z",
            "security_schemes": [{"scheme_type": "none", "description": ""}],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(card, schema)

    def test_identity_hashes_are_deterministic(self):
        i1 = build_identity_metadata("a1")
        i2 = build_identity_metadata("a1")
        assert i1.agent_id_hash == i2.agent_id_hash
        assert i1.identity_proof_hash == i2.identity_proof_hash

    def test_identity_hashes_differ_for_different_agents(self):
        i1 = build_identity_metadata("a1")
        i2 = build_identity_metadata("a2")
        assert i1.agent_id_hash != i2.agent_id_hash
        assert i1.identity_proof_hash != i2.identity_proof_hash

    def test_build_agent_card_with_security_preserves_fields(self):
        card = build_agent_card_with_security(
            agent_id="a1",
            name="Test Agent",
            description="Test desc",
            capabilities=["read", "write"],
            supported_task_types=["explore", "build"],
        )
        assert card["schema_version"] == "rig.relay.a2a.agent_card.v1"
        assert card["agent_id"] == "a1"
        assert card["name"] == "Test Agent"
        assert card["description"] == "Test desc"
        assert card["capabilities"] == ["read", "write"]
        assert card["supported_task_types"] == ["explore", "build"]
        assert card["local_only"] is True
        assert card["remote_federation_supported"] is False
        assert card["content_light"] is True

    def test_security_scheme_fields_match_schema_requirements(self):
        scheme = A2ASecurityScheme(scheme_type="bearer", description="Test bearer")
        d = scheme.to_dict()
        assert set(d.keys()) == {"scheme_type", "description"}

    def test_identity_fields_match_schema_requirements(self):
        identity = build_identity_metadata("a1")
        d = identity.to_dict()
        assert set(d.keys()) == {
            "agent_id_hash",
            "identity_proof_hash",
            "federation_trust_boundary",
        }
