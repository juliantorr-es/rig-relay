from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
INTEGRATIONS_DIR = REPO_ROOT / "docs" / "json" / "integrations"

MANIFEST_SCHEMA_PATH = SCHEMAS_DIR / "rig.integration.provider_manifest.v1.schema.json"
PERMISSION_POLICY_SCHEMA_PATH = (
    SCHEMAS_DIR / "rig.integration.permission_policy.v1.schema.json"
)

GITHUB_MANIFEST_PATH = INTEGRATIONS_DIR / "github_provider_manifest.v1.json"
GDRIVE_MANIFEST_PATH = INTEGRATIONS_DIR / "google_drive_provider_manifest.v1.json"
PERMISSION_POLICY_PATH = INTEGRATIONS_DIR / "integration_permission_policy.v1.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest_schema() -> dict:
    return _load_json(MANIFEST_SCHEMA_PATH)


@pytest.fixture(scope="module")
def permission_policy_schema() -> dict:
    return _load_json(PERMISSION_POLICY_SCHEMA_PATH)


@pytest.fixture(scope="module")
def github_manifest() -> dict:
    return _load_json(GITHUB_MANIFEST_PATH)


@pytest.fixture(scope="module")
def gdrive_manifest() -> dict:
    return _load_json(GDRIVE_MANIFEST_PATH)


@pytest.fixture(scope="module")
def permission_policy() -> dict:
    return _load_json(PERMISSION_POLICY_PATH)


class TestProviderManifestSchema:
    def test_github_manifest_validates_against_schema(
        self, manifest_schema, github_manifest
    ):
        jsonschema.validate(github_manifest, manifest_schema)

    def test_google_drive_manifest_validates_against_schema(
        self, manifest_schema, gdrive_manifest
    ):
        jsonschema.validate(gdrive_manifest, manifest_schema)

    def test_github_manifest_has_required_fields(self, github_manifest):
        required = [
            "schema_version",
            "provider_id",
            "display_name",
            "auth_kind",
            "capabilities",
        ]
        for field in required:
            assert field in github_manifest, f"Missing required field: {field}"

    def test_github_manifest_capabilities_have_gated_writes(self, github_manifest):
        for cap in github_manifest["capabilities"]:
            if cap["kind"] == "write":
                assert cap["gated"], (
                    f"Write capability {cap['capability_id']} must be gated"
                )

    def test_github_manifest_no_raw_tokens_in_sensitive_surfaces(self, github_manifest):
        sensitive = github_manifest.get("sensitive_surfaces", [])
        assert "access_token" not in sensitive
        assert "refresh_token" not in sensitive
        assert "id_token" not in sensitive
        assert "private_key" not in sensitive
        assert "client_secret" not in sensitive

    def test_google_drive_manifest_capabilities_have_gated_writes(
        self, gdrive_manifest
    ):
        for cap in gdrive_manifest["capabilities"]:
            if cap["kind"] == "write":
                assert cap["gated"], (
                    f"Write capability {cap['capability_id']} must be gated"
                )

    def test_google_drive_manifest_no_raw_tokens_in_sensitive_surfaces(
        self, gdrive_manifest
    ):
        sensitive = gdrive_manifest.get("sensitive_surfaces", [])
        assert "access_token" not in sensitive
        assert "refresh_token" not in sensitive
        assert "id_token" not in sensitive

    def test_github_manifest_profile_gate_required(self, github_manifest):
        assert github_manifest["profile_gate_required"] is True

    def test_google_drive_manifest_profile_gate_required(self, gdrive_manifest):
        assert gdrive_manifest["profile_gate_required"] is True

    def test_github_manifest_not_a_release_blocker(self, github_manifest):
        assert github_manifest.get("release_gate_required", True) is False

    def test_google_drive_manifest_not_a_release_blocker(self, gdrive_manifest):
        assert gdrive_manifest.get("release_gate_required", True) is False

    def test_schema_rejects_missing_provider_id(self, manifest_schema):
        bad = {"schema_version": "rig.integration.provider_manifest.v1"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, manifest_schema)

    def test_schema_rejects_invalid_auth_kind(self, manifest_schema, github_manifest):
        bad = dict(github_manifest)
        bad["auth_kind"] = "password"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, manifest_schema)

    def test_schema_rejects_empty_capabilities(self, manifest_schema, github_manifest):
        bad = dict(github_manifest)
        bad["capabilities"] = []
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, manifest_schema)

    def test_github_capability_ids_are_valid(self, github_manifest):
        for cap in github_manifest["capabilities"]:
            assert cap["capability_id"].islower() or "_" in cap["capability_id"]
            assert " " not in cap["capability_id"]

    def test_gdrive_capability_ids_are_valid(self, gdrive_manifest):
        for cap in gdrive_manifest["capabilities"]:
            assert cap["capability_id"].islower() or "_" in cap["capability_id"]
            assert " " not in cap["capability_id"]

    def test_telemetry_safety_class_valid(self, manifest_schema, github_manifest):
        valid = {"content_light", "restricted", "forbidden"}
        assert github_manifest["telemetry_safety_class"] in valid
        for cap in github_manifest["capabilities"]:
            assert cap["telemetry_safety_class"] in valid

    def test_redaction_policy_valid(self, manifest_schema, github_manifest):
        valid = {
            "hash_all_identifiers",
            "hash_content_derived",
            "drop_all_content",
            "allow_safe_metadata_only",
        }
        assert github_manifest["redaction_policy"] in valid


