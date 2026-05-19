from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

from jsonschema import ValidationError, validate
import pytest

from rig_relay.acp._protocol import ProtocolMixin
from rig_relay.acp._refusal_adapter import (
    build_acp_permission_refusal,
    build_acp_refusal,
    build_acp_session_refusal,
)
from rig_relay.acp._session_lifecycle import SessionLifecycleMixin
from rig_relay.acp.exceptions import RefusalError

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _get_refusal(exc_info: pytest.ExceptionInfo[RefusalError]) -> dict:
    assert exc_info.value is not None
    err = cast(RefusalError, exc_info.value)
    assert err.data is not None
    return err.data["refusal"]


class _TestProtocolMixin(ProtocolMixin):
    def __init__(self) -> None:
        self.sessions: dict = {}
        self.client = None

    def _find_acp_session_by_vibe_session_id(self, session_id: str) -> None:
        return None

    def _load_session_logging_config(self) -> None:
        return None


class _TestSessionLifecycleMixin(SessionLifecycleMixin):
    def __init__(self) -> None:
        self.sessions: dict = {}
        self.client = None
        self.client_capabilities = None
        self.client_info = None

    def _store_mcp_servers(self, mcp_servers: object | None) -> None:
        pass


class TestBuildAcpRefusal:
    def test_build_returns_schema_valid_dict(self):
        refusal_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        result = build_acp_refusal(
            refusal_code="write_refused",
            reason="not allowed",
            method="prompt",
            trace_id="t1",
            session_id="s1",
        )
        validate(result, refusal_schema)

    def test_refusal_has_correct_schema_version(self):
        result = build_acp_refusal(
            refusal_code="test_code", reason="test reason", method="test_method"
        )
        assert result["schema_version"] == "rig.relay.acp.refusal.v1"

    def test_refusal_includes_all_required_fields(self):
        result = build_acp_refusal(
            refusal_code="test_code", reason="test reason", method="test_method"
        )
        required = {
            "schema_version",
            "trace_id",
            "session_id",
            "method",
            "refusal_code",
            "reason",
            "content_light",
            "generated_at",
        }
        assert required <= set(result.keys())

    def test_content_light_is_always_true(self):
        result = build_acp_refusal(
            refusal_code="test_code", reason="test reason", method="test_method"
        )
        assert result["content_light"] is True

    def test_no_extra_fields_beyond_schema(self):
        refusal_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        result = build_acp_refusal(
            refusal_code="test_code", reason="test reason", method="test_method"
        )
        allowed = set(refusal_schema["properties"].keys())
        extra = set(result.keys()) - allowed
        assert not extra, f"Extra fields: {extra}"

    def test_refusal_rejects_invalid_code(self):
        refusal_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        with pytest.raises(ValidationError):
            validate({}, refusal_schema)


