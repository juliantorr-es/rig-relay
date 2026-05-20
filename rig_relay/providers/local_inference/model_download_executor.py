"""Model download executor — subprocess-based ollama pull (dry-run safe).

Produces ModelAcquisitionPlan receipts. Only executes with explicit approval.
Content-light: never stores raw model data, credentials, or secrets.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import secrets
import subprocess

from rig_relay.providers.local_inference.backend_registry import get_backend
from rig_relay.providers.local_inference.models import ModelAcquisitionPlan


def execute_model_download(
    *,
    backend_id: str,
    model_id: str,
    execute: bool = False,
    timeout_sec: int = 600,
    now: str | None = None,
) -> ModelAcquisitionPlan:
    plan = ModelAcquisitionPlan(
        plan_id=f"map_{secrets.token_hex(8)}",
        generated_at=now or datetime.now(UTC).isoformat(),
        backend_id=backend_id,
        model_id=model_id,
        model_id_hash=hashlib.sha256(model_id.encode("utf-8")).hexdigest(),
        source="registry",
        approval_required=True,
    )

    backend = get_backend(backend_id)
    if backend is None:
        plan.blocked_reasons.append(f"unknown_backend:{backend_id}")
        plan.approval_status = "blocked"
        return plan

    template = backend.pull_command_template
    if not template:
        plan.blocked_reasons.append("no_pull_command_template")
        plan.approval_status = "blocked"
        return plan

    command = template.format(model_id=model_id, backend_id=backend_id)
    plan.command_hash = hashlib.sha256(command.encode("utf-8")).hexdigest()
    plan.command_safe_preview = command

    if not backend.enabled_default and not execute:
        plan.blocked_reasons.append("backend_not_enabled")
        plan.approval_status = "blocked"
        return plan

    if not execute:
        plan.approval_status = "plan_only"
        plan.live_download_enabled = False
        plan.download_executed = False
        plan.blocked_reasons.append("execute_flag_not_set")
        return plan

    plan.approval_status = "approved"
    plan.live_download_enabled = True
    plan.network_required = True
    plan.disk_required_unknown = True

    try:
        result = subprocess.run(
            command.split(), capture_output=True, text=True, timeout=timeout_sec
        )
        plan.download_executed = True
        if result.returncode != 0:
            plan.blocked_reasons.append(f"download_failed:rc={result.returncode}")
            plan.approval_status = "failed"
        else:
            plan.approval_status = "completed"
            plan.download_executed = True
    except subprocess.TimeoutExpired:
        plan.blocked_reasons.append("download_timeout")
        plan.approval_status = "failed"
    except FileNotFoundError:
        plan.blocked_reasons.append(f"executable_not_found:{backend.executable_name}")
        plan.approval_status = "failed"
    except Exception as exc:
        plan.blocked_reasons.append(f"download_error:{exc!s}")
        plan.approval_status = "failed"

    return plan


__all__ = ["execute_model_download"]
