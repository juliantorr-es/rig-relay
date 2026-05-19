"""A2A identity module — security schemes and local identity metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from typing import Literal


@dataclass
class A2ASecurityScheme:
    scheme_type: Literal["bearer", "oauth", "api_key", "none"] = "none"
    description: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"scheme_type": self.scheme_type, "description": self.description}


@dataclass
class A2ALocalIdentity:
    agent_id_hash: str
    identity_proof_hash: str
    federation_trust_boundary: Literal["none"] = "none"

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_id_hash": self.agent_id_hash,
            "identity_proof_hash": self.identity_proof_hash,
            "federation_trust_boundary": self.federation_trust_boundary,
        }


def build_identity_metadata(agent_id: str) -> A2ALocalIdentity:
    agent_id_hash = hashlib.sha256(f"agent:{agent_id}:local".encode()).hexdigest()
    identity_proof_hash = hashlib.sha256(
        f"identity_proof:{agent_id}:local_only".encode()
    ).hexdigest()
    return A2ALocalIdentity(
        agent_id_hash=agent_id_hash, identity_proof_hash=identity_proof_hash
    )


def build_agent_card_with_security(
    agent_id: str,
    name: str,
    description: str = "",
    capabilities: list[str] | None = None,
    supported_task_types: list[str] | None = None,
) -> dict[str, object]:
    identity = build_identity_metadata(agent_id)
    security_scheme = A2ASecurityScheme(scheme_type="none")
    now = datetime.now(UTC).isoformat()
    return {
        "schema_version": "rig.relay.a2a.agent_card.v1",
        "agent_id": agent_id,
        "name": name,
        "description": description,
        "capabilities": capabilities or [],
        "supported_task_types": supported_task_types or [],
        "local_only": True,
        "remote_federation_supported": False,
        "content_light": True,
        "generated_at": now,
        "security_schemes": [security_scheme.to_dict()],
        "identity": identity.to_dict(),
    }


__all__ = [
    "A2ALocalIdentity",
    "A2ASecurityScheme",
    "build_agent_card_with_security",
    "build_identity_metadata",
]
