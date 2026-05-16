"""Tests for the desktop projection widget contract.

Verifies canonical widget names, mode mapping, deferred widget tracking,
and projection field alignment.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from rig_relay.desktop.projection_widgets import (
    ALL_WIDGETS,
    DEFERRED_WIDGETS,
    MODE_NAMES,
    OPERATE_WIDGETS,
    PROJECTION_FIELD_TO_WIDGET,
    REVIEW_WIDGETS,
    SYSTEM_WIDGETS,
    deferred_reason,
    is_deferred,
    widget_mode,
)

# Import build_projection to verify field alignment
from scripts.rig_relay_desktop_projection import build_projection

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROJECTION_MODULE_PATH = REPO_ROOT / "rig_relay" / "desktop" / "projection_widgets.py"


pytestmark = [pytest.mark.integration]


class TestWidgetContractExistence:
    def test_projection_widgets_module_exists(self) -> None:
        assert PROJECTION_MODULE_PATH.is_file()

    def test_module_has_all_canonical_widgets(self) -> None:
        """All widgets from the projection contract are defined."""
        assert "OperatorHeader" in ALL_WIDGETS
        assert "SafetyState" in ALL_WIDGETS
        assert "NextAction" in ALL_WIDGETS
        assert "ActiveChildSessions" in ALL_WIDGETS
        assert "ValidationSummary" in ALL_WIDGETS
        assert "StorageBudget" in ALL_WIDGETS
        assert "ReceiptTimeline" in ALL_WIDGETS
        assert "LatestIntentResult" in ALL_WIDGETS
        assert "RefinementBacklog" in ALL_WIDGETS
        assert "ProgressTimeline" in ALL_WIDGETS
        assert "ProviderStatus" in ALL_WIDGETS
        assert "IdentityStatus" in ALL_WIDGETS
        assert "TelemetryConsentStatus" in ALL_WIDGETS
        assert "LocalAuthorityStatus" in ALL_WIDGETS
        assert "ModelObservationSummary" in ALL_WIDGETS


class TestEveryWidgetHasMode:
    def test_all_widgets_have_a_mode(self) -> None:
        for widget in ALL_WIDGETS:
            mode = widget_mode(widget)
            assert mode in MODE_NAMES, f"Widget {widget} mapped to unknown mode {mode}"

    def test_widget_mode_function(self) -> None:
        assert widget_mode("OperatorHeader") == "Operate"
        assert widget_mode("SafetyState") == "Operate"
        assert widget_mode("ProgressTimeline") == "Review"
        assert widget_mode("ProviderStatus") == "System"

    def test_unknown_widget_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            widget_mode("UnknownWidgetName")


class TestOperateModeWidgets:
    def test_operate_contains_operator_facing_widgets(self) -> None:
        """Operate mode contains only operator-facing widgets."""
        assert "OperatorHeader" in OPERATE_WIDGETS
        assert "SafetyState" in OPERATE_WIDGETS
        assert "NextAction" in OPERATE_WIDGETS
        assert "ValidationSummary" in OPERATE_WIDGETS
        assert "StorageBudget" in OPERATE_WIDGETS
        assert "LatestIntentResult" in OPERATE_WIDGETS

    def test_operate_does_not_contain_review_widgets(self) -> None:
        assert "ActiveChildSessions" not in OPERATE_WIDGETS
        assert "ProgressTimeline" not in OPERATE_WIDGETS
        assert "RefinementBacklog" not in OPERATE_WIDGETS

    def test_operate_does_not_contain_system_widgets(self) -> None:
        assert "ProviderStatus" not in OPERATE_WIDGETS
        assert "IdentityStatus" not in OPERATE_WIDGETS
        assert "ModelObservationSummary" not in OPERATE_WIDGETS


class TestReviewModeWidgets:
    def test_review_contains_evidence_artifact_progress_widgets(self) -> None:
        """Review mode contains evidence/artifact/progress widgets."""
        assert "ActiveChildSessions" in REVIEW_WIDGETS
        assert "ReceiptTimeline" in REVIEW_WIDGETS
        assert "RefinementBacklog" in REVIEW_WIDGETS
        assert "ProgressTimeline" in REVIEW_WIDGETS

    def test_review_contains_validation_and_storage(self) -> None:
        assert "ValidationSummary" in REVIEW_WIDGETS
        assert "StorageBudget" in REVIEW_WIDGETS

    def test_review_does_not_contain_operator_only_widgets(self) -> None:
        assert "OperatorHeader" not in REVIEW_WIDGETS
        assert "NextAction" not in REVIEW_WIDGETS
        assert "LatestIntentResult" not in REVIEW_WIDGETS

    def test_review_does_not_contain_system_widgets(self) -> None:
        assert "ProviderStatus" not in REVIEW_WIDGETS
        assert "TelemetryConsentStatus" not in REVIEW_WIDGETS


class TestSystemModeWidgets:
    def test_system_contains_provider_identity_consent_diagnostics(self) -> None:
        """System mode contains provider/identity/consent/local-authority diagnostics."""
        assert "ProviderStatus" in SYSTEM_WIDGETS
        assert "IdentityStatus" in SYSTEM_WIDGETS
        assert "TelemetryConsentStatus" in SYSTEM_WIDGETS
        assert "LocalAuthorityStatus" in SYSTEM_WIDGETS
        assert "ModelObservationSummary" in SYSTEM_WIDGETS

    def test_system_does_not_contain_operate_widgets(self) -> None:
        assert "OperatorHeader" not in SYSTEM_WIDGETS
        assert "SafetyState" not in SYSTEM_WIDGETS
        assert "NextAction" not in SYSTEM_WIDGETS

    def test_system_does_not_contain_review_widgets(self) -> None:
        assert "ActiveChildSessions" not in SYSTEM_WIDGETS
        assert "ProgressTimeline" not in SYSTEM_WIDGETS
        assert "RefinementBacklog" not in SYSTEM_WIDGETS


class TestProtectedControlsAbsent:
    """Protected execution controls must NOT be listed as widgets."""

    PROTECTED_CONTROLS: ClassVar[set[str]] = {
        "Bash",
        "Shell",
        "WriteFile",
        "SearchReplace",
        "SpawnExecute",
        "FleetExecute",
        "DelegateExecute",
        "RemoteUploadConfirm",
        "LeaseCleanupRemove",
        "CheckpointCommit",
    }

    def test_no_protected_controls_in_widgets(self) -> None:
        for control in self.PROTECTED_CONTROLS:
            assert control not in ALL_WIDGETS, (
                f"Protected control {control} found in widget list"
            )


class TestProjectionFieldAlignment:
    """Projection builder output has enough fields to support required widgets."""

    def test_projection_has_required_fields_for_operate_widgets(self) -> None:
        pj = build_projection()
        # OperatorHeader
        assert "app_version" in pj
        # SafetyState
        assert "current_state" in pj
        # StorageBudget
        assert "storage" in pj
        # NextAction uses warnings
        assert "warnings" in pj
        # ValidationSummary data may be conditional on source availability
        # LatestIntentResult data may be conditional on source availability
        # ReceiptTimeline data may be conditional on source availability

    def test_projection_has_required_fields_for_review_widgets(self) -> None:
        pj = build_projection()
        # ActiveChildSessions info comes from current_state
        assert "current_state" in pj
        # ValidationSummary and StorageBudget overlap with Operate
        assert "storage" in pj
        # ReceiptTimeline and RefinementBacklog are conditional on source availability

    def test_projection_has_required_fields_for_system_widgets(self) -> None:
        pj = build_projection()
        # ProviderStatus
        assert "providers" in pj
        # IdentityStatus is conditional on source availability

    def test_projection_field_to_widget_map_is_consistent(self) -> None:
        """Every projection field maps to a known widget."""
        for field, widget in PROJECTION_FIELD_TO_WIDGET.items():
            assert widget in ALL_WIDGETS, (
                f"Projection field {field} maps to unknown widget {widget}"
            )
            actual_mode = widget_mode(widget)
            assert actual_mode in MODE_NAMES, (
                f"Widget {widget} for field {field} has unknown mode {actual_mode}"
            )


class TestDeferredWidgets:
    """Provider/model observation/progress widgets that are deferred have explicit reason."""

    def test_deferred_widgets_have_reasons(self) -> None:
        for widget, reason in DEFERRED_WIDGETS.items():
            assert reason, f"Deferred widget {widget} has no reason"
            assert len(reason) > 10, (
                f"Deferred widget {widget} reason too short: {reason}"
            )

    def test_model_observation_summary_is_deferred(self) -> None:
        assert is_deferred("ModelObservationSummary")
        reason = deferred_reason("ModelObservationSummary")
        assert "ingestion" in reason.lower()

    def test_deferred_widgets_are_in_widget_list(self) -> None:
        for widget in DEFERRED_WIDGETS:
            assert widget in ALL_WIDGETS, f"Deferred widget {widget} not in ALL_WIDGETS"

    def test_non_deferred_widget_returns_false(self) -> None:
        assert not is_deferred("OperatorHeader")
        assert not is_deferred("SafetyState")
        assert deferred_reason("OperatorHeader") == ""


class TestMultiModeWidgets:
    """ValidationSummary and StorageBudget appear in both Operate and Review."""

    MULTI_MODE_WIDGETS: ClassVar[set[str]] = {"ValidationSummary", "StorageBudget"}

    def test_validation_summary_in_operate_and_review(self) -> None:
        assert "ValidationSummary" in OPERATE_WIDGETS
        assert "ValidationSummary" in REVIEW_WIDGETS

    def test_storage_budget_in_operate_and_review(self) -> None:
        assert "StorageBudget" in OPERATE_WIDGETS
        assert "StorageBudget" in REVIEW_WIDGETS

    def test_multi_mode_widget_has_primary_mode(self) -> None:
        for widget in self.MULTI_MODE_WIDGETS:
            mode = widget_mode(widget)
            assert mode in MODE_NAMES, f"{widget} primary mode {mode} unknown"
            # Primary mode should be Operate (first defined)
            assert mode == "Operate", (
                f"{widget} primary mode should be Operate, got {mode}"
            )

    def test_multi_mode_widget_modes_are_correct(self) -> None:
        from rig_relay.desktop.projection_widgets import widget_modes

        modes = widget_modes("ValidationSummary")
        assert "Operate" in modes
        assert "Review" in modes

    def test_operate_only_widget_has_one_mode(self) -> None:
        from rig_relay.desktop.projection_widgets import widget_modes

        assert len(widget_modes("OperatorHeader")) == 1
        assert len(widget_modes("SafetyState")) == 1


class TestWidgetCountConsistency:
    def test_all_widgets_covered(self) -> None:
        """All widgets are covered by at least one mode."""
        union = OPERATE_WIDGETS | REVIEW_WIDGETS | SYSTEM_WIDGETS
        assert union == ALL_WIDGETS, (
            f"Widgets not covered in any mode: {ALL_WIDGETS - union}"
        )

    def test_total_widget_count(self) -> None:
        """All 15 widgets from the projection contract are defined."""
        assert len(ALL_WIDGETS) == 15
