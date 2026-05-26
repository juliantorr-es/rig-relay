"""A2A protocol models — content-light agent-to-agent delegation data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal


class A2ATaskStatus(StrEnum):
    CREATED = "created"
    SUBMITTED = "submitted"
    RUNNING = "running"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class A2AAgentCard:
    agent_id: str
    name: str
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    supported_task_types: list[str] = field(default_factory=list)
    local_only: bool = True
    remote_federation_supported: bool = False
    content_light: bool = True
    schema_version: str = "rig.relay.a2a.agent_card.v1"
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    extensions: dict[str, object] | None = None
    trust_tier: str = ""


@dataclass
class A2ATaskCard:
    task_id: str
    agent_id: str
    status: A2ATaskStatus = A2ATaskStatus.CREATED
    description: str = ""
    input_hash: str = ""
    output_hash: str = ""
    trace_id: str = ""
    messages: list[str] = field(default_factory=list)
    events: list[A2ATaskLifecycleEvent] = field(default_factory=list)
    seq: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    content_light: bool = True
    schema_version: str = "rig.relay.a2a.task_card.v1"
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    artifact_refs: list[dict[str, object]] = field(default_factory=list)
    extensions: dict[str, object] | None = None
    cancellation_reason: str = ""
    refusal_reason: str = ""
    trust_tier: str = ""
    integrity_digest: str = ""


@dataclass
class A2ATaskLifecycleEvent:
    event_type: A2ATaskStatus
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata_hash: str = ""
    schema_version: str = "rig.relay.a2a.task_lifecycle_event.v1"
    task_id: str = ""
    trace_id: str = ""
    content_light: bool = True
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    seq: int = 0


@dataclass
class A2ATaskLifecycle:
    task_id: str
    events: list[A2ATaskLifecycleEvent] = field(default_factory=list)
    current_status: A2ATaskStatus = A2ATaskStatus.CREATED


@dataclass
class A2ADelegationReceipt:
    receipt_id: str
    delegating_agent_id: str
    receiving_agent_id: str
    task_id: str
    trace_id: str
    verdict: Literal["allowed", "refused", "completed"]
    refusal_code: str = ""
    content_light: bool = True
    schema_version: str = "rig.relay.a2a.delegation_receipt.v1"
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "delegating_agent_id": self.delegating_agent_id,
            "receiving_agent_id": self.receiving_agent_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "verdict": self.verdict,
            "refusal_code": self.refusal_code,
            "content_light": self.content_light,
            "generated_at": self.generated_at,
        }
