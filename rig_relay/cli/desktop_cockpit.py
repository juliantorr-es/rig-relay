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
from typing import Any

from rig_relay.desktop.chat_agent_adapter import ChatAgentAdapter
from rig_relay.desktop.chat_state import ChatMessage, ChatRole
from rig_relay.desktop.chat_store import ChatStore
from rig_relay.desktop.projection import build_projection
from rig_relay.desktop.websocket_server import (
    DEFAULT_PORT as DEFAULT_WS_PORT,
    ProjectionWebSocketServer,
)
from rig_relay import __version__
from rig_relay.core.agent_loop import AgentLoop
from rig_relay.core.config import VibeConfig
from rig_relay.core.config.harness_files import init_harness_files_manager
from rig_relay.core.hooks.config import load_hooks_from_fs
from rig_relay.core.logger import logger
from rig_relay.core.telemetry.build_metadata import build_entrypoint_metadata

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"
FRONTEND_DIR = REPO_ROOT / "frontend" / "desktop"

MAX_MESSAGE_LENGTH = 4000


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


def _run_ws_server(
    build_root: Path,
    host: str,
    port: int,
    token: str,
    chat_state_provider: Any | None = None,
    loop_holder: list[asyncio.AbstractEventLoop] | None = None,
    server_holder: list[ProjectionWebSocketServer] | None = None,
) -> None:
    """Run the WebSocket projection stream in a background thread."""

    async def _start() -> None:
        loop = asyncio.get_running_loop()
        if loop_holder is not None:
            loop_holder[0] = loop

        server = ProjectionWebSocketServer(
            build_root=build_root,
            host=host,
            port=port,
            token=token,
            chat_state_provider=chat_state_provider,
        )
        if server_holder is not None:
            server_holder[0] = server

        await server.start()
        print(f"WebSocket projection stream on ws://{host}:{port}")
        print(f"Auth Token: {token}")
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


