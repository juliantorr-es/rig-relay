"""Server lifecycle supervisor — planning + receipts.

Produces ServerLifecycleReceipt for plan/start/health/stop actions.
Never starts real servers without explicit approval. Default: plan-only.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import secrets

from rig_relay.providers.local_inference.models import (
    RuntimeBackend,
    ServerLifecycleReceipt,
)


def _new_lifecycle_id() -> str:
    return f"slc_{secrets.token_hex(8)}"


def plan_server_start(
    *,
    backend: RuntimeBackend,
    model_id_hash: str = "",
    host: str = "127.0.0.1",
    port: int = 0,
    approval: bool = False,
    now: str | None = None,
) -> ServerLifecycleReceipt:
    port = port or backend.default_port
    command = backend.start_command_template.format(
        model_path="/path/to/model", model_id="example-model", host=host, port=port
    )
    receipt = ServerLifecycleReceipt(
        lifecycle_id=_new_lifecycle_id(),
        generated_at=now or datetime.now(UTC).isoformat(),
        backend_id=backend.backend_id,
        model_id_hash=model_id_hash,
        command_hash=hashlib.sha256(command.encode("utf-8")).hexdigest(),
        command_safe_preview=command,
        host=host,
        port=port,
        cwd_policy="temp_dir",
        env_policy="scrubbed",
        localhost_only=host == "127.0.0.1",
        lifecycle_action="plan",
        health_status="unknown",
    )

    if host != "127.0.0.1" and host != "localhost":
        receipt.blocked_reasons.append("host_not_localhost")
        receipt.remote_network_exposed = True

    if not backend.auto_start_allowed_default and not approval:
        receipt.blocked_reasons.append("auto_start_not_allowed")
        return receipt

    if port < 1024:
        receipt.blocked_reasons.append("privileged_port_blocked")

    return receipt


def build_server_health_result(
    *, backend_id: str, port: int, reachable: bool, now: str | None = None
) -> ServerLifecycleReceipt:
    return ServerLifecycleReceipt(
        lifecycle_id=_new_lifecycle_id(),
        generated_at=now or datetime.now(UTC).isoformat(),
        backend_id=backend_id,
        port=port,
        lifecycle_action="health_probe",
        health_status="ok" if reachable else "unhealthy",
    )


def build_stop_receipt(
    *, backend_id: str, was_running: bool, now: str | None = None
) -> ServerLifecycleReceipt:
    return ServerLifecycleReceipt(
        lifecycle_id=_new_lifecycle_id(),
        generated_at=now or datetime.now(UTC).isoformat(),
        backend_id=backend_id,
        lifecycle_action="stop",
        stopped_by_rig=True,
        health_status="stopped",
        started_by_rig=False,
    )


__all__ = ["build_server_health_result", "build_stop_receipt", "plan_server_start"]
