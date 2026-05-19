from __future__ import annotations

import json
from pathlib import Path

import jsonschema


class TestLiveAuthReadinessSchema:
    SCHEMA_PATH = (
        Path(__file__).parent.parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.live_auth_readiness.v1.schema.json"
    )
    ARTIFACT_PATH = (
        Path(__file__).parent.parent.parent
        / "docs"
        / "json"
        / "governance"
        / "live_auth_readiness_v1.v1.json"
    )

    def test_schema_is_valid_json(self):
        text = self.SCHEMA_PATH.read_text()
        schema = json.loads(text)
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert schema["title"] is not None

    def test_artifact_validates_against_schema(self):
        schema = json.loads(self.SCHEMA_PATH.read_text())
        artifact = json.loads(self.ARTIFACT_PATH.read_text())
        jsonschema.validate(instance=artifact, schema=schema)

    def test_schema_version_matches_const(self):
        schema = json.loads(self.SCHEMA_PATH.read_text())
        artifact = json.loads(self.ARTIFACT_PATH.read_text())
        const = schema["properties"]["schema_version"]["const"]
        assert artifact["schema_version"] == const

    def test_artifact_has_all_required_top_level_fields(self):
        schema = json.loads(self.SCHEMA_PATH.read_text())
        artifact = json.loads(self.ARTIFACT_PATH.read_text())
        for field in schema["required"]:
            assert field in artifact, f"Missing required field: {field}"

    def test_recommendation_is_valid_enum(self):
        artifact = json.loads(self.ARTIFACT_PATH.read_text())
        assert artifact["recommendation"] in ("promote", "park", "reject")

    def test_no_raw_secret_in_artifact(self):
        import re

        raw = self.ARTIFACT_PATH.read_text().lower()
        value_patterns = [
            (r'"access_token"\s*:\s*"[a-zA-Z0-9_\-\.\+/=]{20,}"', "access_token value"),
            (
                r'"refresh_token"\s*:\s*"[a-zA-Z0-9_\-\.\+/=]{20,}"',
                "refresh_token value",
            ),
            (
                r'"client_secret"\s*:\s*"[a-zA-Z0-9_\-\.\+/=]{20,}"',
                "client_secret value",
            ),
            (r'"private_key"\s*:\s*"[a-zA-Z0-9_\-\.\+/=]{20,}"', "private_key value"),
            (r'"token"\s*:\s*"gh[pousr]_', "GitHub token value"),
            (r'"token"\s*:\s*"ya29\.', "Google token value"),
            (r'"token"\s*:\s*"github_pat_', "GitHub PAT value"),
        ]
        for pattern, label in value_patterns:
            assert not re.search(pattern, raw), (
                f"Secret pattern '{label}' found as value in readiness artifact"
            )
        structural_patterns = [
            "-----BEGIN PRIVATE KEY-----",
            "-----BEGIN RSA PRIVATE KEY-----",
        ]
        for pattern in structural_patterns:
            assert pattern not in raw, "Private key block found in readiness artifact"

    def test_all_boolean_status_fields_are_booleans(self):
        artifact = json.loads(self.ARTIFACT_PATH.read_text())
        status_keys = [
            "github_provider_auth_status",
            "google_workspace_auth_status",
            "mcp_auth_status",
            "acp_auth_status",
            "a2a_auth_status",
            "sdk_auth_api_status",
            "credential_store_status",
            "trace_receipt_joinability_status",
            "adversarial_coverage_status",
            "secret_boundary_status",
        ]
        for key in status_keys:
            obj = artifact[key]
            for field, value in obj.items():
                assert isinstance(value, bool), (
                    f"{key}.{field} must be bool, got {type(value).__name__}"
                )

    def test_auth_flows_implemented_not_empty(self):
        artifact = json.loads(self.ARTIFACT_PATH.read_text())
        assert len(artifact["auth_flows_implemented"]) > 0

    def test_auth_flows_deferred_not_empty(self):
        artifact = json.loads(self.ARTIFACT_PATH.read_text())
        assert len(artifact["auth_flows_deferred"]) > 0

    def test_remaining_blockers_identify_gaps(self):
        artifact = json.loads(self.ARTIFACT_PATH.read_text())
        assert len(artifact["remaining_blockers"]) > 0

    def test_github_fake_auth_module_exists(self):
        from rig_relay.integrations.github_provider._fake_auth import (
            FakeGitHubAppAuth,
            FakeGitHubJwtSigner,
            FakeGitHubTokenEndpoint,
        )

        assert FakeGitHubAppAuth is not None
        assert FakeGitHubJwtSigner is not None
        assert FakeGitHubTokenEndpoint is not None

    def test_google_fake_auth_module_exists(self):
        from rig_relay.integrations.google_workspace._fake_auth import (
            FakeGoogleJwtSigner,
            FakeGoogleServiceAccountAuth,
            FakeGoogleTokenEndpoint,
        )

        assert FakeGoogleJwtSigner is not None
        assert FakeGoogleServiceAccountAuth is not None
        assert FakeGoogleTokenEndpoint is not None

    def test_acp_local_auth_module_exists(self):
        from rig_relay.acp._local_auth import (
            ACPLocalAuthState,
            build_acp_local_auth_state,
        )

        assert ACPLocalAuthState is not None
        assert build_acp_local_auth_state is not None

    def test_a2a_identity_module_exists(self):
        from rig_relay.protocols.a2a._identity import (
            A2ASecurityScheme,
            build_agent_card_with_security,
        )

        assert A2ASecurityScheme is not None
        assert build_agent_card_with_security is not None

    def test_mcp_auth_metadata_module_exists(self):
        from rig_relay.protocols.mcp._auth_metadata import (
            MCPToolAuthMetadata,
            compute_tool_provenance_hash,
        )

        assert MCPToolAuthMetadata is not None
        assert compute_tool_provenance_hash is not None

    def test_credential_store_abstraction_exists(self):
        from rig_relay.identity._credential_store import (
            CredentialMetadata,
            CredentialStore,
            get_credential_store,
        )

        assert CredentialStore is not None
        assert get_credential_store is not None
        metadata = CredentialMetadata(
            provider="test",
            credential_kind="access_token",
            stored_at="2026-01-01T00:00:00Z",
            credential_hash="sha256:deadbeef",
            status="active",
        )
        assert metadata.provider == "test"
        assert metadata.credential_hash.startswith("sha256:")
        assert "access_token" not in metadata.to_dict()
        assert "refresh_token" not in metadata.to_dict()

    def test_sdk_auth_api_functions_exist(self):
        from rig_relay.sdk import (
            check_auth_capability,
            detect_refresh_needed,
            get_auth_receipt_ref,
            get_auth_refusal,
            get_auth_status,
            get_credential_store_ref_hash,
        )

        assert get_auth_status is not None
        assert check_auth_capability is not None
        assert detect_refresh_needed is not None
        assert get_auth_refusal is not None
        assert get_auth_receipt_ref is not None
        assert get_credential_store_ref_hash is not None

    def test_adversarial_test_files_exist(self):
        adversarial_dir = Path(__file__).parent.parent / "adversarial"
        expected_files = [
            "test_fake_auth_endpoints.py",
            "test_credential_injection.py",
            "test_auth_refusal_boundaries.py",
            "test_auth_trace_joinability.py",
            "test_auth_schema_adversarial.py",
        ]
        for fname in expected_files:
            assert (adversarial_dir / fname).exists(), (
                f"Adversarial test file missing: {fname}"
            )

    def test_github_provider_tests_exist(self):
        test_dir = Path(__file__).parent.parent / "integrations"
        assert (test_dir / "test_github_fake_auth.py").exists()
        assert (test_dir / "test_github_provider_implementation.py").exists()

    def test_google_workspace_tests_exist(self):
        test_dir = Path(__file__).parent.parent / "integrations"
        assert (test_dir / "test_google_fake_auth.py").exists()
        assert (test_dir / "test_google_workspace_implementation.py").exists()

    def test_acp_auth_tests_exist(self):
        test_dir = Path(__file__).parent.parent / "acp"
        assert (test_dir / "test_acp_local_auth_v1.py").exists()

    def test_a2a_identity_tests_exist(self):
        test_dir = Path(__file__).parent.parent / "protocols" / "a2a"
        assert (test_dir / "test_a2a_identity_v1.py").exists()

    def test_mcp_auth_metadata_tests_exist(self):
        test_dir = Path(__file__).parent.parent / "protocols" / "mcp"
        assert (test_dir / "test_mcp_auth_metadata_v1.py").exists()

    def test_credential_store_schema_exists(self):
        schema_path = (
            Path(__file__).parent.parent.parent
            / "docs"
            / "schemas"
            / "rig.relay.credential_store.metadata.v1.schema.json"
        )
        assert schema_path.exists()
        schema = json.loads(schema_path.read_text())
        assert schema["type"] == "object"

    def test_sdk_auth_schemas_exist(self):
        schemas_dir = Path(__file__).parent.parent.parent / "docs" / "schemas"
        for fname in [
            "rig.relay.sdk.auth_status.v1.schema.json",
            "rig.relay.sdk.auth_capability_check.v1.schema.json",
            "rig.relay.sdk.auth_refusal.v1.schema.json",
            "rig.relay.sdk.auth_receipt_ref.v1.schema.json",
        ]:
            assert (schemas_dir / fname).exists(), f"SDK auth schema missing: {fname}"
