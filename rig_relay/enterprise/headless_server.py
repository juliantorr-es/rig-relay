from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import os
import signal
import subprocess
from threading import Thread
from typing import Any


@dataclass(slots=True)
class HeadlessServerConfig:
    host: str = "127.0.0.1"
    port: int = 9100
    tenant_id: str | None = None
    server_only: bool = True
    enable_health_endpoint: bool = True
    health_endpoint_port: int = 9101


@dataclass(slots=True)
class _HealthSnapshot:
    status: str
    tenant_id: str | None
    bridge_health: str
    active_strands: int
    event_count: int
    uptime_seconds: str
    generated_at: str


@dataclass(slots=True)
class HeadlessServer:
    _config: HeadlessServerConfig = field(default_factory=HeadlessServerConfig)
    _process: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    _health_snapshot: _HealthSnapshot | None = field(default=None, repr=False)
    _started_at: str = ""
    _stopped: bool = False
    _health_thread: Thread | None = field(default=None, repr=False)

    @property
    def config(self) -> HeadlessServerConfig:
        return self._config

    def start(self, config: HeadlessServerConfig | None = None) -> None:
        if config is not None:
            self._config = config
        self._started_at = datetime.now(UTC).isoformat()
        self._stopped = False
        self._health_snapshot = _HealthSnapshot(
            status="starting",
            tenant_id=self._config.tenant_id,
            bridge_health="starting",
            active_strands=0,
            event_count=0,
            uptime_seconds="0s",
            generated_at=self._started_at,
        )
        cmd = ["uv", "run", "rig-relay", "--server-only"]
        if self._config.tenant_id:
            cmd.extend(["--tenant-id", self._config.tenant_id])
        cmd.extend(["--ws-port", str(self._config.port)])
        self._process = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if self._config.enable_health_endpoint:
            self._health_thread = Thread(target=self._run_health_endpoint, daemon=True)
            self._health_thread.start()

    def stop(self) -> None:
        self._stopped = True
        if self._process is not None and self._process.pid is not None:
            try:
                os.kill(self._process.pid, signal.SIGTERM)
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.kill(self._process.pid, signal.SIGKILL)
                    self._process.wait(timeout=2)
            except (ProcessLookupError, OSError):
                pass
        self._process = None

    def health(self) -> dict[str, Any]:
        if self._health_snapshot is None:
            now = datetime.now(UTC).isoformat()
            return {
                "status": "stopped",
                "tenant_id": self._config.tenant_id,
                "bridge_health": "stopped",
                "active_strands": 0,
                "event_count": 0,
                "uptime_seconds": "0s",
                "generated_at": now,
            }
        snapshot = self._health_snapshot
        running = (
            self._process is not None
            and self._process.poll() is None
            and not self._stopped
        )
        uptime = "0s"
        if self._started_at:
            try:
                started = datetime.fromisoformat(self._started_at)
                delta = (datetime.now(UTC) - started).total_seconds()
                uptime = f"{int(delta)}s"
            except (ValueError, TypeError):
                pass
        return {
            "status": snapshot.status if running else "stopped",
            "tenant_id": snapshot.tenant_id,
            "bridge_health": snapshot.bridge_health if running else "stopped",
            "active_strands": snapshot.active_strands,
            "event_count": snapshot.event_count,
            "uptime_seconds": uptime,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    def _run_health_endpoint(self) -> None:
        import http.server

        config = self._config

        class HealthHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path != "/health":
                    self.send_response(404)
                    self.end_headers()
                    return
                data = HeadlessServer.__self_health()  # type: ignore[attr-defined]
                payload = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        server = http.server.HTTPServer(
            (config.host, config.health_endpoint_port), HealthHandler
        )
        HealthHandler.__self_health = self.health  # type: ignore[attr-defined]
        try:
            while not self._stopped:
                server.handle_request()
        except Exception:
            pass
        finally:
            server.server_close()


__all__ = ["HeadlessServer", "HeadlessServerConfig"]
