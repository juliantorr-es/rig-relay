"""Provider adapter contract profiles for external coding agents.

Defines explicit adapter profiles for Claude Code, Codex, Cursor,
Antigravity, and future tools. Each profile identifies:

- Verified integration surfaces (what the product actually supports)
- Whether the provider can act as A2A client, A2A server, MCP host,
  MCP client, etc.
- Supported authentication model
- Streaming/cancellation/artifact support where known
- Local mutation risk
- Required user configuration
- Trust tier assignment
- Admitted Rig Relay capability subset
- Status: verified, proposal-only, transport-unverified, deferred

No provider profile advertises unverified A2A capability. No profile
launches external tools or imports their SDKs. This is a contract
describing what IS possible and what is NOT yet possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class IntegrationSurface(StrEnum):
    """An integration surface that a provider actually supports."""

    A2A_CLIENT = "a2a_client"
    A2A_SERVER = "a2a_server"
    MCP_HOST = "mcp_host"
    MCP_CLIENT = "mcp_client"
    CLI_LAUNCHED_WORKER = "cli_launched_worker"
    IDE_CLIENT = "ide_client"
    JSONRPC_CLIENT = "jsonrpc_client"
    HTTP_API = "http_api"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class AdapterStatus(StrEnum):
    """Status of an adapter profile."""

    VERIFIED = "verified"
    PROPOSAL_ONLY = "proposal_only"
    TRANSPORT_UNVERIFIED = "transport_unverified"
    DEFERRED = "deferred"


class AuthenticationModel(StrEnum):
    """Supported authentication model for a provider adapter."""

    NONE = "none"
    API_KEY = "api_key"
    OAUTH = "oauth"
    HMAC_SESSION = "hmac_session"
    BEARER_TOKEN = "bearer_token"
    UNKNOWN = "unknown"


@dataclass
class ProviderAdapterProfile:
    """Contract profile for an external coding-agent provider.

    This is not an SDK wrapper — it defines what IS known about the
    provider's supported interfaces, what Rig Relay capabilities can
    be safely exposed to it, and what is not yet implemented.
    """

    provider_id: str
    provider_name: str
    provider_description: str = ""

    verified_integration_surfaces: list[IntegrationSurface] = field(
        default_factory=lambda: [IntegrationSurface.UNKNOWN]
    )

    can_act_as_a2a_client: bool = False
    can_act_as_a2a_server: bool = False
    can_consume_mcp_tools: bool = False
    can_expose_mcp_tools: bool = False

    supported_authentication: list[AuthenticationModel] = field(
        default_factory=lambda: [AuthenticationModel.NONE]
    )

    streaming_supported: bool = False
    cancellation_supported: bool = False
    artifact_exchange_supported: bool = False

    local_mutation_risk: bool = True
    requires_user_configuration: bool = True
    required_config_keys: list[str] = field(default_factory=list)

    assigned_trust_tier: str = "external_unauthenticated"
    admitted_rig_capabilities: list[str] = field(default_factory=list)

    adapter_status: AdapterStatus = AdapterStatus.TRANSPORT_UNVERIFIED
    status_note: str = ""

    content_light: bool = True


def _mcp_bridge_caps() -> list[str]:
    """Capabilities available through an MCP bridge."""
    return [
        "discovery_only",
        "proposal_generation",
        "content_light_artifact_exchange",
        "evidence_verification",
    ]


# ---- Verified Provider Profiles ----

CLAUDE_CODE_PROFILE = ProviderAdapterProfile(
    provider_id="claude_code",
    provider_name="Claude Code",
    provider_description="Anthropic's CLI coding agent. MCP support is documented.",
    verified_integration_surfaces=[IntegrationSurface.MCP_CLIENT],
    can_act_as_a2a_client=False,
    can_act_as_a2a_server=False,
    can_consume_mcp_tools=True,
    can_expose_mcp_tools=False,
    supported_authentication=[AuthenticationModel.API_KEY],
    streaming_supported=True,
    cancellation_supported=True,
    artifact_exchange_supported=False,
    local_mutation_risk=True,
    requires_user_configuration=True,
    required_config_keys=["api_key"],
    assigned_trust_tier="external_provider_adapter",
    admitted_rig_capabilities=_mcp_bridge_caps(),
    adapter_status=AdapterStatus.PROPOSAL_ONLY,
    status_note=(
        "MCP verified. Can consume Rig Relay MCP tools exposing bounded A2A "
        "task operations. Not natively A2A. A2A task requests are bridged "
        "through MCP tool calls, not direct A2A protocol."
    ),
)

CODEX_PROFILE = ProviderAdapterProfile(
    provider_id="codex",
    provider_name="Codex App",
    provider_description="OpenAI's Codex coding agent. MCP support is documented.",
    verified_integration_surfaces=[IntegrationSurface.MCP_CLIENT],
    can_act_as_a2a_client=False,
    can_act_as_a2a_server=False,
    can_consume_mcp_tools=True,
    can_expose_mcp_tools=False,
    supported_authentication=[AuthenticationModel.API_KEY],
    streaming_supported=True,
    cancellation_supported=True,
    artifact_exchange_supported=False,
    local_mutation_risk=True,
    requires_user_configuration=True,
    required_config_keys=["api_key"],
    assigned_trust_tier="external_provider_adapter",
    admitted_rig_capabilities=_mcp_bridge_caps(),
    adapter_status=AdapterStatus.PROPOSAL_ONLY,
    status_note=(
        "MCP verified. Can consume Rig Relay MCP tools exposing bounded A2A "
        "task operations. Not natively A2A."
    ),
)

CURSOR_PROFILE = ProviderAdapterProfile(
    provider_id="cursor",
    provider_name="Cursor",
    provider_description="Cursor IDE with MCP integration support.",
    verified_integration_surfaces=[
        IntegrationSurface.MCP_CLIENT,
        IntegrationSurface.IDE_CLIENT,
    ],
    can_act_as_a2a_client=False,
    can_act_as_a2a_server=False,
    can_consume_mcp_tools=True,
    can_expose_mcp_tools=False,
    supported_authentication=[AuthenticationModel.API_KEY],
    streaming_supported=True,
    cancellation_supported=True,
    artifact_exchange_supported=False,
    local_mutation_risk=True,
    requires_user_configuration=True,
    required_config_keys=["api_key"],
    assigned_trust_tier="external_provider_adapter",
    admitted_rig_capabilities=_mcp_bridge_caps(),
    adapter_status=AdapterStatus.PROPOSAL_ONLY,
    status_note=(
        "MCP verified. Cursor can consume Rig Relay MCP tools. IDE "
        "integration surface is documented but not directly bridged here."
    ),
)

ANTIGRAVITY_PROFILE = ProviderAdapterProfile(
    provider_id="antigravity",
    provider_name="Antigravity",
    provider_description="Antigravity IDE. MCP integration with Rig Relay's tiered tool exposure.",
    verified_integration_surfaces=[IntegrationSurface.MCP_CLIENT],
    can_act_as_a2a_client=False,
    can_act_as_a2a_server=False,
    can_consume_mcp_tools=True,
    can_expose_mcp_tools=False,
    supported_authentication=[AuthenticationModel.API_KEY],
    streaming_supported=True,
    cancellation_supported=True,
    artifact_exchange_supported=False,
    local_mutation_risk=True,
    requires_user_configuration=True,
    required_config_keys=["api_key"],
    assigned_trust_tier="external_provider_adapter",
    admitted_rig_capabilities=_mcp_bridge_caps(),
    adapter_status=AdapterStatus.PROPOSAL_ONLY,
    status_note=(
        "MCP verified. Rig Relay's MCP server already targets Antigravity. "
        "Tiered tool exposure in place. No verified A2A endpoint."
    ),
)

GENERIC_MCP_PROFILE = ProviderAdapterProfile(
    provider_id="generic_mcp",
    provider_name="Generic MCP Client",
    provider_description="Any MCP-compatible client that can consume Rig Relay's MCP server.",
    verified_integration_surfaces=[IntegrationSurface.MCP_CLIENT],
    can_act_as_a2a_client=False,
    can_act_as_a2a_server=False,
    can_consume_mcp_tools=True,
    can_expose_mcp_tools=False,
    supported_authentication=[AuthenticationModel.NONE],
    streaming_supported=False,
    cancellation_supported=False,
    artifact_exchange_supported=False,
    local_mutation_risk=False,
    requires_user_configuration=False,
    assigned_trust_tier="external_unauthenticated",
    admitted_rig_capabilities=["discovery_only"],
    adapter_status=AdapterStatus.PROPOSAL_ONLY,
    status_note="Generic MCP client. Safe default with minimal capabilities.",
)


ALL_PROVIDER_PROFILES: dict[str, ProviderAdapterProfile] = {
    "claude_code": CLAUDE_CODE_PROFILE,
    "codex": CODEX_PROFILE,
    "cursor": CURSOR_PROFILE,
    "antigravity": ANTIGRAVITY_PROFILE,
    "generic_mcp": GENERIC_MCP_PROFILE,
}


def get_profile(provider_id: str) -> ProviderAdapterProfile | None:
    """Look up a provider adapter profile by ID."""
    return ALL_PROVIDER_PROFILES.get(provider_id)


def all_profiles() -> list[ProviderAdapterProfile]:
    """Return all registered provider profiles."""
    return list(ALL_PROVIDER_PROFILES.values())


def profiles_by_status(status: AdapterStatus) -> list[ProviderAdapterProfile]:
    """Return all profiles with a given adapter status."""
    return [p for p in ALL_PROVIDER_PROFILES.values() if p.adapter_status == status]


def profiles_claiming_a2a() -> list[ProviderAdapterProfile]:
    """Return any profiles that claim A2A capability (should be none)."""
    return [
        p
        for p in ALL_PROVIDER_PROFILES.values()
        if p.can_act_as_a2a_client or p.can_act_as_a2a_server
    ]


def build_bridge_mapping(provider_id: str, a2a_task_id: str) -> dict[str, object]:
    """Build a provider-neutral A2A-to-MCP bridge mapping.

    Maps a safe external client request into A2A task operations
    exposed as MCP tools. Returns a content-light mapping dict.
    """
    profile = get_profile(provider_id)
    if profile is None:
        return {
            "status": "refused",
            "refusal_code": "unknown_provider",
            "task_id": a2a_task_id,
            "content_light": True,
        }
    return {
        "status": "bridged",
        "provider_id": provider_id,
        "task_id": a2a_task_id,
        "bridge_transport": "mcp",
        "admitted_capabilities": profile.admitted_rig_capabilities,
        "mutation_refused": True,
        "content_light": True,
    }


__all__ = [
    "ALL_PROVIDER_PROFILES",
    "ANTIGRAVITY_PROFILE",
    "CLAUDE_CODE_PROFILE",
    "CODEX_PROFILE",
    "CURSOR_PROFILE",
    "GENERIC_MCP_PROFILE",
    "AdapterStatus",
    "AuthenticationModel",
    "IntegrationSurface",
    "ProviderAdapterProfile",
    "all_profiles",
    "build_bridge_mapping",
    "get_profile",
    "profiles_by_status",
    "profiles_claiming_a2a",
]
