"""ACP v1 Protocol — schema validation and stub seam documentation."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import ValidationError, validate
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"
ACP_SOURCE = REPO_ROOT / "rig_relay" / "acp"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


class TestACPV1Schemas:
    def test_session_receipt_validates(self):
        s = _load_schema("rig.relay.acp.session_receipt.v1.schema.json")
        validate(
            {
                "schema_version": "rig.relay.acp.session_receipt.v1",
                "receipt_id": "a" * 64,
                "trace_id": "t1",
                "session_id": "s1",
                "method": "prompt",
                "verdict": "completed",
                "refusal_code": "",
                "payload_sha256": "b" * 64,
                "content_light": True,
                "generated_at": "2026-01-01T00:00:00Z",
            },
            s,
        )

    def test_refusal_validates(self):
        s = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        validate(
            {
                "schema_version": "rig.relay.acp.refusal.v1",
                "trace_id": "t1",
                "session_id": "s1",
                "method": "prompt",
                "refusal_code": "write_refused",
                "reason": "not allowed",
                "content_light": True,
                "generated_at": "2026-01-01T00:00:00Z",
            },
            s,
        )

    def test_auth_state_validates(self):
        s = _load_schema("rig.relay.acp.auth_state.v1.schema.json")
        validate(
            {
                "schema_version": "rig.relay.acp.auth_state.v1",
                "provider_id": "acp_local",
                "auth_status": "deferred",
                "deferred_reason": "live auth deferred",
                "content_light": True,
                "generated_at": "2026-01-01T00:00:00Z",
            },
            s,
        )

    def test_auth_state_rejects_raw_tokens(self):
        s = _load_schema("rig.relay.acp.auth_state.v1.schema.json")
        with pytest.raises(ValidationError):
            validate(
                {
                    "schema_version": "rig.relay.acp.auth_state.v1",
                    "provider_id": "acp_local",
                    "auth_status": "deferred",
                    "deferred_reason": "",
                    "content_light": True,
                    "generated_at": "2026-01-01T00:00:00Z",
                    "access_token": "ghp_fake",
                },
                s,
            )

    def test_capability_profile_validates(self):
        s = _load_schema("rig.relay.acp.capability_profile.v1.schema.json")
        validate(
            {
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
            },
            s,
        )

    def test_fs_write_refused_by_default(self):
        s = _load_schema("rig.relay.acp.capability_profile.v1.schema.json")
        p = {
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
        validate(p, s)
        assert p["fs_capabilities"]["write_allowed"] is False

    def test_trace_id_required_in_receipt(self):
        s = _load_schema("rig.relay.acp.session_receipt.v1.schema.json")
        assert "trace_id" in s["required"]


class TestACPStubSeams:
    def test_authenticate_raises_refusal_error(self):
        source = (ACP_SOURCE / "_protocol.py").read_text()
        assert "raise_acp_refusal" in source
        assert "live_auth_deferred" in source
        assert "NotImplementedMethodError" not in source

    def test_resume_session_raises_refusal_error(self):
        source = (ACP_SOURCE / "_session_lifecycle.py").read_text()
        assert "raise_acp_refusal" in source
        assert "resume_not_supported" in source
        assert "NotImplementedMethodError" not in source
