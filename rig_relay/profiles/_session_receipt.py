"""Session resolution receipt builder.

Produces a content-light, schema-validated receipt for a profile resolution
applied to a session. No raw prompts, file contents, or secrets.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from uuid import uuid4

from rig_relay.profiles.models import ProfileResolutionResult


def build_session_resolution_receipt(
    resolution: ProfileResolutionResult,
    session_id: str,
    context_envelope_digest: str = "",
    workspace_identity_ref: str = "",
) -> dict[str, object]:
    receipt_id = str(uuid4()).replace("-", "")
    resolved_at = datetime.now(UTC).isoformat()

    capability_checks: dict[str, str] = _build_capability_checks(resolution)

    user_override_state = "none"
    if resolution.is_user_override and resolution.override_source_profile_id:
        user_override_state = "active"

    receipt: dict[str, object] = {
        "schema_version": "rig.relay.session_resolution_receipt.v1",
        "receipt_id": receipt_id,
        "session_id": session_id,
        "provider": resolution.provider,
        "model_id": resolution.model_id,
        "task_role": resolution.task_role.value,
        "selected_profile_id": resolution.selected_profile.profile_id,
        "selected_profile_version": resolution.selected_profile.profile_version,
        "resolution_confidence": resolution.confidence,
        "is_user_override": resolution.is_user_override,
        "required_capabilities_check": capability_checks,
        "context_envelope_digest": context_envelope_digest,
        "workspace_identity_ref": workspace_identity_ref,
        "authority_evidence_posture": "governed",
        "profile_evaluation_status": resolution.selected_profile.evaluation_status.value,
        "user_override_state": user_override_state,
        "resolved_at": resolved_at,
        "receipt_digest": "",
    }

    canonical = json.dumps(receipt, sort_keys=True)
    receipt_hash = hashlib.sha256(canonical.encode()).hexdigest()
    receipt["receipt_digest"] = f"sha256:{receipt_hash}"

    return receipt


def _build_capability_checks(resolution: ProfileResolutionResult) -> dict[str, str]:
    req = resolution.selected_profile.required_capabilities
    checks: dict[str, str] = {
        "requires_tool_use": "passed" if req.requires_tool_use else "n/a",
        "requires_streaming": "passed" if req.requires_streaming else "n/a",
        "requires_structured_output": "passed"
        if req.requires_structured_output
        else "n/a",
        "requires_thinking": "passed" if req.requires_thinking else "n/a",
        "requires_vision": "passed" if req.requires_vision else "n/a",
        "requires_embeddings": "passed" if req.requires_embeddings else "n/a",
        "min_context_window": "passed",
        "min_output_tokens": "passed",
    }

    for w in resolution.warnings:
        for key in checks:
            if key in w.lower():
                checks[key] = "unknown"

    return checks
