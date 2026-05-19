"""Tests for the batteries-included release candidate verification.

Validates the smoke report schema and the release candidate artifact.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCHEMAS_DIR = _REPO_ROOT / "docs" / "schemas"


def _load_schema(name: str) -> dict:
    path = _SCHEMAS_DIR / name
    return json.loads(path.read_text())


class TestBatteriesIncludedSchema:
    def test_schema_is_valid_json(self) -> None:
        schema = _load_schema(
            "rig.relay.release_candidate_batteries_included.v1.schema.json"
        )
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "properties" in schema

    def test_schema_validates_minimal_instance(self) -> None:
        schema = _load_schema(
            "rig.relay.release_candidate_batteries_included.v1.schema.json"
        )
        instance = {
            "schema_version": "rig.relay.release_candidate_batteries_included.v1",
            "run_id": "test-001",
            "branch": "main",
            "head_sha": "6ee5a2f72830ddfdfb5a104e961d063d7565f420",
            "generated_at": "2026-05-19T19:00:00Z",
            "overall_status": "pass",
            "surfaces_verified": [
                {
                    "surface_id": "schema_validation",
                    "surface_name": "Schema Validation",
                    "status": "verified",
                }
            ],
            "release_recommendation": "release_candidate_with_known_limitations",
            "files_changed": [],
            "files_created": [],
        }
        jsonschema.validate(instance, schema)

    def test_schema_rejects_invalid_overall_status(self) -> None:
        schema = _load_schema(
            "rig.relay.release_candidate_batteries_included.v1.schema.json"
        )
        instance = {
            "schema_version": "rig.relay.release_candidate_batteries_included.v1",
            "run_id": "test-001",
            "branch": "main",
            "head_sha": "6ee5a2f72830ddfdfb5a104e961d063d7565f420",
            "generated_at": "2026-05-19T19:00:00Z",
            "overall_status": "invalid_status",
            "surfaces_verified": [
                {
                    "surface_id": "schema_validation",
                    "surface_name": "Schema Validation",
                    "status": "verified",
                }
            ],
            "release_recommendation": "hold",
            "files_changed": [],
            "files_created": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_schema_rejects_invalid_release_rec(self) -> None:
        schema = _load_schema(
            "rig.relay.release_candidate_batteries_included.v1.schema.json"
        )
        instance = {
            "schema_version": "rig.relay.release_candidate_batteries_included.v1",
            "run_id": "test-001",
            "branch": "main",
            "head_sha": "6ee5a2f72830ddfdfb5a104e961d063d7565f420",
            "generated_at": "2026-05-19T19:00:00Z",
            "overall_status": "pass",
            "surfaces_verified": [
                {
                    "surface_id": "schema_validation",
                    "surface_name": "Schema Validation",
                    "status": "verified",
                }
            ],
            "release_recommendation": "not_a_valid_recommendation",
            "files_changed": [],
            "files_created": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_schema_requires_surfaces_verified(self) -> None:
        schema = _load_schema(
            "rig.relay.release_candidate_batteries_included.v1.schema.json"
        )
        instance = {
            "schema_version": "rig.relay.release_candidate_batteries_included.v1",
            "run_id": "test-001",
            "branch": "main",
            "head_sha": "6ee5a2f72830ddfdfb5a104e961d063d7565f420",
            "generated_at": "2026-05-19T19:00:00Z",
            "overall_status": "pass",
            "surfaces_verified": [
                {
                    "surface_id": "schema_validation",
                    "surface_name": "Schema Validation",
                    "status": "verified",
                }
            ],
            "release_recommendation": "hold",
            "files_changed": [],
            "files_created": [],
        }
        jsonschema.validate(instance, schema)


class TestACPDisabledTools:
    def test_module_imports(self) -> None:
        from rig_relay.acp._disabled_tools import NON_INTERACTIVE_DISABLED_TOOLS

        assert isinstance(NON_INTERACTIVE_DISABLED_TOOLS, list)
        assert "exit_plan_mode" in NON_INTERACTIVE_DISABLED_TOOLS
        assert "checkpoint" in NON_INTERACTIVE_DISABLED_TOOLS

    def test_all_entries_are_strings(self) -> None:
        from rig_relay.acp._disabled_tools import NON_INTERACTIVE_DISABLED_TOOLS

        for entry in NON_INTERACTIVE_DISABLED_TOOLS:
            assert isinstance(entry, str)


class TestACPExceptions:
    def test_new_error_codes_defined(self) -> None:
        from rig_relay.acp import exceptions as ex

        assert ex.REFUSAL_GENERAL == -31005
        assert ex.REFUSAL_SESSION_RESUME == -31006
        assert ex.REFUSAL_LIVE_AUTH == -31007
        assert ex.REFUSAL_CAPABILITY_DISABLED == -31008
        assert ex.REFUSAL_WORKSPACE_ISOLATION == -31009
        assert ex.REFUSAL_STALE_SESSION == -31010
        assert ex.REFUSAL_MUTATION_DENIED == -31011

    def test_rig_refusal_error(self) -> None:
        from rig_relay.acp.exceptions import RigRefusalError

        err = RigRefusalError(
            refusal_code="test_refusal",
            detail="Test refusal message",
            remediation="Try running 'uv run rig-relay' first.",
        )
        assert err.code == -31005
        data = err.data or {}
        assert data.get("refusal_code") == "test_refusal"
        assert data.get("remediation") == "Try running 'uv run rig-relay' first."
        assert data.get("content_light") is True

    def test_session_resume_refusal_error(self) -> None:
        from rig_relay.acp.exceptions import SessionResumeRefusalError

        err = SessionResumeRefusalError(
            session_id="test-session",
            detail="Session resume is not supported",
            remediation="Use new_session with the same cwd.",
        )
        assert err.code == -31006
        data = err.data or {}
        assert data.get("session_id") == "test-session"
        assert "remediation" in data

    def test_live_auth_refusal_error(self) -> None:
        from rig_relay.acp.exceptions import LiveAuthRefusalError

        err = LiveAuthRefusalError(
            method_id="terminal",
            detail="Live authentication is deferred",
            remediation="Complete provider setup first.",
        )
        assert err.code == -31007
        data = err.data or {}
        assert data.get("method_id") == "terminal"

    def test_capability_disabled_error(self) -> None:
        from rig_relay.acp.exceptions import CapabilityDisabledError

        err = CapabilityDisabledError(
            capability="mcp.mutation", detail="Capability gated"
        )
        assert err.code == -31008
        data = err.data or {}
        assert data.get("capability") == "mcp.mutation"

    def test_workspace_isolation_error(self) -> None:
        from rig_relay.acp.exceptions import WorkspaceIsolationError

        err = WorkspaceIsolationError(detail="Outside allowed workspace")
        assert err.code == -31009

    def test_stale_session_error(self) -> None:
        from rig_relay.acp.exceptions import StaleSessionError

        err = StaleSessionError(session_id="old-session", detail="Session has expired")
        assert err.code == -31010
        data = err.data or {}
        assert data.get("session_id") == "old-session"

    def test_mutation_denied_error(self) -> None:
        from rig_relay.acp.exceptions import MutationDeniedError

        err = MutationDeniedError(
            tool_name="write_file", detail="Mutation denied in read-only mode"
        )
        assert err.code == -31011
        data = err.data or {}
        assert data.get("tool_name") == "write_file"


class TestA2APromotionReadiness:
    def test_file_exists(self) -> None:
        path = (
            _REPO_ROOT
            / "docs"
            / "json"
            / "protocols"
            / "a2a_promotion_readiness.v1.json"
        )
        assert path.exists()

    def test_file_is_valid_json(self) -> None:
        path = (
            _REPO_ROOT
            / "docs"
            / "json"
            / "protocols"
            / "a2a_promotion_readiness.v1.json"
        )
        data = json.loads(path.read_text())
        assert data["external_enabled"] is False
        assert data["local_only"] is True
        assert len(data["promotion_gates"]) == 10
        passing = sum(1 for g in data["promotion_gates"] if g["status"] == "passing")
        blocked = sum(1 for g in data["promotion_gates"] if g["status"] == "blocked")
        assert passing >= 8
        assert blocked <= 2


class TestReleaseCandidateSmokeScript:
    def test_script_exists(self) -> None:
        path = _REPO_ROOT / "scripts" / "rig_release_candidate_smoke.py"
        assert path.exists()

    def test_script_is_parseable(self) -> None:
        path = _REPO_ROOT / "scripts" / "rig_release_candidate_smoke.py"
        source = path.read_text()
        compile(source, str(path), "exec")
