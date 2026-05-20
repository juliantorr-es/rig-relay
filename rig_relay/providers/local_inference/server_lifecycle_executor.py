"""Server lifecycle executor — start, stop, and health probe for local inference runtimes.

Content-light: never records raw output, env vars, or secrets.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import os
import secrets
import signal
import socket
import subprocess
import time

import httpx

from rig_relay.providers.local_inference.backend_registry import get_backend
from rig_relay.providers.local_inference.models import (
    RuntimeBackend,
    ServerLifecycleReceipt,
)

_HTTP_OK = 200
_LOCALHOST_SET = {"127.0.0.1", "localhost"}


def _new_lifecycle_id() -> str:
    return f"slc_{secrets.token_hex(8)}"


def _check_port_free(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return False
    except (TimeoutError, ConnectionRefusedError, OSError):
        return True


def start_server(
    *,
    backend_id: str,
    host: str = "127.0.0.1",
    port: int = 0,
    model_path: str = "",
    model_id: str = "",
    execute: bool = False,
    timeout_sec: int = 30,
    now: str | None = None,
) -> ServerLifecycleReceipt:
    receipt = ServerLifecycleReceipt(
        lifecycle_id=_new_lifecycle_id(),
        generated_at=now or datetime.now(UTC).isoformat(),
        backend_id=backend_id,
        host=host,
        port=port,
        timeout_sec=timeout_sec,
        lifecycle_action="plan",
    )

    if host not in _LOCALHOST_SET:
        receipt.blocked_reasons.append("host_not_localhost")
        receipt.remote_network_exposed = True
        receipt.localhost_only = False
        return receipt

    backend = get_backend(backend_id)
    if backend is None:
        receipt.blocked_reasons.append(f"unknown_backend:{backend_id}")
        return receipt

    port = port or backend.default_port
    receipt.port = port

    template = backend.start_command_template
    if not template:
        receipt.blocked_reasons.append("no_start_command_template")
        return receipt

    command = template.format(
        host=host, port=port, model_path=model_path, model_id=model_id
    )
    receipt.command_hash = hashlib.sha256(command.encode("utf-8")).hexdigest()
    receipt.command_safe_preview = command

    if not execute:
        receipt.blocked_reasons.append("execute_flag_not_set")
        return receipt

    return _execute_start(receipt, backend, command, host, port, timeout_sec)


def _execute_start(
    receipt: ServerLifecycleReceipt,
    backend: RuntimeBackend,
    command: str,
    host: str,
    port: int,
    timeout_sec: int,
) -> ServerLifecycleReceipt:
    if not backend.auto_start_allowed_default:
        receipt.blocked_reasons.append("auto_start_not_allowed")
        return receipt

    if not _check_port_free(host, port):
        receipt.port_collision_detected = True
        receipt.blocked_reasons.append(f"port_occupied:{host}:{port}")
        receipt.lifecycle_action = "start_blocked"
        return receipt

    receipt.lifecycle_action = "start"
    try:
        proc = subprocess.Popen(
            command.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        receipt.blocked_reasons.append(
            f"executable_not_found:{backend.executable_name}"
        )
        receipt.lifecycle_action = "start_failed"
        return receipt
    except Exception as exc:
        receipt.blocked_reasons.append(f"start_error:{exc!s}")
        receipt.lifecycle_action = "start_failed"
        return receipt

    receipt.pid = proc.pid
    receipt.started_by_rig = True

    health_url = f"http://{host}:{port}{backend.health_endpoint}"
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        time.sleep(2)
        try:
            with httpx.Client(timeout=httpx.Timeout(3.0)) as client:
                resp = client.get(health_url)
                if resp.status_code == _HTTP_OK:
                    receipt.health_status = "ok"
                    return receipt
        except Exception:
            continue

    receipt.health_status = "unhealthy"
    return receipt


def stop_server(
    backend_id: str,
    *,
    port: int = 0,
    pid: int = 0,
    execute: bool = False,
    now: str | None = None,
) -> ServerLifecycleReceipt:
    receipt = ServerLifecycleReceipt(
        lifecycle_id=_new_lifecycle_id(),
        generated_at=now or datetime.now(UTC).isoformat(),
        backend_id=backend_id,
        port=port,
        pid=pid,
        lifecycle_action="stop",
    )

    if not execute:
        receipt.blocked_reasons.append("execute_flag_not_set")
        receipt.lifecycle_action = "plan"
        return receipt

    target_pid = pid
    if target_pid == 0 and port != 0:
        target_pid = _find_pid_on_port(port)
        if target_pid == 0:
            receipt.blocked_reasons.append(f"no_process_on_port:{port}")
            receipt.health_status = "stopped"
            receipt.stopped_by_rig = True
            return receipt

    if target_pid == 0:
        receipt.blocked_reasons.append("no_pid_or_port_provided")
        return receipt

    _kill_process(target_pid)
    receipt.stopped_by_rig = True
    receipt.health_status = "stopped"
    return receipt


def _find_pid_on_port(port: int) -> int:
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split("\n")[0])
    except Exception:
        pass
    return 0


def _kill_process(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(5)
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    except OSError:
        pass


def probe_server_health(
    endpoint_url: str, port: int, *, timeout_sec: float = 5.0, now: str | None = None
) -> ServerLifecycleReceipt:
    receipt = ServerLifecycleReceipt(
        lifecycle_id=_new_lifecycle_id(),
        generated_at=now or datetime.now(UTC).isoformat(),
        backend_id="health_probe",
        port=port,
        lifecycle_action="health_probe",
    )

    try:
        with httpx.Client(timeout=httpx.Timeout(timeout_sec)) as client:
            resp = client.get(f"{endpoint_url.rstrip('/')}/health")
            receipt.health_status = (
                "ok" if resp.status_code == _HTTP_OK else "unhealthy"
            )
    except Exception:
        receipt.health_status = "unreachable"

    return receipt


__all__ = ["probe_server_health", "start_server", "stop_server"]
