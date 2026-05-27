from __future__ import annotations

import subprocess
from unittest.mock import patch

from rig_relay.native._safari_x0_contract import (
    SafariCompanionState,
    SafariNativeProjection,
    build_safari_native_blockers,
    build_safari_native_projection,
    check_safari_extension_enabled,
)


def test_build_safari_native_projection_returns_typed_model():
    result = build_safari_native_projection()
    assert isinstance(result, SafariNativeProjection)
    assert result.safari_companion_state in (
        "unavailable",
        "extension_built",
        "extension_embedded",
    )
    assert result.generated_at is not None
    assert "T" in result.generated_at


def test_build_safari_native_projection_returns_all_required_fields():
    result = build_safari_native_projection()
    fields = result.model_dump()
    required_keys = [
        "safari_companion_state",
        "safari_distribution_signing_state",
        "safari_notarization_state",
        "safari_update_delivery_state",
        "safari_diagnostic_export_blocked",
        "safari_recovery_action_state",
        "safari_extension_built",
        "safari_artifact_manifest_available",
    ]
    for key in required_keys:
        assert key in fields, f"Missing key: {key}"


def test_build_safari_native_blockers_returns_list():
    blockers = build_safari_native_blockers()
    assert isinstance(blockers, list)


def test_check_safari_extension_enabled_returns_dict():
    result = check_safari_extension_enabled()
    assert isinstance(result, dict)
    assert "safari_running" in result
    assert "extension_installed" in result
    assert "extension_enabled" in result
    assert "error" in result


def test_projection_content_light():
    result = build_safari_native_projection()
    fields = result.model_dump()
    for _k, v in fields.items():
        if isinstance(v, str):
            assert "ghp_" not in v.lower()
            assert "sk-" not in v.lower()
    assert result.safari_extension_error is None or (
        "/" not in result.safari_extension_error
        and "/Users/" not in result.safari_extension_error
        and "/home/" not in result.safari_extension_error
        and "\n" not in result.safari_extension_error
    )


def test_projection_accepts_override_fields():
    result = build_safari_native_projection(
        safari_companion_state=SafariCompanionState.EXTENSION_EMBEDDED,
        safari_extension_built=True,
    )
    assert result.safari_companion_state == "extension_embedded"
    assert result.safari_extension_built


def test_build_environment_keys_present():
    result = build_safari_native_projection()
    env = result.build_environment
    assert "xcode_available" in env
    assert "signing_identity_found" in env
    assert "app_bundle_exists" in env
    assert "extension_appex_exists" in env
    assert "notarytool_available" in env


def test_check_safari_extension_enabled_error_on_defaults_missing():
    pgrep_ok = subprocess.CompletedProcess(
        args=["pgrep", "-x", "Safari"], returncode=1, stdout=b"", stderr=b""
    )

    def run_side_effect(args, **_kwargs):
        if args[0] == "pgrep":
            return pgrep_ok
        if args[0] == "defaults":
            raise FileNotFoundError
        raise RuntimeError("unexpected subprocess call")

    with patch(
        "rig_relay.native._safari_x0_contract.subprocess.run",
        side_effect=run_side_effect,
    ):
        result = check_safari_extension_enabled()
    assert result["error"] is not None
    assert "defaults read failed" in result["error"]
    assert result["extension_installed"] is False
    assert result["extension_enabled"] is False


def test_check_safari_extension_enabled_sanitizes_unexpected_exception():
    pgrep_ok = subprocess.CompletedProcess(
        args=["pgrep", "-x", "Safari"], returncode=1, stdout=b"", stderr=b""
    )

    def run_side_effect(args, **_kwargs):
        if args[0] == "pgrep":
            return pgrep_ok
        if args[0] == "defaults":
            raise RuntimeError("traceback would leak /Users/user/path")
        raise RuntimeError("unexpected subprocess call")

    with patch(
        "rig_relay.native._safari_x0_contract.subprocess.run",
        side_effect=run_side_effect,
    ):
        result = check_safari_extension_enabled()
    assert result["error"] is not None
    assert result["error"] == "unexpected error during safari extension check"
    assert "/" not in result["error"]
    assert "traceback" not in result["error"].lower()
    assert "\n" not in result["error"]
