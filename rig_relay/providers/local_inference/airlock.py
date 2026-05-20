"""Local inference airlock — governed endpoint configuration and gating.

No endpoint is active by default. Configuration is explicit, user-controlled,
and never auto-starts servers. This airlock prevents any agent from accidentally
using local inference before an endpoint is configured and probed.

Content-light throughout: never stores prompts, completions, keys, or raw content.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.providers.local_inference.models import (
    APIProtocol,
    LocalRuntimeKind,
    PlatformClass,
)

ENDPOINT_CONFIG_SCHEMA = "rig.relay.local_inference.endpoint_config.v1"
DEFAULT_CONFIG_ROOT = Path.home() / ".rig" / "relay" / "local_inference"


class LocalInferenceEndpointConfig(BaseModel):
    """Configuration for a local inference endpoint.

    Content-light: stores endpoint URL and metadata only. No API keys or tokens.
    Explicit: the endpoint must be user-configured before any probing occurs.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=ENDPOINT_CONFIG_SCHEMA, frozen=True)
    endpoint_url: str = ""
    runtime_kind: LocalRuntimeKind = LocalRuntimeKind.UNKNOWN
    api_protocol: APIProtocol = APIProtocol.OPENAI_COMPATIBLE
    platform_class: PlatformClass = PlatformClass.UNKNOWN
    endpoint_sha256: str = ""
    configured_at: str = ""
    configured_by: str = "manual"

    def set_endpoint(self, url: str) -> None:
        from datetime import UTC, datetime

        self.endpoint_url = url.rstrip("/")
        self.endpoint_sha256 = hashlib.sha256(
            self.endpoint_url.encode("utf-8")
        ).hexdigest()
        self.configured_at = datetime.now(UTC).isoformat()


class LocalInferenceAirlock:
    """Governed airlock for local inference endpoint configuration.

    An airlock is active only when explicitly configured. Until then,
    local inference is unavailable to agents, tools, and routing.
    """

    def __init__(self, config_root: Path | None = None) -> None:
        self._config_root = config_root or DEFAULT_CONFIG_ROOT
        self._config_path = self._config_root / "endpoint_config.json"

    @property
    def is_configured(self) -> bool:
        return self._config_path.is_file()

    def get_config(self) -> LocalInferenceEndpointConfig | None:
        if not self.is_configured:
            return None
        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
            return LocalInferenceEndpointConfig(**data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def save_config(self, config: LocalInferenceEndpointConfig) -> None:
        self._config_root.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def remove_config(self) -> None:
        if self._config_path.is_file():
            self._config_path.unlink()

    def configure_endpoint(
        self,
        url: str,
        runtime_kind: LocalRuntimeKind = LocalRuntimeKind.UNKNOWN,
        platform_class: PlatformClass = PlatformClass.UNKNOWN,
    ) -> LocalInferenceEndpointConfig:
        config = LocalInferenceEndpointConfig(
            runtime_kind=runtime_kind, platform_class=platform_class
        )
        config.set_endpoint(url)
        self.save_config(config)
        return config

    def build_config_snapshot(self) -> dict[str, Any]:
        config = self.get_config()
        if config is None:
            return {"configured": False, "schema_version": ENDPOINT_CONFIG_SCHEMA}
        return {
            "configured": True,
            "schema_version": ENDPOINT_CONFIG_SCHEMA,
            "endpoint_url": config.endpoint_url,
            "endpoint_sha256": config.endpoint_sha256,
            "runtime_kind": config.runtime_kind.value,
            "api_protocol": config.api_protocol.value,
            "platform_class": config.platform_class.value,
            "configured_at": config.configured_at,
        }


_GLOBAL_AIRLOCK: LocalInferenceAirlock | None = None


def get_airlock() -> LocalInferenceAirlock:
    global _GLOBAL_AIRLOCK
    if _GLOBAL_AIRLOCK is None:
        _GLOBAL_AIRLOCK = LocalInferenceAirlock()
    return _GLOBAL_AIRLOCK


def is_local_inference_configured() -> bool:
    return get_airlock().is_configured


def is_local_inference_available() -> bool:
    if not is_local_inference_configured():
        return False
    from rig_relay.governance.service_state import get_capability_gate

    gate = get_capability_gate()
    allowed, _ = gate.is_allowed("local_inference_probe")
    return allowed


__all__ = [
    "LocalInferenceAirlock",
    "LocalInferenceEndpointConfig",
    "get_airlock",
    "is_local_inference_available",
    "is_local_inference_configured",
]
