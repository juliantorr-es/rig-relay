#!/usr/bin/env python3
"""Rig Relay Desktop WebSocket Projection Stream — CLI entry point.

Starts a WebSocket server that serves content-light projections to the desktop
frontend. Binds to localhost by default. Token-gated. No mutation authority.

Usage:
    uv run python scripts/rig_relay_desktop_websocket.py
    uv run python scripts/rig_relay_desktop_websocket.py --port 9877 --token mytoken
    uv run python scripts/rig_relay_desktop_websocket.py --build-root /path/to/build
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rig_relay.desktop.websocket_server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    ProjectionWebSocketServer,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rig Relay Desktop WebSocket Projection Stream"
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Bind address (default: {DEFAULT_HOST}; non-localhost requires --allow-non-localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Bind port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--build-root",
        type=Path,
        default=DEFAULT_BUILD_ROOT,
        help="Path to .build/rig-relay directory",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Session token (auto-generated if not provided; not printed in normal logs)",
    )
    parser.add_argument(
        "--allow-non-localhost",
        action="store_true",
        default=False,
        help="Allow binding to non-localhost addresses (not recommended)",
    )
    return parser.parse_args(argv)


async def _run_server(args: argparse.Namespace) -> None:
    server = ProjectionWebSocketServer(
        build_root=args.build_root,
        host=args.host,
        port=args.port,
        token=args.token,
        allow_non_localhost=args.allow_non_localhost,
    )
    await server.start()
    print(
        f"Rig Relay WebSocket projection stream running on ws://{args.host}:{args.port}"
    )
    print("Token-gated: enabled")
    print("Press Ctrl+C to stop.")
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        await server.close()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # Non-localhost guard
    if args.host not in {"127.0.0.1", "localhost"}:
        if not args.allow_non_localhost:
            print(
                f"Error: Refusing to bind to non-localhost address '{args.host}'. "
                "Use --allow-non-localhost to override (not recommended).",
                file=__import__("sys").stderr,
            )
            return 1

    try:
        asyncio.run(_run_server(args))
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
