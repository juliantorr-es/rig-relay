"""X0-consumable Safari native state contract (X4.3).

Publishes typed projection fields and intent results that X0 may
consume to display Safari companion status, distribution readiness,
diagnostic and recovery state without exposing raw payloads, tokens,
credentials, or internal paths.

X0 must not edit this module. X4.3 owns the contract authority.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class SafariCompanionState(StrEnum):
    """Projection field values for safari_companion_state."""

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


def build_safari_native_projection(
    *,
    safari_companion_state: SafariCompanionState = SafariCompanionState.EXTENSION_EMBEDDED,
    distribution_signing_state: DistributionSigningState = DistributionSigningState.ADHOC_SIGNED,
    notarization_state: NotarizationState = NotarizationState.NOT_SUBMITTED,
    update_delivery_state: UpdateDeliveryState = UpdateDeliveryState.NOT_INTEGRATED,
    diagnostic_export_state: DiagnosticExportState = DiagnosticExportState.READY,
    recovery_action_state: RecoveryActionState = RecoveryActionState.HEALTHY,
    last_handoff_kind: str | None = None,
    last_handoff_timestamp: str | None = None,
    last_refusal_reason: str | None = None,
    available_actions: list[str] | None = None,
) -> dict[str, Any]:
    """Build a content-light projection for X0 consumption.

    No raw payloads, URLs, tokens, credentials, or internal paths.
    All fields are typed enums or safe summary strings.
    """
    return {
        "schema_version": "rig.relay.native.safari_x0_projection.v1",
        "safari_companion_state": safari_companion_state.value,
        "distribution_signing_state": distribution_signing_state.value,
        "notarization_state": notarization_state.value,
        "update_delivery_state": update_delivery_state.value,
        "diagnostic_export_state": diagnostic_export_state.value,
        "recovery_action_state": recovery_action_state.value,
        "last_handoff_kind": last_handoff_kind,
        "last_handoff_timestamp": last_handoff_timestamp,
        "last_refusal_reason": last_refusal_reason,
        "available_actions": available_actions or [],
        "content_policy": "content_light",
    }


def build_safari_native_blockers(
    *,
    developer_id_missing: bool = True,
    notary_credentials_missing: bool = True,
    sparkle_not_integrated: bool = True,
    app_group_not_configured: bool = True,
    live_transport_not_verified: bool = True,
) -> list[dict[str, str]]:
    """Build a typed list of actionable blockers for X0 display."""
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
    "UpdateDeliveryState",
    "build_safari_native_blockers",
    "build_safari_native_projection",
]
