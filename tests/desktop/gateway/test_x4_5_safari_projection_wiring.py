"""X4.5 SafariCompanionNativeDetectionBoundary wiring tests.

Proves that the M0 projection builder and Inference Studio surface
projection builder correctly consume native Safari companion detection
fields and handle failures in a fail-closed manner.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from rig_relay.desktop.gateway import get_gateway_service, reset_gateway_service
from rig_relay.native._safari_x0_contract import SafariNativeProjection


@pytest.fixture(autouse=True)
def _reset_gateway():
    reset_gateway_service()


def _build_safari_fixture(**overrides) -> SafariNativeProjection:
    """Build a SafariNativeProjection fixture with sensible defaults."""
    defaults = {
        "safari_companion_state": "extension_embedded",
        "safari_extension_built": True,
        "safari_running": True,
        "safari_extension_installed": True,
        "safari_extension_enabled": True,
        "safari_extension_error": None,
        "safari_diagnostic_export_blocked": False,
        "safari_diagnostic_export_state": "ready",
        "safari_recovery_action_state": "healthy",
        "safari_artifact_manifest_available": True,
        "safari_distribution_signing_state": "unsigned",
        "safari_notarization_state": "not_submitted",
        "safari_update_delivery_state": "not_integrated",
        "build_environment": {
            "xcode_available": True,
            "signing_identity_found": False,
            "app_bundle_exists": True,
            "extension_appex_exists": True,
            "notarytool_available": False,
        },
        "generated_at": "2026-05-27T18:30:00Z",
    }
    defaults.update(overrides)
    return SafariNativeProjection(**defaults)


class TestM0ProjectionIncludesSafariFields:
    def test_m0_projection_receives_safari_fields(self):
        fixture = _build_safari_fixture()
        gw = get_gateway_service()
        with patch(
            "rig_relay.native._safari_x0_contract.build_safari_native_projection",
            return_value=fixture,
        ):
            from rig_relay.desktop.gateway._projection import M0_PROJECTION_BUILDER

            result = M0_PROJECTION_BUILDER(gw)
        assert result.safari_companion_state == "extension_embedded"
        assert result.safari_diagnostic_export_state == "ready"
        assert result.safari_extension_built
        assert result.safari_running
        assert result.safari_projection_generated_at is not None

    def test_inference_studio_surface_receives_safari_fields(self):
        fixture = _build_safari_fixture(safari_companion_state="extension_built")
        gw = get_gateway_service()
        with patch(
            "rig_relay.native._safari_x0_contract.build_safari_native_projection",
            return_value=fixture,
        ):
            from rig_relay.desktop.gateway._projection_surfaces import (
                INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER,
            )

            result = INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER(gw)
        assert result.safari_companion_state == "extension_built"
        assert result.safari_diagnostic_export_state == "ready"
        assert result.safari_running is True
        assert result.safari_extension_installed is True
        assert result.safari_extension_enabled is True
        assert result.safari_extension_error is None
        assert result.safari_build_environment == fixture.build_environment
        assert result.safari_projection_generated_at is not None


class TestSafariFailClosed:
    def test_m0_projection_fail_closed_on_unexpected_exception(self):
        gw = get_gateway_service()
        with patch(
            "rig_relay.native._safari_x0_contract.build_safari_native_projection",
            side_effect=RuntimeError("crash"),
        ):
            from rig_relay.desktop.gateway._projection import M0_PROJECTION_BUILDER

            result = M0_PROJECTION_BUILDER(gw)
        assert result.safari_companion_state == "error"
        assert result.safari_diagnostic_export_state == "error"
        assert result.safari_diagnostic_export_blocked

    def test_surface_projection_fail_closed_on_unexpected_exception(self):
        gw = get_gateway_service()
        with patch(
            "rig_relay.native._safari_x0_contract.build_safari_native_projection",
            side_effect=RuntimeError("crash"),
        ):
            from rig_relay.desktop.gateway._projection_surfaces import (
                INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER,
            )

            result = INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER(gw)
        assert result.safari_companion_state == "error"
        assert result.safari_diagnostic_export_state == "error"
        assert result.safari_diagnostic_export_blocked

    def test_m0_projection_fail_closed_on_import_error(self):
        gw = get_gateway_service()
        with patch(
            "rig_relay.native._safari_x0_contract.build_safari_native_projection",
            side_effect=ImportError("no module"),
        ):
            from rig_relay.desktop.gateway._projection import M0_PROJECTION_BUILDER

            result = M0_PROJECTION_BUILDER(gw)
        assert result.safari_companion_state == "error"
        assert result.safari_diagnostic_export_state == "error"
        assert result.safari_diagnostic_export_blocked
