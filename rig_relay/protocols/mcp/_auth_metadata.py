"""MCP auth metadata — tool provenance hashes, descriptor identity, and per-user authorization."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from rig_relay.protocols.mcp.models import (
    MCPDescriptorIdentity,
    MCPTool,
    MCPToolTier,
    compute_descriptor_hash,
)


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def compute_tool_provenance_hash(tool_descriptor: dict[str, Any] | object) -> str:
    canonical = json.dumps(
        {
            "name": getattr(tool_descriptor, "name", "")
            if not isinstance(tool_descriptor, dict)
            else tool_descriptor.get("name", ""),
            "description": (
                getattr(tool_descriptor, "description", "")
                if not isinstance(tool_descriptor, dict)
                else tool_descriptor.get("description", "")
            ),
            "input_schema": (
                getattr(tool_descriptor, "input_schema", {})
                if not isinstance(tool_descriptor, dict)
                else tool_descriptor.get("input_schema", {})
            ),
            "server_identity": "rig.relay.mcp.local",
        },
        sort_keys=True,
    )
    return _sha256(canonical)


@dataclass
class MCPToolAuthMetadata:
    tool_name: str
    provenance_hash: str
    auth_required: bool
    scopes: list[str] = field(default_factory=list)
    bearer_supported: bool = False
    oauth_supported: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "tool_name": self.tool_name,
            "provenance_hash": self.provenance_hash,
            "auth_required": self.auth_required,
            "scopes": self.scopes,
            "bearer_supported": self.bearer_supported,
            "oauth_supported": self.oauth_supported,
        }


def _tier_requires_auth(tier: MCPToolTier) -> bool:
    return tier in {MCPToolTier.MUTATION, MCPToolTier.GIT_RELEASE}


def _tier_scopes(tier: MCPToolTier) -> list[str]:
    match tier:
        case MCPToolTier.READ_ONLY:
            return ["rig:read"]
        case MCPToolTier.ANALYSIS:
            return ["rig:read", "rig:analyze"]
        case MCPToolTier.VALIDATION:
            return ["rig:read", "rig:validate"]
        case MCPToolTier.PATCH_PROPOSAL:
            return ["rig:read", "rig:propose"]
        case MCPToolTier.MUTATION:
            return ["rig:read", "rig:mutate"]
        case MCPToolTier.GIT_RELEASE:
            return ["rig:read", "rig:release"]


def build_mcp_auth_metadata(
    tool_descriptor: MCPTool | dict[str, Any], tool_tier: MCPToolTier | None = None
) -> MCPToolAuthMetadata:
    if isinstance(tool_descriptor, MCPTool):
        tool_name = tool_descriptor.name
        tier = tool_descriptor.tier
    else:
        tool_name = tool_descriptor.get("name", "")
        tier_val = tool_descriptor.get("tier", 0)
        tier = (
            MCPToolTier(tier_val)
            if isinstance(tier_val, int)
            else MCPToolTier.READ_ONLY
        )

    if tool_tier is not None:
        tier = tool_tier

    provenance_hash = compute_tool_provenance_hash(tool_descriptor)
    auth_required = _tier_requires_auth(tier)
    scopes = _tier_scopes(tier)

    return MCPToolAuthMetadata(
        tool_name=tool_name,
        provenance_hash=provenance_hash,
        auth_required=auth_required,
        scopes=scopes,
        bearer_supported=False,
        oauth_supported=False,
    )


@dataclass
class MCPPerUserAuthorization:
    user_id_hash: str
    tool_name: str
    scopes_granted: list[str] = field(default_factory=list)
    authorization_status: str = "refused"  # allowed | refused | expired
    expires_at: str = ""
    content_light: bool = True
    schema_version: str = "rig.relay.mcp.per_user_auth.v1"
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "user_id_hash": self.user_id_hash,
            "tool_name": self.tool_name,
            "scopes_granted": self.scopes_granted,
            "authorization_status": self.authorization_status,
            "expires_at": self.expires_at,
            "content_light": self.content_light,
            "generated_at": self.generated_at,
        }


def build_descriptor_identity(tool: MCPTool, version: int = 1) -> MCPDescriptorIdentity:
    descriptor_hash = compute_descriptor_hash(tool)

    return MCPDescriptorIdentity(
        descriptor_id=f"desc-mcp-{_sha256(tool.name + descriptor_hash)[:16]}",
        descriptor_version=version,
        descriptor_hash=descriptor_hash,
        schema_version="rig.relay.mcp.descriptor.v1",
        tool_name=tool.name,
        capability_id=f"rig.{tool.name}",
        authority_tier=int(tool.tier),
        mutation_class=_mutation_class_for_tool(tool),
        read_only_hint=tool.tier.value < MCPToolTier.PATCH_PROPOSAL.value,
        input_schema_hash=_sha256(
            json.dumps(tool.input_schema, sort_keys=True) if tool.input_schema else "{}"
        ),
    )


def _mutation_class_for_tool(tool: MCPTool) -> str | None:
    if tool.tier.value >= MCPToolTier.MUTATION.value:
        return "FILE_WRITE"
    if tool.tier.value == MCPToolTier.PATCH_PROPOSAL.value:
        return "FILE_WRITE"
    if tool.tier.value == MCPToolTier.GIT_RELEASE.value:
        return "WORKTREE_CHECKPOINT"
    return "read_only"


__all__ = [
    "MCPPerUserAuthorization",
    "MCPToolAuthMetadata",
    "build_descriptor_identity",
    "build_mcp_auth_metadata",
    "compute_tool_provenance_hash",
]
