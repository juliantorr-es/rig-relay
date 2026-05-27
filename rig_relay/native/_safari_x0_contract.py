"""X0-consumable Safari native state contract (X4.5).

Publishes typed projection fields and intent results that X0 may
consume to display Safari companion status, distribution readiness,
diagnostic and recovery state without exposing raw payloads, tokens,
credentials, or internal paths.

X0 must not edit this module. X4.5 owns the contract authority for the
SafariCompanionNativeDetectionBoundary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
import subprocess
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.logger import logger


class SafariCompanionState(StrEnum):
    """Projection field values for safari_companion_state.

    SafariCompanionState reachability:
    - UNAVAILABLE: default when build tools are absent
    - EXTENSION_BUILT: build artifacts exist
    - EXTENSION_EMBEDDED: .appex found in PlugIns directory
    - INSTALLED_DISABLED / INSTALLED_ENABLED: reachable only through explicit override
      (live detection requires check_safari_extension_enabled() wiring)
    - CONNECTED / HANDOFF_* / LIVE_TRANSPORT_VERIFIED / DEGRADED: reachable only through
      explicit override (deferred live-transport seam)
    """

    UNAVAILABLE = "unavailable"
    EXTENSION_BUILT = "extension_built"
    EXTENSION_EMBEDDED = "extension_embedded"
    INSTALLED_DISABLED = "installed_disabled"
    INSTALLED_ENABLED = "installed_enabled"
    CONNECTED = "connected"
    HANDOFF_RECEIVED = "handoff_received"
    HANDOFF_REFUSED = "handoff_refused"
    LIVE_TRANSPORT_VERIFIED = "live_transport_verified"
    DEGRADED = "degraded"


class DistributionSigningState(StrEnum):
    UNSIGNED = "unsigned"
    ADHOC_SIGNED = "adhoc_signed"
    DEVELOPER_ID_AVAILABLE = "developer_id_available"
    DEVELOPER_ID_MISSING = "developer_id_missing"
    SIGNED = "signed"


class NotarizationState(StrEnum):
    NOT_SUBMITTED = "not_submitted"
    CREDENTIALS_MISSING = "credentials_missing"
    SUBMITTED = "submitted"
    IN_PROGRESS = "in_progress"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STAPLED = "stapled"
    FAILED = "failed"


class UpdateDeliveryState(StrEnum):
    NOT_INTEGRATED = "not_integrated"
    FRAMEWORK_WIRED = "framework_wired"
    KEYS_CONFIGURED = "keys_configured"
    APPCAST_PUBLISHED = "appcast_published"
    UPDATE_ARCHIVE_SIGNED = "update_archive_signed"
    ROUND_TRIP_VERIFIED = "round_trip_verified"


class DiagnosticExportState(StrEnum):
    READY = "ready"
    EXPORTED = "exported"
    BLOCKED_UNSAFE_CONTENT = "blocked_unsafe_content"
    REFUSED = "refused"


class RecoveryActionState(StrEnum):
    HEALTHY = "healthy"
    NEEDS_REBUILD = "needs_rebuild"
    NEEDS_EXTENSION_EMBED = "needs_extension_embed"
    NEEDS_SIGNING_IDENTITY = "needs_signing_identity"
    NEEDS_NOTARY_CREDENTIALS = "needs_notary_credentials"
    NEEDS_SPARKLE_CONFIGURATION = "needs_sparkle_configuration"
    NEEDS_APPCAST_HOSTING = "needs_appcast_hosting"
    NEEDS_DIAGNOSTIC_REPAIR = "needs_diagnostic_repair"


class SafariNativeProjection(BaseModel):
    """Content-light typed projection for X0 consumption."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.native.safari_x0_projection.v1", frozen=True
    )

    safari_companion_state: str = "extension_built"
    safari_distribution_signing_state: str = "unsigned"
    safari_notarization_state: str = "not_submitted"
    safari_update_delivery_state: str = "not_integrated"
    safari_diagnostic_export_state: str = "ready"
    safari_diagnostic_export_blocked: bool = False
    safari_recovery_action_state: str = "healthy"
    safari_extension_built: bool = False
    safari_artifact_manifest_available: bool = False
    safari_running: bool = False
    safari_extension_installed: bool = False
    safari_extension_enabled: bool = False
    safari_extension_error: str | None = None

    last_handoff_kind: str | None = None
    last_handoff_timestamp: str | None = None
    last_refusal_reason: str | None = None
    available_actions: list[str] = Field(default_factory=list)

    build_environment: dict[str, bool] = Field(
        default_factory=lambda: {
            "xcode_available": False,
            "signing_identity_found": False,
            "app_bundle_exists": False,
            "extension_appex_exists": False,
            "notarytool_available": False,
        }
    )

    content_policy: str = "content_light"

    generated_at: str | None = None


