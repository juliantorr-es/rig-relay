"""rig_relay.protocols.mcp — MCP server exposing Rig tools, resources, and prompts."""

from rig_relay.protocols.mcp.server import (
    GATED_TOOLS,
    MCPPrompt,
    MCPResource,
    MCPServerInfo,
    MCPTool,
    PROMPTS,
    READ_ONLY_RESOURCES,
    READ_ONLY_TOOLS,
    RigMCPServer,
    ServerCapabilities,
)

__all__ = [
    "GATED_TOOLS",
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