class TestRefusalWiring:
    def test_authenticate_unsupported_returns_schema_valid_refusal(self):
        refusal_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        mixin = _TestProtocolMixin()
        result = asyncio.run(mixin.authenticate("fake_method_id"))
        assert result is not None
        assert result.field_meta is not None
        validate(result.field_meta["refusal"], refusal_schema)

    def test_authenticate_refusal_has_refusal_code_live_auth_deferred(self):
        mixin = _TestProtocolMixin()
        result = asyncio.run(mixin.authenticate("fake_method_id"))
        assert result is not None
        assert result.field_meta is not None
        assert (
            result.field_meta["refusal"]["refusal_code"]
            == "acp.authenticate.deferred_or_unconfigured"
        )

    def test_resume_session_unsupported_returns_schema_valid_refusal(self):
        refusal_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        mixin = _TestSessionLifecycleMixin()
        result = asyncio.run(mixin.resume_session(cwd=str(Path.cwd()), session_id="s1"))
        assert result is not None
        assert result.field_meta is not None
        validate(result.field_meta["refusal"], refusal_schema)

    def test_resume_refusal_has_refusal_code_resume_not_supported(self):
        mixin = _TestSessionLifecycleMixin()
        result = asyncio.run(mixin.resume_session(cwd=str(Path.cwd()), session_id="s1"))
        assert result is not None
        assert result.field_meta is not None
        assert (
            result.field_meta["refusal"]["refusal_code"] == "not_implemented_deferred"
        )

    def test_unknown_ext_method_returns_schema_valid_refusal(self):
        refusal_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        mixin = _TestProtocolMixin()
        with pytest.raises(RefusalError) as exc_info:
            asyncio.run(mixin.ext_method("unknown/method", {}))

        validate(_get_refusal(exc_info), refusal_schema)

    def test_unknown_ext_method_refusal_code_is_not_implemented_deferred(self):
        mixin = _TestProtocolMixin()
        with pytest.raises(RefusalError) as exc_info:
            asyncio.run(mixin.ext_method("unknown/method", {}))

        assert _get_refusal(exc_info)["refusal_code"] == "not_implemented_deferred"

    def test_refusal_preserves_trace_id_when_provided(self):
        result = build_acp_refusal(
            refusal_code="test_code",
            reason="test reason",
            method="test_method",
            trace_id="trace-abc-123",
        )
        assert result["trace_id"] == "trace-abc-123"

    def test_refusal_preserves_session_id_when_provided(self):
        result = build_acp_refusal(
            refusal_code="test_code",
            reason="test reason",
            method="test_method",
            session_id="session-xyz-456",
        )
        assert result["session_id"] == "session-xyz-456"

    def test_refusal_is_content_light_no_raw_params_echoed(self):
        mixin = _TestProtocolMixin()
        result = asyncio.run(mixin.authenticate("fake_method_id"))
        assert result is not None
        assert result.field_meta is not None
        refusal = result.field_meta["refusal"]
        assert refusal["content_light"] is True
        assert "params" not in refusal
        assert "kwargs" not in refusal
        assert "raw" not in refusal

    def test_capability_profile_still_has_authenticate_false(self):
        schema = _load_schema("rig.relay.acp.capability_profile.v1.schema.json")
        profile = {
            "schema_version": "rig.relay.acp.capability_profile.v1",
            "generated_at": "2026-01-01T00:00:00Z",
            "authenticate_supported": False,
            "session_resume_supported": False,
            "session_lifecycle_supported": {
                "initialize": True,
                "authenticate": False,
                "new": True,
                "load": True,
                "prompt": True,
                "cancel": True,
                "close": True,
                "fork": True,
                "resume": False,
            },
            "fs_capabilities": {"read_allowed": True, "write_allowed": False},
            "terminal_allowed": True,
            "mutation_refused": True,
            "credential_refused": True,
            "content_light": True,
        }
        validate(profile, schema)
        assert profile["session_lifecycle_supported"]["authenticate"] is False

    def test_capability_profile_still_has_resume_false(self):
        schema = _load_schema("rig.relay.acp.capability_profile.v1.schema.json")
        profile = {
            "schema_version": "rig.relay.acp.capability_profile.v1",
            "generated_at": "2026-01-01T00:00:00Z",
            "authenticate_supported": False,
            "session_resume_supported": False,
            "session_lifecycle_supported": {
                "initialize": True,
                "authenticate": False,
                "new": True,
                "load": True,
                "prompt": True,
                "cancel": True,
                "close": True,
                "fork": True,
                "resume": False,
            },
            "fs_capabilities": {"read_allowed": True, "write_allowed": False},
            "terminal_allowed": True,
            "mutation_refused": True,
            "credential_refused": True,
            "content_light": True,
        }
        validate(profile, schema)
        assert profile["session_lifecycle_supported"]["resume"] is False

    def test_refusal_includes_method_in_refusal_dict(self):
        result = build_acp_refusal(
            refusal_code="test_code", reason="test reason", method="my_custom_method"
        )
        assert result["method"] == "my_custom_method"

    def test_refusal_generated_at_is_iso_format(self):
        from datetime import datetime

        result = build_acp_refusal(
            refusal_code="test_code", reason="test reason", method="test_method"
        )
        dt = datetime.fromisoformat(result["generated_at"])
        assert dt.tzinfo is not None

    def test_refusal_skips_auth_payload_echo_when_secrets_in_kwargs(self):
        result = build_acp_refusal(
            refusal_code="live_auth_deferred",
            reason="Live authentication is deferred",
            method="authenticate",
        )
        assert "access_token" not in result
        assert "api_key" not in result
        assert "secret" not in result
        assert result["content_light"] is True

    def test_refusal_includes_surface_acp(self):
        result = build_acp_refusal(
            refusal_code="test_code", reason="test reason", method="test_method"
        )
        assert result["surface"] == "acp"

    def test_no_extra_fields_includes_surface_only(self):
        refusal_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        result = build_acp_refusal(
            refusal_code="test_code", reason="test reason", method="test_method"
        )
        validate(result, refusal_schema)


class TestBuildAcpSessionRefusal:
    def test_builds_schema_valid_refusal(self):
        refusal_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        result = build_acp_session_refusal(
            refusal_code="not_implemented_deferred",
            reason="Session operation deferred",
            method="resume",
            trace_id="t1",
            session_id="s1",
        )
        validate(result, refusal_schema)

    def test_sets_method_correctly(self):
        result = build_acp_session_refusal(
            refusal_code="test_code", reason="reason", method="fork"
        )
        assert result["method"] == "fork"

    def test_surface_is_acp(self):
        result = build_acp_session_refusal(
            refusal_code="test_code", reason="reason", method="new_session"
        )
        assert result["surface"] == "acp"


class TestBuildAcpPermissionRefusal:
    def test_builds_schema_valid_refusal(self):
        refusal_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        result = build_acp_permission_refusal(
            permission="write_file",
            reason="Write not allowed",
            trace_id="t1",
            session_id="s1",
        )
        validate(result, refusal_schema)

    def test_uses_permission_missing_code(self):
        result = build_acp_permission_refusal(permission="bash", reason="Not allowed")
        assert result["refusal_code"] == "refused:permission_missing"

    def test_method_includes_permission_prefix(self):
        result = build_acp_permission_refusal(permission="grep", reason="Not allowed")
        assert result["method"] == "permission/grep"

    def test_surface_is_acp(self):
        result = build_acp_permission_refusal(
            permission="write_file", reason="Not allowed"
        )
        assert result["surface"] == "acp"
