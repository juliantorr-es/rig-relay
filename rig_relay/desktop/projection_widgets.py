"""Canonical widget names and mode mapping for the desktop cockpit.

This module defines the canonical widget names and mode mappings from the
Relay Desktop Projection Contract (docs/governance/relay-desktop-projection-contract.md).
It does not replace projection.py — it provides constants and small helpers
used by tests and future projection refactors.
"""

from __future__ import annotations

# ── Canonical Widget Names ─────────────────────────────────────────────

# Operator-facing widgets (rendered in Operate mode)
OPERATOR_HEADER = "OperatorHeader"
SAFETY_STATE = "SafetyState"
NEXT_ACTION = "NextAction"
VALIDATION_SUMMARY = "ValidationSummary"
STORAGE_BUDGET = "StorageBudget"
LATEST_INTENT_RESULT = "LatestIntentResult"

# Activity/review widgets (rendered in Review mode)
ACTIVE_CHILD_SESSIONS = "ActiveChildSessions"
RECEIPT_TIMELINE = "ReceiptTimeline"
REFINEMENT_BACKLOG = "RefinementBacklog"
PROGRESS_TIMELINE = "ProgressTimeline"

# System/diagnostic widgets (rendered in System mode)
PROVIDER_STATUS = "ProviderStatus"
IDENTITY_STATUS = "IdentityStatus"
INTEGRATION_STATUS = "IntegrationStatus"
TELEMETRY_CONSENT_STATUS = "TelemetryConsentStatus"
LOCAL_AUTHORITY_STATUS = "LocalAuthorityStatus"
MODEL_OBSERVATION_SUMMARY = "ModelObservationSummary"

# ── All Canonical Widgets ──────────────────────────────────────────────

ALL_WIDGETS = frozenset({
    OPERATOR_HEADER,
    SAFETY_STATE,
    NEXT_ACTION,
    VALIDATION_SUMMARY,
    STORAGE_BUDGET,
    LATEST_INTENT_RESULT,
    ACTIVE_CHILD_SESSIONS,
    RECEIPT_TIMELINE,
    REFINEMENT_BACKLOG,
    PROGRESS_TIMELINE,
    PROVIDER_STATUS,
    IDENTITY_STATUS,
    INTEGRATION_STATUS,
    TELEMETRY_CONSENT_STATUS,
    LOCAL_AUTHORITY_STATUS,
    MODEL_OBSERVATION_SUMMARY,
})

# ── Mode to Widget Mapping ─────────────────────────────────────────────

OPERATE_WIDGETS = frozenset({
    OPERATOR_HEADER,
    SAFETY_STATE,
    NEXT_ACTION,
    VALIDATION_SUMMARY,
    STORAGE_BUDGET,
    LATEST_INTENT_RESULT,
})

REVIEW_WIDGETS = frozenset({
    ACTIVE_CHILD_SESSIONS,
    RECEIPT_TIMELINE,
    REFINEMENT_BACKLOG,
    PROGRESS_TIMELINE,
    VALIDATION_SUMMARY,
    STORAGE_BUDGET,
})

SYSTEM_WIDGETS = frozenset({
    PROVIDER_STATUS,
    IDENTITY_STATUS,
    INTEGRATION_STATUS,
    TELEMETRY_CONSENT_STATUS,
    LOCAL_AUTHORITY_STATUS,
    MODEL_OBSERVATION_SUMMARY,
})

# ── Mode name list for validation ──────────────────────────────────────

MODE_NAMES = frozenset({"Operate", "Review", "System"})

# ── Widget mode lookup ─────────────────────────────────────────────────
# Some widgets (ValidationSummary, StorageBudget) appear in multiple modes.
# widget_mode() returns the primary mode; widget_modes() returns all modes.

WIDGET_TO_MODES: dict[str, set[str]] = {}
for _widget in OPERATE_WIDGETS:
    WIDGET_TO_MODES.setdefault(_widget, set()).add("Operate")
for _widget in REVIEW_WIDGETS:
    WIDGET_TO_MODES.setdefault(_widget, set()).add("Review")
for _widget in SYSTEM_WIDGETS:
    WIDGET_TO_MODES.setdefault(_widget, set()).add("System")

# Determine primary mode (first encountered) for backwards compat
_WIDGET_TO_PRIMARY_MODE: dict[str, str] = {}
for _widget in OPERATE_WIDGETS:
    _WIDGET_TO_PRIMARY_MODE.setdefault(_widget, "Operate")
for _widget in REVIEW_WIDGETS:
    _WIDGET_TO_PRIMARY_MODE.setdefault(_widget, "Review")
for _widget in SYSTEM_WIDGETS:
    _WIDGET_TO_PRIMARY_MODE.setdefault(_widget, "System")


def widget_mode(widget_name: str) -> str:
    """Return the primary mode a widget belongs to.

    Some widgets (ValidationSummary, StorageBudget) appear in multiple
    modes. This returns the primary mode; use ``widget_modes()`` for all.

    Args:
        widget_name: Canonical widget name (e.g. ``"OperatorHeader"``).

    Returns:
        ``"Operate"``, ``"Review"``, or ``"System"``.

    Raises:
        KeyError: If the widget name is not a known canonical widget.
    """
    if widget_name not in ALL_WIDGETS:
        msg = f"Unknown widget: {widget_name}"
        raise KeyError(msg)
    return _WIDGET_TO_PRIMARY_MODE[widget_name]


def widget_modes(widget_name: str) -> frozenset[str]:
    """Return all modes a widget belongs to.

    Args:
        widget_name: Canonical widget name.

    Returns:
        Frozenset of mode names (``"Operate"``, ``"Review"``, ``"System"``).

    Raises:
        KeyError: If the widget name is not a known canonical widget.
    """
    if widget_name not in ALL_WIDGETS:
        msg = f"Unknown widget: {widget_name}"
        raise KeyError(msg)
    return frozenset(WIDGET_TO_MODES.get(widget_name, set()))


# ── Projection field to widget map ─────────────────────────────────────
# Maps projection.py output field names to widget names.
# This documents which projection fields feed which widget cards.

PROJECTION_FIELD_TO_WIDGET: dict[str, str] = {
    "app_version": OPERATOR_HEADER,
    "current_state": SAFETY_STATE,
    "storage": STORAGE_BUDGET,
    "_last_validation": VALIDATION_SUMMARY,
    "_receipts": RECEIPT_TIMELINE,
    "_refinement": REFINEMENT_BACKLOG,
    "warnings": NEXT_ACTION,
    "progress_events": PROGRESS_TIMELINE,
    "providers": PROVIDER_STATUS,
    "identity": IDENTITY_STATUS,
    "integrations": INTEGRATION_STATUS,
    "telemetry_consent": TELEMETRY_CONSENT_STATUS,
    "source_status": LOCAL_AUTHORITY_STATUS,
}


# ── Deferred widget info ───────────────────────────────────────────────
# Widgets that are documented in the projection contract but not yet
# fully implemented in the cockpit. Each entry has a reason.

DEFERRED_WIDGETS: dict[str, str] = {
    MODEL_OBSERVATION_SUMMARY: (
        "Model observation ingestion pipeline not yet wired; "
        "available via schema/model but not cockpit widgets"
    )
}


def is_deferred(widget_name: str) -> bool:
    """Return True if the widget is intentionally deferred."""
    return widget_name in DEFERRED_WIDGETS


def deferred_reason(widget_name: str) -> str:
    """Return the deferral reason for a deferred widget."""
    return DEFERRED_WIDGETS.get(widget_name, "")
