from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate
import pytest

from rig_relay.acp._local_auth import (
    build_acp_local_auth_state,
    compute_credential_store_ref_hash,
)
from rig_relay.acp._protocol import ProtocolMixin
from rig_relay.acp._session_lifecycle import SessionLifecycleMixin
from rig_relay.governance.service_state import (
    LocalProfile,
    ProfileState,
    ServiceState,
    set_profile_store_override,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


class _FakeProfileStore:
    def load(self) -> LocalProfile | None:
        return LocalProfile(
            profile_id="test",
            created_at="2026-01-01T00:00:00Z",
            local_auth_enabled=False,
            profile_state=ProfileState.UNLOCKED,
        )

    def exists(self) -> bool:
        return True

    def profile_summary(self):
        return {
            "exists": True,
            "profile_state": ProfileState.UNLOCKED.value,
            "service_state": ServiceState.READY.value,
            "local_auth_enabled": False,
            "passkey_registered": False,
        }


def _setup_fake_profile() -> None:
    set_profile_store_override(_FakeProfileStore())  # type: ignore[arg-type]


def _teardown_fake_profile() -> None:
    set_profile_store_override(None)


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _field_meta(result: Any) -> dict[str, Any]:
    assert result is not None
    assert result.field_meta is not None
    return result.field_meta


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


class TestACPLocalAuthState:
    def test_local_auth_state_validates(self):
        schema = _load_schema("rig.relay.acp.auth_state.v1.schema.json")
        state = build_acp_local_auth_state(
            auth_status="deferred",
            auth_method="unsupported",
            capability_id="acp.authenticate",
            trace_id="trace-1",
            deferred_reason="not configured",
        )
        validate(state.to_dict(), schema)

    def test_local_auth_state_rejects_raw_tokens(self):
        state = build_acp_local_auth_state(
            auth_status="authenticated",
            auth_method="none",
            capability_id="acp.authenticate",
        )
        d = state.to_dict()
        assert "access_token" not in d
        assert "api_key" not in d
        assert "secret" not in d
        assert "token" not in d
        assert d["content_light"] is True

    def test_build_auth_state_deferred_when_unconfigured(self):
        state = build_acp_local_auth_state(
            auth_status="deferred",
            auth_method="unsupported",
            capability_id="acp.authenticate",
            deferred_reason="Live authentication is deferred",
        )
        assert state.auth_status == "deferred"
        assert state.auth_method == "unsupported"
        assert state.deferred_reason == "Live authentication is deferred"

    def test_auth_state_has_stable_schema_version(self):
        state = build_acp_local_auth_state(
            auth_status="deferred", auth_method="none", capability_id="acp.authenticate"
        )
        assert state.schema_version == "rig.relay.acp.auth_state.v1"

    def test_credential_store_ref_hash_computed_from_metadata(self):
        h1 = compute_credential_store_ref_hash()
        h2 = compute_credential_store_ref_hash()
        assert len(h1) == 64
        assert isinstance(h1, str)
        assert h1 != h2

    def test_auth_state_hash_is_deterministic_for_same_input(self):
        s1 = build_acp_local_auth_state(
            auth_status="deferred",
            auth_method="none",
            capability_id="acp.authenticate",
            trace_id="trace-1",
        )
        s2 = build_acp_local_auth_state(
            auth_status="deferred",
            auth_method="none",
            capability_id="acp.authenticate",
            trace_id="trace-1",
        )
        assert s1.auth_state_hash == s2.auth_state_hash

    def test_auth_state_hash_different_for_different_inputs(self):
        s1 = build_acp_local_auth_state(
            auth_status="deferred",
            auth_method="none",
            capability_id="acp.authenticate",
            trace_id="trace-1",
        )
        s2 = build_acp_local_auth_state(
            auth_status="refused",
            auth_method="none",
            capability_id="acp.authenticate",
            trace_id="trace-2",
        )
        assert s1.auth_state_hash != s2.auth_state_hash

    def test_no_raw_secrets_in_field_names(self):
        state = build_acp_local_auth_state(
            auth_status="deferred", auth_method="none", capability_id="acp.authenticate"
        )
        d = state.to_dict()
        for key in d:
            assert "secret" not in key.lower()
            assert "password" not in key.lower()
            assert "raw" not in key.lower()


class TestAuthenticateReturnsAuthState:
    def test_authenticate_returns_auth_state_not_just_refusal(self):
        mixin = _TestProtocolMixin()
        result = asyncio.run(mixin.authenticate("terminal", trace_id="t1"))
        meta = _field_meta(result)
        assert "auth_state" in meta
        auth_state = meta["auth_state"]
        assert isinstance(auth_state, dict)
        assert auth_state["auth_status"] == "deferred"

    def test_authenticate_refusal_includes_capability_id(self):
        mixin = _TestProtocolMixin()
        result = asyncio.run(mixin.authenticate("terminal", trace_id="t1"))
        meta = _field_meta(result)
        auth_state = meta["auth_state"]
        assert auth_state["capability_id"] == "acp.authenticate"

    def test_authenticate_refusal_includes_refusal_metadata(self):
        mixin = _TestProtocolMixin()
        result = asyncio.run(mixin.authenticate("terminal", trace_id="t1"))
        meta = _field_meta(result)
        refusal = meta["refusal"]
        assert refusal["refusal_code"] == "acp.authenticate.deferred_or_unconfigured"
        assert refusal["content_light"] is True

    def test_authenticate_auth_state_validates_against_schema(self):
        schema = _load_schema("rig.relay.acp.auth_state.v1.schema.json")
        mixin = _TestProtocolMixin()
        result = asyncio.run(mixin.authenticate("terminal", trace_id="t1"))
        meta = _field_meta(result)
        validate(meta["auth_state"], schema)

    def test_authenticate_refusal_validates_against_schema(self):
        refusal_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        mixin = _TestProtocolMixin()
        result = asyncio.run(mixin.authenticate("terminal", trace_id="t1"))
        meta = _field_meta(result)
        validate(meta["refusal"], refusal_schema)

    def test_authenticate_refusal_code_is_acp_authenticate_deferred(self):
        mixin = _TestProtocolMixin()
        result = asyncio.run(mixin.authenticate("terminal"))
        meta = _field_meta(result)
        refusal = meta["refusal"]
        assert refusal["refusal_code"] == "acp.authenticate.deferred_or_unconfigured"


class TestResumeSessionReportsUnsupported:
    def setup_method(self) -> None:
        _setup_fake_profile()

    def teardown_method(self) -> None:
        _teardown_fake_profile()

    def test_session_resume_reports_not_supported_in_response(self):
        mixin = _TestSessionLifecycleMixin()
        cwd = str(Path.cwd())
        result = asyncio.run(mixin.resume_session(cwd=cwd, session_id="s1"))
        meta = _field_meta(result)
        assert meta.get("resumable") is False

    def test_session_resume_includes_auth_state(self):
        mixin = _TestSessionLifecycleMixin()
        cwd = str(Path.cwd())
        result = asyncio.run(mixin.resume_session(cwd=cwd, session_id="s1"))
        meta = _field_meta(result)
        auth_state = meta["auth_state"]
        assert auth_state["auth_status"] == "deferred"
        assert auth_state["capability_id"] == "acp.session_resume"

    def test_session_resume_auth_state_validates(self):
        schema = _load_schema("rig.relay.acp.auth_state.v1.schema.json")
        mixin = _TestSessionLifecycleMixin()
        cwd = str(Path.cwd())
        result = asyncio.run(mixin.resume_session(cwd=cwd, session_id="s1"))
        meta = _field_meta(result)
        validate(meta["auth_state"], schema)

    def test_session_resume_includes_refusal_metadata(self):
        mixin = _TestSessionLifecycleMixin()
        cwd = str(Path.cwd())
        result = asyncio.run(mixin.resume_session(cwd=cwd, session_id="s1"))
        meta = _field_meta(result)
        refusal = meta["refusal"]
        assert refusal["refusal_code"] == "not_implemented_deferred"
        assert refusal["content_light"] is True

    def test_session_resume_no_raw_secrets_leaked(self):
        mixin = _TestSessionLifecycleMixin()
        cwd = str(Path.cwd())
        result = asyncio.run(
            mixin.resume_session(
                cwd=cwd,
                session_id="s1",
                trace_id="t1",
                api_key="sk-should-not-appear",
                secret="also-should-not-appear",
            )
        )
        meta = _field_meta(result)
        serialized = json.dumps(meta)
        assert "sk-should-not-appear" not in serialized
        assert "also-should-not-appear" not in serialized


class TestCapabilityProfile:
    def test_capability_profile_authenticate_supported_false(self):
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
        assert profile["authenticate_supported"] is False

    def test_capability_profile_session_resume_supported_false(self):
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
        assert profile["session_resume_supported"] is False

    def test_capability_profile_rejects_when_auth_supported_true(self):
        schema = _load_schema("rig.relay.acp.capability_profile.v1.schema.json")
        profile = {
            "schema_version": "rig.relay.acp.capability_profile.v1",
            "generated_at": "2026-01-01T00:00:00Z",
            "authenticate_supported": True,
            "session_resume_supported": True,
            "session_lifecycle_supported": {
                "initialize": True,
                "authenticate": True,
                "new": True,
                "load": True,
                "prompt": True,
                "cancel": True,
                "close": True,
                "fork": True,
                "resume": True,
            },
            "fs_capabilities": {"read_allowed": True, "write_allowed": False},
            "terminal_allowed": True,
            "mutation_refused": True,
            "credential_refused": True,
            "content_light": True,
        }
        with pytest.raises(ValidationError):
            validate(profile, schema)

    def test_capability_profile_rejects_when_fields_missing(self):
        schema = _load_schema("rig.relay.acp.capability_profile.v1.schema.json")
        profile = {
            "schema_version": "rig.relay.acp.capability_profile.v1",
            "generated_at": "2026-01-01T00:00:00Z",
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
        with pytest.raises(ValidationError):
            validate(profile, schema)
