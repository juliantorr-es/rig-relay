"""pywebview entry point for the Rig Console.

Usage:
    uv run rig-console-webview --mode fixture
    uv run rig-console-webview --mode runtime
    uv run rig-console-textual  (legacy Textual fallback)
"""

from __future__ import annotations

import asyncio
from pathlib import Path


def _find_static_dir() -> Path:
    """Resolve the frontend/rig_console/ static directory."""
    return Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "rig_console"


def _load_html() -> str:
    static = _find_static_dir()
    index = static / "index.html"
    if not index.is_file():
        return "<html><body><h1>Frontend not found</h1></body></html>"
    return index.read_text(encoding="utf-8")


def _inject_bootstrap(html: str, port: int, token: str) -> str:
    """Inject session token, WebSocket URL, and port into the HTML."""
    return (
        html.replace("{{WS_PORT}}", str(port))
        .replace("{{WS_TOKEN}}", token)
        .replace("{{API_BASE}}", f"http://127.0.0.1:{port}")
    )


def main() -> None:
    """Launch the pywebview console."""
    import argparse

    parser = argparse.ArgumentParser(description="Rig Console (pywebview)")
    parser.add_argument("--mode", choices=["fixture", "runtime"], default="runtime")
    parser.add_argument("--session-id", default="rig-console-webview")
    parser.add_argument("--workspace-root", type=Path, default=None)
    parser.add_argument("--receipt-root", type=Path, default=None)
    parser.add_argument("--debug", action="store_true", default=False)
    args = parser.parse_args()

    # Build backend
    from vibe.cli.webview_console.backend import RigConsoleBackend

    backend = RigConsoleBackend(
        session_id=args.session_id,
        workspace_root=args.workspace_root,
        receipt_root=args.receipt_root,
    )

    # Start WebSocket server
    from vibe.cli.webview_console.ws_api import ConsoleWebSocketServer

    ws = ConsoleWebSocketServer(backend, port=0)
    asyncio.run(ws.start())
    port = ws.port
    token = ws.token

    # Load and inject frontend HTML
    html = _load_html()
    html = _inject_bootstrap(html, port, token)

    # Start pywebview window
    import webview

    webview.create_window(
        "Rig Console",
        html=html,
        width=1200,
        height=800,
        min_size=(800, 600),
    )

    webview.start(
        gui=None,  # use platform default
        debug=args.debug,
        private_mode=False,
    )

    # Cleanup
    asyncio.run(ws.close())


if __name__ == "__main__":
    main()
