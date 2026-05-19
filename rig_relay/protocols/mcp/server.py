"""Rig Relay MCP Server — governed tools, resources, and prompts.

Exposes Rig's mission envelopes, receipts, worktree state, and evidence
as MCP resources and tools. Read-only by default. Mutation tools are
gated behind receipt-backed authorization.

Tool tiers:
  Tier 0 — Read-only context (safe by default)
  Tier 1 — Analysis / packet generation (non-mutating, produces artifacts)
  Tier 2 — Validation / bounded execution (known validators, audits)
  Tier 3 — Patch proposal (generates diffs, does NOT apply)
  Tier 4 — Mutation (requires explicit Rig approval gate)
  Tier 5 — Git / release / publish (denied by default)

Transport: stdio (local) or Streamable HTTP (remote).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

from rig_relay.coordination.council import RedactionMode
from rig_relay.protocols._transport_budgets import BudgetTracker
from rig_relay.protocols.mcp.models import (
    GATED_TOOLS,
    PROMPTS,
    READ_ONLY_RESOURCES,
    READ_ONLY_TOOLS,
    MCPPrompt,
    MCPResource,
    MCPTool,
    MCPToolTier,
    ServerCapabilities,
)


class RigMCPServer:
    """MCP server exposing Rig's governed tools, resources, and prompts.

    Tiered exposure: Antigravity and other clients see only the tools
    appropriate for their authorization level. Every dangerous tool
    returns approval_required + receipt_id instead of doing the action.

    Usage:
        server = RigMCPServer()
        await server.serve_stdio()
    """

    def __init__(self) -> None:
        self._initialized = False
        self._budgets = BudgetTracker()
        self._budgets.connection_start = time.monotonic()
        self._capabilities = ServerCapabilities(
            tools={"listChanged": True},
            resources={"subscribe": False, "listChanged": True},
            prompts={"listChanged": True},
        )

    @property
    def capabilities(self) -> ServerCapabilities:
        return self._capabilities

    def list_tools(self, tier: MCPToolTier | None = None) -> list[MCPTool]:
        all_tools = READ_ONLY_TOOLS + GATED_TOOLS
        if tier is None:
            return all_tools
        return [t for t in all_tools if t.tier == tier]

    def list_resources(self) -> list[MCPResource]:
        return READ_ONLY_RESOURCES

    def list_prompts(self) -> list[MCPPrompt]:
        return PROMPTS

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        all_tools = {t.name: t for t in self.list_tools()}
        tool = all_tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool: {name}", "code": -32601}

        # Tier 4+ tools require authorization receipt
        if tool.tier and tool.tier.value >= 4:
            receipt = arguments.get("authorization_receipt")
            if not receipt:
                return {
                    "status": "blocked_pending_approval",
                    "tool": name,
                    "message": "Authorization receipt required for mutation.",
                    "approval_required": True,
                }

        return await self._dispatch(tool.name, arguments)

    async def handle_jsonrpc_request(self, raw_request: str) -> str:
        if not self._budgets.can_accept_request(len(raw_request.encode("utf-8"))):
            return json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32000,
                    "message": "Rate limited: request budget exceeded",
                },
            })

        self._budgets.track_request()
        try:
            try:
                request = json.loads(raw_request)
            except json.JSONDecodeError:
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                })

            if not isinstance(request, dict):
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                })

            if request.get("jsonrpc") != "2.0":
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {
                        "code": -32600,
                        "message": "Invalid Request: missing or wrong jsonrpc version",
                    },
                })

            method = request.get("method")
            req_id = request.get("id")

            if method == "tools/call":
                params = request.get("params", {})
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})
                result = await self.call_tool(tool_name, arguments)
                return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})

            if method == "tools/list":
                tools = self.list_tools()
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": [t.model_dump() for t in tools]},
                })

            if method == "resources/list":
                resources = self.list_resources()
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"resources": [r.model_dump() for r in resources]},
                })

            if method == "prompts/list":
                prompts = self.list_prompts()
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"prompts": [p.model_dump() for p in prompts]},
                })

            return json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })
        finally:
            self._budgets.release_request()

    def process_jsonrpc_sync(self, raw_request: str) -> str:
        if not self._budgets.can_accept_request(len(raw_request.encode("utf-8"))):
            return json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32000,
                    "message": "Rate limited: request budget exceeded",
                },
            })

        self._budgets.track_request()
        try:
            try:
                request = json.loads(raw_request)
            except json.JSONDecodeError:
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                })

            if not isinstance(request, dict):
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                })

            if request.get("jsonrpc") != "2.0":
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {
                        "code": -32600,
                        "message": "Invalid Request: missing or wrong jsonrpc version",
                    },
                })

            method = request.get("method")
            req_id = request.get("id")

            if method == "tools/list":
                tools = self.list_tools()
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": [t.model_dump() for t in tools]},
                })

            if method == "resources/list":
                resources = self.list_resources()
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"resources": [r.model_dump() for r in resources]},
                })

            if method == "prompts/list":
                prompts = self.list_prompts()
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"prompts": [p.model_dump() for p in prompts]},
                })

            return json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })
        finally:
            self._budgets.release_request()

    @property
    def budget_tracker(self) -> BudgetTracker:
        return self._budgets

    async def _dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        dispatch = {
            "rig.search_evidence": self._search_evidence,
            "rig.read_receipt": self._read_receipt,
            "rig.build_context_packet": self._build_context_packet,
            "rig.create_consult_packet": self._create_consult_packet,
            "rig.run_readonly_doctor": self._run_readonly_doctor,
            "rig.summarize_dirty_state": self._summarize_dirty_state,
            "rig.read_council_findings": self._read_council_findings,
            "rig.list_worktrees": self._list_worktrees,
            "rig.current_mission": self._current_mission,
            "rig.inspect_schema": self._inspect_schema,
            "rig.propose_patch": self._propose_patch,
            "rig.run_validator": self._run_validator,
            "rig.request_user_approval": self._request_approval,
            "rig.check_merge_friendly": self._check_merge_friendly,
            "rig.audit_dirty_state": self._audit_dirty_state,
            "rig.compare_provider_opinions": self._compare_provider_opinions,
        }
        handler = dispatch.get(name)
        if handler is None:
            return {"error": f"Tool not implemented: {name}", "code": -32601}
        return await handler(args)

    # ═══ Tier 0 — Read-only context ═════════════════════════════════════

    async def _current_mission(self, args: dict) -> dict:
        return {"status": "ok", "mission": None, "message": "No active mission"}

    async def _inspect_schema(self, args: dict) -> dict:
        schema_name = args.get("schema", "mission-envelope")
        return {"status": "ok", "schema": schema_name, "version": "v1"}

    async def _list_worktrees(self, args: dict) -> dict:
        try:
            from rig_relay.coordination.worktree_manager import WorktreeManager

            mgr = WorktreeManager(Path.cwd())
            records = mgr.list_worktrees()
            return {
                "status": "ok",
                "worktrees": [
                    {
                        "workspace_id": r.workspace_id,
                        "path": r.path,
                        "status": str(r.status),
                        "head_sha": r.head_sha,
                    }
                    for r in records
                ],
                "count": len(records),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ═══ Tier 0 — Search / read ═════════════════════════════════════════

    async def _search_evidence(self, args: dict) -> dict:
        return {
            "status": "ok",
            "query": args.get("query"),
            "kind": args.get("kind"),
            "results": [],
            "count": 0,
        }

    async def _read_receipt(self, args: dict) -> dict:
        receipt_id = args.get("receipt_id", "")
        return {"status": "ok", "receipt_id": receipt_id, "found": False}

    async def _read_council_findings(self, args: dict) -> dict:
        return {"status": "ok", "receipt_id": args.get("receipt_id"), "findings": []}

    # ═══ Tier 1 — Analysis / packet generation ══════════════════════════

    async def _build_context_packet(self, args: dict) -> dict:
        mission_id = args.get("mission_id", "")
        redaction = args.get("redaction_mode", "standard")
        packet = json.dumps(
            {"mission_id": mission_id, "redaction_mode": redaction}, sort_keys=True
        ).encode()
        return {
            "status": "ok",
            "mission_id": mission_id,
            "redaction_mode": redaction,
            "packet_sha256": hashlib.sha256(packet).hexdigest(),
        }

    async def _create_consult_packet(self, args: dict) -> dict:
        question = args.get("question", "")
        providers = args.get("providers", [])
        redaction = RedactionMode(args.get("redaction_mode", "standard"))
        return {
            "status": "ok",
            "question": question,
            "providers": providers,
            "redaction_mode": str(redaction),
            "message": "Consultation packet created. Use /send_to <provider> in Rig Relay to dispatch.",
        }

    async def _compare_provider_opinions(self, args: dict) -> dict:
        return {
            "status": "ok",
            "providers_compared": args.get("providers", []),
            "consensus": [],
            "disagreements": [],
        }

    # ═══ Tier 2 — Validation / bounded execution ════════════════════════

    async def _run_readonly_doctor(self, args: dict) -> dict:
        try:
            import subprocess

            cwd = Path.cwd()
            is_git = (
                subprocess.run(
                    ["git", "rev-parse", "--git-dir"],
                    capture_output=True,
                    text=True,
                    cwd=str(cwd),
                ).returncode
                == 0
            )
            return {"status": "ok", "git_repo": is_git, "cwd": str(cwd)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _summarize_dirty_state(self, args: dict) -> dict:
        try:
            import subprocess

            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=str(Path.cwd()),
            )
            dirty = result.stdout.strip()
            if not dirty:
                return {
                    "status": "ok",
                    "dirty_files": 0,
                    "path_hashes": [],
                    "message": "Clean working tree",
                }
            lines = [l.strip() for l in dirty.split("\n") if l.strip()]
            path_hashes = [
                hashlib.sha256(l.split(None, 1)[-1].encode()).hexdigest()[:12]
                for l in lines
                if len(l.split(None, 1)) > 1
            ]
            return {
                "status": "ok",
                "dirty_files": len(lines),
                "path_hashes": path_hashes,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _run_validator(self, args: dict) -> dict:
        validator = args.get("validator", "")
        if not validator:
            return {"status": "error", "message": "validator name required"}
        receipt_id = f"rec-val-{hashlib.sha256(validator.encode()).hexdigest()[:12]}"
        return {
            "status": "blocked_pending_approval",
            "receipt_id": receipt_id,
            "validator": validator,
            "message": f"Validator '{validator}' requires approval. Use rig.request_user_approval first.",
            "approval_required": True,
        }

    async def _check_merge_friendly(self, args: dict) -> dict:
        try:
            import subprocess

            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=str(Path.cwd()),
            )
            dirty = bool(result.stdout.strip())
            return {
                "status": "ok",
                "merge_friendly": not dirty,
                "dirty_files": len(result.stdout.strip().split("\n")) if dirty else 0,
                "recommendation": "Clean working tree. Safe to proceed."
                if not dirty
                else "Dirty tree. Commit or stash before merging.",
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _audit_dirty_state(self, args: dict) -> dict:
        summary = await self._summarize_dirty_state(args)
        summary["audit_kind"] = "dirty_state_audit"
        summary["recommendation"] = (
            "Clean tree. No action needed."
            if summary.get("dirty_files", 0) == 0
            else f"{summary['dirty_files']} files dirty. Consider checkpointing before proceeding."
        )
        return summary

    # ═══ Tier 3 — Patch proposal ════════════════════════════════════════

    async def _propose_patch(self, args: dict) -> dict:
        mission_id = args.get("mission_id", "")
        rationale = args.get("rationale", "")
        target_files = args.get("target_files", [])
        receipt_id = f"rec-patch-{hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()[:12]}"

        return {
            "status": "blocked_pending_approval",
            "receipt_id": receipt_id,
            "patch_proposal_created": True,
            "mission_id": mission_id,
            "target_files": target_files,
            "rationale": rationale,
            "next_action": "approve_in_rig",
            "message": f"Patch proposal created ({receipt_id}). User approval required before workspace mutation.",
            "approval_required": True,
        }

    # ═══ Tier 4 — Mutation (requires approval gate) ═════════════════════

    async def _request_approval(self, args: dict) -> dict:
        action = args.get("action", "")
        rationale = args.get("rationale", "")
        receipt_id = f"rec-auth-{hashlib.sha256(action.encode()).hexdigest()[:12]}"
        return {
            "status": "approval_requested",
            "receipt_id": receipt_id,
            "action": action,
            "rationale": rationale,
            "message": f"Approval requested for '{action}'. Awaiting user confirmation in Rig Relay.",
        }

    # ═══ Transport — stdio ═══════════════════════════════════════════════

    async def serve_stdio(self) -> None:
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            line_str = line.strip()
            if not line_str:
                continue

            try:
                request = json.loads(line_str)
            except json.JSONDecodeError:
                response = self._jsonrpc_error(-32700, "Parse error", None)
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
                continue

            request_id = request.get("id")
            method = request.get("method", "")
            params = request.get("params", {})
            jsonrpc = request.get("jsonrpc")

            if jsonrpc != "2.0" or not method:
                response = self._jsonrpc_error(-32600, "Invalid Request", request_id)
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
                continue

            trace_id = params.get("trace_id", "") if isinstance(params, dict) else ""
            result = await self._handle_jsonrpc(method, params, request_id)
            if "error" in result:
                response = {
                    "jsonrpc": "2.0",
                    "error": result["error"],
                    "id": request_id,
                }
            else:
                response = {"jsonrpc": "2.0", "result": result, "id": request_id}
            if trace_id:
                response["trace_id"] = trace_id
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

    def _jsonrpc_error(
        self,
        code: int,
        message: str,
        request_id: str | int | None = None,
        data: dict | None = None,
    ) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "error": error, "id": request_id}  # type: ignore[return-type]

    async def _handle_jsonrpc(
        self, method: str, params: dict, request_id: str | int
    ) -> dict[str, Any]:
        match method:
            case "initialize":
                return {
                    "capabilities": self._capabilities,
                    "server_info": {"name": "Rig Relay MCP Server", "version": "0.1.0"},
                    "content_light": True,
                }
            case "tools/list":
                tool_list = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "input_schema": t.input_schema,
                        "tier": int(t.tier),
                    }
                    for t in self.list_tools()
                ]
                return {"tools": tool_list}
            case "tools/call":
                name = params.get("name", "")
                arguments = params.get("arguments", {})
                return await self.call_tool(name, arguments)
            case "resources/list":
                resource_list = [
                    {
                        "uri": r.uri,
                        "name": r.name,
                        "description": r.description,
                        "mime_type": r.mime_type,
                    }
                    for r in self.list_resources()
                ]
                return {"resources": resource_list}
            case "prompts/list":
                prompt_list = [
                    {
                        "name": p.name,
                        "description": p.description,
                        "arguments": p.arguments,
                    }
                    for p in self.list_prompts()
                ]
                return {"prompts": prompt_list}
            case _:
                return self._jsonrpc_error(
                    -32601, f"Method not found: {method}", request_id
                )

    async def serve_streamable_http(self, host: str, port: int) -> None:
        raise NotImplementedError("Streamable HTTP transport deferred")


__all__ = ["RigMCPServer"]
