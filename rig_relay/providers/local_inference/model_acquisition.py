"""Model acquisition planner — governed, blocked by default.

Produces ModelAcquisitionPlan receipts. Never downloads models without
explicit approval. Default: blocked/plan-only.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import secrets

from rig_relay.providers.local_inference.models import ModelAcquisitionPlan


def _new_plan_id() -> str:
    return f"map_{secrets.token_hex(8)}"


def plan_model_download(
    *,
    backend_id: str,
    model_id: str,
    approval: bool = False,
    dry_run: bool = True,
    now: str | None = None,
) -> ModelAcquisitionPlan:
    plan = ModelAcquisitionPlan(
        plan_id=_new_plan_id(),
        generated_at=now or datetime.now(UTC).isoformat(),
        backend_id=backend_id,
        model_id=model_id,
        model_id_hash=hashlib.sha256(model_id.encode("utf-8")).hexdigest(),
        source="registry",
        approval_required=True,
    )

    if not approval:
        plan.blocked_reasons.append("approval_required")
        plan.approval_status = "blocked"
        return plan

    if dry_run:
        plan.approval_status = "plan_only"
        plan.live_download_enabled = False
        plan.download_executed = False
        plan.blocked_reasons.append("dry_run_enabled")
        return plan

    plan.approval_status = "approved"
    plan.live_download_enabled = True
    return plan


def compute_command_hash(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


__all__ = ["compute_command_hash", "plan_model_download"]
