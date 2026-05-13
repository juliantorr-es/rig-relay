#!/usr/bin/env python3
"""Rig Relay Desktop Cockpit — Read-Only Shell — CLI wrapper.

The core implementation now lives in ``rig_relay.desktop.projection`` and
``rig_relay.desktop.websocket_server``. This script is the thin CLI wrapper.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import secrets
import threading

from rig_relay.desktop.projection import build_projection
from rig_relay.desktop.websocket_server import (
    DEFAULT_PORT as DEFAULT_WS_PORT,
    ProjectionWebSocketServer,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"
FRONTEND_DIR = REPO_ROOT / "frontend" / "desktop"


def _print_summary(projection: dict) -> None:
    """Print projection summary to stdout."""
    available = sum(1 for v in projection["source_status"].values() if v)
    total = len(projection["source_status"])
    print("Projection summary:")
    print(f"  App version: {projection['app_version']}")
    print(f"  Schema: {projection['schema_version']}")
    print(f"  Generated at: {projection['generated_at']}")
    print(f"  Data sources: {available}/{total} available")
    for name, avail in sorted(projection["source_status"].items()):
        status = "OK" if avail else "MISSING"
        print(f"    [{status}] {name}")
    print(f"  Warnings: {len(projection['warnings'])}")
    for w in projection["warnings"]:
        print(f"    ! {w}")
    print(f"  Available actions: {len(projection['read_only_actions'])}")
    print()


def load_data() -> dict:
    """Backward-compatible data loader — builds a projection dict."""
    return build_projection(build_root=BUILD_ROOT)


def _dry_run(ws_port: int = DEFAULT_WS_PORT) -> None:
    """Build and print projection summary without opening a window."""
    projection = build_projection(build_root=BUILD_ROOT)
    _print_summary(projection)
    print(f"WebSocket stream would listen on ws://127.0.0.1:{ws_port}")
    print("WebSocket auth/token gating: enabled (token auto-generated)")
    print()
    print(json.dumps(projection, indent=2))


def _run_ws_server(build_root: Path, host: str, port: int, token: str) -> None:
    """Run the WebSocket projection stream in a background thread."""

    async def _start() -> None:
        server = ProjectionWebSocketServer(
            build_root=build_root, host=host, port=port, token=token
        )
        await server.start()
        print(f"WebSocket projection stream on ws://{host}:{port}")
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass
        finally:
            await server.close()

    asyncio.run(_start())


def _generate_ws_token() -> str:
    """Generate a session token for the WebSocket projection stream."""
    return secrets.token_hex(32)


def _open_window(ws_port: int | None) -> None:
    """Open pywebview window with optional WebSocket stream."""
    try:
        import webview  # type: ignore[import-untyped]
    except ImportError:
        print("pywebview not available. Install with: uv add pywebview")
        print("Running dry-run instead...")
        _dry_run(ws_port or DEFAULT_WS_PORT)
        return

    index_path = FRONTEND_DIR / "index.html"
    if not index_path.is_file():
        print(f"Frontend not found at {index_path}")
        return

    ws_token: str | None = None
    ws_thread: threading.Thread | None = None
    if ws_port is not None:
        ws_token = _generate_ws_token()
        ws_thread = threading.Thread(
            target=_run_ws_server,
            args=(BUILD_ROOT, "127.0.0.1", ws_port, ws_token),
            daemon=True,
        )
        ws_thread.start()

    class CockpitAPI:
        """Read-only API exposed to JS bridge (fallback transport)."""

        def get_projection(self) -> dict:
            return build_projection(build_root=BUILD_ROOT)

        def refresh_projection(self) -> dict:
            return build_projection(build_root=BUILD_ROOT)

        def get_available_actions(self) -> list[str]:
            from rig_relay.desktop.projection import READ_ONLY_ACTIONS

            return list(READ_ONLY_ACTIONS)

        def get_ws_config(self) -> dict:
            """Return WebSocket config (token, host, port) for frontend.

            Token is never printed in normal logs. Exposed only through
            the pywebview bridge to the frontend.
            """
            return {
                "token": ws_token or "",
                "host": "127.0.0.1",
                "port": ws_port or DEFAULT_WS_PORT,
            }

    webview.create_window(
        title="Rig Relay Cockpit",
        url=str(index_path),
        js_api=CockpitAPI(),
        width=1200,
        height=800,
        resizable=True,
        min_size=(800, 600),
    )
    webview.start()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rig Relay Desktop Cockpit — Read-Only Shell"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print projection, exit without opening a window.",
    )
    parser.add_argument(
        "--no-ws",
        action="store_true",
        help="Disable the WebSocket projection stream (use pywebview JS bridge only).",
    )
    parser.add_argument(
        "--ws-port",
        type=int,
        default=DEFAULT_WS_PORT,
        help=f"Port for WebSocket projection stream (default: {DEFAULT_WS_PORT}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    ws_port: int | None = None if args.no_ws else args.ws_port

    if args.dry_run:
        _dry_run(ws_port or DEFAULT_WS_PORT)
        return 0

    _open_window(ws_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
