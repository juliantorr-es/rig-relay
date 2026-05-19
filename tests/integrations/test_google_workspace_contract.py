"""Google Workspace Provider Contract v1 — contract, real-artifact, adversarial tests.

No live Google API calls. No credentials.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
INTEGRATIONS_DIR = REPO_ROOT / "docs" / "json" / "integrations"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(artifact: dict, schema_id: str) -> list[str]:
    import jsonschema

    schema = _load(SCHEMAS_DIR / f"{schema_id}.schema.json")
    return [e.message for e in jsonschema.Draft7Validator(schema).iter_errors(artifact)]


class TestSchemasExistAndValidate:
    @pytest.mark.contract
    def test_all_google_workspace_schemas_validate(self):
        for sid in [
            "contract.v1",
            "capability_manifest.v1",
            "auth_state.v1",
            "operation_receipt.v1",
            "status_snapshot.v1",
            "v1_readiness.v1",
        ]:
            schema_path = SCHEMAS_DIR / f"rig.google_workspace.{sid}.schema.json"
            assert schema_path.is_file(), f"Missing: {schema_path}"
            assert isinstance(_load(schema_path), dict)

    @pytest.mark.contract
    def test_capability_manifest_artifact_validates(self):
        data = _load(INTEGRATIONS_DIR / "google_workspace_capability_manifest.v1.json")
        assert not _validate(data, "rig.google_workspace.capability_manifest.v1")

    @pytest.mark.contract
    def test_manifest_every_capability_has_required_scopes(self):
        data = _load(INTEGRATIONS_DIR / "google_workspace_capability_manifest.v1.json")
        for c in data["capabilities"]:
            assert c.get("required_scopes"), (
                f"{c['capability_id']} missing required_scopes"
            )

    @pytest.mark.contract
    def test_contract_artifact_validates(self):
        data = _load(INTEGRATIONS_DIR / "google_workspace_contract_v1.v1.json")
        assert not _validate(data, "rig.google_workspace.contract.v1")

    @pytest.mark.adversarial
    def test_auth_state_schema_rejects_raw_token_fields(self):
        data = {
            "schema_version": "rig.google_workspace.auth_state.v1",
            "provider_id": "google_workspace",
            "auth_mode": "none",
            "auth_status": "unauthenticated",
            "account_hash": "",
            "scope_grants": [],
            "generated_at": "2026-01-01T00:00:00Z",
            "redaction_status": "clean",
            "access_token": "ya29.fake",
        }
        assert _validate(data, "rig.google_workspace.auth_state.v1")

    @pytest.mark.adversarial
    def test_auth_state_schema_rejects_private_key_fields(self):
        data = {
            "schema_version": "rig.google_workspace.auth_state.v1",
            "provider_id": "google_workspace",
            "auth_mode": "none",
            "auth_status": "unauthenticated",
            "account_hash": "",
            "scope_grants": [],
            "generated_at": "2026-01-01T00:00:00Z",
            "redaction_status": "clean",
            "private_key": "-----BEGIN PRIVATE KEY-----\n...",
        }
        assert _validate(data, "rig.google_workspace.auth_state.v1")

    @pytest.mark.adversarial
    def test_receipt_schema_rejects_raw_workspace_content(self):
        data = {
            "schema_version": "rig.google_workspace.operation_receipt.v1",
            "provider_id": "google_workspace",
            "operation_id": "x",
            "capability_id": "x",
            "operation_class": "public_read",
            "auth_mode": "none",
            "auth_state_hash": "a" * 64,
            "request_hash": "b" * 64,
            "response_hash": "c" * 64,
            "subject_hash": "",
            "customer_hash": "",
            "resource_hash": "",
            "verdict": "allowed",
            "refusal_code": "",
            "redaction_status": "clean",
            "content_light": True,
            "generated_at": "2026-01-01T00:00:00Z",
            "raw_email": "user@example.com",
        }
        assert _validate(data, "rig.google_workspace.operation_receipt.v1")

    @pytest.mark.contract
    def test_contract_artifact_documents_restricted_scope_deferral(self):
        data = _load(INTEGRATIONS_DIR / "google_workspace_contract_v1.v1.json")
        rsp = data["scope_taxonomy"]["restricted_scope_policy"]
        assert rsp["live_refused"] is True
        assert rsp["requires_security_assessment"] is True
