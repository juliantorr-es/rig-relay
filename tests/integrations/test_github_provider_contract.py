"""GitHub Provider Contract v0 — contract, real-artifact, adversarial tests.

Test classifications:
  - contract: schema validation, structural assertions, policy compliance
  - real_artifact: tests consuming real JSON artifacts and schemas
  - adversarial: rejection of forbidden fields, invalid auth modes, token leakage

No network calls. No credentials. No GitHub API. No GitHub Actions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
INTEGRATIONS_DIR = REPO_ROOT / "docs" / "json" / "integrations"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_schema(artifact: dict, schema_id: str) -> list[str]:
    import jsonschema

    schema_path = SCHEMAS_DIR / f"{schema_id}.schema.json"
    if not schema_path.is_file():
        return [f"Schema file not found: {schema_path}"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    return [
        f"{'/'.join(str(p) for p in err.absolute_path)}: {err.message}"
        for err in validator.iter_errors(artifact)
    ]


class TestGitHubProviderSchemas:
    @pytest.mark.contract
    def test_all_four_schemas_exist_and_parse_as_json(self):
        for schema_id in [
            "rig.github_provider.contract.v1",
            "rig.github_provider.capability_manifest.v1",
            "rig.github_provider.auth_state.v1",
            "rig.github_provider.operation_receipt.v1",
        ]:
            schema_path = SCHEMAS_DIR / f"{schema_id}.schema.json"
            assert schema_path.is_file(), f"Missing schema: {schema_path}"
            schema = _load_json(schema_path)
            assert isinstance(schema, dict)
            assert "$schema" in schema

    @pytest.mark.contract
    def test_contract_v0_validates_against_schema(self):
        data = _load_json(INTEGRATIONS_DIR / "github_provider_contract_v0.v1.json")
        errors = _validate_schema(data, "rig.github_provider.contract.v1")
        assert not errors, f"Contract v0 schema errors: {errors}"

    @pytest.mark.contract
    def test_capability_manifest_validates_against_schema(self):
        data = _load_json(
            INTEGRATIONS_DIR / "github_provider_capability_manifest.v1.json"
        )
        errors = _validate_schema(data, "rig.github_provider.capability_manifest.v1")
        assert not errors, f"Capability manifest schema errors: {errors}"

    @pytest.mark.contract
    def test_contract_schema_version_matches_const(self):
        data = _load_json(INTEGRATIONS_DIR / "github_provider_contract_v0.v1.json")
        assert data["schema_version"] == "rig.github_provider.contract.v1"

    @pytest.mark.contract
    def test_capability_manifest_provider_id_is_github(self):
        data = _load_json(
            INTEGRATIONS_DIR / "github_provider_capability_manifest.v1.json"
        )
        assert data["provider_id"] == "github"


class TestAuthModes:
    @pytest.mark.contract
    def test_auth_modes_include_all_six_required(self):
        data = _load_json(INTEGRATIONS_DIR / "github_provider_contract_v0.v1.json")
        modes = {m["auth_mode"] for m in data["auth_modes"]}
        required = {
            "none",
            "device_flow",
            "oauth_web_flow",
            "github_app_installation",
            "github_app_user",
            "personal_access_token_manual_import",
        }
        assert modes == required, f"Missing modes: {required - modes}"

    @pytest.mark.contract
    def test_github_app_installation_automation_suitable(self):
        data = _load_json(INTEGRATIONS_DIR / "github_provider_contract_v0.v1.json")
        mode = next(
            m for m in data["auth_modes"] if m["auth_mode"] == "github_app_installation"
        )
        assert mode["allowed_for_automation"] is True
        assert mode["requires_user_interaction"] is False

    @pytest.mark.contract
    def test_github_app_user_is_user_attributed(self):
        data = _load_json(INTEGRATIONS_DIR / "github_provider_contract_v0.v1.json")
        mode = next(
            m for m in data["auth_modes"] if m["auth_mode"] == "github_app_user"
        )
        assert mode["requires_user_interaction"] is True
        assert mode["requires_github_app_registration"] is True

    @pytest.mark.contract
    def test_oauth_and_device_flow_require_user_interaction(self):
        data = _load_json(INTEGRATIONS_DIR / "github_provider_contract_v0.v1.json")
        for mode_name in ("oauth_web_flow", "device_flow"):
            mode = next(m for m in data["auth_modes"] if m["auth_mode"] == mode_name)
            assert mode["requires_user_interaction"] is True, (
                f"{mode_name} must require user interaction"
            )

    @pytest.mark.contract
    def test_pat_import_is_user_managed_not_recommended(self):
        data = _load_json(INTEGRATIONS_DIR / "github_provider_contract_v0.v1.json")
        mode = next(
            m
            for m in data["auth_modes"]
            if m["auth_mode"] == "personal_access_token_manual_import"
        )
        assert mode["token_lifetime_class"] == "user_managed"
        assert mode["allowed_for_automation"] is False

    @pytest.mark.contract
    def test_token_storage_policy_forbids_json_file(self):
        data = _load_json(INTEGRATIONS_DIR / "github_provider_contract_v0.v1.json")
        tsp = data["token_storage_policy"]
        assert tsp["forbids_json_file_storage"] is True
        assert "forbidden_json_file" in tsp["storage_authorities_forbidden"]


class TestAuthStateSchema:
    @pytest.mark.contract
    def test_valid_auth_state_validates_against_schema(self):
        data = {
            "schema_version": "rig.github_provider.auth_state.v1",
            "provider_id": "github",
            "auth_mode": "oauth_web_flow",
            "auth_status": "authenticated",
            "account_hash": "a" * 64,
            "installation_id_hash": "",
            "scopes_or_permissions": ["read:user", "user:email"],
            "token_storage_authority": "keychain_future",
            "token_material_present": True,
            "token_material_stored": False,
            "expires_at": "2026-06-01T00:00:00Z",
            "generated_at": "2026-05-19T00:00:00Z",
            "redaction_status": "clean",
        }
        errors = _validate_schema(data, "rig.github_provider.auth_state.v1")
        assert not errors, f"Auth state schema errors: {errors}"

    @pytest.mark.adversarial
    def test_auth_state_rejects_raw_token_field(self):
        data = {
            "schema_version": "rig.github_provider.auth_state.v1",
            "provider_id": "github",
            "auth_mode": "oauth_web_flow",
            "auth_status": "authenticated",
            "account_hash": "a" * 64,
            "installation_id_hash": "",
            "scopes_or_permissions": [],
            "token_storage_authority": "keychain_future",
            "token_material_present": True,
            "token_material_stored": False,
            "expires_at": "2026-06-01T00:00:00Z",
            "generated_at": "2026-05-19T00:00:00Z",
            "redaction_status": "clean",
            "access_token": "ghu_fake_token_value_here",
        }
        errors = _validate_schema(data, "rig.github_provider.auth_state.v1")
        assert errors, "Must reject auth state with raw access_token field"

    @pytest.mark.adversarial
    def test_auth_state_rejects_client_secret_field(self):
        data = {
            "schema_version": "rig.github_provider.auth_state.v1",
            "provider_id": "github",
            "auth_mode": "oauth_web_flow",
            "auth_status": "authenticated",
            "account_hash": "a" * 64,
            "installation_id_hash": "",
            "scopes_or_permissions": [],
            "token_storage_authority": "keychain_future",
            "token_material_present": True,
            "token_material_stored": False,
            "expires_at": "2026-06-01T00:00:00Z",
            "generated_at": "2026-05-19T00:00:00Z",
            "redaction_status": "clean",
            "client_secret": "fake_secret_value",
        }
        errors = _validate_schema(data, "rig.github_provider.auth_state.v1")
        assert errors, "Must reject auth state with raw client_secret field"

    @pytest.mark.adversarial
    def test_auth_state_token_material_stored_must_be_false(self):
        data = {
            "schema_version": "rig.github_provider.auth_state.v1",
            "provider_id": "github",
            "auth_mode": "oauth_web_flow",
            "auth_status": "authenticated",
            "account_hash": "a" * 64,
            "installation_id_hash": "",
            "scopes_or_permissions": [],
            "token_storage_authority": "keychain_future",
            "token_material_present": True,
            "token_material_stored": True,
            "expires_at": "2026-06-01T00:00:00Z",
            "generated_at": "2026-05-19T00:00:00Z",
            "redaction_status": "clean",
        }
        errors = _validate_schema(data, "rig.github_provider.auth_state.v1")
        assert errors, "Must reject token_material_stored=true"


class TestOperationReceiptSchema:
    @pytest.mark.contract
    def test_valid_operation_receipt_validates(self):
        data = {
            "schema_version": "rig.github_provider.operation_receipt.v1",
            "provider_id": "github",
            "operation_id": "op-001",
            "capability_id": "github.repo.metadata.read",
            "operation_kind": "Read repository metadata",
            "operation_class": "read_only",
            "auth_mode": "none",
            "auth_state_hash": "a" * 64,
            "request_hash": "b" * 64,
            "response_hash": "c" * 64,
            "repository_hash": "d" * 64,
            "actor_hash": "e" * 64,
            "verdict": "completed",
            "refusal_code": "",
            "redaction_status": "clean",
            "content_light": True,
            "generated_at": "2026-05-19T00:00:00Z",
        }
        errors = _validate_schema(data, "rig.github_provider.operation_receipt.v1")
        assert not errors, f"Operation receipt schema errors: {errors}"

    @pytest.mark.adversarial
    def test_operation_receipt_rejects_raw_token(self):
        data = {
            "schema_version": "rig.github_provider.operation_receipt.v1",
            "provider_id": "github",
            "operation_id": "op-001",
            "capability_id": "github.repo.metadata.read",
            "operation_kind": "Read repository metadata",
            "operation_class": "read_only",
            "auth_mode": "none",
            "auth_state_hash": "a" * 64,
            "request_hash": "b" * 64,
            "response_hash": "c" * 64,
            "repository_hash": "d" * 64,
            "actor_hash": "e" * 64,
            "verdict": "completed",
            "refusal_code": "",
            "redaction_status": "clean",
            "content_light": True,
            "generated_at": "2026-05-19T00:00:00Z",
            "raw_token": "ghp_fake12345",
        }
        errors = _validate_schema(data, "rig.github_provider.operation_receipt.v1")
        assert errors, "Must reject receipt with raw_token field"

    @pytest.mark.adversarial
    def test_operation_receipt_rejects_raw_response_body(self):
        data = {
            "schema_version": "rig.github_provider.operation_receipt.v1",
            "provider_id": "github",
            "operation_id": "op-001",
            "capability_id": "github.repo.metadata.read",
            "operation_kind": "Read repository metadata",
            "operation_class": "read_only",
            "auth_mode": "none",
            "auth_state_hash": "a" * 64,
            "request_hash": "b" * 64,
            "response_hash": "c" * 64,
            "repository_hash": "d" * 64,
            "actor_hash": "e" * 64,
            "verdict": "completed",
            "refusal_code": "",
            "redaction_status": "clean",
            "content_light": True,
            "generated_at": "2026-05-19T00:00:00Z",
            "raw_response_body": '{"name": "octocat", "private": false}',
        }
        errors = _validate_schema(data, "rig.github_provider.operation_receipt.v1")
        assert errors, "Must reject receipt with raw_response_body field"

    @pytest.mark.adversarial
    def test_operation_receipt_rejects_raw_prompt(self):
        data = {
            "schema_version": "rig.github_provider.operation_receipt.v1",
            "provider_id": "github",
            "operation_id": "op-001",
            "capability_id": "github.repo.metadata.read",
            "operation_kind": "Read repository metadata",
            "operation_class": "read_only",
            "auth_mode": "none",
            "auth_state_hash": "a" * 64,
            "request_hash": "b" * 64,
            "response_hash": "c" * 64,
            "repository_hash": "d" * 64,
            "actor_hash": "e" * 64,
            "verdict": "completed",
            "refusal_code": "",
            "redaction_status": "clean",
            "content_light": True,
            "generated_at": "2026-05-19T00:00:00Z",
            "raw_prompt": "Tell me about this repository",
        }
        errors = _validate_schema(data, "rig.github_provider.operation_receipt.v1")
        assert errors, "Must reject receipt with raw_prompt field"


class TestCapabilityManifest:
    @pytest.mark.contract
    def test_remote_mutation_capabilities_default_refused(self):
        data = _load_json(
            INTEGRATIONS_DIR / "github_provider_capability_manifest.v1.json"
        )
        mutation_caps = [
            c
            for c in data["capabilities"]
            if c["operation_class"]
            in ("remote_mutation", "credentialed_remote_mutation")
        ]
        assert len(mutation_caps) > 0
        for cap in mutation_caps:
            assert cap["default_allowed"] is False, (
                f"{cap['capability_id']} must default to refused"
            )

    @pytest.mark.contract
    def test_destructive_mutation_refused_in_v0(self):
        data = _load_json(
            INTEGRATIONS_DIR / "github_provider_capability_manifest.v1.json"
        )
        destructive_caps = [
            c
            for c in data["capabilities"]
            if c["operation_class"] == "destructive_remote_mutation"
        ]
        assert len(destructive_caps) > 0
        for cap in destructive_caps:
            assert cap["default_allowed"] is False, (
                f"{cap['capability_id']} must be refused in v0"
            )
            assert "destructive" in cap["refusal_code_when_denied"].lower()

    @pytest.mark.contract
    def test_read_only_capabilities_do_not_require_step_up(self):
        data = _load_json(
            INTEGRATIONS_DIR / "github_provider_capability_manifest.v1.json"
        )
        read_only_caps = [
            c for c in data["capabilities"] if c["operation_class"] == "read_only"
        ]
        assert len(read_only_caps) > 0
        for cap in read_only_caps:
            assert cap["requires_step_up"] is False, (
                f"{cap['capability_id']} should not require step-up"
            )

    @pytest.mark.contract
    def test_every_capability_requires_receipt(self):
        data = _load_json(
            INTEGRATIONS_DIR / "github_provider_capability_manifest.v1.json"
        )
        for cap in data["capabilities"]:
            assert cap["requires_receipt"] is True, (
                f"{cap['capability_id']} must require receipt"
            )

    @pytest.mark.contract
    def test_every_capability_has_refusal_code(self):
        data = _load_json(
            INTEGRATIONS_DIR / "github_provider_capability_manifest.v1.json"
        )
        for cap in data["capabilities"]:
            assert cap["refusal_code_when_denied"], (
                f"{cap['capability_id']} must have a refusal_code_when_denied"
            )

    @pytest.mark.contract
    def test_no_capability_stores_raw_content(self):
        data = _load_json(
            INTEGRATIONS_DIR / "github_provider_capability_manifest.v1.json"
        )
        for cap in data["capabilities"]:
            assert cap["stores_raw_content"] is False, (
                f"{cap['capability_id']} must not store raw content"
            )

    @pytest.mark.contract
    def test_capability_ids_are_unique(self):
        data = _load_json(
            INTEGRATIONS_DIR / "github_provider_capability_manifest.v1.json"
        )
        ids = [c["capability_id"] for c in data["capabilities"]]
        assert len(ids) == len(set(ids)), f"Duplicate capability IDs: {ids}"

    @pytest.mark.contract
    def test_capability_has_valid_operation_class(self):
        data = _load_json(
            INTEGRATIONS_DIR / "github_provider_capability_manifest.v1.json"
        )
        valid_classes = {
            "read_only",
            "safe_local_mutation",
            "remote_read",
            "remote_mutation",
            "credentialed_remote_mutation",
            "destructive_remote_mutation",
        }
        for cap in data["capabilities"]:
            assert cap["operation_class"] in valid_classes, (
                f"Invalid operation_class: {cap['operation_class']}"
            )

    @pytest.mark.adversarial
    def test_destructive_mutation_default_allowed_rejected(self):
        data = _load_json(
            INTEGRATIONS_DIR / "github_provider_capability_manifest.v1.json"
        )
        destructive_caps = [
            c
            for c in data["capabilities"]
            if c["operation_class"] == "destructive_remote_mutation"
        ]
        for cap in destructive_caps:
            assert cap["default_allowed"] is False, (
                f"{cap['capability_id']}: destructive must never default to allowed"
            )

    @pytest.mark.adversarial
    def test_capability_without_refusal_code_rejected(self):
        cap_data = {
            "capability_id": "test.no_refusal",
            "operation_kind": "Test",
            "operation_class": "read_only",
            "required_auth_modes": ["none"],
            "requires_step_up": False,
            "requires_receipt": True,
            "stores_raw_content": False,
            "content_light_output": True,
            "default_allowed": True,
        }
        errors = _validate_schema(
            cap_data, "rig.github_provider.capability_manifest.v1"
        )
        assert errors, "Capability without refusal_code_when_denied must be rejected"

    @pytest.mark.adversarial
    def test_capability_with_unknown_operation_class_rejected(self):
        cap_data = {
            "capability_id": "test.unknown_class",
            "operation_kind": "Test",
            "operation_class": "dangerous_experimental",
            "required_auth_modes": ["none"],
            "requires_step_up": False,
            "requires_receipt": True,
            "stores_raw_content": False,
            "content_light_output": True,
            "default_allowed": True,
            "refusal_code_when_denied": "test_refused",
        }
        errors = _validate_schema(
            cap_data, "rig.github_provider.capability_manifest.v1"
        )
        assert errors, "Unknown operation_class must be rejected"


class TestNoRawTokensInArtifacts:
    @pytest.mark.adversarial
    def test_no_github_token_patterns_in_contract(self):
        import re

        token_patterns: list[re.Pattern[str]] = [
            re.compile(r"ghp_[a-zA-Z0-9]{20,}"),
            re.compile(r"gho_[a-zA-Z0-9]{20,}"),
            re.compile(r"ghu_[a-zA-Z0-9]{20,}"),
            re.compile(r"ghs_[a-zA-Z0-9]{20,}"),
            re.compile(r"ghr_[a-zA-Z0-9]{20,}"),
        ]
        contract_path = INTEGRATIONS_DIR / "github_provider_contract_v0.v1.json"
        text = contract_path.read_text(encoding="utf-8")
        for pat in token_patterns:
            assert not pat.search(text), (
                f"Token pattern found in contract: {pat.pattern}"
            )

    @pytest.mark.adversarial
    def test_no_github_token_patterns_in_capability_manifest(self):
        import re

        token_patterns: list[re.Pattern[str]] = [
            re.compile(r"ghp_[a-zA-Z0-9]{20,}"),
            re.compile(r"gho_[a-zA-Z0-9]{20,}"),
            re.compile(r"ghu_[a-zA-Z0-9]{20,}"),
            re.compile(r"ghs_[a-zA-Z0-9]{20,}"),
            re.compile(r"ghr_[a-zA-Z0-9]{20,}"),
        ]
        manifest_path = INTEGRATIONS_DIR / "github_provider_capability_manifest.v1.json"
        text = manifest_path.read_text(encoding="utf-8")
        for pat in token_patterns:
            assert not pat.search(text), (
                f"Token pattern found in capability manifest: {pat.pattern}"
            )
