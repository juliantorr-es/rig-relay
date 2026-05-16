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

import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.coordination.council import RedactionMode
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
        return {
            "status": "ok",
            "receipt_id": receipt_id,
            "found": False,
        }

    async def _read_council_findings(self, args: dict) -> dict:
        return {
            "status": "ok",
            "receipt_id": args.get("receipt_id"),
            "findings": [],
        }

    # ═══ Tier 1 — Analysis / packet generation ══════════════════════════

    async def _build_context_packet(self, args: dict) -> dict:
        mission_id = args.get("mission_id", "")
        redaction = args.get("redaction_mode", "standard")
        packet = json.dumps({
            "mission_id": mission_id,
            "redaction_mode": redaction,
        }, sort_keys=True).encode()
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
            is_git = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                capture_output=True, text=True, cwd=str(cwd),
            ).returncode == 0
            return {
                "status": "ok",
                "git_repo": is_git,
                "cwd": str(cwd),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _summarize_dirty_state(self, args: dict) -> dict:
        try:
            import subprocess
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, cwd=str(Path.cwd()),
            )
            dirty = result.stdout.strip()
            if not dirty:
                return {"status": "ok", "dirty_files": 0, "path_hashes": [], "message": "Clean working tree"}
            lines = [l.strip() for l in dirty.split("\n") if l.strip()]
            path_hashes = [
                hashlib.sha256(l.split(None, 1)[-1].encode()).hexdigest()[:12]
                for l in lines if len(l.split(None, 1)) > 1
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
                capture_output=True, text=True, cwd=str(Path.cwd()),
            )
            dirty = bool(result.stdout.strip())
            return {
                "status": "ok",
                "merge_friendly": not dirty,
                "dirty_files": len(result.stdout.strip().split("\n")) if dirty else 0,
                "recommendation": "Clean working tree. Safe to proceed." if not dirty else "Dirty tree. Commit or stash before merging.",
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _audit_dirty_state(self, args: dict) -> dict:
        summary = await self._summarize_dirty_state(args)
        summary["audit_kind"] = "dirty_state_audit"
        summary["recommendation"] = (
            "Clean tree. No action needed." if summary.get("dirty_files", 0) == 0
            else f"{summary['dirty_files']} files dirty. Consider checkpointing before proceeding."
        )
        return summary

    # ═══ Tier 3 — Patch proposal ════════════════════════════════════════

    async def _propose_patch(self, args: dict) -> dict:
        mission_id = args.get("mission_id", "")
        rationale = args.get("rationale", "")
        target_files = args.get("target_files", [])
        proposed_changes = args.get("proposed_changes", "")

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


__all__ = ["RigMCPServer"]