def _run_check(args: list[str], timeout: float = 5.0) -> bool:
    try:
        subprocess.run(args, capture_output=True, timeout=timeout, check=True)
        return True
    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
    ):
        return False
    except OSError:
        return False


def _derive_companion_state_from_detection(
    extension_built: bool, extension_appex_exists: bool
) -> SafariCompanionState:
    if extension_appex_exists:
        return SafariCompanionState.EXTENSION_EMBEDDED
    if extension_built:
        return SafariCompanionState.EXTENSION_BUILT
    return SafariCompanionState.UNAVAILABLE


def _derive_recovery_action_state(
    signing_identity_found: bool,
    notarytool_available: bool,
    extension_appex_exists: bool,
) -> RecoveryActionState:
    if not extension_appex_exists:
        return RecoveryActionState.NEEDS_EXTENSION_EMBED
    if not signing_identity_found:
        return RecoveryActionState.NEEDS_SIGNING_IDENTITY
    if not notarytool_available:
        return RecoveryActionState.NEEDS_NOTARY_CREDENTIALS
    return RecoveryActionState.HEALTHY


def check_safari_extension_enabled() -> dict[str, Any]:
    result: dict[str, Any] = {
        "safari_running": False,
        "extension_installed": False,
        "extension_enabled": False,
        "error": None,
    }
    try:
        try:
            pgrep_result = subprocess.run(
                ["pgrep", "-x", "Safari"], capture_output=True, timeout=3.0, check=False
            )
            if pgrep_result.returncode == 0:
                result["safari_running"] = True
        except (FileNotFoundError, OSError):
            result["error"] = "pgrep unavailable"
            return result
        except subprocess.TimeoutExpired:
            result["error"] = "pgrep timed out"
            return result
        try:
            defaults = subprocess.run(
                ["defaults", "read", "com.apple.Safari.Extensions"],
                capture_output=True,
                timeout=5.0,
                check=False,
            )
            if (
                defaults.returncode == 0
                and b"com.juliantorres.RigRelayShell" in defaults.stdout
            ):
                result["extension_installed"] = True
                result["extension_enabled"] = True
            if defaults.returncode != 0:
                result["error"] = (
                    "defaults read returned non-zero: Safari extension state unavailable"
                )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            result["error"] = (
                "defaults read failed: cannot check Safari extension state"
            )
    except Exception as exc:
        logger.warning(
            "check_safari_extension_enabled raised unexpected exception: %s", exc
        )
        result["error"] = "unexpected error during safari extension check"
    return result


def _build_environment_detection() -> dict[str, bool]:
    return {
        "xcode_available": _run_check(["xcodebuild", "-version"]),
        "signing_identity_found": _run_check([
            "security",
            "find-identity",
            "-v",
            "-p",
            "macappstore",
            "Developer ID Application",
        ]),
        "app_bundle_exists": Path("macos/RigRelayShell/RigRelayShell.app").exists(),
        "extension_appex_exists": Path(
            "macos/RigRelayShell/RigRelayShell.app/Contents/PlugIns"
            "/RigRelayShell Extension.appex"
        ).exists(),
        "notarytool_available": _run_check(["xcrun", "notarytool", "help"]),
    }


def _detect_artifact_manifest_available() -> bool:
    return Path(".build/rig-relay/artifacts/distribution_manifest.json").exists()


def _detect_diagnostic_export_blocked() -> bool:
    return False


