"""Bridge server test helper — starts the real DesktopBridgeServer on an ephemeral
port for integration tests. Does not launch pywebview.

Usage:
    from tests.helpers.bridge_runner import BridgeRunner

    async with BridgeRunner() as bridge:
        # bridge.frontend_url → http://127.0.0.1:<port>/index.html
        # bridge.ws_url → ws://127.0.0.1:<port>/ws
        # bridge.handshake_id → the runtime config handshake_id
        # bridge.trace_store → InMemoryTraceStore for assertions
        # await bridge.wait_for_event("desktop.bridge.server_bound", timeout=5)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from typing import Any

from rig_relay.desktop.bridge_server import DesktopBridgeConfig, DesktopBridgeServer
from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.store import InMemoryTraceStore

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend" / "desktop"


class BridgeRunner:
    """Starts the real bridge server on an ephemeral port in a background thread.

    Provides synchronous access to bridge state for test assertions.
    """

    def __init__(self, *, auth_token: str = "integration-test-token-32chars-x") -> None:
        self._config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=FRONTEND_DIR,
            auth_token=auth_token,
            ssl_context=None,
        )
        self._trace_store = InMemoryTraceStore()
        self._trace_recorder = TraceRecorder(self._trace_store)
        self._bridge = DesktopBridgeServer(self._config)
        self._bridge._trace_recorder = self._trace_recorder
        self._bridge._golden_trace_id = ""
        self._bridge._golden_handshake_id = ""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._error: Exception | None = None

    @property
    def frontend_url(self) -> str:
        return self._bridge.runtime_config.frontend_url

    @property
    def ws_url(self) -> str:
        return self._bridge.runtime_config.ws_url

    @property
    def handshake_id(self) -> str:
        return self._bridge.runtime_config.handshake_id

    @property
    def trace_store(self) -> InMemoryTraceStore:
        return self._trace_store

    @property
    def port(self) -> int:
        return self._bridge.bound_port

    def start(self) -> None:
        def _run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._bridge.start())
                self._started.set()
                self._loop.run_forever()
            except Exception as exc:
                self._error = exc
                self._started.set()
            finally:
                try:
                    self._loop.run_until_complete(self._bridge.stop())
                except Exception:
                    pass
                self._loop.close()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        if not self._started.wait(timeout=10):
            raise RuntimeError("Bridge failed to start within timeout")
        if self._error is not None:
            raise self._error

    def stop(self) -> None:
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)

    def get_events(self) -> list[dict[str, Any]]:
        return list(self._trace_store.events)

    def get_event_names(self) -> list[str]:
        return [
            str(e.get("event_type") or e.get("name", "")) for e in self._trace_store.events
        ]

    def __enter__(self) -> BridgeRunner:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
