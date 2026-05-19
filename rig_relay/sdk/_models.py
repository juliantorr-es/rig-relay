"""rig_relay.sdk._models — SDK dataclasses, enums, and client."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
from uuid import uuid4


class RigVerdict(StrEnum):
    ALLOWED = "allowed"
    REFUSED = "refused"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass
class RigStatus:
    provider_id: str = "rig_sdk"
    mcp_available: bool = True
    acp_available: bool = True
    a2a_available: bool = False
    sdk_version: str = "1.0.0"
    available_capabilities: list[str] = field(
        default_factory=lambda: ["mcp.read_only", "acp.session"]
    )
    refused_capabilities: list[str] = field(
        default_factory=lambda: ["mcp.mutation", "a2a.mutation"]
    )
    mutation_refused_by_default: bool = True
    trace_support: bool = True
    content_light: bool = True
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "rig.relay.sdk.status.v1",
            "provider_id": self.provider_id,
            "mcp_available": self.mcp_available,
            "acp_available": self.acp_available,
            "a2a_available": self.a2a_available,
            "sdk_version": self.sdk_version,
            "available_capabilities": self.available_capabilities,
            "refused_capabilities": self.refused_capabilities,
            "mutation_refused_by_default": self.mutation_refused_by_default,
            "trace_support": self.trace_support,
            "content_light": self.content_light,
            "generated_at": self.generated_at,
        }


@dataclass
class RigRunResult:
    operation_id: str
    operation_kind: str
    verdict: RigVerdict
    trace_id: str
    refusal_code: str = ""
    operation_hash: str = ""
    response_hash: str = ""
    content_light: bool = True
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "rig.relay.sdk.run_result.v1",
            "provider_id": "rig_sdk",
            "run_id": self.operation_id,
            "operation_kind": self.operation_kind,
            "verdict": self.verdict.value,
            "refusal_code": self.refusal_code,
            "trace_id": self.trace_id,
            "content_light": self.content_light,
            "generated_at": self.generated_at,
        }


@dataclass
class RigRefusal:
    refusal_code: str
    reason: str
    capability_id: str
    trace_id: str = ""
    content_light: bool = True
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "rig.relay.sdk.refusal.v1",
            "refusal_code": self.refusal_code,
            "reason": self.reason,
            "capability_id": self.capability_id,
            "trace_id": self.trace_id,
            "content_light": self.content_light,
            "generated_at": self.generated_at,
        }


@dataclass
class RigReceiptRef:
    receipt_id: str
    surface: str
    trace_id: str
    verdict: str
    content_light: bool = True
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "rig.relay.sdk.receipt_ref.v1",
            "receipt_id": self.receipt_id,
            "surface": self.surface,
            "trace_id": self.trace_id,
            "verdict": self.verdict,
            "content_light": self.content_light,
            "generated_at": self.generated_at,
        }


@dataclass
class RigCapabilityDecision:
    capability_id: str
    verdict: RigVerdict
    allowed: bool
    refusal_code: str = ""
    reason: str = ""
    trace_id: str = ""


@dataclass
class RigClient:
    available_capabilities: list[str] = field(
        default_factory=lambda: ["mcp.read_only", "acp.session"]
    )
    mutation_refused: bool = True
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    _MUTATION_CAPABILITIES: tuple[str, ...] = (
        "mcp.mutation",
        "acp.mutation",
        "a2a.mutation",
    )
    _REFUSAL_MUTATION = "mutation_refused_by_default"

    def status(self) -> RigStatus:
        return RigStatus(
            provider_id="rig_sdk",
            available_capabilities=list(self.available_capabilities),
            refused_capabilities=list(self._MUTATION_CAPABILITIES),
        )

    def evaluate_capability(self, capability_id: str) -> RigCapabilityDecision:
        if capability_id in self._MUTATION_CAPABILITIES:
            return RigCapabilityDecision(
                capability_id=capability_id,
                verdict=RigVerdict.REFUSED,
                allowed=False,
                refusal_code=self._REFUSAL_MUTATION,
                reason="Mutation capabilities refused by default in SDK v1",
                trace_id=self.trace_id,
            )
        if capability_id in self.available_capabilities:
            return RigCapabilityDecision(
                capability_id=capability_id,
                verdict=RigVerdict.ALLOWED,
                allowed=True,
                trace_id=self.trace_id,
            )
        return RigCapabilityDecision(
            capability_id=capability_id,
            verdict=RigVerdict.REFUSED,
            allowed=False,
            refusal_code="unknown_capability",
            reason=f"Capability '{capability_id}' not registered",
            trace_id=self.trace_id,
        )

    def run_mcp_read_only(self, tool_name: str, trace_id: str) -> RigRunResult:
        op_id = str(uuid4())
        h = compute_sha256(f"{tool_name}:{op_id}")
        return RigRunResult(
            operation_id=op_id,
            operation_kind="mcp_read_only",
            verdict=RigVerdict.COMPLETED,
            trace_id=trace_id,
            operation_hash=h,
            response_hash=compute_sha256(f"response:{op_id}"),
        )

    def start_acp_session(self, trace_id: str) -> RigRunResult:
        op_id = str(uuid4())
        h = compute_sha256(f"acp_session:{op_id}")
        return RigRunResult(
            operation_id=op_id,
            operation_kind="acp_session",
            verdict=RigVerdict.COMPLETED,
            trace_id=trace_id,
            operation_hash=h,
            response_hash=compute_sha256(f"response:{op_id}"),
        )

    def send_a2a_local_task(
        self, task_id: str, agent_id: str, trace_id: str
    ) -> RigRunResult:
        op_id = str(uuid4())
        h = compute_sha256(f"a2a:{task_id}:{agent_id}:{op_id}")
        return RigRunResult(
            operation_id=op_id,
            operation_kind="a2a_local_task",
            verdict=RigVerdict.COMPLETED,
            trace_id=trace_id,
            operation_hash=h,
            response_hash=compute_sha256(f"response:{op_id}"),
        )


def compute_sha256(content: bytes | str) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()
