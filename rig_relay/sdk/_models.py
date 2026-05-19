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
    github_provider_available: bool = False
    google_workspace_provider_available: bool = False
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
            "github_provider_available": self.github_provider_available,
            "google_workspace_provider_available": (
                self.google_workspace_provider_available
            ),
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
    receipt_ref: RigReceiptRef | None = None
    content_light: bool = True
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
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
        if self.receipt_ref is not None:
            result["receipt_ref"] = self.receipt_ref.to_dict()
        return result


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
        github_available = _provider_manifest_exists("github")
        google_workspace_available = _provider_manifest_exists("google_workspace")
        return RigStatus(
            provider_id="rig_sdk",
            available_capabilities=list(self.available_capabilities),
            refused_capabilities=list(self._MUTATION_CAPABILITIES),
            github_provider_available=github_available,
            google_workspace_provider_available=google_workspace_available,
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

    def check_github_provider_status_sync(self, trace_id: str = "") -> RigRunResult:
        return asyncio.run(self.check_github_provider_status(trace_id))

    async def check_github_provider_status(self, trace_id: str = "") -> RigRunResult:
        from rig_relay.integrations.github_provider._capabilities import (
            load_github_capability_manifest,
        )
        from rig_relay.integrations.github_provider._models import (
            GitHubProviderAuthState,
        )
        from rig_relay.integrations.github_provider._status import build_status_snapshot

        op_id = str(uuid4())
        tid = trace_id or self.trace_id

        try:
            manifest = load_github_capability_manifest()
        except Exception:
            return self._build_run_result(
                op_id,
                "github_provider_read",
                tid,
                RigVerdict.FAILED,
                "manifest_load_failed",
            )

        auth_state = GitHubProviderAuthState.unauthenticated()
        snapshot = build_status_snapshot(auth_state, manifest)

        receipt_id = str(uuid4())
        receipt_ref = RigReceiptRef(
            receipt_id=receipt_id, surface="github", trace_id=tid, verdict="completed"
        )

        return self._build_run_result(
            op_id,
            "github_provider_read",
            tid,
            RigVerdict.COMPLETED,
            response_data=snapshot,
        ).__class__(
            operation_id=op_id,
            operation_kind="github_provider_read",
            verdict=RigVerdict.COMPLETED,
            trace_id=tid,
            operation_hash=compute_sha256(f"github_provider_read:{op_id}"),
            response_hash=compute_sha256(
                json.dumps(snapshot, sort_keys=True, default=str)
            ),
            receipt_ref=receipt_ref,
        )

    def run_github_live_read_sync(
        self,
        capability_id: str,
        token: str = "",
        repository_owner: str = "",
        repository_name: str = "",
        trace_id: str = "",
    ) -> RigRunResult:
        return asyncio.run(
            self.run_github_live_read(
                capability_id, token, repository_owner, repository_name, trace_id
            )
        )

    async def run_github_live_read(
        self,
        capability_id: str,
        token: str = "",
        repository_owner: str = "",
        repository_name: str = "",
        trace_id: str = "",
    ) -> RigRunResult:
        import os

        from rig_relay.integrations.github_provider._capabilities import (
            evaluate_github_capability,
            load_github_capability_manifest,
        )
        from rig_relay.integrations.github_provider._models import (
            GitHubProviderAuthState,
        )

        op_id = str(uuid4())
        tid = trace_id or self.trace_id
        surface = "github"
        receipt_id = str(uuid4())

        if os.environ.get("RIG_LIVE_PROVIDER_TESTS") != "1":
            receipt_ref = RigReceiptRef(
                receipt_id=receipt_id, surface=surface, trace_id=tid, verdict="refused"
            )
            return self._build_run_result(
                op_id,
                "github_provider_read",
                tid,
                RigVerdict.REFUSED,
                "live_network_disabled",
            ).__class__(
                operation_id=op_id,
                operation_kind="github_provider_read",
                verdict=RigVerdict.REFUSED,
                trace_id=tid,
                refusal_code="live_network_disabled",
                operation_hash=compute_sha256(f"github_provider_read:{op_id}"),
                response_hash=compute_sha256(f"refused:live_network_disabled:{op_id}"),
                receipt_ref=receipt_ref,
            )

        token_hash = compute_sha256(token) if token else ""
        owner_hash = compute_sha256(repository_owner) if repository_owner else ""
        repo_hash = compute_sha256(repository_name) if repository_name else ""

        manifest = load_github_capability_manifest()
        cap = manifest.get_capability(capability_id)
        if cap is None:
            receipt_ref = RigReceiptRef(
                receipt_id=receipt_id, surface=surface, trace_id=tid, verdict="refused"
            )
            return self._build_run_result(
                op_id,
                "github_provider_read",
                tid,
                RigVerdict.REFUSED,
                "github.capability.unknown",
            ).__class__(
                operation_id=op_id,
                operation_kind="github_provider_read",
                verdict=RigVerdict.REFUSED,
                trace_id=tid,
                refusal_code="github.capability.unknown",
                operation_hash=compute_sha256(f"github_provider_read:{op_id}"),
                response_hash=compute_sha256(
                    f"refused:unknown_capability:{capability_id}"
                ),
                receipt_ref=receipt_ref,
            )

        if cap.is_destructive or cap.is_credentialed or cap.is_mutation:
            receipt_ref = RigReceiptRef(
                receipt_id=receipt_id, surface=surface, trace_id=tid, verdict="refused"
            )
            return self._build_run_result(
                op_id,
                "github_provider_read",
                tid,
                RigVerdict.REFUSED,
                cap.refusal_code_when_denied or "mutation_refused",
            ).__class__(
                operation_id=op_id,
                operation_kind="github_provider_read",
                verdict=RigVerdict.REFUSED,
                trace_id=tid,
                refusal_code=cap.refusal_code_when_denied or "mutation_refused",
                operation_hash=compute_sha256(f"github_provider_read:{op_id}"),
                response_hash=compute_sha256(f"refused:mutation:{capability_id}"),
                receipt_ref=receipt_ref,
            )

        auth_state = GitHubProviderAuthState.unauthenticated()
        repo_hash_full = (
            compute_sha256(f"{repository_owner}/{repository_name}")
            if repository_owner and repository_name
            else ""
        )
        decision = evaluate_github_capability(
            auth_state,
            capability_id,
            target_repository_hash=repo_hash_full,
            manifest=manifest,
        )

        if decision.is_refused:
            receipt_ref = RigReceiptRef(
                receipt_id=receipt_id, surface=surface, trace_id=tid, verdict="refused"
            )
            return self._build_run_result(
                op_id,
                "github_provider_read",
                tid,
                RigVerdict.REFUSED,
                decision.refusal_code,
            ).__class__(
                operation_id=op_id,
                operation_kind="github_provider_read",
                verdict=RigVerdict.REFUSED,
                trace_id=tid,
                refusal_code=decision.refusal_code,
                operation_hash=compute_sha256(f"github_provider_read:{op_id}"),
                response_hash=compute_sha256(
                    f"refused:{decision.refusal_code}:{capability_id}"
                ),
                receipt_ref=receipt_ref,
            )

        response_payload = {
            "capability_id": capability_id,
            "verdict": "completed",
            "token_hash": token_hash,
            "owner_hash": owner_hash,
            "repo_hash": repo_hash,
            "content_light": True,
        }

        receipt_ref = RigReceiptRef(
            receipt_id=receipt_id, surface=surface, trace_id=tid, verdict="completed"
        )

        return self._build_run_result(
            op_id,
            "github_provider_read",
            tid,
            RigVerdict.COMPLETED,
            response_data=response_payload,
        ).__class__(
            operation_id=op_id,
            operation_kind="github_provider_read",
            verdict=RigVerdict.COMPLETED,
            trace_id=tid,
            operation_hash=compute_sha256(f"github_provider_read:{op_id}"),
            response_hash=compute_sha256(
                json.dumps(response_payload, sort_keys=True, default=str)
            ),
            receipt_ref=receipt_ref,
        )

    async def evaluate_github_capability(
        self, capability_id: str, trace_id: str = ""
    ) -> RigCapabilityDecision:
        from rig_relay.integrations.github_provider._capabilities import (
            evaluate_github_capability as gh_eval,
            load_github_capability_manifest,
        )
        from rig_relay.integrations.github_provider._models import (
            GitHubProviderAuthState,
        )

        tid = trace_id or self.trace_id
        manifest = load_github_capability_manifest()
        auth_state = GitHubProviderAuthState.unauthenticated()
        decision = gh_eval(auth_state, capability_id, manifest=manifest)

        verdict_map = {
            "allowed": RigVerdict.ALLOWED,
            "refused": RigVerdict.REFUSED,
            "failed": RigVerdict.FAILED,
            "completed": RigVerdict.COMPLETED,
        }
        return RigCapabilityDecision(
            capability_id=capability_id,
            verdict=verdict_map.get(decision.verdict.value, RigVerdict.REFUSED),
            allowed=decision.is_allowed,
            refusal_code=decision.refusal_code,
            reason=decision.reason,
            trace_id=tid,
        )

    def check_google_workspace_status_sync(self, trace_id: str = "") -> RigRunResult:
        return asyncio.run(self.check_google_workspace_status(trace_id))

    async def check_google_workspace_status(self, trace_id: str = "") -> RigRunResult:
        from rig_relay.integrations.google_workspace._capabilities import (
            load_capability_manifest,
        )
        from rig_relay.integrations.google_workspace._models import (
            GoogleWorkspaceAuthState,
        )
        from rig_relay.integrations.google_workspace._status import (
            build_status_snapshot,
        )

        op_id = str(uuid4())
        tid = trace_id or self.trace_id

        try:
            manifest = load_capability_manifest()
        except Exception:
            return self._build_run_result(
                op_id,
                "google_workspace_provider_read",
                tid,
                RigVerdict.FAILED,
                "manifest_load_failed",
            )

        auth = GoogleWorkspaceAuthState.unauthenticated()
        snapshot = build_status_snapshot(auth, manifest)

        receipt_id = str(uuid4())
        receipt_ref = RigReceiptRef(
            receipt_id=receipt_id,
            surface="google_workspace",
            trace_id=tid,
            verdict="completed",
        )

        return self._build_run_result(
            op_id,
            "google_workspace_provider_read",
            tid,
            RigVerdict.COMPLETED,
            response_data=snapshot,
        ).__class__(
            operation_id=op_id,
            operation_kind="google_workspace_provider_read",
            verdict=RigVerdict.COMPLETED,
            trace_id=tid,
            operation_hash=compute_sha256(f"google_workspace_provider_read:{op_id}"),
            response_hash=compute_sha256(
                json.dumps(snapshot, sort_keys=True, default=str)
            ),
            receipt_ref=receipt_ref,
        )

    def run_google_workspace_live_read_sync(
        self,
        capability_id: str,
        token: str = "",
        subject_hash: str = "",
        trace_id: str = "",
    ) -> RigRunResult:
        return asyncio.run(
            self.run_google_workspace_live_read(
                capability_id, token, subject_hash, trace_id
            )
        )

    async def run_google_workspace_live_read(
        self,
        capability_id: str,
        token: str = "",
        subject_hash: str = "",
        trace_id: str = "",
    ) -> RigRunResult:
        import os

        from rig_relay.integrations.google_workspace._capabilities import (
            evaluate_workspace_capability,
            load_capability_manifest,
        )
        from rig_relay.integrations.google_workspace._models import (
            GoogleWorkspaceAuthState,
        )

        op_id = str(uuid4())
        tid = trace_id or self.trace_id
        surface = "google_workspace"
        receipt_id = str(uuid4())

        if os.environ.get("RIG_LIVE_PROVIDER_TESTS") != "1":
            receipt_ref = RigReceiptRef(
                receipt_id=receipt_id, surface=surface, trace_id=tid, verdict="refused"
            )
            return self._build_run_result(
                op_id,
                "google_workspace_provider_read",
                tid,
                RigVerdict.REFUSED,
                "live_network_disabled",
            ).__class__(
                operation_id=op_id,
                operation_kind="google_workspace_provider_read",
                verdict=RigVerdict.REFUSED,
                trace_id=tid,
                refusal_code="live_network_disabled",
                operation_hash=compute_sha256(
                    f"google_workspace_provider_read:{op_id}"
                ),
                response_hash=compute_sha256(f"refused:live_network_disabled:{op_id}"),
                receipt_ref=receipt_ref,
            )

        token_hash = compute_sha256(token) if token else ""
        subj_hash = subject_hash or ""

        manifest = load_capability_manifest()
        cap = manifest.get_capability(capability_id)
        if cap is None:
            receipt_ref = RigReceiptRef(
                receipt_id=receipt_id, surface=surface, trace_id=tid, verdict="refused"
            )
            return self._build_run_result(
                op_id,
                "google_workspace_provider_read",
                tid,
                RigVerdict.REFUSED,
                "google.capability.unknown",
            ).__class__(
                operation_id=op_id,
                operation_kind="google_workspace_provider_read",
                verdict=RigVerdict.REFUSED,
                trace_id=tid,
                refusal_code="google.capability.unknown",
                operation_hash=compute_sha256(
                    f"google_workspace_provider_read:{op_id}"
                ),
                response_hash=compute_sha256(
                    f"refused:unknown_capability:{capability_id}"
                ),
                receipt_ref=receipt_ref,
            )

        mutation_classes = {"user_credentialed", "domain_credentialed", "destructive"}
        is_mutation = str(cap.mutation_class) in mutation_classes
        is_destructive_operation = str(cap.operation_class) in {
            "destructive_mutation",
            "credentialed_live_operation",
        }

        if is_mutation or is_destructive_operation:
            receipt_ref = RigReceiptRef(
                receipt_id=receipt_id, surface=surface, trace_id=tid, verdict="refused"
            )
            return self._build_run_result(
                op_id,
                "google_workspace_provider_read",
                tid,
                RigVerdict.REFUSED,
                "google.mutation.refused",
            ).__class__(
                operation_id=op_id,
                operation_kind="google_workspace_provider_read",
                verdict=RigVerdict.REFUSED,
                trace_id=tid,
                refusal_code="google.mutation.refused",
                operation_hash=compute_sha256(
                    f"google_workspace_provider_read:{op_id}"
                ),
                response_hash=compute_sha256(f"refused:mutation:{capability_id}"),
                receipt_ref=receipt_ref,
            )

        if str(cap.scope_sensitivity) in {"restricted", "admin_restricted", "unknown"}:
            receipt_ref = RigReceiptRef(
                receipt_id=receipt_id, surface=surface, trace_id=tid, verdict="refused"
            )
            return self._build_run_result(
                op_id,
                "google_workspace_provider_read",
                tid,
                RigVerdict.REFUSED,
                "google.live_read.restricted_scope",
            ).__class__(
                operation_id=op_id,
                operation_kind="google_workspace_provider_read",
                verdict=RigVerdict.REFUSED,
                trace_id=tid,
                refusal_code="google.live_read.restricted_scope",
                operation_hash=compute_sha256(
                    f"google_workspace_provider_read:{op_id}"
                ),
                response_hash=compute_sha256(
                    f"refused:restricted_scope:{capability_id}"
                ),
                receipt_ref=receipt_ref,
            )

        auth = GoogleWorkspaceAuthState.unauthenticated()
        decision = evaluate_workspace_capability(
            auth, capability_id, subject_hash=subj_hash, manifest=manifest
        )

        if decision.is_refused:
            receipt_ref = RigReceiptRef(
                receipt_id=receipt_id, surface=surface, trace_id=tid, verdict="refused"
            )
            return self._build_run_result(
                op_id,
                "google_workspace_provider_read",
                tid,
                RigVerdict.REFUSED,
                str(decision.refusal_code),
            ).__class__(
                operation_id=op_id,
                operation_kind="google_workspace_provider_read",
                verdict=RigVerdict.REFUSED,
                trace_id=tid,
                refusal_code=str(decision.refusal_code),
                operation_hash=compute_sha256(
                    f"google_workspace_provider_read:{op_id}"
                ),
                response_hash=compute_sha256(
                    f"refused:{decision.refusal_code}:{capability_id}"
                ),
                receipt_ref=receipt_ref,
            )

        response_payload = {
            "capability_id": capability_id,
            "verdict": "completed",
            "token_hash": token_hash,
            "subject_hash": subj_hash,
            "content_light": True,
        }

        receipt_ref = RigReceiptRef(
            receipt_id=receipt_id, surface=surface, trace_id=tid, verdict="completed"
        )

        return self._build_run_result(
            op_id,
            "google_workspace_provider_read",
            tid,
            RigVerdict.COMPLETED,
            response_data=response_payload,
        ).__class__(
            operation_id=op_id,
            operation_kind="google_workspace_provider_read",
            verdict=RigVerdict.COMPLETED,
            trace_id=tid,
            operation_hash=compute_sha256(f"google_workspace_provider_read:{op_id}"),
            response_hash=compute_sha256(
                json.dumps(response_payload, sort_keys=True, default=str)
            ),
            receipt_ref=receipt_ref,
        )

    async def evaluate_google_workspace_capability(
        self, capability_id: str, trace_id: str = ""
    ) -> RigCapabilityDecision:
        from rig_relay.integrations.google_workspace._capabilities import (
            evaluate_workspace_capability,
            load_capability_manifest,
        )
        from rig_relay.integrations.google_workspace._models import (
            GoogleWorkspaceAuthState,
        )

        tid = trace_id or self.trace_id
        manifest = load_capability_manifest()
        auth = GoogleWorkspaceAuthState.unauthenticated()
        decision = evaluate_workspace_capability(auth, capability_id, manifest=manifest)

        verdict_map = {
            "allowed": RigVerdict.ALLOWED,
            "refused": RigVerdict.REFUSED,
            "failed": RigVerdict.FAILED,
            "completed": RigVerdict.COMPLETED,
        }
        return RigCapabilityDecision(
            capability_id=capability_id,
            verdict=verdict_map.get(str(decision.verdict), RigVerdict.REFUSED),
            allowed=decision.is_allowed,
            refusal_code=str(decision.refusal_code),
            reason=decision.reason,
            trace_id=tid,
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
class RigProviderLiveAuthStatus:
    provider_id: str
    configured: bool = False
    auth_mode: str = "none"
    auth_status: str = "unconfigured"
    credential_store_available: bool = False
    credential_store_ref_hash: str | None = None
    token_expires_at: str | None = None
    refresh_needed: bool = False
    scopes_or_permissions: list[str] = field(default_factory=list)
    capability_id: str = ""
    trace_id: str = ""
    receipt_id: str | None = None
    refusal_code: str | None = None
    content_light: bool = True
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "rig.relay.sdk.provider_live_auth_status.v1",
            "provider_id": self.provider_id,
            "configured": self.configured,
            "auth_mode": self.auth_mode,
            "auth_status": self.auth_status,
            "credential_store_available": self.credential_store_available,
            "credential_store_ref_hash": self.credential_store_ref_hash,
            "token_expires_at": self.token_expires_at,
            "refresh_needed": self.refresh_needed,
            "scopes_or_permissions": list(self.scopes_or_permissions),
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


def _provider_manifest_exists(provider_id: str) -> bool:

    if provider_id == "github":
        from rig_relay.integrations.github_provider._capabilities import (
            _DEFAULT_MANIFEST_PATH as gh_path,
        )

        return gh_path.exists()
    if provider_id == "google_workspace":
        from rig_relay.integrations.google_workspace._capabilities import (
            _DEFAULT_MANIFEST_PATH as gw_path,
        )

        return gw_path.exists()
    return False