class CockpitAPI:
    """Read-only API exposed to JS bridge (fallback transport)."""

    def __init__(
        self,
        ws_token: str | None = None,
        ws_port: int | None = None,
        loop_holder: list[asyncio.AbstractEventLoop] | None = None,
        server_holder: list[ProjectionWebSocketServer] | None = None,
        mode: str = "runtime",
    ) -> None:
        self._store = ChatStore(chat_root=BUILD_ROOT / "desktop" / "chat")
        self._chat_state = self._store.load_state()
        self._ws_token = ws_token
        self._ws_port = ws_port
        self._loop_holder = loop_holder
        self._server_holder = server_holder
        self._mode = mode

        if mode == "fixture":
            self._agent_loop = None
            self._adapter = None  # type: ignore
        else:
            # Initialize AgentLoop
            config = VibeConfig.load()
            hook_config_result = load_hooks_from_fs(config)
            entrypoint_metadata = build_entrypoint_metadata(
                agent_entrypoint="desktop",
                agent_version=__version__,
                client_name="rig_relay_desktop",
                client_version=__version__,
            )
            self._agent_loop = AgentLoop(
                config,
                agent_name=config.default_agent,
                enable_streaming=True,
                entrypoint_metadata=entrypoint_metadata,
                defer_heavy_init=True,
                hook_config_result=hook_config_result,
            )
            self._adapter = ChatAgentAdapter(
                agent_loop=self._agent_loop,
                store=self._store,
                on_update=self._notify_update,
            )

        # Log startup event
        self._store.append_event(
            "chat.backend.ready",
            note="CockpitAPI initialized with AgentLoop",
            backend_wired=True,
        )

        # Update state to reflect backend status
        self._chat_state.backend_wired = True
        self._store.save_state(self._chat_state)

    def _notify_update(self) -> None:
        """Trigger a WebSocket broadcast of the chat state update."""
        lh = self._loop_holder
        sh = self._server_holder
        if (
            lh is not None
            and lh[0] is not None
            and sh is not None
            and sh[0] is not None
        ):
            lh[0].call_soon_threadsafe(
                lambda: asyncio.create_task(sh[0].broadcast_chat_state_updated())
            )

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
            "token": self._ws_token or "",
            "host": "127.0.0.1",
            "port": self._ws_port or DEFAULT_WS_PORT,
        }

    def get_chat_state(self) -> dict:
        return self._chat_state.model_dump(mode="json")

    def send_chat_message(
        self, text: str, client_message_id: str | None = None
    ) -> dict:
        if not text.strip():
            return {"error": "Empty message refused"}

        # Max length enforced
        if len(text) > MAX_MESSAGE_LENGTH:
            return {"error": "Message too long"}

        # Refuse if another response is active
        if self._adapter is not None and self._adapter.is_running:
            return {"error": "another_response_active"}

        # Idempotency check for client_message_id
        if client_message_id:
            for msg in self._chat_state.messages:
                if msg.metadata.get("client_message_id") == client_message_id:
                    return self.get_chat_state()

        # Generate a message ID if not provided
        msg_id = client_message_id or f"msg_{secrets.token_hex(8)}"

        # Immediate feedback: append user message synchronously
        user_msg = ChatMessage(
            role=ChatRole.USER,
            content=text,
            metadata={"client_message_id": client_message_id}
            if client_message_id
            else {"msg_id": msg_id},
        )
        self._chat_state.messages.append(user_msg)
        self._store.append_event("chat.message.created", message=user_msg)
        self._store.save_state(self._chat_state)

        # Schedule processing on the background loop (thread-safe)
        lh = self._loop_holder
        if lh is not None and lh[0] is not None and self._adapter is not None:
            asyncio.run_coroutine_threadsafe(
                self._adapter.process_message(text, msg_id), lh[0]
            )
        else:
            # If no loop, we just keep the user message but no assistant will respond
            logger.warning("No background loop for agent response")

        return self.get_chat_state()

    def clear_chat(self) -> dict:
        """JS-facing alias for clear_chat_view."""
        return self.clear_chat_view()

    def clear_chat_view(self) -> dict:
        self._chat_state.messages = []
        self._store.save_state(self._chat_state)
        self._store.append_event("chat.view.cleared")
        self._notify_update()
        return self.get_chat_state()

    def cancel_chat_response(self) -> dict:
        if self._adapter is None or not self._adapter.is_running:
            return {"error": "no_active_response"}

        if self._adapter.cancel():
            self._store.append_event("chat.response.cancelled")
            self._notify_update()
            return self.get_chat_state()

        return {"error": "cancel_failed"}

    def execute_intent(self, intent_request_json: str) -> dict:
        """JS-facing entry point for governed intents."""
        try:
            req = json.loads(intent_request_json)
        except json.JSONDecodeError:
            return {"error": "invalid_json"}
        return self.run_desktop_intent(req)

    def run_desktop_intent(self, intent_request: dict) -> dict:
        """Execute a governed desktop intent (read-only/dry-run only).

        Args:
            intent_request: Dict matching desktop_intent_request schema.

        Returns:
            Content-light intent result dict.
        """
        from rig_relay.desktop.intents import execute_desktop_intent

        return execute_desktop_intent(
            request=intent_request, chat_state_provider=self.get_chat_state
        )

    def mint_authorization_receipt_dev(
        self, action: str, ttl_seconds: int = 300, reason: str = ""
    ) -> dict:
        from rig_relay.desktop.authorization_receipts import mint_dev_receipt

        return mint_dev_receipt(action, ttl_seconds=ttl_seconds, reason=reason)

    def mint_authorization_receipt_local(
        self, action: str, ttl_seconds: int = 300, reason: str = ""
    ) -> dict:
        from rig_relay.desktop.authorization_receipts import mint_local_auth_receipt

        return mint_local_auth_receipt(action, ttl_seconds=ttl_seconds, reason=reason)

    def inspect_authorization_receipt(self, authorization_receipt: dict) -> dict:
        from rig_relay.desktop.authorization_receipts import inspect_receipt

        return inspect_receipt(authorization_receipt)