class TestPermissionPolicy:
    def test_permission_policy_validates_against_schema(
        self, permission_policy_schema, permission_policy
    ):
        jsonschema.validate(permission_policy, permission_policy_schema)

    def test_policy_rejects_broad_drive_scope(self, permission_policy):
        drive_rule = None
        for rule in permission_policy["rules"]:
            if rule["rule_id"] == "no_broad_drive_scope_unless_justified":
                drive_rule = rule
                break
        assert drive_rule is not None
        assert drive_rule["enforcement"] == "hard_block"
        assert "google_drive" in drive_rule["applies_to_providers"]

    def test_policy_rejects_github_mutation_without_gate(self, permission_policy):
        gh_rule = None
        for rule in permission_policy["rules"]:
            if rule["rule_id"] == "github_mutation_capability_gated":
                gh_rule = rule
                break
        assert gh_rule is not None
        assert gh_rule["enforcement"] == "hard_block"
        assert "create_check_run_or_status" in gh_rule["affected_capabilities"]
        assert "create_issue_comment" in gh_rule["affected_capabilities"]
        assert "propose_patch_metadata" in gh_rule["affected_capabilities"]

    def test_temp_fixture_broad_drive_scope_blocked(self, permission_policy):
        scope_allowlist = permission_policy.get("scope_allowlist", {}).get(
            "google_drive", []
        )
        allowed_scopes = {s["scope"] for s in scope_allowlist}
        assert "drive" not in allowed_scopes, (
            "Broad drive scope must not be in allowlist"
        )
        assert "drive.readonly" not in allowed_scopes, (
            "Broad drive.readonly scope must not be in allowlist"
        )
        assert "drive.file" in allowed_scopes, "drive.file must be in allowlist"

    def test_temp_fixture_github_repo_scopes_not_in_allowlist(self, permission_policy):
        scope_allowlist = permission_policy.get("scope_allowlist", {}).get("github", [])
        allowed_scopes = {s["scope"] for s in scope_allowlist}
        assert "repo" not in allowed_scopes
        assert "public_repo" not in allowed_scopes

    def test_every_mutation_rule_requires_profile_unlock(self, permission_policy):
        for rule in permission_policy.get("mutation_gate_rules", []):
            assert rule["requires_profile_unlock"] is True

    def test_every_mutation_rule_requires_explicit_approval(self, permission_policy):
        for rule in permission_policy.get("mutation_gate_rules", []):
            assert rule["requires_explicit_approval"] is True

    def test_no_raw_token_projection_rule_is_hard_block(self, permission_policy):
        for rule in permission_policy.get("global_rules", []):
            if rule["rule_id"] == "no_raw_token_projection":
                assert rule["enforcement"] == "hard_block"
                return
        pytest.fail("no_raw_token_projection rule not found")

    def test_no_private_content_in_telemetry_rule_is_hard_block(
        self, permission_policy
    ):
        for rule in permission_policy.get("global_rules", []):
            if rule["rule_id"] == "no_private_content_in_telemetry":
                assert rule["enforcement"] == "hard_block"
                return
        pytest.fail("no_private_content_in_telemetry rule not found")

    def test_content_light_evidence_rule_is_hard_block(self, permission_policy):
        for rule in permission_policy.get("global_rules", []):
            if rule["rule_id"] == "content_light_evidence_default":
                assert rule["enforcement"] == "hard_block"
                return
        pytest.fail("content_light_evidence_default rule not found")
