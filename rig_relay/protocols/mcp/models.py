"""MCP protocol models — tiered tools, resources, prompts.

Tool tiers:
  Tier 0 — Read-only context (safe by default)
  Tier 1 — Analysis / packet generation
  Tier 2 — Validation / bounded execution
  Tier 3 — Patch proposal (no apply)
  Tier 4 — Mutation (requires approval gate)
  Tier 5 — Git / release / publish (denied by default)

Descriptor integrity: every MCP tool descriptor is treated as a governed
capability declaration. Provenance hashes are computed at registration and
verified at dispatch. Drift/rug-pull detection runs on every tools/list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MCPToolTier(IntEnum):
    READ_ONLY = 0
    ANALYSIS = 1
    VALIDATION = 2
    PATCH_PROPOSAL = 3
    MUTATION = 4
    GIT_RELEASE = 5


class MCPTool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    tier: MCPToolTier = MCPToolTier.READ_ONLY
    requires_approval: bool = False
    descriptor_hash: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.descriptor_hash:
            self.descriptor_hash = compute_descriptor_hash(self)


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


def _canonical_sha256(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_descriptor_hash(tool: MCPTool) -> str:
    return _canonical_sha256({
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "tier": int(tool.tier),
        "server_identity": "rig.relay.mcp.local",
    })


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

# ═══ Descriptor identity model ═══════════════════════════════════════


class RefusalCode:
    DESCRIPTOR_DRIFT = "descriptor_integrity_failure"
    UNKNOWN_TOOL = "unknown_tool"
    MUTATION_TIER = "mutation_tier_mcp"
    GIT_RELEASE_TIER = "git_release_tier_mcp"
    FORBIDDEN = "forbidden_permanently"
    NOT_DISPATCHABLE = "not_dispatchable"
    ROOT_SCOPE_VIOLATION = "root_scope_violation"
    SECRET_BEARING_OUTPUT = "secret_bearing_output"
    FORBIDDEN_RAW_OUTPUT = "forbidden_raw_output"
    SENSITIVE_METADATA_BLOCKED = "sensitive_metadata_blocked"
    AUTH_REQUIRED = "authentication_required"
    INVALID_SESSION_TOKEN = "invalid_session_token"
    UNAUTHORIZED_TIER = "unauthorized_tier"


class ContentLightClass:
    PUBLIC_SAFE = "public_safe"
    PRIVATE_LOCAL = "private_local"
    SENSITIVE_METADATA = "sensitive_metadata"
    SECRET_BEARING = "secret_bearing"
    FORBIDDEN_RAW = "forbidden_raw"


@dataclass
class MCPDescriptorIdentity:
    descriptor_id: str
    descriptor_version: int
    descriptor_hash: str
    schema_version: str
    tool_name: str
    capability_id: str
    authority_tier: int
    mutation_class: str | None = None
    read_only_hint: bool = True
    input_schema_hash: str = ""
    server_identity: str = "rig.relay.mcp.local"
    registered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    content_light: bool = True
    quarantined: bool = False
    drift_detected_at: str | None = None
    drift_reason: str | None = None


class MCPEvidenceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envelope_schema: str = "rig.relay.mcp.evidence_envelope.v1"
    request_id: str
    session_id: str = ""
    actor_id: str = ""
    surface: str = "mcp"
    authority_tier: int = 0
    capability_id: str = ""
    input_hash: str = ""
    output_hash: str = ""
    payload_schema: str = ""
    policy_decision_id: str = ""
    approval_receipt_id: str = ""
    trace_id: str = ""
    artifact_refs: list[str] = Field(default_factory=list)
    content_light_classification: str = ContentLightClass.PUBLIC_SAFE
    redaction_scan_id: str = ""
    source_of_truth_refs: list[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    producer: str = "rig.relay.mcp.server"
    payload: dict[str, Any] = Field(default_factory=dict)


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
    "ContentLightClass",
    "MCPDescriptorIdentity",
    "MCPEvidenceEnvelope",
    "MCPPrompt",
    "MCPResource",
    "MCPTool",
    "MCPToolTier",
    "RefusalCode",
    "ServerCapabilities",
    "compute_descriptor_hash",
]