def _open_window(ws_port: int | None, mode: str = "runtime", server_only: bool = False) -> None:
    """Open pywebview window with optional WebSocket stream."""
    import time

    index_path = FRONTEND_DIR / "index.html"
    if not index_path.is_file():
        print(f"Frontend not found at {index_path}")
        return

    ws_token: str | None = None
    if ws_port is not None:
        ws_token = _generate_ws_token()

    loop_holder: list[asyncio.AbstractEventLoop] = [None]  # type: ignore[list-item]
    server_holder: list[ProjectionWebSocketServer] = [None]  # type: ignore[list-item]

    api = CockpitAPI(
        ws_token=ws_token,
        ws_port=ws_port,
        loop_holder=loop_holder,
        server_holder=server_holder,
        mode=mode,
    )

    if ws_port is not None:
        ws_thread = threading.Thread(
            target=_run_ws_server,
            args=(
                BUILD_ROOT,
                "127.0.0.1",
                ws_port,
                ws_token,
                api.get_chat_state,
                loop_holder,
                server_holder,
            ),
            daemon=True,
        )
        ws_thread.start()
        # Give the server a moment to start
        time.sleep(0.5)

    if server_only:
        print("Server-only mode. WebSocket is running.")
        print(f"URL: file://{index_path}")
        print(f"WebSocket Token: {ws_token}")
        print("Press Ctrl+C to exit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Exiting...")
            return

    try:
        import webview  # type: ignore[import-untyped]
    except ImportError:
        print("pywebview not available. Install with: uv add pywebview")
        print("Running dry-run instead...")
        _dry_run(ws_port or DEFAULT_WS_PORT)
        return
    if not hasattr(webview, "__version__"):  # type: ignore[reportAttributeAccessIssue]
        webview.__version__ = "6.2.1"  # type: ignore[reportAttributeAccessIssue]

    index_path = FRONTEND_DIR / "index.html"
    if not index_path.is_file():
        print(f"Frontend not found at {index_path}")
        return

    ws_token: str | None = None
    if ws_port is not None:
        ws_token = _generate_ws_token()

    loop_holder: list[asyncio.AbstractEventLoop] = [None]  # type: ignore[list-item]
    server_holder: list[ProjectionWebSocketServer] = [None]  # type: ignore[list-item]

    api = CockpitAPI(
        ws_token=ws_token,
        ws_port=ws_port,
        loop_holder=loop_holder,
        server_holder=server_holder,
        mode=mode,
    )

    if ws_port is not None:
        ws_thread = threading.Thread(
            target=_run_ws_server,
            args=(
                BUILD_ROOT,
                "127.0.0.1",
                ws_port,
                ws_token,
                api.get_chat_state,
                loop_holder,
                server_holder,
            ),
            daemon=True,
        )
        ws_thread.start()
        # Give the server a moment to start
        time.sleep(0.5)

    if server_only:
        print("Server-only mode. WebSocket is running.")
        print(f"URL: file://{index_path}")
        print(f"WebSocket Token: {ws_token}")
        print("Press Ctrl+C to exit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Exiting...")
            return

    webview.create_window(
        title="Rig Relay Cockpit",
        url=str(index_path),
        js_api=api,
        width=1200,
        height=800,
        resizable=True,
        min_size=(800, 600),
    )
    webview.start(gui='cocoa')


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rig Relay Desktop Cockpit — Read-Only Shell"
    )
    parser.add_argument(
        "--mode",
        choices=["runtime", "fixture"],
        default="runtime",
        help="Run in runtime mode (real agents) or fixture mode (sample data).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print projection, exit without opening a window.",
    )
    parser.add_argument(
        "--server-only",
        action="store_true",
        help="Start the WebSocket server and print the URL, but don't open a window.",
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
    init_harness_files_manager("user", "project")

    ws_port: int | None = None if args.no_ws else args.ws_port

    if args.dry_run:
        _dry_run(ws_port or DEFAULT_WS_PORT)
        return 0

    _open_window(ws_port, mode=args.mode, server_only=args.server_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
