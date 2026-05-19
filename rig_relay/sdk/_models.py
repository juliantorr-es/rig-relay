"""rig_relay.sdk._models — SDK dataclasses, enums, and client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from typing import Any
from uuid import uuid4


class RigVerdict(StrEnum):
    ALLOWED = "allowed"
    REFUSED = "refused"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass
class RigTransportBudgets:
    max_request_bytes: int = 65536
    max_response_bytes: int = 65536
    max_stream_event_bytes: int = 65536
    max_pending_requests: int = 64
    max_connection_lifetime_seconds: int = 300
    max_concurrent_sessions: int = 8
    request_timeout_seconds: int = 30
    cancel_timeout_seconds: int = 5
    content_light: bool = True


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
    budgets: RigTransportBudgets = field(default_factory=RigTransportBudgets)
    _MUTATION_CAPABILITIES: tuple[str, ...] = (
        "mcp.mutation",
        "acp.mutation",
        "a2a.mutation",
    )
    _REFUSAL_MUTATION = "mutation_refused_by_default"
    _MUTATION_TIER_THRESHOLD = 4

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

    def _build_run_result(
        self,
        operation_id: str,
        operation_kind: str,
        trace_id: str,
        verdict: RigVerdict,
        refusal_code: str = "",
        response_data: Any = None,
    ) -> RigRunResult:
        op_hash = compute_sha256(f"{operation_kind}:{operation_id}")
        resp_hash = ""
        if response_data is not None:
            resp_hash = compute_sha256(
                json.dumps(response_data, sort_keys=True, default=str)
            )
        else:
            resp_hash = compute_sha256(f"response:{operation_id}")
        return RigRunResult(
            operation_id=operation_id,
            operation_kind=operation_kind,
            verdict=verdict,
            trace_id=trace_id,
            refusal_code=refusal_code,
            operation_hash=op_hash,
            response_hash=resp_hash,
        )

    def run_mcp_read_only(self, tool_name: str, trace_id: str) -> RigRunResult:
        return asyncio.run(self.async_run_mcp_read_only(tool_name, trace_id))

    async def async_run_mcp_read_only(
        self, tool_name: str, trace_id: str = ""
    ) -> RigRunResult:
        from rig_relay.protocols.mcp.server import RigMCPServer

        op_id = str(uuid4())
        server = RigMCPServer()
        all_tools = {t.name: t for t in server.list_tools()}
        tool = all_tools.get(tool_name)

        if tool is None:
            return self._build_run_result(
                op_id,
                "mcp_read_only",
                trace_id,
                RigVerdict.FAILED,
                "unknown_capability",
            )

        if tool.tier.value >= self._MUTATION_TIER_THRESHOLD:
            return self._build_run_result(
                op_id, "mcp_read_only", trace_id, RigVerdict.REFUSED, "mutation_refused"
            )

        try:
            response = await server.call_tool(tool_name, {})
        except Exception:
            return self._build_run_result(
                op_id,
                "mcp_read_only",
                trace_id,
                RigVerdict.FAILED,
                "unknown_capability",
            )

        if isinstance(response, dict) and response.get("error"):
            return self._build_run_result(
                op_id,
                "mcp_read_only",
                trace_id,
                RigVerdict.FAILED,
                "unknown_capability",
            )

        return self._build_run_result(
            op_id,
            "mcp_read_only",
            trace_id,
            RigVerdict.COMPLETED,
            response_data=response,
        )

    async def async_list_mcp_tools(self, trace_id: str = "") -> RigRunResult:
        from rig_relay.protocols.mcp.server import RigMCPServer

        op_id = str(uuid4())
        server = RigMCPServer()
        tools = server.list_tools()
        tool_data = [
            {"name": t.name, "description": t.description, "tier": t.tier.value}
            for t in tools
        ]
        return self._build_run_result(
            op_id,
            "list_mcp_tools",
            trace_id,
            RigVerdict.COMPLETED,
            response_data=tool_data,
        )

    async def async_list_mcp_resources(self, trace_id: str = "") -> RigRunResult:
        from rig_relay.protocols.mcp.server import RigMCPServer

        op_id = str(uuid4())
        server = RigMCPServer()
        resources = server.list_resources()
        resource_data = [
            {"uri": r.uri, "name": r.name, "mime_type": r.mime_type} for r in resources
        ]
        return self._build_run_result(
            op_id,
            "list_mcp_resources",
            trace_id,
            RigVerdict.COMPLETED,
            response_data=resource_data,
        )

    async def async_list_mcp_prompts(self, trace_id: str = "") -> RigRunResult:
        from rig_relay.protocols.mcp.server import RigMCPServer

        op_id = str(uuid4())
        server = RigMCPServer()
        prompts = server.list_prompts()
        prompt_data = [{"name": p.name, "description": p.description} for p in prompts]
        return self._build_run_result(
            op_id,
            "list_mcp_prompts",
            trace_id,
            RigVerdict.COMPLETED,
            response_data=prompt_data,
        )

    async def async_run_mcp_analysis(
        self, tool_name: str, trace_id: str = ""
    ) -> RigRunResult:
        from rig_relay.protocols.mcp.server import RigMCPServer

        op_id = str(uuid4())
        server = RigMCPServer()
        all_tools = {t.name: t for t in server.list_tools()}
        tool = all_tools.get(tool_name)

        if tool is None:
            return self._build_run_result(
                op_id, "mcp_analysis", trace_id, RigVerdict.FAILED, "unknown_capability"
            )

        if tool.tier.value >= self._MUTATION_TIER_THRESHOLD:
            return self._build_run_result(
                op_id, "mcp_analysis", trace_id, RigVerdict.REFUSED, "mutation_refused"
            )

        try:
            response = await server.call_tool(tool_name, {})
        except Exception:
            return self._build_run_result(
                op_id, "mcp_analysis", trace_id, RigVerdict.FAILED, "unknown_capability"
            )

        if isinstance(response, dict) and response.get("error"):
            return self._build_run_result(
                op_id, "mcp_analysis", trace_id, RigVerdict.FAILED, "unknown_capability"
            )

        return self._build_run_result(
            op_id,
            "mcp_analysis",
            trace_id,
            RigVerdict.COMPLETED,
            response_data=response,
        )

    async def async_run_mcp_validation(
        self, tool_name: str, trace_id: str = ""
    ) -> RigRunResult:
        from rig_relay.protocols.mcp.server import RigMCPServer

        op_id = str(uuid4())
        server = RigMCPServer()
        all_tools = {t.name: t for t in server.list_tools()}
        tool = all_tools.get(tool_name)

        if tool is None:
            return self._build_run_result(
                op_id,
                "mcp_validation",
                trace_id,
                RigVerdict.FAILED,
                "unknown_capability",
            )

        if tool.tier.value >= self._MUTATION_TIER_THRESHOLD:
            return self._build_run_result(
                op_id,
                "mcp_validation",
                trace_id,
                RigVerdict.REFUSED,
                "mutation_refused",
            )

        try:
            response = await server.call_tool(tool_name, {})
        except Exception:
            return self._build_run_result(
                op_id,
                "mcp_validation",
                trace_id,
                RigVerdict.FAILED,
                "unknown_capability",
            )

        if isinstance(response, dict) and response.get("error"):
            return self._build_run_result(
                op_id,
                "mcp_validation",
                trace_id,
                RigVerdict.FAILED,
                "unknown_capability",
            )

        return self._build_run_result(
            op_id,
            "mcp_validation",
            trace_id,
            RigVerdict.COMPLETED,
            response_data=response,
        )

    def start_acp_session(self, trace_id: str) -> RigRunResult:
        return asyncio.run(self.async_start_acp_session(trace_id))

    async def async_start_acp_session(self, trace_id: str = "") -> RigRunResult:
        from rig_relay.protocols.acp.agent import RigACPAgent

        op_id = str(uuid4())
        try:
            agent = RigACPAgent()
            session = await agent.create_session()
            return self._build_run_result(
                op_id,
                "acp_session",
                trace_id,
                RigVerdict.COMPLETED,
                response_data={
                    "session_id": session.session_id,
                    "status": session.status.value,
                },
            )
        except Exception:
            return self._build_run_result(
                op_id, "acp_session", trace_id, RigVerdict.FAILED, "unknown_capability"
            )

    def send_a2a_local_task(
        self, task_id: str, agent_id: str, trace_id: str
    ) -> RigRunResult:
        return asyncio.run(self.async_send_a2a_local_task(task_id, agent_id, trace_id))

    async def async_send_a2a_local_task(
        self, task_id: str, agent_id: str, trace_id: str = ""
    ) -> RigRunResult:
        from rig_relay.protocols.a2a._lifecycle import (
            build_delegation_receipt,
            build_task_card,
            transition_task,
        )
        from rig_relay.protocols.a2a._models import A2ATaskStatus

        op_id = str(uuid4())
        card = build_task_card(task_id, agent_id, trace_id=trace_id)
        card = transition_task(card, A2ATaskStatus.SUBMITTED)
        card = transition_task(card, A2ATaskStatus.RUNNING)
        receipt = build_delegation_receipt(
            "rig_sdk", agent_id, task_id, trace_id=trace_id, verdict="completed"
        )
        return self._build_run_result(
            op_id,
            "a2a_local_task",
            trace_id,
            RigVerdict.COMPLETED,
            response_data=receipt.to_dict(),
        )


@dataclass
class RigAuthStatus:
    provider_id: str
    auth_capable: bool = False
    auth_status: str = "unauthenticated"
    refresh_needed: bool = False
    expires_at: str | None = None
    credential_store_ref_hash: str | None = None
    capability_id: str = ""
    trace_id: str = ""
    receipt_id: str | None = None
    refusal_code: str | None = None
    content_light: bool = True
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "rig.relay.sdk.auth_status.v1",
            "provider_id": self.provider_id,
            "auth_capable": self.auth_capable,
            "auth_status": self.auth_status,
            "refresh_needed": self.refresh_needed,
            "expires_at": self.expires_at,
            "credential_store_ref_hash": self.credential_store_ref_hash,
            "capability_id": self.capability_id,
            "trace_id": self.trace_id,
            "receipt_id": self.receipt_id,
            "refusal_code": self.refusal_code,
            "content_light": self.content_light,
            "generated_at": self.generated_at,
        }


@dataclass
class RigAuthCapabilityCheck:
    capability_id: str
    supported: bool = False
    requires_credentials: bool = False
    credential_store_available: bool = False
    verdict: str = "REFUSED"
    trace_id: str = ""
    content_light: bool = True
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "rig.relay.sdk.auth_capability_check.v1",
            "capability_id": self.capability_id,
            "supported": self.supported,
            "requires_credentials": self.requires_credentials,
            "credential_store_available": self.credential_store_available,
            "verdict": self.verdict,
            "trace_id": self.trace_id,
            "content_light": self.content_light,
            "generated_at": self.generated_at,
        }


@dataclass
class RigAuthRefusal:
    refusal_code: str
    reason: str
    capability_id: str
    trace_id: str = ""
    receipt_id: str = ""
    content_light: bool = True
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "rig.relay.sdk.auth_refusal.v1",
            "refusal_code": self.refusal_code,
            "reason": self.reason,
            "capability_id": self.capability_id,
            "trace_id": self.trace_id,
            "receipt_id": self.receipt_id,
            "content_light": self.content_light,
            "generated_at": self.generated_at,
        }


@dataclass
class RigAuthReceiptRef:
    receipt_id: str
    surface: str
    trace_id: str = ""
    auth_state_hash: str = ""
    credential_store_ref_hash: str | None = None
    verdict: str = ""
    content_light: bool = True
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "rig.relay.sdk.auth_receipt_ref.v1",
            "receipt_id": self.receipt_id,
            "surface": self.surface,
            "trace_id": self.trace_id,
            "auth_state_hash": self.auth_state_hash,
            "credential_store_ref_hash": self.credential_store_ref_hash,
            "verdict": self.verdict,
            "content_light": self.content_light,
            "generated_at": self.generated_at,
        }


def compute_sha256(content: bytes | str) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()
