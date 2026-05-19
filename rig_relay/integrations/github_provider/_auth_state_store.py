"""GitHub Provider auth state persistence — content-light read/write.

Default path: .rig/relay/github_auth_state.v1.json
Never stores raw tokens, client secrets, raw owner/repo, or raw installation IDs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.integrations.github_provider._models import (
    GitHubProviderAuthState,
    GitHubRepositoryPermissionGrant,
)
from rig_relay.integrations.github_provider._redaction import assert_no_raw_github_token

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_AUTH_PATH = _REPO_ROOT / ".rig" / "relay" / "github_auth_state.v1.json"
_SCHEMAS_DIR = _REPO_ROOT / "docs" / "schemas"

_TOKEN_FORBIDDEN_FIELDS = frozenset({
    "access_token",
    "token",
    "client_secret",
    "private_key",
    "refresh_token",
    "api_key",
    "oauth_code",
})


def _validate_persisted_auth_state(data: dict[str, Any]) -> list[str]:
    import jsonschema

    schema_path = _SCHEMAS_DIR / "rig.github_provider.auth_state.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(data)]


def write_auth_state(
    auth_state: GitHubProviderAuthState, path: Path | None = None
) -> Path:
    output_path = path or _DEFAULT_AUTH_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = auth_state.to_dict()

    for key in _TOKEN_FORBIDDEN_FIELDS:
        if key in data:
            raise ValueError(
                f"raw_token_field_rejected: auth state contains forbidden field '{key}'"
            )

    errors = _validate_persisted_auth_state(data)
    if errors:
        raise ValueError(f"Auth state fails schema validation: {'; '.join(errors)}")

    body = json.dumps(data, indent=2, ensure_ascii=False)
    assert_no_raw_github_token(body)

    output_path.write_text(body + "\n", encoding="utf-8")
    return output_path


def read_auth_state(path: Path | None = None) -> GitHubProviderAuthState:
    read_path = path or _DEFAULT_AUTH_PATH
    raw = json.loads(read_path.read_text(encoding="utf-8"))

    for key in _TOKEN_FORBIDDEN_FIELDS:
        if key in raw:
            raise ValueError(
                f"raw_token_field_rejected: persisted auth state contains forbidden field '{key}'"
            )

    errors = _validate_persisted_auth_state(raw)
    if errors:
        raise ValueError(
            f"Persisted auth state fails schema validation: {'; '.join(errors)}"
        )

    body = read_path.read_text(encoding="utf-8")
    assert_no_raw_github_token(body)

    grants: list[GitHubRepositoryPermissionGrant] = []
    for g_raw in raw.get("repository_permission_grants", []):
        grants.append(
            GitHubRepositoryPermissionGrant(
                repository_hash=g_raw["repository_hash"],
                permission_id=g_raw["permission_id"],
                permission_kind=g_raw["permission_kind"],
                access_level=g_raw["access_level"],
                source_auth_mode=g_raw["source_auth_mode"],
                grant_hash=g_raw["grant_hash"],
                granted_at=g_raw.get("granted_at", ""),
                expires_at=g_raw.get("expires_at", ""),
            )
        )

    return GitHubProviderAuthState(
        auth_mode=raw.get("auth_mode", "none"),
        auth_status=raw.get("auth_status", "unauthenticated"),
        account_hash=raw.get("account_hash", ""),
        installation_id_hash=raw.get("installation_id_hash") or None,
        scopes_or_permissions=raw.get("scopes_or_permissions", []),
        repository_access_hashes=raw.get("repository_access_hashes", []),
        repository_permission_grants=grants,
        token_storage_authority=raw.get("token_storage_authority", "none"),
        token_material_present=raw.get("token_material_present", False),
        token_material_stored=raw.get("token_material_stored", False),
        expires_at=raw.get("expires_at", ""),
        redaction_status=raw.get("redaction_status", "clean"),
    )
