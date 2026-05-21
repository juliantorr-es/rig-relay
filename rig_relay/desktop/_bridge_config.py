from __future__ import annotations

import os
from pathlib import Path
import ssl
from typing import Any

from rig_relay.desktop.correlation import new_correlation_id

__all__ = ["DesktopBridgeConfig", "DesktopBridgeRuntimeConfig"]


def _is_loopback_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def _unsafe_non_loopback_allowed() -> bool:
    return os.getenv("RIG_RELAY_ALLOW_NON_LOOPBACK_LOCAL_BRIDGE", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _tls_trust_state(config: DesktopBridgeConfig) -> str:
    if not config.tls_enabled:
        return "disabled"
    if config.tls_mode == "mkcert":
        return "unknown"
    if config.tls_mode in {"adhoc_local", "self_signed"}:
        return "self_signed"
    return "unknown"


def _transport_label(tls_enabled: bool, tls_trust_state: str) -> str:
    if not tls_enabled:
        return "Loopback Token Bridge"
    if tls_trust_state == "trusted":
        return "TLS Loopback Bridge"
    if tls_trust_state in {"self_signed", "untrusted", "development"}:
        return "Untrusted Development TLS Bridge"
    return "TLS Loopback Bridge"


class DesktopBridgeConfig:
    """Configuration for the single bridge server."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        host: str = "127.0.0.1",
        port: int | None = None,
        frontend_dir: Path | None = None,
        auth_token: str = "",
        ssl_context: ssl.SSLContext | None = None,
        tls_mode: str | None = None,
        cert_fingerprint_sha256: str | None = None,
        build_root: Path | None = None,
        chat_state_provider: Any | None = None,
        chat_message_handler: Any | None = None,
        pywebview_loopback_mode: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.frontend_dir = frontend_dir
        self.auth_token = auth_token
        self.ssl_context = ssl_context
        self.tls_enabled = ssl_context is not None
        self.tls_mode = tls_mode or ("tls" if self.tls_enabled else "insecure")
        self.cert_fingerprint_sha256 = cert_fingerprint_sha256
        self.build_root = build_root
        self.chat_state_provider = chat_state_provider
        self.chat_message_handler = chat_message_handler
        self.pywebview_loopback_mode = pywebview_loopback_mode


class DesktopBridgeRuntimeConfig:
    """Runtime config delivered to frontend via JS API bridge."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        tls_enabled: bool,
        tls_mode: str,
        auth_token: str,
        cert_fingerprint_sha256: str | None = None,
        app_version: str = "dev",
        tls_trust_state: str = "disabled",
        handshake_id: str | None = None,
    ) -> None:
        scheme = "https" if tls_enabled else "http"
        ws_scheme = "wss" if tls_enabled else "ws"
        self.frontend_url = f"{scheme}://{host}:{port}/index.html"
        self.ws_url = f"{ws_scheme}://{host}:{port}/ws"
        self.bridge_origin = f"{scheme}://{host}:{port}"
        self.bridge_host = host
        self.bridge_port = port
        self.tls_enabled = tls_enabled
        self.tls_mode = tls_mode
        self.cert_fingerprint_sha256 = cert_fingerprint_sha256
        self.tls_trust_state = tls_trust_state
        self.transport_label = _transport_label(tls_enabled, tls_trust_state)
        self.handshake_id = handshake_id or new_correlation_id()
        self.local_mode = True
        self.merge_enabled = False
        self.push_enabled = False
        self.auth_required = True
        self.auth_token = auth_token
        self.app_version = app_version

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "rig.desktop.runtime_config.v1",
            "frontend_url": self.frontend_url,
            "ws_url": self.ws_url,
            "bridge_origin": self.bridge_origin,
            "bridge_host": self.bridge_host,
            "bridge_port": self.bridge_port,
            "tls_enabled": self.tls_enabled,
            "tls_mode": self.tls_mode,
            "tls_trust_state": self.tls_trust_state,
            "cert_fingerprint_sha256": self.cert_fingerprint_sha256,
            "transport_label": self.transport_label,
            "handshake_id": self.handshake_id,
            "local_mode": self.local_mode,
            "merge_enabled": self.merge_enabled,
            "push_enabled": self.push_enabled,
            "auth_required": self.auth_required,
            "token_present": bool(self.auth_token),
            "auth_token": self.auth_token,
            "token": self.auth_token,
            "app_version": self.app_version,
        }
