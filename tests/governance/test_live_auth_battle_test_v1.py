from __future__ import annotations

import json
from pathlib import Path
import re

import jsonschema

ALLOWED_AUTH_FLOW_ENUMS = frozenset({
    "implemented_live",
    "implemented_fake_only",
    "opt_in_live_test",
    "deferred",
    "refused",
})

ALLOWED_RECOMMENDATIONS = frozenset({"promote", "promote_with_limitations", "hold"})


class TestLiveAuthBattleTest:
    SCHEMA_PATH = (
        Path(__file__).parent.parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.live_auth_battle_test.v1.schema.json"
    )
    ARTIFACT_PATH = (
        Path(__file__).parent.parent.parent
        / "docs"
        / "json"
        / "governance"
        / "live_auth_battle_test_v1.v1.json"
    )

    def _load_schema(self):
        return json.loads(self.SCHEMA_PATH.read_text())

    def _load_artifact(self):
        return json.loads(self.ARTIFACT_PATH.read_text())

    def test_schema_is_valid_json(self):
        text = self.SCHEMA_PATH.read_text()
        schema = json.loads(text)
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert schema["title"] is not None

    def test_artifact_validates_against_schema(self):
        schema = self._load_schema()
        artifact = self._load_artifact()
        jsonschema.validate(instance=artifact, schema=schema)

    def test_schema_version_matches_const(self):
        schema = self._load_schema()
        artifact = self._load_artifact()
        const = schema["properties"]["schema_version"]["const"]
        assert artifact["schema_version"] == const

    def test_all_required_fields_present(self):
        schema = self._load_schema()
        artifact = self._load_artifact()
        for field in schema["required"]:
            assert field in artifact, f"Missing required field: {field}"

    def test_recommendation_is_valid_enum(self):
        artifact = self._load_artifact()
        assert artifact["recommendation"] in ALLOWED_RECOMMENDATIONS

    def test_no_raw_secrets_in_artifact(self):
        raw = self.ARTIFACT_PATH.read_text().lower()
        value_patterns = [
            (r'"access_token"\s*:\s*"[a-z0-9_\-.]{20,}"', "access_token value"),
            (r'"refresh_token"\s*:\s*"[a-z0-9_\-.]{20,}"', "refresh_token value"),
            (r'"client_secret"\s*:\s*"[a-z0-9_\-.]{20,}"', "client_secret value"),
            (r'"private_key"\s*:\s*"[a-z0-9_\-.]{20,}"', "private_key value"),
            (r'"token"\s*:\s*"gh[pousr]_', "GitHub token value"),
            (r'"token"\s*:\s*"ya29\.', "Google token value"),
            (r'"token"\s*:\s*"github_pat_', "GitHub PAT value"),
        ]
        for pattern, label in value_patterns:
            assert not re.search(pattern, raw), (
                f"Secret pattern '{label}' found as value in battle test artifact"
            )
        structural_patterns = [
            "-----begin private key-----",
            "-----begin rsa private key-----",
        ]
        for pat in structural_patterns:
            assert pat not in raw, "Private key block found in battle test artifact"

    def test_all_boolean_fields_are_booleans(self):
        artifact = self._load_artifact()

        def _check_obj(obj: dict, path: str) -> None:
            for key, value in obj.items():
                if isinstance(value, bool):
                    assert isinstance(value, bool), (
                        f"{path}.{key} must be bool, got {type(value).__name__}"
                    )
                elif isinstance(value, dict):
                    _check_obj(value, f"{path}.{key}")

        _check_obj(artifact, "root")

    def test_auth_flow_enums_valid(self):
        artifact = self._load_artifact()

        def _check_enums(obj: dict, path: str) -> None:
            for key, value in obj.items():
                if isinstance(value, str) and value in ALLOWED_AUTH_FLOW_ENUMS:
                    pass
                elif isinstance(value, str) and key in {
                    "app_installation_token_flow",
                    "oauth_code_flow",
                    "pat_manual_import",
                    "user_app_auth",
                    "oauth_pkce_flow",
                    "service_account_jwt",
                    "domain_wide_delegation",
                    "marketplace_app",
                }:
                    assert value in ALLOWED_AUTH_FLOW_ENUMS, (
                        f"{path}.{key} invalid enum value: {value}"
                    )
                elif isinstance(value, dict):
                    _check_enums(value, f"{path}.{key}")

        _check_enums(artifact, "root")

    def test_claims_supported_not_empty(self):
        artifact = self._load_artifact()
        assert len(artifact["claims_supported"]) > 0

    def test_claims_rejected_not_empty(self):
        artifact = self._load_artifact()
        assert len(artifact["claims_rejected"]) > 0

    def test_opt_in_commands_not_empty(self):
        artifact = self._load_artifact()
        assert len(artifact["opt_in_live_test_commands"]) > 0
        for cmd in artifact["opt_in_live_test_commands"]:
            assert "RIG_LIVE_AUTH_TESTS=1" in cmd, f"Command missing env guard: {cmd}"

    def test_safety_boundaries_all_true(self):
        artifact = self._load_artifact()
        boundaries = artifact["safety_boundaries"]
        for key, value in boundaries.items():
            assert value is True, f"safety_boundaries.{key} must be true, got {value}"

    def test_dev_store_blocked_reported(self):
        artifact = self._load_artifact()
        assert (
            artifact["credential_storage_status"]["dev_store_blocked_by_default"]
            is True
        )

    def test_pkce_module_exists(self):
        from rig_relay.integrations.google_workspace._pkce import (
            generate_code_challenge,
            generate_code_verifier,
        )

        assert generate_code_challenge is not None
        assert generate_code_verifier is not None

    def test_live_auth_modules_exist(self):
        from rig_relay.integrations.github_provider._live_auth import (
            GitHubLiveAuthError,
        )
        from rig_relay.integrations.google_workspace._live_auth import (
            _content_light_token_response,
        )

        assert GitHubLiveAuthError is not None
        assert _content_light_token_response is not None

    def test_scope_manifest_exists(self):
        manifest_path = (
            Path(__file__).parent.parent.parent
            / "docs"
            / "json"
            / "integrations"
            / "google_workspace_scope_manifest_v1.v1.json"
        )
        assert manifest_path.exists(), (
            f"Google Workspace scope manifest missing: {manifest_path}"
        )
