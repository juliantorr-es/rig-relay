from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import jsonschema

from rig_relay.sdk import (
    RigAuthCapabilityCheck,
    RigAuthReceiptRef,
    RigAuthRefusal,
    RigAuthStatus,
    check_auth_capability,
    detect_refresh_needed,
    get_auth_receipt_ref,
    get_auth_refusal,
    get_auth_status,
    get_credential_store_ref_hash,
)

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


class TestSDKAuthModels:
    def test_get_auth_status_returns_rig_auth_status(self):
        status = get_auth_status("github")
        assert isinstance(status, RigAuthStatus)
        assert status.provider_id == "github"
        assert status.auth_status in {
            "unauthenticated",
            "authenticated",
            "expired",
            "revoked",
            "deferred",
            "unconfigured",
        }

    def test_auth_status_includes_refresh_needed(self):
        status = get_auth_status("github")
        assert isinstance(status.refresh_needed, bool)

    def test_auth_status_includes_credential_store_ref_hash(self):
        status = get_auth_status("github")
        assert isinstance(status.credential_store_ref_hash, str | type(None))

    def test_check_auth_capability_returns_decision(self):
        result = check_auth_capability("github")
        assert isinstance(result, RigAuthCapabilityCheck)
        assert isinstance(result.capability_id, str)
        assert isinstance(result.supported, bool)
        assert isinstance(result.verdict, str)

    def test_detect_refresh_needed_returns_bool(self):
        result = detect_refresh_needed("github")
        assert isinstance(result, bool)

    def test_get_auth_refusal_includes_receipt_id(self):
        refusal = get_auth_refusal("github")
        assert isinstance(refusal, RigAuthRefusal)
        assert refusal.refusal_code
        assert refusal.receipt_id
        assert refusal.capability_id == "github"

    def test_get_auth_receipt_ref_has_all_fields(self):
        ref = get_auth_receipt_ref("receipt-123")
        assert isinstance(ref, RigAuthReceiptRef)
        assert ref.receipt_id == "receipt-123"
        assert ref.surface == "sdk"
        assert ref.trace_id
        assert ref.auth_state_hash
        assert ref.verdict

    def test_sdk_auth_models_no_raw_credentials(self):
        status = get_auth_status("github")
        status_dict = status.to_dict()
        assert "access_token" not in status_dict
        assert "refresh_token" not in status_dict
        assert "credential" not in status_dict
        assert "password" not in status_dict
        assert "secret" not in status_dict
        assert "api_key" not in status_dict

    def test_sdk_auth_models_validate_against_schema(self):
        status = get_auth_status("github")
        _v(status.to_dict(), "rig.relay.sdk.auth_status.v1.schema.json")

    def test_auth_capability_check_validates(self):
        result = check_auth_capability("github")
        _v(result.to_dict(), "rig.relay.sdk.auth_capability_check.v1.schema.json")

    def test_auth_refusal_validates(self):
        refusal = get_auth_refusal("acp.mutation")
        _v(refusal.to_dict(), "rig.relay.sdk.auth_refusal.v1.schema.json")

    def test_auth_receipt_ref_validates(self):
        ref = get_auth_receipt_ref("receipt-abc-123")
        _v(ref.to_dict(), "rig.relay.sdk.auth_receipt_ref.v1.schema.json")

    def test_get_credential_store_ref_hash(self):
        result = get_credential_store_ref_hash("github")
        assert isinstance(result, str)
        assert len(result) == 64

    def test_trace_ids_are_valid_uuids(self):
        status = get_auth_status("github")
        assert _is_valid_uuid(status.trace_id)

        result = check_auth_capability("github")
        assert _is_valid_uuid(result.trace_id)

        refusal = get_auth_refusal("github")
        assert _is_valid_uuid(refusal.trace_id)

    def test_auth_status_unauthenticated_for_unknown(self):
        status = get_auth_status("nonexistent_provider")
        assert status.auth_status == "unauthenticated"
        assert not status.auth_capable
        assert not status.refresh_needed

    def test_auth_capability_check_verdict_is_valid(self):
        result = check_auth_capability("sdk")
        assert result.verdict in {"ALLOWED", "REFUSED", "DEFERRED"}

    def test_auth_refusal_reason_non_empty(self):
        refusal = get_auth_refusal("github")
        assert refusal.reason
        assert "github" in refusal.reason
