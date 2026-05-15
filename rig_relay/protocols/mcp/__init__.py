"""rig_relay.protocols.mcp — MCP server exposing Rig tools, resources, and prompts."""

from rig_relay.protocols.mcp.models import (
    GATED_TOOLS,
    MCPPrompt,
    MCPResource,
    MCPTool,
    MCPToolTier,
    PROMPTS,
    READ_ONLY_RESOURCES,
    READ_ONLY_TOOLS,
    ServerCapabilities,
    TIER_1_TOOLS,
    TIER_2_TOOLS,
    TIER_3_TOOLS,
    TIER_4_TOOLS,
    TIER_5_TOOLS,
)
from rig_relay.protocols.mcp.server import RigMCPServer

__all__ = [
    "GATED_TOOLS",
    "MCPPrompt",
    "MCPResource",
    "MCPTool",
    "MCPToolTier",
    "PROMPTS",
    "READ_ONLY_RESOURCES",
    "READ_ONLY_TOOLS",
    "RigMCPServer",
    "ServerCapabilities",
    "TIER_1_TOOLS",
    "TIER_2_TOOLS",
    "TIER_3_TOOLS",
    "TIER_4_TOOLS",
    "TIER_5_TOOLS",
]
