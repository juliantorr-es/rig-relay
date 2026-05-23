"""Telemetry mode feature gates for Rig Relay.

Separates local operational telemetry (required for governed mode) from
remote beta data sharing (optional, gates advanced orchestration during beta).

Three operation modes:
- basic_local: no remote sharing, no advanced orchestration, local safety only
- governed_local: local telemetry enabled, remote sharing disabled
- beta_orchestration: remote sharing enabled, advanced features available

Feature gates:
- Features requiring local operational telemetry: governed mode, fleet,
  checkpoint, coordination leases, current_state, queue planning, replay/debug,
  autonomous spawn execution, local derived datasets
- Features requiring remote beta sharing (during beta): Drive upload,
  maintainer-assisted debugging, shared benchmark contribution,
  cross-user aggregate reports
"""

from __future__ import annotations

from typing import Any

# ── Feature identifiers ──────────────────────────────────────────────────

DISABLED_FEATURES_LOCAL_OFF: tuple[str, ...] = (
    "governed_mode",
    "delegate_fleet",
    "checkpoint_commits",
    "coordination_leases",
    "current_state",
    "queue_planning",
    "replay_debug",
    "autonomous_spawn_execution",
    "local_derived_datasets",
)

DISABLED_FEATURES_REMOTE_OFF: tuple[str, ...] = (
    "remote_upload",
    "maintainer_debugging",
    "shared_benchmarks",
    "cross_user_reports",
)

ALLOWED_SHARE_LEVELS_FOR_UPLOAD: tuple[str, ...] = (
    "derived_only",
    "evidence_hashes",
    "debug_opt_in",
)


def disabled_features_for_settings(settings: dict[str, Any]) -> list[str]:
    """Compute the list of disabled features based on telemetry settings.

    Args:
        settings: Telemetry settings dict matching telemetry_settings.v1 schema.

    Returns:
        List of feature identifiers that are disabled.
    """
    disabled: list[str] = []

    local_op = settings.get("local_operational_enabled", True)
    remote_sharing = settings.get("remote_beta_sharing_enabled", False)
    share_level = settings.get("share_level", "off")
    mode = settings.get("mode", "basic_local")

    # If local operational telemetry is disabled, disable all governed features
    if not local_op:
        disabled.extend(DISABLED_FEATURES_LOCAL_OFF)
        # Also disable remote features since governed base is missing
        disabled.extend(DISABLED_FEATURES_REMOTE_OFF)
        return disabled

    # If remote beta sharing is disabled, disable remote/cloud features
    if not remote_sharing:
        disabled.extend(DISABLED_FEATURES_REMOTE_OFF)

    # If share_level is off, disable upload even if remote_sharing is on
    if share_level in {"off", "debug_local_only"}:
        if "remote_upload" not in disabled:
            disabled.append("remote_upload")

    # Mode-based gates
    if mode == "basic_local":
        # Basic local mode disables all advanced features
        for f in DISABLED_FEATURES_LOCAL_OFF:
            if f not in disabled and f != "local_derived_datasets":
                disabled.append(f)
        if "remote_upload" not in disabled:
            disabled.extend(DISABLED_FEATURES_REMOTE_OFF)

    return sorted(set(disabled))


def can_use_governed_mode(settings: dict[str, Any]) -> bool:
    """Governed mode requires local operational telemetry."""
    return bool(settings.get("local_operational_enabled", True))


def can_use_delegate_fleet(settings: dict[str, Any]) -> bool:
    """Delegate/fleet requires local operational telemetry and beta sharing."""
    if not settings.get("local_operational_enabled", True):
        return False
    mode = settings.get("mode", "basic_local")
    if mode == "basic_local":
        return False
    return True


def can_use_checkpoint(settings: dict[str, Any]) -> bool:
    """Checkpoint commits require local operational telemetry."""
    return bool(settings.get("local_operational_enabled", True))


def can_use_coordination_leases(settings: dict[str, Any]) -> bool:
    """Coordination leases require local operational telemetry."""
    return bool(settings.get("local_operational_enabled", True))


def can_use_current_state(settings: dict[str, Any]) -> bool:
    """Current state requires local operational telemetry."""
    return bool(settings.get("local_operational_enabled", True))


