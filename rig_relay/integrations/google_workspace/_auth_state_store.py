"""Google Workspace auth state persistence — content-light read/write.

Default: .rig/relay/google_workspace_auth_state.v1.json
Never stores raw tokens, private keys, client secrets, OAuth codes, JWT assertions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceAuthState,
    GoogleWorkspaceScopeGrant,
)
from rig_relay.integrations.google_workspace._redaction import (
    assert_no_raw_secret_patterns,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PATH = _REPO_ROOT / ".rig" / "relay" / "google_workspace_auth_state.v1.json"
_SCHEMAS_DIR = _REPO_ROOT / "docs" / "schemas"

_FORBIDDEN_FIELDS = frozenset({
    "access_token",
    "refresh_token",
    "client_secret",
    "private_key",
    "private_key_id",
    "authorization_code",
    "oauth_code",
    "jwt_assertion",
    "id_token",
    "token",
    "api_key",
})


def _validate(data: dict[str, Any]) -> list[str]:
    import jsonschema

    path = _SCHEMAS_DIR / "rig.google_workspace.auth_state.v1.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    v = jsonschema.Draft7Validator(schema)
    return [e.message for e in v.iter_errors(data)]


def write_workspace_auth_state(
    auth_state: GoogleWorkspaceAuthState, path: Path | None = None
) -> Path:
    output = path or _DEFAULT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    data = auth_state.to_dict()
    for key in _FORBIDDEN_FIELDS:
        if key in data:
            raise ValueError(f"raw_credential_rejected: field '{key}'")
    errors = _validate(data)
    if errors:
        raise ValueError(f"Schema validation failed: {'; '.join(errors)}")
    text = json.dumps(data, indent=2, ensure_ascii=False)
    assert_no_raw_secret_patterns(text)
    output.write_text(text + "\n", encoding="utf-8")
    return output


def read_workspace_auth_state(path: Path | None = None) -> GoogleWorkspaceAuthState:
    read_path = path or _DEFAULT_PATH
    raw = json.loads(read_path.read_text(encoding="utf-8"))
    for key in _FORBIDDEN_FIELDS:
        if key in raw:
            raise ValueError(f"raw_credential_rejected: field '{key}'")
    errors = _validate(raw)
    if errors:
        raise ValueError(f"Schema validation failed: {'; '.join(errors)}")
    assert_no_raw_secret_patterns(read_path.read_text(encoding="utf-8"))
    grants = [
        GoogleWorkspaceScopeGrant(
            scope_id=g["scope_id"],
            scope_sensitivity=g["scope_sensitivity"],
            grant_status=g.get("grant_status", "active"),
            access_level=g.get("access_level", "read"),
            grant_hash=g.get("grant_hash", ""),
            granted_at=g.get("granted_at", ""),
            expires_at=g.get("expires_at", ""),
        )
        for g in raw.get("scope_grants", [])
    ]
    return GoogleWorkspaceAuthState(
        auth_mode=raw.get("auth_mode", "none"),
        auth_status=raw.get("auth_status", "unauthenticated"),
        account_hash=raw.get("account_hash", ""),
        customer_hash=raw.get("customer_hash", ""),
        domain_hash=raw.get("domain_hash", ""),
        subject_hashes=raw.get("subject_hashes", []),
        domain_wide_delegation_authorized=raw.get(
            "domain_wide_delegation_authorized", False
        ),
        scope_grants=grants,
        token_storage_authority=raw.get("token_storage_authority", "none"),
        token_material_present=raw.get("token_material_present", False),
        token_material_stored=raw.get("token_material_stored", False),
        redaction_status=raw.get("redaction_status", "clean"),
    )
