"""OAuth loopback callback server for desktop native apps.

Implements RFC 8252: native apps must use an external browser and local
loopback callback, not embedded webviews.

This module provides:
    - find_free_loopback_port: pick an available localhost port
    - build_loopback_redirect_uri: construct the callback URI
    - start_loopback_server: run a minimal HTTP server to capture the callback
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

DEFAULT_LOOPBACK_HOST = "127.0.0.1"
DEFAULT_LOOPBACK_PORT = 18080


def find_free_loopback_port() -> int:
    """Find a free TCP port on 127.0.0.1."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((DEFAULT_LOOPBACK_HOST, 0))
        return int(s.getsockname()[1])


def build_loopback_redirect_uri(port: int) -> str:
    """Build loopback redirect URI for the given port."""
    return f"http://{DEFAULT_LOOPBACK_HOST}:{port}/callback"


def start_loopback_server(port: int, timeout: float = 120.0) -> dict[str, Any]:
    """Start a minimal HTTP loopback server to capture OAuth callback.

    Blocks until callback received or timeout.

    Args:
        port: Localhost port to listen on.
        timeout: Maximum seconds to wait for callback.

    Returns:
        Dict with 'code' and 'state' if successful, or 'error' on failure.
    """
    result: dict[str, Any] = {"error": "callback_not_received"}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            nonlocal result
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)

            error = params.get("error", [None])[0]
            if error:
                result = {"error": error}
                self._respond(400, f"OAuth error: {error}")
                return

            code = params.get("code", [None])[0]
            state = params.get("state", [None])[0]

            if code and state:
                result = {"code": code, "state": state}
                self._respond(200, "Authorization received. You may close this tab.")
            else:
                result = {"error": "missing_code_or_state"}
                self._respond(400, "Missing authorization code or state.")

        def _respond(self, status: int, body: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, format: str, *args: Any) -> None:
            return  # suppress HTTP server logs

    server = HTTPServer((DEFAULT_LOOPBACK_HOST, port), CallbackHandler)
    server.timeout = timeout

    try:
        while result.get("error") == "callback_not_received":
            server.handle_request()
    except (TimeoutError, KeyboardInterrupt):
        result = {"error": "timeout"}
    finally:
        server.server_close()

    return result