def can_use_queue_planning(settings: dict[str, Any]) -> bool:
    """Queue planning requires local operational telemetry."""
    return bool(settings.get("local_operational_enabled", True))


def can_use_replay_debug(settings: dict[str, Any]) -> bool:
    """Replay/debug requires local operational telemetry."""
    return bool(settings.get("local_operational_enabled", True))


def can_use_autonomous_spawn(settings: dict[str, Any]) -> bool:
    """Autonomous spawn execution requires local op telemetry and beta sharing."""
    if not settings.get("local_operational_enabled", True):
        return False
    mode = settings.get("mode", "basic_local")
    if mode == "basic_local":
        return False
    return True


def can_upload_remote_beta_data(settings: dict[str, Any]) -> bool:
    """Remote upload requires remote sharing enabled and valid share level.

    Upload is only allowed when:
    - remote_beta_sharing_enabled is True
    - share_level is not 'off' and not 'debug_local_only'
    """
    if not settings.get("remote_beta_sharing_enabled", False):
        return False
    share_level = settings.get("share_level", "off")
    return share_level in ALLOWED_SHARE_LEVELS_FOR_UPLOAD


def compute_degradation_mode(settings: dict[str, Any]) -> dict[str, Any]:
    """Compute degradation fields from telemetry settings booleans.

    Returns a dict with degradation_mode, degraded_capabilities,
    degradation_reason, and degraded_at suitable for merging into
    the telemetry settings output.
    """
    from datetime import UTC, datetime

    from rig_relay.core.telemetry.types import TelemetryMode

    local = bool(settings.get("local_operational_enabled", True))
    remote = bool(settings.get("remote_beta_sharing_enabled", False))
    share_level = settings.get("share_level", "off")
    mode = settings.get("mode", "basic_local")
    degraded: list[str] = []

    if local and remote:
        degradation_mode = TelemetryMode.FULL.value
    elif local and not remote:
        degradation_mode = TelemetryMode.ENABLED_FIRST_PARTY.value
    else:
        degradation_mode = TelemetryMode.DISABLED_BY_USER.value

    if not local:
        degraded.extend(DISABLED_FEATURES_LOCAL_OFF)
        degraded.extend(DISABLED_FEATURES_REMOTE_OFF)
    elif not remote:
        degraded.extend(DISABLED_FEATURES_REMOTE_OFF)

    if share_level in {"off", "debug_local_only"}:
        if "remote_upload" not in degraded:
            degraded.append("remote_upload")

    if mode == "basic_local":
        for f in DISABLED_FEATURES_LOCAL_OFF:
            if f not in degraded and f != "local_derived_datasets":
                degraded.append(f)
        for f in DISABLED_FEATURES_REMOTE_OFF:
            if f not in degraded:
                degraded.append(f)

    match degradation_mode:
        case TelemetryMode.FULL.value:
            reason = "All telemetry features enabled"
        case TelemetryMode.ENABLED_FIRST_PARTY.value:
            reason = "Remote beta sharing disabled — remote features unavailable"
        case TelemetryMode.DISABLED_BY_USER.value:
            reason = "Local operational telemetry disabled by configuration"
        case _:
            reason = "Unknown degradation mode"
            degradation_mode = TelemetryMode.DISABLED_BY_USER.value

    return {
        "degradation_mode": degradation_mode,
        "degraded_capabilities": sorted(set(degraded)),
        "degradation_reason": reason,
        "degraded_at": datetime.now(UTC).isoformat(),
    }


def get_telemetry_degradation_state(settings: dict[str, Any]) -> dict[str, Any]:
    """Return an inspectable telemetry degradation state dict.

    Combines the computed degradation mode with key settings values
    so consumers can determine what is degraded and why without
    needing to re-derive the computation.
    """
    degradation = compute_degradation_mode(settings)

    return {
        "degradation_mode": degradation["degradation_mode"],
        "degraded_capabilities": degradation["degraded_capabilities"],
        "degradation_reason": degradation["degradation_reason"],
        "effective_at": degradation["degraded_at"],
        "local_observability_enabled": bool(
            settings.get("local_operational_enabled", True)
        ),
        "remote_export_enabled": bool(
            settings.get("remote_beta_sharing_enabled", False)
        ),
        "share_level": settings.get("share_level", "off"),
        "mode": settings.get("mode", "basic_local"),
    }
