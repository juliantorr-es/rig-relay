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
    _agent_loop_sessions: dict[str, object] = field(default_factory=dict, repr=False)
    _a2a_server: object | None = field(default=None, repr=False)

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

    # ── AgentLoop-backed operations ──

    async def _create_agent_loop(self) -> object:
        from rig_relay import __version__
        from rig_relay.core.agent_loop import AgentLoop
        from rig_relay.core.agents.models import CHAT as CHAT_AGENT, BuiltinAgentName
        from rig_relay.core.config import MissingAPIKeyError, VibeConfig
        from rig_relay.core.telemetry.build_metadata import build_entrypoint_metadata

        try:
            config = VibeConfig.load()
        except MissingAPIKeyError:
            return self._build_run_result(
                str(uuid4()),
                "agent_loop_create",
                self.trace_id,
                RigVerdict.FAILED,
                "missing_api_key",
            )
        except Exception:
            return self._build_run_result(
                str(uuid4()),
                "agent_loop_create",
                self.trace_id,
                RigVerdict.FAILED,
                "config_load_failed",
            )

        try:
            entrypoint_meta = build_entrypoint_metadata(
                agent_entrypoint="programmatic",
                agent_version=__version__,
                client_name="rig_sdk",
                client_version="1.0.0",
            )
            agent_loop = AgentLoop(
                config=config,
                agent_name=BuiltinAgentName.DEFAULT,
                enable_streaming=True,
                entrypoint_metadata=entrypoint_meta,
                defer_heavy_init=True,
            )
            agent_loop.agent_manager.register_agent(CHAT_AGENT)
            await agent_loop.wait_until_ready()
            return agent_loop
        except Exception:
            return self._build_run_result(
                str(uuid4()),
                "agent_loop_create",
                self.trace_id,
                RigVerdict.FAILED,
                "agent_loop_construct_failed",
            )

    async def async_start_agent_chat(
        self, prompt: str, trace_id: str = ""
    ) -> RigRunResult:
        op_id = str(uuid4())
        tid = trace_id or self.trace_id

        agent_loop = await self._create_agent_loop()
        if not hasattr(agent_loop, "act"):
            from rig_relay.sdk._models import RigRunResult as _RRR

            if isinstance(agent_loop, _RRR):
                return agent_loop
            return self._build_run_result(
                op_id, "agent_chat", tid, RigVerdict.FAILED, "agent_loop_create_failed"
            )

        try:
            response_parts: list[str] = []
            from rig_relay.core.types import AssistantEvent

            async for event in agent_loop.act(prompt):  # type: ignore[union-attr]
                if isinstance(event, AssistantEvent) and event.content:
                    response_parts.append(event.content)

            response_text = (
                "".join(response_parts) if response_parts else "(no response)"
            )
            response_hash = compute_sha256(response_text)
            return self._build_run_result(
                op_id,
                "agent_chat",
                tid,
                RigVerdict.COMPLETED,
                response_data={
                    "response": response_text,
                    "response_hash": response_hash,
                    "content_light": False,
                },
            )
        except Exception:
            return self._build_run_result(
                op_id, "agent_chat", tid, RigVerdict.FAILED, "agent_chat_failed"
            )
        finally:
            try:
                await agent_loop.aclose()  # type: ignore[union-attr]
            except Exception:
                pass

    async def async_list_tools(self, trace_id: str = "") -> RigRunResult:
        op_id = str(uuid4())
        tid = trace_id or self.trace_id

        agent_loop = await self._create_agent_loop()
        if not hasattr(agent_loop, "tool_manager"):
            if isinstance(agent_loop, RigRunResult):
                return agent_loop
            return self._build_run_result(
                op_id, "list_tools", tid, RigVerdict.FAILED, "agent_loop_create_failed"
            )

        try:
            tools = agent_loop.tool_manager.available_tools  # type: ignore[union-attr]
            tool_data = [
                {
                    "name": name,
                    "description": (
                        tool_cls.__doc__ or "" if hasattr(tool_cls, "__doc__") else ""
                    ),
                    "parameters": (
                        tool_cls.get_parameters()
                        if hasattr(tool_cls, "get_parameters")
                        else {}
                    ),
                }
                for name, tool_cls in tools.items()
            ]
            return self._build_run_result(
                op_id,
                "list_tools",
                tid,
                RigVerdict.COMPLETED,
                response_data={"tools": tool_data},
            )
        except Exception:
            return self._build_run_result(
                op_id, "list_tools", tid, RigVerdict.FAILED, "list_tools_failed"
            )
        finally:
            try:
                await agent_loop.aclose()  # type: ignore[union-attr]
            except Exception:
                pass

    async def async_invoke_tool(
        self, tool_name: str, args: dict[str, Any] | None = None, trace_id: str = ""
    ) -> RigRunResult:
        op_id = str(uuid4())
        tid = trace_id or self.trace_id

        agent_loop = await self._create_agent_loop()
        if not hasattr(agent_loop, "tool_manager"):
            if isinstance(agent_loop, RigRunResult):
                return agent_loop
            return self._build_run_result(
                op_id, "invoke_tool", tid, RigVerdict.FAILED, "agent_loop_create_failed"
            )

        try:
            from rig_relay.core.tools.base import InvokeContext
            from rig_relay.core.tools.manager import NoSuchToolError
            from rig_relay.core.types import ToolStreamEvent

            try:
                tool_instance = agent_loop.tool_manager.get(tool_name)  # type: ignore[union-attr]
            except NoSuchToolError:
                return self._build_run_result(
                    op_id, "invoke_tool", tid, RigVerdict.FAILED, "unknown_tool"
                )

            invoke_ctx = InvokeContext(
                tool_call_id=str(uuid4()),
                session_dir=agent_loop.session_dir,  # type: ignore[union-attr]
                tool_manager=agent_loop.tool_manager,  # type: ignore[union-attr]
            )

            results: list[dict[str, Any]] = []
            async for event in tool_instance.invoke(ctx=invoke_ctx, **(args or {})):
                if isinstance(event, ToolStreamEvent):
                    results.append({"type": "stream", "message": event.message})
                else:
                    results.append({"type": "result", "data": str(event)[:1024]})

            return self._build_run_result(
                op_id,
                "invoke_tool",
                tid,
                RigVerdict.COMPLETED,
                response_data={"tool_name": tool_name, "results": results},
            )
        except Exception:
            return self._build_run_result(
                op_id, "invoke_tool", tid, RigVerdict.FAILED, "tool_invoke_failed"
            )
        finally:
            try:
                await agent_loop.aclose()  # type: ignore[union-attr]
            except Exception:
                pass

    # ── ACP session (wired to real AgentLoop) ──

    def start_acp_session(self, trace_id: str) -> RigRunResult:
        return asyncio.run(self.async_start_acp_session(trace_id))

    async def async_start_acp_session(self, trace_id: str = "") -> RigRunResult:
        op_id = str(uuid4())
        tid = trace_id or self.trace_id

        agent_loop = await self._create_agent_loop()
        if not hasattr(agent_loop, "session_id"):
            if isinstance(agent_loop, RigRunResult):
                return agent_loop
            return self._build_run_result(
                op_id, "acp_session", tid, RigVerdict.FAILED, "agent_loop_create_failed"
            )

        session_id = agent_loop.session_id  # type: ignore[union-attr]
        self._agent_loop_sessions[session_id] = agent_loop

        receipt_id = str(uuid4())
        receipt_ref = RigReceiptRef(
            receipt_id=receipt_id, surface="acp", trace_id=tid, verdict="completed"
        )

        return self._build_run_result(
            op_id,
            "acp_session",
            tid,
            RigVerdict.COMPLETED,
            response_data={"session_id": session_id, "status": "active"},
        ).__class__(
            operation_id=op_id,
            operation_kind="acp_session",
            verdict=RigVerdict.COMPLETED,
            trace_id=tid,
            operation_hash=compute_sha256(f"acp_session:{op_id}"),
            response_hash=compute_sha256(session_id),
            receipt_ref=receipt_ref,
        )

    async def async_send_acp_message(
        self, session_id: str, message: str, trace_id: str = ""
    ) -> RigRunResult:
        op_id = str(uuid4())
        tid = trace_id or self.trace_id

        agent_loop = self._agent_loop_sessions.get(session_id)
        if agent_loop is None:
            return self._build_run_result(
                op_id, "acp_message", tid, RigVerdict.FAILED, "session_not_found"
            )

        try:
            response_parts: list[str] = []
            from rig_relay.core.types import AssistantEvent

            async for event in agent_loop.act(message):  # type: ignore[union-attr]
                if isinstance(event, AssistantEvent) and event.content:
                    response_parts.append(event.content)

            response_text = (
                "".join(response_parts) if response_parts else "(no response)"
            )
            response_hash = compute_sha256(response_text)
            return self._build_run_result(
                op_id,
                "acp_message",
                tid,
                RigVerdict.COMPLETED,
                response_data={
                    "session_id": session_id,
                    "response": response_text,
                    "response_hash": response_hash,
                    "content_light": False,
                },
            )
        except Exception:
            return self._build_run_result(
                op_id, "acp_message", tid, RigVerdict.FAILED, "acp_message_failed"
            )

    # ── A2A delegation (wired to real A2AServer) ──

    def send_a2a_local_task(
        self, task_id: str, agent_id: str, trace_id: str
    ) -> RigRunResult:
        return asyncio.run(self.async_send_a2a_local_task(task_id, agent_id, trace_id))

    async def async_send_a2a_local_task(
        self, task_id: str, agent_id: str, trace_id: str = ""
    ) -> RigRunResult:
        import json

        from rig_relay.protocols.a2a._lifecycle import (
            build_delegation_receipt,
            delegation_allowed_by_governance,
        )
        from rig_relay.protocols.a2a.server import A2AServer

        op_id = str(uuid4())
        tid = trace_id or self.trace_id

        allowed, reason = delegation_allowed_by_governance(
            "rig_sdk", agent_id, str(task_id)
        )
        if not allowed:
            receipt = build_delegation_receipt(
                "rig_sdk", agent_id, task_id, trace_id=tid, verdict="refused"
            )
            return self._build_run_result(
                op_id,
                "a2a_local_task",
                tid,
                RigVerdict.REFUSED,
                reason,
                response_data=receipt.to_dict(),
            )

        if self._a2a_server is None:
            self._a2a_server = A2AServer(agent_id=agent_id)

        raw_request = json.dumps({
            "jsonrpc": "2.0",
            "id": op_id,
            "method": "tasks/send",
            "params": {
                "task_id": task_id,
                "description": f"SDK delegation to {agent_id}",
                "trace_id": tid,
            },
        })

        try:
            response_str = self._a2a_server.handle_jsonrpc_request(raw_request)  # type: ignore[union-attr]
            response = json.loads(response_str)
        except Exception:
            return self._build_run_result(
                op_id, "a2a_local_task", tid, RigVerdict.FAILED, "a2a_dispatch_failed"
            )

        if "error" in response:
            return self._build_run_result(
                op_id, "a2a_local_task", tid, RigVerdict.FAILED, "a2a_server_error"
            )

        receipt = build_delegation_receipt(
            "rig_sdk", agent_id, task_id, trace_id=tid, verdict="completed"
        )
        return self._build_run_result(
            op_id,
            "a2a_local_task",
            tid,
            RigVerdict.COMPLETED,
            response_data=receipt.to_dict(),
        )

    # ── Sync wrappers for wired operations ──

    def start_agent_chat(self, prompt: str, trace_id: str = "") -> RigRunResult:
        return asyncio.run(self.async_start_agent_chat(prompt, trace_id))

    def list_tools(self, trace_id: str = "") -> RigRunResult:
        return asyncio.run(self.async_list_tools(trace_id))

    def invoke_tool(
        self, tool_name: str, args: dict[str, Any] | None = None, trace_id: str = ""
    ) -> RigRunResult:
        return asyncio.run(self.async_invoke_tool(tool_name, args, trace_id))

    def send_acp_message(
        self, session_id: str, message: str, trace_id: str = ""
    ) -> RigRunResult:
        return asyncio.run(self.async_send_acp_message(session_id, message, trace_id))

    # ── GitHub provider ──

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
