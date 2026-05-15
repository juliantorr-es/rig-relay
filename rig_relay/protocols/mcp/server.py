"""Rig Relay MCP Server — governed tools, resources, and prompts.

Exposes Rig's mission envelopes, receipts, worktree state, and evidence
as MCP resources and tools. Read-only by default. Mutation tools are
gated behind receipt-backed authorization.

Transport: stdio (local) or Streamable HTTP (remote).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ═══ JSON-RPC 2.0 Base ═════════════════════════════════════════════════

class JSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] | None = None


class JSONRPCResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    result: Any | None = None
    error: dict[str, Any] | None = None


class JSONRPCNotification(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] | None = None


JSONRPC_ERROR_CODES = {
    -32700: "Parse error",
    -32600: "Invalid Request",
    -32601: "Method not found",
    -32602: "Invalid params",
    -32603: "Internal error",
    -32000: "Server error",
}


# ═══ MCP Lifecycle ═══════════════════════════════════════════════════════


@dataclass
class ServerCapabilities:
    tools: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    prompts: dict[str, Any] = field(default_factory=dict)


class MCPServerInfo(BaseModel):
    name: str = "rig-relay"
    version: str = "0.1.0"
    protocol_version: str = "2024-11-05"


# ═══ MCP Resources ══════════════════════════════════════════════════════

class MCPResource(BaseModel):
    uri: str
    name: str
    description: str = ""
    mime_type: str = "application/json"


READ_ONLY_RESOURCES: list[MCPResource] = [
    MCPResource(
        uri="rig://mission/current",
        name="Current Mission",
        description="The active mission envelope with scope, sprint, and task assignments.",
    ),
    MCPResource(
        uri="rig://receipts/latest",
        name="Latest Receipts",
        description="Recent coordination receipts (checkpoints, leases, patches).",
    ),
    MCPResource(
        uri="rig://worktree/status",
        name="Worktree Status",
        description="Git worktree state: branch, HEAD, dirty files, active leases.",
    ),
    MCPResource(
        uri="rig://schemas/mission-envelope",
        name="Mission Envelope Schema",
        description="JSON Schema for Rig mission envelopes.",
    ),
    MCPResource(
        uri="rig://projection/current",
        name="Current Projection",
        description="Content-light desktop projection snapshot.",
    ),
    MCPResource(
        uri="rig://council/findings",
        name="Council Findings",
        description="Latest council consultation receipt with provider opinions.",
    ),
]


# ═══ MCP Tools ══════════════════════════════════════════════════════════

class MCPTool(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


READ_ONLY_TOOLS: list[MCPTool] = [
    MCPTool(
        name="rig.search_evidence",
        description="Search Rig's evidence ledger for receipts, findings, and coordination events.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "kind": {"type": "string", "description": "Receipt kind filter"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    ),
    MCPTool(
        name="rig.read_receipt",
        description="Read a specific receipt by ID. Content-light: returns summary + hashes.",
        input_schema={
            "type": "object",
            "properties": {
                "receipt_id": {"type": "string"},
            },
            "required": ["receipt_id"],
        },
    ),
    MCPTool(
        name="rig.build_context_packet",
        description="Build a content-light mission context packet for external consultation.",
        input_schema={
            "type": "object",
            "properties": {
                "mission_id": {"type": "string"},
                "redaction_mode": {
                    "type": "string",
                    "enum": ["minimal", "standard", "full", "paranoid"],
                    "default": "standard",
                },
            },
            "required": ["mission_id"],
        },
    ),
    MCPTool(
        name="rig.create_consult_packet",
        description="Create a structured consultation packet for adversarial review.",
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "redaction_mode": {
                    "type": "string",
                    "enum": ["minimal", "standard", "full", "paranoid"],
                    "default": "standard",
                },
            },
            "required": ["question"],
        },
    ),
    MCPTool(
        name="rig.run_readonly_doctor",
        description="Run a read-only diagnostics check: git state, worktree health, lease status.",
        input_schema={
            "type": "object",
            "properties": {},
        },
    ),
    MCPTool(
        name="rig.summarize_dirty_state",
        description="Summarize dirty files with path hashes only. No file contents.",
        input_schema={
            "type": "object",
            "properties": {},
        },
    ),
    MCPTool(
        name="rig.read_council_findings",
        description="Read council consultation findings: consensus, disagreements, risks.",
        input_schema={
            "type": "object",
            "properties": {
                "receipt_id": {"type": "string"},
            },
        },
    ),
]

# Gated mutation tools — require authorization receipt
GATED_TOOLS: list[MCPTool] = [
    MCPTool(
        name="rig.propose_patch",
        description="Propose a patch for review. Does NOT apply — creates a PatchProposal receipt.",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "touched_paths": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "summary"],
        },
    ),
    MCPTool(
        name="rig.run_validator",
        description="Run a named validator suite. Read-only — produces a validation receipt.",
        input_schema={
            "type": "object",
            "properties": {
                "validator": {"type": "string", "default": "pytest"},
            },
        },
    ),
    MCPTool(
        name="rig.request_user_approval",
        description="Request user approval for a gated action. Returns an authorization receipt.",
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "rationale": {"type": "string"},
            },
            "required": ["action"],
        },
    ),
]


# ═══ MCP Prompts ════════════════════════════════════════════════════════

class MCPPrompt(BaseModel):
    name: str
    description: str
    arguments: list[dict[str, Any]] = Field(default_factory=list)


PROMPTS: list[MCPPrompt] = [
    MCPPrompt(
        name="rig.mission_review",
        description="Review the current mission and recommend next slice.",
        arguments=[
            {"name": "mission_id", "description": "Mission to review", "required": True},
        ],
    ),
    MCPPrompt(
        name="rig.consultation_request",
        description="Create a structured consultation request for external providers.",
        arguments=[
            {"name": "question", "description": "Question for providers", "required": True},
            {"name": "providers", "description": "Provider list", "required": False},
        ],
    ),
    MCPPrompt(
        name="rig.adversarial_review",
        description="Adversarial patch review: find risks, blockers, and do-not-dos.",
        arguments=[
            {"name": "patch_proposal_id", "description": "Proposal to review", "required": True},
        ],
    ),
]


# ═══ MCP Server ═════════════════════════════════════════════════════════


class RigMCPServer:
    """MCP server exposing Rig's governed tools, resources, and prompts.

    Read-only by default. Gated tools require authorization receipts.
    Uses stdio transport for local use, Streamable HTTP for remote.

    Usage:
        server = RigMCPServer()
        await server.serve_stdio()
    """

    def __init__(self) -> None:
        self._initialized = False
        self._server_info = MCPServerInfo()
        self._capabilities = ServerCapabilities(
            tools={"listChanged": True},
            resources={"subscribe": False, "listChanged": True},
            prompts={"listChanged": True},
        )

    @property
    def capabilities(self) -> ServerCapabilities:
        return self._capabilities

    @property
    def server_info(self) -> MCPServerInfo:
        return self._server_info

    def list_tools(self) -> list[MCPTool]:
        return READ_ONLY_TOOLS + GATED_TOOLS

    def list_resources(self) -> list[MCPResource]:
        return READ_ONLY_RESOURCES

    def list_prompts(self) -> list[MCPPrompt]:
        return PROMPTS

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Dispatch a tool call. Read-only tools execute immediately.
        Gated tools require authorization receipt in arguments."""
        all_tools = {t.name: t for t in self.list_tools()}
        if name not in all_tools:
            return {"error": f"Unknown tool: {name}"}

        gated_names = {t.name for t in GATED_TOOLS}
        if name in gated_names:
            receipt = arguments.get("authorization_receipt")
            if not receipt:
                return {
                    "error": "Authorization required",
                    "code": "AUTHORIZATION_REQUIRED",
                    "tool": name,
                }

        if name == "rig.search_evidence":
            return await self._search_evidence(arguments)
        if name == "rig.read_receipt":
            return await self._read_receipt(arguments)
        if name == "rig.build_context_packet":
            return await self._build_context_packet(arguments)
        if name == "rig.create_consult_packet":
            return await self._create_consult_packet(arguments)
        if name == "rig.run_readonly_doctor":
            return await self._run_readonly_doctor(arguments)
        if name == "rig.summarize_dirty_state":
            return await self._summarize_dirty_state(arguments)
        if name == "rig.read_council_findings":
            return await self._read_council_findings(arguments)

        return {"error": f"Tool not implemented: {name}"}

    def read_resource(self, uri: str) -> Any:
        """Read a resource by URI."""
        resources = {r.uri: r for r in READ_ONLY_RESOURCES}
        if uri not in resources:
            return {"error": f"Unknown resource: {uri}"}
        return {"uri": uri, "name": resources[uri].name}

    # ── Tool implementations (stubs — wire to Rig internals) ──────────

    async def _search_evidence(self, args: dict) -> dict:
        return {"status": "ok", "query": args.get("query"), "results": []}

    async def _read_receipt(self, args: dict) -> dict:
        return {"status": "ok", "receipt_id": args.get("receipt_id")}

    async def _build_context_packet(self, args: dict) -> dict:
        return {
            "status": "ok",
            "mission_id": args.get("mission_id"),
            "redaction_mode": args.get("redaction_mode", "standard"),
            "packet_sha256": "",
        }

    async def _create_consult_packet(self, args: dict) -> dict:
        return {
            "status": "ok",
            "question": args.get("question"),
            "providers": args.get("providers", []),
        }

    async def _run_readonly_doctor(self, args: dict) -> dict:
        return {"status": "ok", "git_repo": True, "worktrees": 0, "leases": 0}

    async def _summarize_dirty_state(self, args: dict) -> dict:
        return {"status": "ok", "dirty_files": 0, "path_hashes": []}

    async def _read_council_findings(self, args: dict) -> dict:
        return {"status": "ok", "receipt_id": args.get("receipt_id"), "findings": []}


__all__ = [
    "GATED_TOOLS",
    "JSONRPC_ERROR_CODES",
    "JSONRPCNotification",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "MCPPrompt",
    "MCPResource",
    "MCPServerInfo",
    "MCPTool",
    "PROMPTS",
    "READ_ONLY_RESOURCES",
    "READ_ONLY_TOOLS",
    "RigMCPServer",
    "ServerCapabilities",
]
