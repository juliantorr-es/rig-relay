from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum, auto
import hashlib
import json
import secrets
from typing import Any


class EventSensitivityClass(StrEnum):
    PUBLIC = auto()
    INTERNAL_OPERATIONAL = auto()
    TELEMETRY_OPT_IN = auto()
    REDACTION_REQUIRED = auto()
    NEVER_EMIT = auto()


class EventRedactionStatus(StrEnum):
    PASSED = auto()
    QUARANTINED = auto()
    NEEDS_REVIEW = auto()


def new_event_id() -> str:
    return "evt_" + secrets.token_hex(12)


def new_correlation_id() -> str:
    return "corr_" + secrets.token_hex(6)


def new_causation_id(parent_event_id: str) -> str:
    return parent_event_id


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class EventEnvelope:
    schema_version: str = field(default="rig.event.envelope.v1", init=False)
    event_id: str = field(default_factory=new_event_id)
    event_type: str = ""
    source: str = ""
    occurred_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    producer: str = ""
    correlation_id: str = field(default_factory=new_correlation_id)
    causation_id: str = ""
    command_id: str = ""
    trace_id: str = ""
    span_id: str = ""
    sequence: int = 0
    subject: str = ""
    payload_schema: str = ""
    payload_hash: str = ""
    sensitivity_class: str = field(default=EventSensitivityClass.INTERNAL_OPERATIONAL)
    redaction_status: str = field(default=EventRedactionStatus.PASSED)
    content_light: bool = True
    resource_tags: list[str] = field(default_factory=list)
    policy_tags: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def finalize(self) -> EventEnvelope:
        self.payload_hash = canonical_payload_hash(self.payload)
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "occurred_at": self.occurred_at,
            "producer": self.producer,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "command_id": self.command_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "sequence": self.sequence,
            "subject": self.subject,
            "payload_schema": self.payload_schema,
            "payload_hash": self.payload_hash,
            "sensitivity_class": self.sensitivity_class,
            "redaction_status": self.redaction_status,
            "content_light": self.content_light,
            "resource_tags": self.resource_tags,
            "policy_tags": self.policy_tags,
            "payload": self.payload,
        }


__all__ = [
    "EventEnvelope",
    "EventRedactionStatus",
    "EventSensitivityClass",
    "canonical_payload_hash",
    "new_causation_id",
    "new_correlation_id",
    "new_event_id",
]
