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
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import secrets
import sys
import time
from typing import Any
import uuid

from rig_relay.coordination.council import RedactionMode
from rig_relay.evidence.redaction import _FORBIDDEN_FIELD_KEYS, _SECRET_VALUE_PATTERNS
from rig_relay.protocols._transport_budgets import BudgetTracker
from rig_relay.protocols.mcp._auth_metadata import build_descriptor_identity
from rig_relay.protocols.mcp._refusal_adapter import classify_tool_descriptor_suspicious
from rig_relay.protocols.mcp.models import (
    GATED_TOOLS,
    PROMPTS,
    READ_ONLY_RESOURCES,
    READ_ONLY_TOOLS,
    ContentLightClass,
    MCPDescriptorIdentity,
    MCPPrompt,
    MCPResource,
    MCPTool,
    MCPToolTier,
    RefusalCode,
    ServerCapabilities,
    compute_descriptor_hash,
)


class RigMCPServer:
    """MCP server exposing Rig's governed tools, resources, and prompts.

    Tiered exposure: Antigravity and other clients see only the tools
    appropriate for their authorization level. Every dangerous tool
    returns approval_required + receipt_id instead of doing the action.

    Usage:
        server = RigMCPServer(workspace_root=Path("/path/to/project"))
        await server.serve_stdio()
    """

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        receipt_store: object | None = None,
        require_auth: bool = False,
    ) -> None:
        self._workspace_root = (workspace_root or Path.cwd()).resolve()
        self._receipt_store = receipt_store
        self._session_token = secrets.token_hex(32)
        self._session_token_fingerprint = hashlib.sha256(
            f"rig.relay.mcp.session:{self._session_token}".encode()
        ).hexdigest()[:16]
        self._require_auth = require_auth
        self._initialized = False
        self._budgets = BudgetTracker()
        self._budgets.connection_start = time.monotonic()
        self._capabilities = ServerCapabilities(
            tools={"listChanged": True},
            resources={"subscribe": False, "listChanged": True},
            prompts={"listChanged": True},
        )
        self._descriptors: dict[str, MCPDescriptorIdentity] = {}
        self._register_descriptors()

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

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, session_token: str = ""
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())

        refusal = self._validate_auth(session_token)
        if refusal is not None:
            refusal["request_id"] = request_id
            self._persist_outcome(refusal, request_id, name)
            return refusal

        all_tools = {t.name: t for t in self.list_tools()}
        tool = all_tools.get(name)
        if tool is None:
            result = {
                "error": {
                    "code": -32601,
                    "message": f"Unknown tool: {name}",
                    "data": {
                        "surface": "mcp",
                        "refusal_code": RefusalCode.UNKNOWN_TOOL,
                        "tool": name,
                        "capability_id": f"rig.{name}",
                        "content_light": True,
                        "content_light_classification": "public_safe",
                        "request_id": request_id,
                        "generated_at": datetime.now(UTC).isoformat(),
                    },
                }
            }
            self._persist_outcome(result, request_id, name)
            return result

        # ── Descriptor integrity ─────────────────────────────
        ok, refusal_code = self._verify_descriptor_integrity(name, tool)
        if not ok:
            result = self._build_refusal(
                name,
                refusal_code,
                "Tool descriptor integrity check failed. "
                "The tool's declaration may have been modified after server startup.",
                int(tool.tier) if tool.tier is not None else 0,
            )
            self._persist_outcome(result, request_id, name)
            return result

        # ── Forbidden tool refusal ──────────────────────────
        if name == "rig.promote_to_preproduction":
            result = self._build_refusal(
                name,
                RefusalCode.FORBIDDEN,
                "Git/release-tier tool permanently forbidden. "
                "Enterprise-gated feature requiring multi-person attestation.",
                int(tool.tier),
            )
            self._persist_outcome(result, request_id, name)
            return result

        if tool.tier is not None and tool.tier.value >= MCPToolTier.MUTATION.value:
            receipt = arguments.get("authorization_receipt")
            if not receipt:
                result = {
                    "status": "blocked",
                    "tool": name,
                    "surface": "mcp",
                    "capability_id": f"rig.{name}",
                    "authority_tier": int(tool.tier),
                    "message": "Mutation-tier tool blocked: signed authorization receipt required. "
                    "MCP mutation tools are FORBIDDEN until approval receipts are "
                    "cryptographically enforced server-side per cross_surface_authority_spine v1.",
                    "refusal_code": "mutation_tier_mcp",
                    "approval_required": True,
                    "content_light": True,
                    "content_light_classification": "public_safe",
                    "request_id": request_id,
                }
                self._persist_outcome(result, request_id, name)
                return result

        if tool.tier is not None and tool.tier.value >= MCPToolTier.GIT_RELEASE.value:
            result = {
                "status": "blocked",
                "tool": name,
                "surface": "mcp",
                "capability_id": f"rig.{name}",
                "authority_tier": int(tool.tier),
                "message": "Git/release-tier tool blocked: these operations are "
                "denied by default per cross_surface_authority_spine v1. "
                "Enterprise-gated feature not yet implemented.",
                "refusal_code": "git_release_tier_mcp",
                "content_light": True,
                "content_light_classification": "public_safe",
                "request_id": request_id,
            }
            self._persist_outcome(result, request_id, name)
            return result

        dispatch_result = await self._dispatch(tool.name, arguments)
        classification, refusal = self._scan_tool_output(dispatch_result)
        if refusal is not None:
            refusal["request_id"] = request_id
            self._persist_outcome(refusal, request_id, name)
            return refusal
        result = {
            **dispatch_result,
            "surface": "mcp",
            "capability_id": f"rig.{name}",
            "authority_tier": int(tool.tier) if tool.tier is not None else 0,
            "content_light_classification": classification,
            "request_id": request_id,
        }
        self._persist_outcome(result, request_id, name)
        return result

    def call_tool_sync(
        self, name: str, arguments: dict[str, Any], *, session_token: str = ""
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())

        refusal = self._validate_auth(session_token)
        if refusal is not None:
            refusal["request_id"] = request_id
            self._persist_outcome(refusal, request_id, name)
            return refusal

        all_tools = {t.name: t for t in self.list_tools()}
        tool = all_tools.get(name)
        if tool is None:
            result = {
                "error": {
                    "code": -32601,
                    "message": f"Unknown tool: {name}",
                    "data": {
                        "surface": "mcp",
                        "refusal_code": RefusalCode.UNKNOWN_TOOL,
                        "tool": name,
                        "capability_id": f"rig.{name}",
                        "content_light": True,
                        "content_light_classification": "public_safe",
                        "request_id": request_id,
                        "generated_at": datetime.now(UTC).isoformat(),
                    },
                }
            }
            self._persist_outcome(result, request_id, name)
            return result

        # ── Descriptor integrity ─────────────────────────────
        ok, refusal_code = self._verify_descriptor_integrity(name, tool)
        if not ok:
            result = self._build_refusal(
                name,
                refusal_code,
                "Tool descriptor integrity check failed.",
                int(tool.tier) if tool.tier is not None else 0,
            )
            self._persist_outcome(result, request_id, name)
            return result

        if name == "rig.promote_to_preproduction":
            result = self._build_refusal(
                name,
                RefusalCode.FORBIDDEN,
                "Git/release-tier tool permanently forbidden.",
                int(tool.tier),
            )
            self._persist_outcome(result, request_id, name)
            return result

        if tool.tier is not None and tool.tier.value >= MCPToolTier.MUTATION.value:
            receipt = arguments.get("authorization_receipt")
            if not receipt:
                result = {
                    "status": "blocked",
                    "tool": name,
                    "surface": "mcp",
                    "capability_id": f"rig.{name}",
                    "authority_tier": int(tool.tier),
                    "message": "Mutation-tier tool blocked: signed authorization receipt required. "
                    "MCP mutation tools are FORBIDDEN until approval receipts are "
                    "cryptographically enforced server-side per cross_surface_authority_spine v1.",
                    "refusal_code": "mutation_tier_mcp",
                    "approval_required": True,
                    "content_light": True,
                    "content_light_classification": "public_safe",
                    "request_id": request_id,
                }
                self._persist_outcome(result, request_id, name)
                return result

        if tool.tier is not None and tool.tier.value >= MCPToolTier.GIT_RELEASE.value:
            result = {
                "status": "blocked",
                "tool": name,
                "surface": "mcp",
                "capability_id": f"rig.{name}",
                "authority_tier": int(tool.tier),
                "message": "Git/release-tier tool blocked: these operations are "
                "denied by default per cross_surface_authority_spine v1. "
                "Enterprise-gated feature not yet implemented.",
                "refusal_code": "git_release_tier_mcp",
                "content_light": True,
                "content_light_classification": "public_safe",
                "request_id": request_id,
            }
            self._persist_outcome(result, request_id, name)
            return result

        if tool.tier is not None and tool.tier.value < MCPToolTier.MUTATION.value:
            dispatch_result = self._dispatch_sync(tool.name, arguments)
            classification, refusal = self._scan_tool_output(dispatch_result)
            if refusal is not None:
                refusal["request_id"] = request_id
                self._persist_outcome(refusal, request_id, name)
                return refusal
            result = {
                **dispatch_result,
                "surface": "mcp",
                "capability_id": f"rig.{name}",
                "authority_tier": int(tool.tier) if tool.tier is not None else 0,
                "content_light_classification": classification,
                "request_id": request_id,
            }
            self._persist_outcome(result, request_id, name)
            return result

        result = {"error": f"Tool not dispatched: {name}", "code": -32601}
        self._persist_outcome(result, request_id, name)
        return result

    # ── Descriptor integrity ──────────────────────────────────────

    def _register_descriptors(self) -> None:
        for tool in self.list_tools():
            identity = build_descriptor_identity(tool)
            self._descriptors[tool.name] = identity

    def _verify_descriptor_integrity(
        self, name: str, tool: MCPTool
    ) -> tuple[bool, str]:
        registered = self._descriptors.get(name)
        if registered is None:
            return False, RefusalCode.UNKNOWN_TOOL
        current_hash = compute_descriptor_hash(tool)
        if current_hash != registered.descriptor_hash:
            self._quarantine_descriptor(
                name,
                f"hash mismatch: registered={registered.descriptor_hash[:12]} "
                f"current={current_hash[:12]}",
            )
            return False, RefusalCode.DESCRIPTOR_DRIFT
        if registered.quarantined:
            return False, RefusalCode.DESCRIPTOR_DRIFT
        return True, ""

    def _detect_descriptor_drift_for_listing(
        self, tool: MCPTool
    ) -> MCPDescriptorIdentity | None:
        registered = self._descriptors.get(tool.name)
        if registered is None:
            return None
        current_hash = compute_descriptor_hash(tool)
        if current_hash != registered.descriptor_hash:
            self._quarantine_descriptor(
                tool.name,
                f"drift detected on tools/list: "
                f"registered={registered.descriptor_hash[:12]} "
                f"current={current_hash[:12]}",
            )
            return registered
        suspicious = classify_tool_descriptor_suspicious(tool.model_dump())
        if suspicious:
            self._quarantine_descriptor(
                tool.name,
                f"suspicious descriptor on tools/list: {', '.join(suspicious)}",
            )
            return registered
        return None

    def _quarantine_descriptor(self, name: str, reason: str) -> None:
        registered = self._descriptors.get(name)
        if registered is None:
            return
        from datetime import UTC, datetime

        registered.quarantined = True
        registered.drift_detected_at = datetime.now(UTC).isoformat()
        registered.drift_reason = reason

    def _build_refusal(
        self, name: str, refusal_code: str, reason: str, tier: int | None = None
    ) -> dict[str, Any]:
        descriptor = self._descriptors.get(name)
        return {
            "status": "refused",
            "surface": "mcp",
            "tool": name,
            "capability_id": f"rig.{name}",
            "authority_tier": tier,
            "refusal_code": refusal_code,
            "reason": reason,
            "content_light": True,
            "descriptor_id": descriptor.descriptor_id if descriptor else None,
            "descriptor_hash": descriptor.descriptor_hash if descriptor else None,
            "content_light_classification": "public_safe",
            "request_id": str(uuid.uuid4()),
            "generated_at": datetime.now(UTC).isoformat(),
        }

    def _build_decision_id(self, seed: str) -> str:
        return f"gd-mcp-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"

    def _persist_outcome(
        self, outcome: dict[str, Any], request_id: str, tool_name: str
    ) -> None:
        if self._receipt_store is None:
            return
        try:
            from rig_relay.evidence.receipt_envelope import (
                ReceiptActor,
                ReceiptActorKind,
                ReceiptDecision,
                ReceiptSubject,
                ReceiptSubjectKind,
                build_receipt_envelope,
            )

            descriptor = self._descriptors.get(tool_name)
            tier = outcome.get("authority_tier", 0)
            refusal_code = outcome.get("refusal_code", "")
            is_refused = outcome.get("status") in ("refused", "blocked")

            actor = ReceiptActor(
                actor_id="mcp_server",
                actor_kind=ReceiptActorKind.RUNTIME,
                display_name="Rig MCP Server",
                is_human=False,
                is_authoritative=True,
            )

            subject = ReceiptSubject(
                subject_id=tool_name,
                subject_kind=ReceiptSubjectKind.TOOL_INVOCATION,
                session_id=None,
            )

            decision_id = self._build_decision_id(
                f"{request_id}:{tool_name}:{refusal_code}"
            )
            receipt_decision = ReceiptDecision(
                decision="blocked" if is_refused else "allowed",
                rationale=outcome.get("reason"),
                gate="mcp_tool_gate",
                governance_decision_id=decision_id,
                surface="mcp",
                authority_tier=f"tier_{tier}" if tier is not None else None,
                capability_id=f"rig.{tool_name}",
                content_light_classification=outcome.get(
                    "content_light_classification", "public_safe"
                ),
            )

            envelope = build_receipt_envelope(
                receipt_kind="mcp_tool_call",
                actor=actor,
                subject=subject,
                decision=receipt_decision,
            )

            append = getattr(self._receipt_store, "append", None)
            if append is not None and callable(append):
                append(envelope)
        except Exception:
            pass

    # ── Workspace root boundary ───────────────────────────────────

    def _resolve_workspace_path(
        self, user_path: str
    ) -> tuple[Path | None, dict | None]:
        if not user_path:
            return self._workspace_root, None
        try:
            candidate = (self._workspace_root / user_path).resolve()
        except (OSError, ValueError, RuntimeError):
            return None, self._build_refusal(
                user_path or "(empty)",
                RefusalCode.ROOT_SCOPE_VIOLATION,
                "Invalid path: cannot resolve.",
            )
        try:
            candidate.relative_to(self._workspace_root)
        except ValueError:
            return None, self._build_refusal(
                user_path,
                RefusalCode.ROOT_SCOPE_VIOLATION,
                "Path traversal outside workspace root denied.",
            )
        return candidate, None

    def _assert_within_root(self, resolved: Path) -> dict | None:
        try:
            resolved.relative_to(self._workspace_root)
        except ValueError:
            return self._build_refusal(
                str(resolved),
                RefusalCode.ROOT_SCOPE_VIOLATION,
                "Resolved path outside workspace root.",
            )
        return None

    def _filter_drift_for_listing(
        self, tools: list[MCPTool]
    ) -> tuple[list[MCPTool], list[str]]:
        clean = []
        drifted = []
        for t in tools:
            registered = self._descriptors.get(t.name)
            if registered is None:
                clean.append(t)
                continue
            if registered.quarantined:
                drifted.append(t.name)
                continue
            drift = self._detect_descriptor_drift_for_listing(t)
            if drift is not None:
                drifted.append(t.name)
                continue
            clean.append(t)
        return clean, drifted

    # ── Content-light output scanning ─────────────────────────────

    # ── Authentication ─────────────────────────────────────────

    def _validate_auth(self, session_token: str) -> dict | None:
        if not self._require_auth:
            return None
        if not session_token:
            return self._build_refusal(
                "tools/call",
                RefusalCode.AUTH_REQUIRED,
                "Session token required for MCP tool calls.",
            )
        if not secrets.compare_digest(session_token, self._session_token):
            return self._build_refusal(
                "tools/call",
                RefusalCode.INVALID_SESSION_TOKEN,
                "Invalid session token. Token fingerprint: "
                + self._session_token_fingerprint,
            )
        return None

    def _classify_mcp_output(self, result: dict[str, Any]) -> str:
        text = json.dumps(result, sort_keys=True, default=str)
        text_lower = text.lower()

        has_forbidden_key = any(
            forbidden in result for forbidden in _FORBIDDEN_FIELD_KEYS
        )
        if has_forbidden_key:
            return ContentLightClass.FORBIDDEN_RAW

        has_secret_value = any(
            pattern.search(text) for pattern in _SECRET_VALUE_PATTERNS
        )
        if has_secret_value:
            return ContentLightClass.SECRET_BEARING

        has_token_like = (
            "access_token" in text_lower
            or "refresh_token" in text_lower
            or "authorization" in text_lower
            or "bearer" in text_lower
            or "api_key" in text_lower
        )
        if has_token_like:
            return ContentLightClass.SENSITIVE_METADATA

        has_raw_content_key = any(
            f in result
            for f in (
                "raw_file_contents",
                "source_code",
                "diff",
                "stdout",
                "stderr",
                "model_output",
                "raw_prompt",
            )
        )
        if has_raw_content_key:
            return ContentLightClass.FORBIDDEN_RAW

        has_cwd_or_path = (
            "cwd" in result
            and isinstance(result.get("cwd"), str)
            and result["cwd"].startswith("/")
        )
        if has_cwd_or_path:
            return ContentLightClass.PRIVATE_LOCAL

        return ContentLightClass.PUBLIC_SAFE

    def _scan_tool_output(self, result: dict[str, Any]) -> tuple[str, dict | None]:
        classification = self._classify_mcp_output(result)

        match classification:
            case ContentLightClass.PUBLIC_SAFE:
                result["content_light_classification"] = classification
                return classification, None
            case ContentLightClass.PRIVATE_LOCAL:
                result["content_light_classification"] = classification
                return classification, None
            case ContentLightClass.SENSITIVE_METADATA:
                return classification, self._build_refusal(
                    "tool_output",
                    RefusalCode.SENSITIVE_METADATA_BLOCKED,
                    "Output classified as sensitive_metadata. "
                    "Returning metadata-only refusal.",
                )
            case ContentLightClass.SECRET_BEARING:
                return classification, self._build_refusal(
                    "tool_output",
                    RefusalCode.SECRET_BEARING_OUTPUT,
                    "Output contains secret-bearing content. Refused.",
                )
            case ContentLightClass.FORBIDDEN_RAW:
                return classification, self._build_refusal(
                    "tool_output",
                    RefusalCode.FORBIDDEN_RAW_OUTPUT,
                    "Output contains forbidden raw content. Refused.",
                )
            case _:
                return classification, None

    def _dispatch_sync(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        dispatch = {
            "rig.current_mission": lambda a: {
                "status": "ok",
                "mission": None,
                "message": "No active mission",
            },
            "rig.inspect_schema": lambda a: {
                "status": "ok",
                "schema": a.get("schema", "mission-envelope"),
                "version": "v1",
            },
            "rig.list_worktrees": lambda a: {
                "status": "ok",
                "worktrees": [],
                "count": 0,
            },
            "rig.search_evidence": lambda a: {
                "status": "ok",
                "query": a.get("query"),
                "results": [],
                "count": 0,
            },
            "rig.read_receipt": lambda a: {
                "status": "ok",
                "receipt_id": a.get("receipt_id", ""),
                "found": False,
            },
            "rig.summarize_dirty_state": lambda a: {
                "status": "ok",
                "dirty_files": 0,
                "path_hashes": [],
                "message": "Clean working tree",
            },
            "rig.run_readonly_doctor": lambda a: {
                "status": "ok",
                "git_repo": True,
                "cwd": ".",
            },
            "rig.build_context_packet": lambda a: {
                "status": "ok",
                "mission_id": a.get("mission_id"),
                "packet_sha256": "0" * 64,
            },
            "rig.create_consult_packet": lambda a: {
                "status": "ok",
                "question": a.get("question"),
                "providers": a.get("providers", []),
            },
            "rig.compare_provider_opinions": lambda a: {
                "status": "ok",
                "consensus": [],
                "disagreements": [],
            },
            "rig.check_merge_friendly": lambda a: {
                "status": "ok",
                "merge_friendly": True,
                "dirty_files": 0,
                "recommendation": "Safe.",
            },
            "rig.audit_dirty_state": lambda a: {
                "status": "ok",
                "dirty_files": 0,
                "recommendation": "Clean tree.",
            },
            "rig.propose_patch": lambda a: {
                "status": "blocked_pending_approval",
                "approval_required": True,
            },
            "rig.run_validator": lambda a: {
                "status": "blocked_pending_approval",
                "validator": a.get("validator"),
                "approval_required": True,
            },
        }
        handler = dispatch.get(name)
        if handler is None:
            return {"error": f"Tool not implemented: {name}", "code": -32601}
        return handler(args)

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
        refusal = self._assert_within_root(self._workspace_root)
        if refusal is not None:
            return refusal
        try:
            from rig_relay.coordination.worktree_manager import WorktreeManager

            mgr = WorktreeManager(self._workspace_root)
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
        refusal = self._assert_within_root(self._workspace_root)
        if refusal is not None:
            return refusal
        try:
            import subprocess

            cwd = self._workspace_root
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
        refusal = self._assert_within_root(self._workspace_root)
        if refusal is not None:
            return refusal
        try:
            import subprocess

            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=str(self._workspace_root),
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
        refusal = self._assert_within_root(self._workspace_root)
        if refusal is not None:
            return refusal
        try:
            import subprocess

            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=str(self._workspace_root),
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
                tools = self.list_tools()
                clean_tools, drifted = self._filter_drift_for_listing(tools)
                result = {
                    "tools": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "input_schema": t.input_schema,
                            "tier": int(t.tier),
                        }
                        for t in clean_tools
                    ],
                    "content_light": True,
                }
                if drifted:
                    result["descriptor_drift_detected"] = drifted
                return result
            case "tools/call":
                name = params.get("name", "")
                arguments = params.get("arguments", {})
                session_token = params.get("session_token", "")
                return await self.call_tool(
                    name, arguments, session_token=session_token
                )
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
