from __future__ import annotations

from enum import StrEnum, auto

from pydantic import BaseModel, ConfigDict


class IntegrationConnectionState(StrEnum):
    NOT_CONFIGURED = auto()
    DISCONNECTED = auto()
    AUTH_REQUIRED = auto()
    CONNECTED = auto()
    DEGRADED = auto()
    ERROR = auto()


class IntegrationCapabilityKind(StrEnum):
    READ = auto()
    WRITE = auto()
    OBSERVE = auto()
    WEBHOOK_INGEST = auto()


class IntegrationAuthKind(StrEnum):
    GITHUB_APP = auto()
    OAUTH = auto()
    SERVICE_ACCOUNT_NOT_SUPPORTED = auto()
    API_KEY = auto()
    NONE = auto()


class IntegrationCapabilityState(BaseModel):
    capability_id: str
    display_name: str
    kind: IntegrationCapabilityKind
    gated: bool
    profile_gate_required: bool
    available: bool = False
    requires_approval: bool = False
    mcp_acp_exposable: bool = False

    model_config = ConfigDict(extra="forbid")


class IntegrationProviderState(BaseModel):
    provider_id: str
    display_name: str
    auth_kind: IntegrationAuthKind
    connection_state: IntegrationConnectionState = (
        IntegrationConnectionState.NOT_CONFIGURED
    )
    profile_gate_required: bool = True
    account_id_hash: str = ""
    granted_scopes: list[str] = []
    capabilities: list[IntegrationCapabilityState] = []
    last_checked_at: str = ""
    degraded_reason: str = ""
    warnings: list[str] = []

    model_config = ConfigDict(extra="forbid")
