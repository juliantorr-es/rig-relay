"""rig_relay.protocols.mcp — MCP server exposing Rig tools, resources, and prompts."""

from __future__ import annotations

from rig_relay.protocols.mcp._auth_metadata import (
    MCPPerUserAuthorization,
    MCPToolAuthMetadata,
    build_mcp_auth_metadata,
    compute_tool_provenance_hash,
)
from rig_relay.protocols.mcp._refusal_adapter import (
    classify_tool_descriptor_suspicious,
    evaluate_mcp_request,
)
from rig_relay.protocols.mcp.models import (
    GATED_TOOLS,
    PROMPTS,
    READ_ONLY_RESOURCES,
    READ_ONLY_TOOLS,
    TIER_1_TOOLS,
    TIER_2_TOOLS,
    TIER_3_TOOLS,
    TIER_4_TOOLS,
    TIER_5_TOOLS,
    ContentLightClass,
    MCPEvidenceEnvelope,
    MCPPrompt,
    MCPResource,
    MCPTool,
    MCPToolTier,
    RefusalCode,
    ServerCapabilities,
)
from rig_relay.protocols.mcp.server import RigMCPServer

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
    "MCPEvidenceEnvelope",
    "MCPPerUserAuthorization",
    "MCPPrompt",
    "MCPResource",
    "MCPTool",
    "MCPToolAuthMetadata",
    "MCPToolTier",
    "RefusalCode",
    "RigMCPServer",
    "ServerCapabilities",
    "build_mcp_auth_metadata",
    "classify_tool_descriptor_suspicious",
    "compute_tool_provenance_hash",
    "evaluate_mcp_request",
]
