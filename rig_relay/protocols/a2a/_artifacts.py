"""A2A artifact models — typed, hash-heavy, content-light artifact exchange.

Artifacts are the canonical evidence container for A2A task results.
They comply with Rig Relay's content-light doctrine: no raw prompts,
private source files, secrets, or uncontrolled model outputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class A2AArtifactKind(StrEnum):
    """Typed artifact kinds for A2A evidence exchange."""

    PROPOSED_SCOPE = "proposed_scope"
    PROGRESS_UPDATE = "progress_update"
    BOUNDED_PROOF_REFERENCE = "bounded_proof_reference"
    BLOCKED_STATE = "blocked_state"
    REFUSAL_EVIDENCE = "refusal_evidence"
    CHECKPOINT_REQUEST_PROPOSAL = "checkpoint_request_proposal"
    INTEGRATION_READINESS_PROPOSAL = "integration_readiness_proposal"
    VALIDATION_REQUEST_PROPOSAL = "validation_request_proposal"
    DISCOVERED_RISK = "discovered_risk"
    TASK_RESULT = "task_result"
    EVIDENCE_BUNDLE = "evidence_bundle"
    CAPABILITY_RESPONSE = "capability_response"


@dataclass
class A2AArtifact:
    """A content-light artifact produced or consumed by an A2A task.

    Carries a hash reference to its payload, never the raw content
    in durable records. Payload retrieval is bounded and governed
    separately.
    """

    artifact_id: str
    artifact_kind: A2AArtifactKind
    description: str = ""
    content_hash: str = ""
    byte_size: int = 0
    content_type: str = "application/json"
    task_id: str = ""
    trace_id: str = ""
    producer_trust_tier: str = ""
    required_capability: str = ""
    content_light: bool = True
    schema_version: str = "rig.relay.a2a.artifact.v1"
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class A2AArtifactRef:
    """Lightweight reference to an A2A artifact.

    Carried in task cards and status updates instead of the
    full artifact body. Enables content-light task state while
    preserving discoverability.
    """

    artifact_id: str
    artifact_kind: A2AArtifactKind
    content_hash: str = ""
    description: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_kind": self.artifact_kind.value,
            "content_hash": self.content_hash,
            "description": self.description,
            "generated_at": self.generated_at,
        }


__all__ = ["A2AArtifact", "A2AArtifactKind", "A2AArtifactRef"]
