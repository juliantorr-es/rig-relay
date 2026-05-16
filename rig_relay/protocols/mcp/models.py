"""MCP protocol models — tiered tools, resources, prompts.

Tool tiers:
  Tier 0 — Read-only context (safe by default)
  Tier 1 — Analysis / packet generation
  Tier 2 — Validation / bounded execution
  Tier 3 — Patch proposal (no apply)
  Tier 4 — Mutation (requires approval gate)
  Tier 5 — Git / release / publish (denied by default)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field


class MCPToolTier(IntEnum):
    READ_ONLY = 0
    ANALYSIS = 1
    VALIDATION = 2
    PATCH_PROPOSAL = 3
    MUTATION = 4
    GIT_RELEASE = 5


class MCPTool(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    tier: MCPToolTier = MCPToolTier.READ_ONLY
    requires_approval: bool = False


class MCPResource(BaseModel):
    uri: str
    name: str
    description: str = ""
    mime_type: str = "application/json"


class MCPPrompt(BaseModel):
    name: str
    description: str
    arguments: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class ServerCapabilities:
    tools: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    prompts: dict[str, Any] = field(default_factory=dict)


# ═══ Tier 0 — Read-only context ═════════════════════════════════════════

READ_ONLY_TOOLS: list[MCPTool] = [
    MCPTool(
        name="rig.current_mission",
        description="Get the current active mission envelope with scope, sprint, and task assignments.",
        tier=MCPToolTier.READ_ONLY,
    ),
    MCPTool(
        name="rig.search_evidence",
        description="Search Rig's evidence ledger for receipts, findings, and coordination events.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "kind": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        tier=MCPToolTier.READ_ONLY,
    ),
    MCPTool(
        name="rig.read_receipt",
        description="Read a specific receipt by ID. Content-light: returns summary + hashes.",
        input_schema={
            "type": "object",
            "properties": {"receipt_id": {"type": "string"}},
            "required": ["receipt_id"],
        },
        tier=MCPToolTier.READ_ONLY,
    ),
    MCPTool(
        name="rig.list_worktrees",
        description="List all tracked git worktrees with status, path, and HEAD SHA.",
        tier=MCPToolTier.READ_ONLY,
    ),
    MCPTool(
        name="rig.inspect_schema",
        description="Inspect a Rig schema (mission-envelope, receipt, patch-proposal, consultation).",
        input_schema={"type": "object", "properties": {"schema": {"type": "string"}}},
        tier=MCPToolTier.READ_ONLY,
    ),
    MCPTool(
        name="rig.summarize_dirty_state",
        description="Summarize dirty files with path hashes only. No file contents exposed.",
        tier=MCPToolTier.READ_ONLY,
    ),
    MCPTool(
        name="rig.run_readonly_doctor",
        description="Run read-only diagnostics: git repo check, worktree health, lease status.",
        tier=MCPToolTier.READ_ONLY,
    ),
]

# ═══ Tier 1 — Analysis / packet generation ══════════════════════════════

TIER_1_TOOLS: list[MCPTool] = [
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
        tier=MCPToolTier.ANALYSIS,
    ),
    MCPTool(
        name="rig.create_consult_packet",
        description="Create a structured consultation packet for adversarial provider review.",
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "providers": {"type": "array", "items": {"type": "string"}},
                "redaction_mode": {
                    "type": "string",
                    "enum": ["minimal", "standard", "full", "paranoid"],
                    "default": "standard",
                },
            },
            "required": ["question"],
        },
        tier=MCPToolTier.ANALYSIS,
    ),
    MCPTool(
        name="rig.compare_provider_opinions",
        description="Compare council consultation findings across providers. Returns consensus and disagreements.",
        input_schema={
            "type": "object",
            "properties": {"providers": {"type": "array", "items": {"type": "string"}}},
        },
        tier=MCPToolTier.ANALYSIS,
    ),
]

# ═══ Tier 2 — Validation / bounded execution ════════════════════════════

TIER_2_TOOLS: list[MCPTool] = [
    MCPTool(
        name="rig.run_validator",
        description="Run an approved Rig validator by name and return a receipt-backed result.",
        input_schema={
            "type": "object",
            "properties": {
                "validator": {
                    "type": "string",
                    "enum": ["pytest", "ruff", "pyright", "work_doctor"],
                },
                "scope": {"type": "string"},
            },
            "required": ["validator"],
        },
        tier=MCPToolTier.VALIDATION,
    ),
    MCPTool(
        name="rig.check_merge_friendly",
        description="Check if the working tree is clean and safe to merge. Returns recommendation.",
        tier=MCPToolTier.VALIDATION,
    ),
    MCPTool(
        name="rig.audit_dirty_state",
        description="Audit dirty file state and produce a recommendation. No mutation.",
        tier=MCPToolTier.VALIDATION,
    ),
]

# ═══ Tier 3 — Patch proposal ════════════════════════════════════════════

TIER_3_TOOLS: list[MCPTool] = [
    MCPTool(
        name="rig.propose_patch",
        description="Create a patch proposal artifact for review. Does NOT apply — returns receipt + approval gate.",
        input_schema={
            "type": "object",
            "properties": {
                "mission_id": {"type": "string"},
                "rationale": {"type": "string"},
                "target_files": {"type": "array", "items": {"type": "string"}},
                "proposed_changes": {"type": "string"},
            },
            "required": ["mission_id", "rationale", "target_files", "proposed_changes"],
        },
        tier=MCPToolTier.PATCH_PROPOSAL,
        requires_approval=True,
    )
]

# ═══ Tier 4 — Mutation ══════════════════════════════════════════════════

TIER_4_TOOLS: list[MCPTool] = [
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
        tier=MCPToolTier.MUTATION,
    )
]

# ═══ Tier 5 — Git / release / publish ═══════════════════════════════════

TIER_5_TOOLS: list[MCPTool] = [
    MCPTool(
        name="rig.promote_to_preproduction",
        description="Promote approved patches to the preproduction branch. Requires authorization receipt.",
        input_schema={
            "type": "object",
            "properties": {
                "receipt_ids": {"type": "array", "items": {"type": "string"}},
                "authorization_receipt": {"type": "string"},
            },
            "required": ["receipt_ids", "authorization_receipt"],
        },
        tier=MCPToolTier.GIT_RELEASE,
        requires_approval=True,
    )
]

# ═══ Aggregates ═════════════════════════════════════════════════════════

READ_ONLY_TOOLS.extend(TIER_1_TOOLS + TIER_2_TOOLS)

GATED_TOOLS: list[MCPTool] = TIER_3_TOOLS + TIER_4_TOOLS + TIER_5_TOOLS

# ═══ Resources ══════════════════════════════════════════════════════════

READ_ONLY_RESOURCES: list[MCPResource] = [
    MCPResource(
        uri="rig://mission/current",
        name="Current Mission",
        description="Active mission envelope.",
    ),
    MCPResource(
        uri="rig://receipts/latest",
        name="Latest Receipts",
        description="Recent coordination receipts.",
    ),
    MCPResource(
        uri="rig://worktree/status",
        name="Worktree Status",
        description="Git worktree state.",
    ),
    MCPResource(
        uri="rig://schemas/mission-envelope",
        name="Mission Envelope Schema",
        description="JSON Schema.",
    ),
    MCPResource(
        uri="rig://projection/current",
        name="Current Projection",
        description="Desktop projection.",
    ),
    MCPResource(
        uri="rig://council/findings",
        name="Council Findings",
        description="Provider opinions.",
    ),
]

# ═══ Prompts ════════════════════════════════════════════════════════════

PROMPTS: list[MCPPrompt] = [
    MCPPrompt(
        name="rig.mission_review",
        description="Review the current mission and recommend next slice.",
        arguments=[{"name": "mission_id", "required": True}],
    ),
    MCPPrompt(
        name="rig.consultation_request",
        description="Create a structured consultation request.",
        arguments=[
            {"name": "question", "required": True},
            {"name": "providers", "required": False},
        ],
    ),
    MCPPrompt(
        name="rig.adversarial_review",
        description="Adversarial patch review: find risks, blockers, do-not-dos.",
        arguments=[{"name": "patch_proposal_id", "required": True}],
    ),
]

__all__ = [
    "GATED_TOOLS",
    "PROMPTS",
    "READ_ONLY_RESOURCES",
    "READ_ONLY_TOOLS",
    "TIER_1_TOOLS",
    "TIER_2_TOOLS",
    "TIER_3_TOOLS",
    "TIER_4_TOOLS",
    "TIER_5_TOOLS",
    "MCPPrompt",
    "MCPResource",
    "MCPTool",
    "MCPToolTier",
    "ServerCapabilities",
]
