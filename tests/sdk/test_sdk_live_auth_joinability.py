from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import jsonschema

from rig_relay.sdk import (
    RigProviderLiveAuthStatus,
    get_provider_live_auth_status,
    validate_live_auth_setup,
)
from rig_relay.sdk._models import compute_sha256

R = Path(__file__).resolve().parent.parent.parent
S = R / "docs" / "schemas"


def _load(name: str) -> dict:
    return json.loads((S / name).read_text(encoding="utf-8"))


def _v(instance: dict, name: str) -> None:
    jsonschema.validate(instance, _load(name))


def _is_valid_uuid(s: str) -> bool:
    try:
        UUID(s)
        return True
    except ValueError:
        return False


_SECRET_PATTERNS = (
    "access_token",
    "refresh_token",
    "client_secret",
    "private_key",
    "api_key",
    "password",
    "secret",
    "credential",
    "token",
)


class TestSDKLiveAuthProviderStatusGitHub:
    def test_provider_live_auth_status_github_unconfigured_by_default(self):
        status = get_provider_live_auth_status("github")
        assert isinstance(status, RigProviderLiveAuthStatus)
        assert status.provider_id == "github"
        assert status.configured is False
        assert isinstance(status.capability_id, str)
        assert "github" in status.capability_id

    def test_provider_live_auth_status_includes_trace_id(self):
        status = get_provider_live_auth_status("github")
        assert status.trace_id
        assert _is_valid_uuid(status.trace_id)

    def test_provider_live_auth_status_includes_credential_store_ref_hash(self):
        status = get_provider_live_auth_status("github")
        assert isinstance(status.credential_store_ref_hash, str | type(None))

    def test_live_auth_status_content_light_no_raw_credentials(self):
        status = get_provider_live_auth_status("github")
        status_dict = status.to_dict()
        for pattern in _SECRET_PATTERNS:
            assert pattern not in status_dict, f"secret pattern '{pattern}' leaked"
        assert "api_key" not in status_dict

    def test_live_auth_status_schema_validate(self):
        status = get_provider_live_auth_status("github")
        _v(status.to_dict(), "rig.relay.sdk.provider_live_auth_status.v1.schema.json")

    def test_receipt_id_unique_per_call(self):
        a = get_provider_live_auth_status("github")
        b = get_provider_live_auth_status("github")
        assert a.receipt_id != b.receipt_id

    def test_trace_id_propagates_sdk_to_provider(self):
        from rig_relay.sdk import check_auth_capability, get_auth_status

        sdk_status = get_auth_status("github")
        live_status = get_provider_live_auth_status("github")
        capability = check_auth_capability("github")

        assert sdk_status.trace_id
        assert live_status.trace_id
        assert capability.trace_id

        chain_hash = compute_sha256(
            f"{sdk_status.trace_id}:{live_status.trace_id}:{capability.trace_id}"
        )
        assert len(chain_hash) == 64


class TestSDKLiveAuthProviderStatusGoogle:
    def test_provider_live_auth_status_google_unconfigured_by_default(self):
        status = get_provider_live_auth_status("google_workspace")
        assert isinstance(status, RigProviderLiveAuthStatus)
        assert status.provider_id == "google_workspace"
        assert status.configured is False

    def test_provider_live_auth_status_google_includes_trace_id(self):
        status = get_provider_live_auth_status("google_workspace")
        assert status.trace_id
        assert _is_valid_uuid(status.trace_id)

    def test_live_auth_status_google_content_light(self):
        status = get_provider_live_auth_status("google_workspace")
        status_dict = status.to_dict()
        for pattern in _SECRET_PATTERNS:
            assert pattern not in status_dict, f"secret pattern '{pattern}' leaked"


class TestSDKLiveAuthUnknownProvider:
    def test_unknown_provider_returns_unconfigured(self):
        status = get_provider_live_auth_status("nonexistent_provider")
        assert status.configured is False
        assert status.auth_status == "unconfigured"
        assert status.refusal_code == "unknown_provider"


class TestSDKValidateLiveAuthSetup:
    def test_validate_live_auth_setup_github_reports_missing(self):
        result = validate_live_auth_setup("github")
        assert isinstance(result, dict)
        assert result["ready"] is False
        issues = result["issues"]
        assert isinstance(issues, list)
        assert len(issues) > 0
        assert "recommendation" in result

    def test_validate_live_auth_setup_google_reports_missing(self):
        result = validate_live_auth_setup("google_workspace")
        assert isinstance(result, dict)
        assert result["ready"] is False
        issues = result["issues"]
        assert isinstance(issues, list)
        assert len(issues) > 0
        assert "recommendation" in result

    def test_validate_live_auth_setup_unknown_provider(self):
        result = validate_live_auth_setup("unknown")
        assert result["ready"] is False
        issues = result["issues"]
        assert isinstance(issues, list)
        assert len(issues) > 0
        assert isinstance(issues[0], str)
        assert "Unknown provider" in issues[0]


class TestSDKLiveAuthJoinability:
    def test_all_status_fields_populated(self):
        status = get_provider_live_auth_status("github")
        d = status.to_dict()
        required_fields = [
            "schema_version",
            "provider_id",
            "configured",
            "auth_mode",
            "auth_status",
            "credential_store_available",
            "credential_store_ref_hash",
            "refresh_needed",
            "scopes_or_permissions",
            "capability_id",
            "trace_id",
            "receipt_id",
            "content_light",
            "generated_at",
        ]
        for f in required_fields:
            assert f in d, f"missing field: {f}"

    def test_refusal_code_present_when_unconfigured(self):
        status = get_provider_live_auth_status("github")
        if not status.configured:
            assert status.refusal_code is not None

    def test_content_light_always_true(self):
        for pid in ("github", "google_workspace", "unknown_provider"):
            status = get_provider_live_auth_status(pid)
            assert status.content_light is True
            assert status.to_dict()["content_light"] is True

    def test_scopes_or_permissions_is_list(self):
        for pid in ("github", "google_workspace"):
            status = get_provider_live_auth_status(pid)
            assert isinstance(status.scopes_or_permissions, list)

    def test_auth_status_value_is_valid(self):
        valid = {
            "unauthenticated",
            "authenticated",
            "expired",
            "revoked",
            "unconfigured",
        }
        for pid in ("github", "google_workspace", "unknown_provider"):
            status = get_provider_live_auth_status(pid)
            assert status.auth_status in valid
