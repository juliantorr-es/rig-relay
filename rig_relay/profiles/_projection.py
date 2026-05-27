"""Y0/Y1/Y4-facing profile projections.

Builds a content-light projection for the desktop cockpit that describes
the current profile resolution state and available profiles.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from rig_relay.profiles.models import (
    HarnessCompatibilityProfile,
    ProfileResolutionResult,
)


def build_profile_projection(
    resolution: ProfileResolutionResult | None,
    available_profiles: Sequence[HarnessCompatibilityProfile],
    build_root: Path | None = None,
) -> dict[str, object]:
    now = datetime.now(UTC).isoformat()

    if resolution is not None:
        current_profile: dict[str, object] | None = {
            "profile_id": resolution.selected_profile.profile_id,
            "display_name": resolution.selected_profile.display_name,
            "evaluation_status": resolution.selected_profile.evaluation_status.value,
            "confidence": resolution.confidence,
            "provider": resolution.provider,
            "model_id": resolution.model_id,
            "task_role": resolution.task_role.value,
            "is_user_override": resolution.is_user_override,
            "context_envelope_strategy": resolution.selected_profile.context_envelope_strategy.value,
            "tool_dialect_strategy": resolution.selected_profile.tool_dialect_strategy.value,
        }
    else:
        current_profile = None

    profiles_list: list[dict[str, object]] = []
    for p in available_profiles:
        profiles_list.append({
            "profile_id": p.profile_id,
            "display_name": p.display_name,
            "description": p.description,
            "supported_roles": [r.value for r in p.supported_roles],
            "evaluation_status": p.evaluation_status.value,
            "provider_families": p.provider_families,
        })

    eval_summary: dict[str, int] = {}
    for p in available_profiles:
        status = p.evaluation_status.value
        eval_summary[status] = eval_summary.get(status, 0) + 1

    warnings: list[str] = []
    if resolution is not None and resolution.warnings:
        warnings = resolution.warnings

    return {
        "schema_version": "rig.relay.profile_resolution_projection.v1",
        "generated_at": now,
        "current_profile": current_profile,
        "available_profile_count": len(available_profiles),
        "profiles": profiles_list,
        "resolution_history": [],
        "evaluation_summary": eval_summary,
        "warnings": warnings,
    }


def merge_profile_projection_into_desktop(
    desktop_projection: dict[str, object], profile_projection: dict[str, object]
) -> dict[str, object]:
    result = dict(desktop_projection)
    result["provider_profiles"] = profile_projection
    return result
