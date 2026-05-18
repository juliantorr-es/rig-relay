from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INTEGRATIONS_DIR = REPO_ROOT / "docs" / "json" / "integrations"

GITHUB_MANIFEST_PATH = INTEGRATIONS_DIR / "github_provider_manifest.v1.json"
GDRIVE_MANIFEST_PATH = INTEGRATIONS_DIR / "google_drive_provider_manifest.v1.json"
PERMISSION_POLICY_PATH = INTEGRATIONS_DIR / "integration_permission_policy.v1.json"

TOKEN_FIELD_NAMES = {
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "bearer_token",
    "api_key",
    "private_key",
    "client_secret",
    "webhook_secret",
    "installation_token",
    "jwt",
    "authorization_code",
}

CONTENT_FIELD_NAMES = {
    "raw_output",
    "file_content",
    "document_text",
    "code",
    "source_code",
    "payload",
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_token_fields(obj, path="", found=None):
    if found is None:
        found = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            full_path = f"{path}.{key}" if path else key
            if key.lower() in TOKEN_FIELD_NAMES or (
                isinstance(value, str) and _looks_like_token(key, value)
            ):
                found[full_path] = value
            _find_token_fields(value, full_path, found)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _find_token_fields(item, f"{path}[{i}]", found)
    return found


def _looks_like_token(key: str, value: str) -> bool:
    if not value or len(value) < 20:
        return False
    suspicious_keys = {"token", "secret", "key", "password", "credential"}
    key_lower = key.lower()
    if any(s in key_lower for s in suspicious_keys):
        if value.startswith("ghp_") or value.startswith("github_pat_"):
            return True
        if value.startswith("ghs_") or value.startswith("gho_"):
            return True
        if value.startswith("ya29."):
            return True
        if len(value) > 40 and "/" not in value and " " not in value:
            return True
    return False


class TestIntegrationProjectionNoTokens:
    def test_github_manifest_contains_no_token_fields(self):
        manifest = _load_json(GITHUB_MANIFEST_PATH)
        token_fields = _find_token_fields(manifest)
        assert not token_fields, (
            f"GitHub manifest contains token-like fields: {token_fields}"
        )

    def test_google_drive_manifest_contains_no_token_fields(self):
        manifest = _load_json(GDRIVE_MANIFEST_PATH)
        token_fields = _find_token_fields(manifest)
        assert not token_fields, (
            f"Google Drive manifest contains token-like fields: {token_fields}"
        )

    def test_permission_policy_contains_no_token_fields(self):
        policy = _load_json(PERMISSION_POLICY_PATH)
        token_fields = _find_token_fields(policy)
        assert not token_fields, (
            f"Permission policy contains token-like fields: {token_fields}"
        )

    def test_github_manifest_capabilities_no_raw_tokens(self):
        manifest = _load_json(GITHUB_MANIFEST_PATH)
        for cap in manifest.get("capabilities", []):
            cap_json = json.dumps(cap)
            assert "access_token" not in cap_json.lower()
            assert "api_key" not in cap_json.lower()

    def test_gdrive_manifest_capabilities_no_raw_tokens(self):
        manifest = _load_json(GDRIVE_MANIFEST_PATH)
        for cap in manifest.get("capabilities", []):
            cap_json = json.dumps(cap)
            assert "access_token" not in cap_json.lower()
            assert "api_key" not in cap_json.lower()

    def test_integration_projection_model_has_no_token_fields(self):
        from rig_relay.core.integrations.models import IntegrationProviderState

        fields = set(IntegrationProviderState.model_fields.keys())
        for token_name in TOKEN_FIELD_NAMES:
            assert token_name not in fields, (
                f"IntegrationProviderState has token field: {token_name}"
            )

    def test_integration_capability_state_has_no_token_fields(self):
        from rig_relay.core.integrations.models import IntegrationCapabilityState

        fields = set(IntegrationCapabilityState.model_fields.keys())
        for token_name in TOKEN_FIELD_NAMES:
            assert token_name not in fields, (
                f"IntegrationCapabilityState has token field: {token_name}"
            )


class TestIntegrationProjectionContentLight:
    def test_projection_uses_account_id_hash_not_raw_id(self):
        from rig_relay.core.integrations.models import IntegrationProviderState

        fields = set(IntegrationProviderState.model_fields.keys())
        assert "account_id_hash" in fields
        assert "account_id" not in fields
        assert "email" not in fields

    def test_projection_has_no_raw_content_fields(self):
        from rig_relay.core.integrations.models import IntegrationProviderState

        fields = set(IntegrationProviderState.model_fields.keys())
        for content_name in CONTENT_FIELD_NAMES:
            assert content_name not in fields, (
                f"IntegrationProviderState has content field: {content_name}"
            )

    def test_github_manifest_evidence_paths_are_relative(self, github_manifest=None):
        manifest = _load_json(GITHUB_MANIFEST_PATH)
        for evidence_path in manifest.get("evidence_paths", []):
            assert evidence_path.startswith(".rig/"), (
                f"Evidence path not relative: {evidence_path}"
            )

    def test_gdrive_manifest_evidence_paths_are_relative(self):
        manifest = _load_json(GDRIVE_MANIFEST_PATH)
        for evidence_path in manifest.get("evidence_paths", []):
            assert evidence_path.startswith(".rig/"), (
                f"Evidence path not relative: {evidence_path}"
            )
