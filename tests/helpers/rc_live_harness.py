"""Live RC golden-path harness helpers.

Starts the real ``rig-relay --server-only`` subprocess with isolated home
state, captures a bounded startup/shutdown log, and exposes WebSocket and
health endpoints for live product-path tests.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time
from typing import Any

import httpx
import websockets

REPO_ROOT = Path(__file__).resolve().parents[2]


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_live_env(home_root: Path, *, telemetry_enabled: bool) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home_root)
    env["RIG_RELAY_HOME"] = str(home_root / ".rig" / "relay")
    env["RIG_RELAY_DISABLE_LEGACY_CONFIG"] = "1"
    env["RIG_TELEMETRY_ENABLED"] = "1" if telemetry_enabled else "0"
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("DEEPSEEK_API_KEY", "mock")
    env.setdefault("MISTRAL_API_KEY", "mock")
    return env


@dataclass(slots=True)
class RCLiveServer:
    repo_root: Path = REPO_ROOT
    home_root: Path = field(
        default_factory=lambda: Path.cwd() / ".build" / "rc-live-home"
    )
    evidence_root: Path = field(
        default_factory=lambda: Path.cwd() / ".build" / "rc-live-evidence"
    )
    telemetry_enabled: bool = True
    mode: str = "fixture"
    ws_port: int = 0

    _process: subprocess.Popen[str] | None = field(init=False, default=None)
    _reader_thread: threading.Thread | None = field(init=False, default=None)
    _startup_ready: threading.Event = field(init=False, default_factory=threading.Event)
    _stdout_lines: list[str] = field(init=False, default_factory=list)
    _stdout_lock: threading.Lock = field(init=False, default_factory=threading.Lock)
    _frontend_url: str = field(init=False, default="")
    _websocket_token: str = field(init=False, default="")
    _startup_duration_ms: int = field(init=False, default=0)
    _startup_log_path: Path = field(init=False)
    _startup_summary_path: Path = field(init=False)
    _shutdown_summary_path: Path = field(init=False)

    def __post_init__(self) -> None:
        if not self.ws_port:
            self.ws_port = find_free_port()
        self.home_root = self.home_root.resolve()
        self.evidence_root = self.evidence_root.resolve()
        self._startup_log_path = self.evidence_root / "server-startup.log"
        self._startup_summary_path = self.evidence_root / "server-startup.json"
        self._shutdown_summary_path = self.evidence_root / "server-shutdown.json"
        self.home_root.mkdir(parents=True, exist_ok=True)
        self.evidence_root.mkdir(parents=True, exist_ok=True)

    @property
    def frontend_url(self) -> str:
        if not self._frontend_url:
            raise RuntimeError("Server has not started yet")
        return self._frontend_url

    @property
    def healthz_url(self) -> str:
        return self.frontend_url.replace("/index.html", "/healthz")

    @property
    def runtime_config_url(self) -> str:
        return self.frontend_url.replace("/index.html", "/runtime-config")

    @property
    def ws_url(self) -> str:
        return self.frontend_url.replace("http://", "ws://").replace(
            "/index.html", "/ws"
        )

    @property
    def startup_log(self) -> Path:
        return self._startup_log_path

    @property
    def startup_summary(self) -> Path:
        return self._startup_summary_path

    @property
    def shutdown_summary(self) -> Path:
        return self._shutdown_summary_path

    def __enter__(self) -> RCLiveServer:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    def start(self) -> None:
        started = time.monotonic()
        cmd = [
            "uv",
            "run",
            "rig-relay",
            "--server-only",
            "--mode",
            self.mode,
            "--ws-port",
            str(self.ws_port),
        ]
        self._process = subprocess.Popen(
            cmd,
            cwd=self.repo_root,
            env=build_live_env(
                self.home_root, telemetry_enabled=self.telemetry_enabled
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self._reader_thread = threading.Thread(
            target=self._drain_stdout, name="rc-live-server-stdout", daemon=True
        )
        self._reader_thread.start()
        try:
            self._wait_for_startup()
            self._startup_duration_ms = int((time.monotonic() - started) * 1000)
            self._write_startup_summary()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if self._process is None:
            return

        proc = self._process
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGINT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=5)
        self._write_shutdown_summary()

    def _drain_stdout(self) -> None:
        if self._process is None or self._process.stdout is None:
            return

        with self._startup_log_path.open("a", encoding="utf-8") as log_file:
            for raw_line in self._process.stdout:
                line = raw_line.rstrip("\n")
                self._append_stdout_line(line)
                log_file.write(self._redact_line(line) + "\n")
                log_file.flush()
                if self._process.poll() is not None and self._startup_ready.is_set():
                    continue

    def _append_stdout_line(self, line: str) -> None:
        with self._stdout_lock:
            self._stdout_lines.append(line)
            if len(self._stdout_lines) > 500:
                self._stdout_lines = self._stdout_lines[-500:]

            if line.startswith("URL: "):
                self._frontend_url = line.split("URL: ", 1)[1].strip()
            elif line.startswith("WebSocket Token: "):
                self._websocket_token = line.split("WebSocket Token: ", 1)[1].strip()

            if self._frontend_url and self._websocket_token:
                self._startup_ready.set()

    def _redact_line(self, line: str) -> str:
        if self._websocket_token:
            return line.replace(self._websocket_token, "[REDACTED]")
        return line

    def _wait_for_startup(self, timeout_s: float = 60.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                self._write_startup_failure("process_exited", timeout_s)
                raise RuntimeError(
                    "RC live server exited before startup completed: "
                    f"returncode={self._process.returncode}"
                )

            if self._startup_ready.wait(timeout=0.1):
                self._wait_for_healthz(timeout_s=max(5.0, deadline - time.monotonic()))
                return

        self._write_startup_failure("startup_timeout", timeout_s)
        raise RuntimeError(
            "RC live server failed to print URL and WebSocket token within timeout"
        )

    def _wait_for_healthz(self, timeout_s: float = 20.0) -> None:
        deadline = time.monotonic() + timeout_s
        last_error: str | None = None
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                self._write_startup_failure("process_exited", timeout_s)
                raise RuntimeError(
                    "RC live server exited before /healthz became ready: "
                    f"returncode={self._process.returncode}"
                )
            try:
                response = httpx.get(self.healthz_url, timeout=2.0)
                body = response.json()
                if response.status_code == 200 and body.get("ok") is True:
                    return
                last_error = f"healthz status={response.status_code} body={body}"
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.2)

        self._write_startup_failure("healthz_timeout", timeout_s, last_error)
        raise RuntimeError(
            "RC live server started but /healthz was not ready within timeout"
        )

    async def websocket_exchange(
        self,
        message: dict[str, Any],
        *,
        expect_type: str | None = None,
        timeout_s: float = 10.0,
    ) -> list[dict[str, Any]]:
        if not self._websocket_token:
            raise RuntimeError("Server has not started yet")

        received: list[dict[str, Any]] = []
        deadline = time.monotonic() + timeout_s

        async with websockets.connect(self.ws_url) as ws:
            await ws.send(json.dumps({"type": "auth", "token": self._websocket_token}))
            auth_reply = json.loads(
                await asyncio.wait_for(
                    ws.recv(), timeout=max(0.5, deadline - time.monotonic())
                )
            )
            received.append(auth_reply)
            if auth_reply.get("type") != "auth_ok":
                raise AssertionError(f"WebSocket auth failed: {auth_reply}")

            await ws.send(json.dumps(message))
            while time.monotonic() < deadline:
                next_reply = json.loads(
                    await asyncio.wait_for(
                        ws.recv(), timeout=max(0.5, deadline - time.monotonic())
                    )
                )
                received.append(next_reply)
                if expect_type is None or next_reply.get("type") == expect_type:
                    return received

        raise TimeoutError(
            f"Timed out waiting for WebSocket message type {expect_type!r}"
        )

    def read_healthz(self) -> dict[str, Any]:
        response = httpx.get(self.healthz_url, timeout=5.0)
        response.raise_for_status()
        return response.json()

    def read_runtime_config(self) -> dict[str, Any]:
        response = httpx.get(self.runtime_config_url, timeout=5.0)
        response.raise_for_status()
        return response.json()

    def _write_startup_summary(self) -> None:
        summary = {
            "schema_version": "rig.relay.rc_live_server_startup.v1",
            "repo_root": str(self.repo_root),
            "home_root": str(self.home_root),
            "frontend_url": self._frontend_url,
            "ws_url": self.ws_url,
            "healthz_url": self.healthz_url,
            "telemetry_enabled": self.telemetry_enabled,
            "startup_duration_ms": self._startup_duration_ms,
            "log_path": str(self._startup_log_path),
            "stdout_tail": self.stdout_tail(),
            "runtime_config": self._runtime_config_snapshot(),
            "healthz": self.read_healthz(),
        }
        self._startup_summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    def _runtime_config_snapshot(self) -> dict[str, Any]:
        try:
            config = self.read_runtime_config()
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

        return {
            "schema_version": config.get("schema_version", ""),
            "frontend_url": config.get("frontend_url", ""),
            "ws_url": config.get("ws_url", ""),
            "bridge_origin": config.get("bridge_origin", ""),
            "bridge_host": config.get("bridge_host", ""),
            "bridge_port": config.get("bridge_port", 0),
            "tls_enabled": config.get("tls_enabled", False),
            "transport_label": config.get("transport_label", ""),
            "handshake_id": config.get("handshake_id", ""),
            "local_mode": config.get("local_mode", False),
            "auth_required": config.get("auth_required", False),
            "token_present": config.get("token_present", False),
            "app_version": config.get("app_version", ""),
        }

    def _write_startup_failure(
        self, reason: str, timeout_s: float, detail: str | None = None
    ) -> None:
        payload = {
            "schema_version": "rig.relay.rc_live_server_startup_error.v1",
            "reason": reason,
            "detail": detail,
            "timeout_s": timeout_s,
            "repo_root": str(self.repo_root),
            "home_root": str(self.home_root),
            "frontend_url": self._frontend_url,
            "ws_url": self.ws_url if self._frontend_url else "",
            "stdout_tail": self.stdout_tail(),
            "process_returncode": self._process.returncode if self._process else None,
        }
        self._startup_summary_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    def _write_shutdown_summary(self) -> None:
        returncode = self._process.returncode if self._process else None
        payload = {
            "schema_version": "rig.relay.rc_live_server_shutdown.v1",
            "repo_root": str(self.repo_root),
            "home_root": str(self.home_root),
            "frontend_url": self._frontend_url,
            "ws_port": self.ws_port,
            "process_returncode": returncode,
            "clean_exit": returncode in {0, 130},
            "port_processes_remaining": self._matching_port_processes(),
            "stdout_tail": self.stdout_tail(),
        }
        self._shutdown_summary_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    def _matching_port_processes(self) -> list[str]:
        try:
            result = subprocess.run(
                ["ps", "-ax", "-o", "command="],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            return []

        needle = f"--ws-port {self.ws_port}"
        return [
            line.strip()
            for line in result.stdout.splitlines()
            if needle in line and "rig-relay" in line
        ]

    def stdout_tail(self, limit: int = 30) -> list[str]:
        with self._stdout_lock:
            return list(self._stdout_lines[-limit:])