def build_safari_native_projection(
    *,
    safari_companion_state: SafariCompanionState | None = None,
    safari_distribution_signing_state: DistributionSigningState = DistributionSigningState.UNSIGNED,
    safari_notarization_state: NotarizationState = NotarizationState.NOT_SUBMITTED,
    safari_update_delivery_state: UpdateDeliveryState = UpdateDeliveryState.NOT_INTEGRATED,
    safari_diagnostic_export_state: DiagnosticExportState = DiagnosticExportState.READY,
    safari_diagnostic_export_blocked: bool | None = None,
    safari_recovery_action_state: RecoveryActionState | None = None,
    safari_extension_built: bool | None = None,
    safari_artifact_manifest_available: bool | None = None,
    safari_running: bool | None = None,
    safari_extension_installed: bool | None = None,
    safari_extension_enabled: bool | None = None,
    safari_extension_error: str | None = None,
    last_handoff_kind: str | None = None,
    last_handoff_timestamp: str | None = None,
    last_refusal_reason: str | None = None,
    available_actions: list[str] | None = None,
) -> SafariNativeProjection:
    env = _build_environment_detection()
    extension_state = check_safari_extension_enabled()

    if safari_companion_state is None:
        safari_companion_state = _derive_companion_state_from_detection(
            extension_built=safari_extension_built
            if safari_extension_built is not None
            else any(
                Path(f"macos/RigRelayShell/{p}").exists()
                for p in ["RigRelayShell.xcodeproj", "SafariExtension"]
            ),
            extension_appex_exists=env["extension_appex_exists"],
        )

    if safari_recovery_action_state is None:
        safari_recovery_action_state = _derive_recovery_action_state(
            signing_identity_found=env["signing_identity_found"],
            notarytool_available=env["notarytool_available"],
            extension_appex_exists=env["extension_appex_exists"],
        )

    if safari_diagnostic_export_blocked is None:
        safari_diagnostic_export_blocked = _detect_diagnostic_export_blocked()

    if safari_extension_built is None:
        safari_extension_built = any(
            Path(f"macos/RigRelayShell/{p}").exists()
            for p in ["RigRelayShell.xcodeproj", "RigRelayShell.app"]
        )

    if safari_artifact_manifest_available is None:
        safari_artifact_manifest_available = _detect_artifact_manifest_available()

    if safari_running is None:
        safari_running = extension_state["safari_running"]

    if safari_extension_installed is None:
        safari_extension_installed = extension_state["extension_installed"]

    if safari_extension_enabled is None:
        safari_extension_enabled = extension_state["extension_enabled"]

    if safari_extension_error is None:
        safari_extension_error = extension_state.get("error")

    _export_blocked: bool = cast("bool", safari_diagnostic_export_blocked)
    _extension_built: bool = cast("bool", safari_extension_built)
    _manifest_available: bool = cast("bool", safari_artifact_manifest_available)
    _running: bool = cast("bool", safari_running)
    _ext_installed: bool = cast("bool", safari_extension_installed)
    _ext_enabled: bool = cast("bool", safari_extension_enabled)

    return SafariNativeProjection(
        safari_companion_state=safari_companion_state.value,
        safari_distribution_signing_state=safari_distribution_signing_state.value,
        safari_notarization_state=safari_notarization_state.value,
        safari_update_delivery_state=safari_update_delivery_state.value,
        safari_diagnostic_export_state=safari_diagnostic_export_state.value,
        safari_diagnostic_export_blocked=_export_blocked,
        safari_recovery_action_state=safari_recovery_action_state.value,
        safari_extension_built=_extension_built,
        safari_artifact_manifest_available=_manifest_available,
        safari_running=_running,
        safari_extension_installed=_ext_installed,
        safari_extension_enabled=_ext_enabled,
        safari_extension_error=safari_extension_error,
        last_handoff_kind=last_handoff_kind,
        last_handoff_timestamp=last_handoff_timestamp,
        last_refusal_reason=last_refusal_reason,
        available_actions=available_actions or [],
        build_environment=env,
        generated_at=datetime.now(UTC).isoformat(),
    )


def build_safari_native_blockers(
    *,
    developer_id_missing: bool = True,
    notary_credentials_missing: bool = True,
    sparkle_not_integrated: bool = True,
    app_group_not_configured: bool = True,
    live_transport_not_verified: bool = True,
) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    if developer_id_missing:
        blockers.append({
            "kind": "developer_id_missing",
            "action": "Add Developer ID Application certificate to keychain",
            "detail": "Required for notarized distribution",
        })
    if notary_credentials_missing:
        blockers.append({
            "kind": "notary_credentials_missing",
            "action": "Run: xcrun notarytool store-credentials rig-relay-notary",
            "detail": "Required for notarization submission",
        })
    if sparkle_not_integrated:
        blockers.append({
            "kind": "sparkle_not_integrated",
            "action": "Add Sparkle 2 SPM dependency and wire SPUStandardUpdaterController",
            "detail": "Required for update delivery",
        })
    if app_group_not_configured:
        blockers.append({
            "kind": "app_group_not_configured",
            "action": "Add com.apple.security.application-groups to app and extension entitlements",
            "detail": "Required for shared state between app and Safari extension",
        })
    if live_transport_not_verified:
        blockers.append({
            "kind": "live_transport_not_verified",
            "action": "Enable extension in Safari and send test handoff message",
            "detail": "Required to prove end-to-end Safari message corridor",
        })
    return blockers


__all__ = [
    "DiagnosticExportState",
    "DistributionSigningState",
    "NotarizationState",
    "RecoveryActionState",
    "SafariCompanionState",
    "SafariNativeProjection",
    "UpdateDeliveryState",
    "build_safari_native_blockers",
    "build_safari_native_projection",
    "check_safari_extension_enabled",
]
