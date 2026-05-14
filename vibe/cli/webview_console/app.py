"""pywebview entry point for the Rig Console.

Usage:
    uv run rig-console --mode fixture
    uv run rig-console --mode runtime
    uv run rig-console-textual  (legacy Textual fallback)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import threading
import time
from typing import Any

from vibe.cli.webview_console.backend import RigConsoleBackend
from vibe.cli.webview_console.ws_api import ConsoleWebSocketServer


def _run_ws_server(
    ws: Any, loop_holder: list[asyncio.AbstractEventLoop | None]
) -> None:
    async def _start() -> None:
        loop = asyncio.get_running_loop()
        loop_holder[0] = loop
        await ws.start()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass
        finally:
            await ws.close()

    asyncio.run(_start())


def _find_static_dir() -> Path:
    """Resolve the frontend/rig_console/ static directory."""
    return (
        Path(__file__).resolve().parent.parent.parent.parent
        / "frontend"
        / "rig_console"
    )


def _load_html() -> str:
    static = _find_static_dir()
    index = static / "index.html"
    if not index.is_file():
        return "<html><body><h1>Frontend not found</h1></body></html>"
    return index.read_text(encoding="utf-8")


def _inject_bootstrap(html: str, port: int, token: str) -> str:
    """Inject session token, WebSocket URL, and port into the HTML."""
    return (
        html
        .replace("{{WS_PORT}}", str(port))
        .replace("{{WS_TOKEN}}", token)
        .replace("{{API_BASE}}", f"http://127.0.0.1:{port}")
    )


def main(argv: list[str] | None = None) -> None:
    """Launch the pywebview console."""
    import argparse

    parser = argparse.ArgumentParser(description="Rig Console (pywebview)")
    parser.add_argument("--mode", choices=["fixture", "runtime"], default="runtime")
    parser.add_argument("--session-id", default="rig-console-webview")
    parser.add_argument("--workspace-root", type=Path, default=None)
    parser.add_argument("--receipt-root", type=Path, default=None)
    parser.add_argument("--debug", action="store_true", default=False)
    args = parser.parse_args(argv)

    backend = RigConsoleBackend(
        session_id=args.session_id,
        workspace_root=args.workspace_root,
        receipt_root=args.receipt_root,
        mode=args.mode,
    )

    ws = ConsoleWebSocketServer(backend, port=0)
    loop_holder: list[asyncio.AbstractEventLoop | None] = [None]
    ws_thread = threading.Thread(
        target=_run_ws_server, args=(ws, loop_holder), daemon=True
    )
    ws_thread.start()
    while ws.port == 0:
        if not ws_thread.is_alive():
            raise RuntimeError("WebSocket server failed to start")
        time.sleep(0.01)
    port = ws.port
    token = ws.token

    # Load and inject frontend HTML
    html = _load_html()
    html = _inject_bootstrap(html, port, token)

    # Start pywebview window
    import webview

    webview.create_window(
        "Rig Console", html=html, width=1200, height=800, min_size=(800, 600)
    )

    webview.start(
        gui=None,  # use platform default
        debug=args.debug,
        private_mode=False,
    )

    if loop_holder[0] is not None:
        asyncio.run_coroutine_threadsafe(ws.close(), loop_holder[0]).result()


if __name__ == "__main__":
    main()
