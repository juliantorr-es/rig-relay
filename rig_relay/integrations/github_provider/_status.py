"""GitHub Provider status snapshot — local, no live network.

Produces a schema-valid status snapshot from local auth state + manifest.
Never calls GitHub API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.integrations.github_provider._capabilities import (
    load_github_capability_manifest,
)
from rig_relay.integrations.github_provider._live_auth import GitHubLiveAuthConfig
from rig_relay.integrations.github_provider._models import (
    GitHubProviderAuthState,
    GitHubProviderCapabilityManifest,
    _now_iso,
)
from rig_relay.integrations.github_provider._redaction import hash_identifier

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCHEMAS_DIR = _REPO_ROOT / "docs" / "schemas"

STATUS_SNAPSHOT_SCHEMA_ID = "rig.github_provider.status_snapshot.v1"


def _validate_status_snapshot(data: dict[str, Any]) -> list[str]:
    import jsonschema

    schema_path = _SCHEMAS_DIR / f"{STATUS_SNAPSHOT_SCHEMA_ID}.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(data)]


def build_status_snapshot(
    auth_state: GitHubProviderAuthState,
    manifest: GitHubProviderCapabilityManifest | None = None,
) -> dict[str, Any]:
    if manifest is None:
        manifest = load_github_capability_manifest()

    capabilities = list(manifest.capabilities.keys())
    refused_capabilities = [
        c.capability_id for c in manifest.capabilities.values() if not c.default_allowed
    ]

    active_grants = auth_state.active_grants()
    expired_grants = [
        g
        for g in auth_state.repository_permission_grants
        if str(g.grant_status) == "expired"
    ]
    revoked_grants = [
        g
        for g in auth_state.repository_permission_grants
        if str(g.grant_status) == "revoked"
    ]

    live_config = GitHubLiveAuthConfig.from_environment()
    live_configured = live_config.is_configured()

    return {
        "schema_version": STATUS_SNAPSHOT_SCHEMA_ID,
        "provider_id": "github",
        "generated_at": _now_iso(),
        "auth_state_hash": hash_identifier(
            json.dumps(auth_state.to_dict(), sort_keys=True)
        ),
        "capability_manifest_hash": hash_identifier(
            json.dumps(
                {
                    "provider_id": manifest.provider_id,
                    "capabilities": list(manifest.capabilities.keys()),
                },
                sort_keys=True,
            )
        ),
        "configured_auth_modes": [auth_state.auth_mode.value],
        "available_capabilities": capabilities,
        "refused_capabilities": refused_capabilities,
        "grant_count": len(active_grants),
        "expired_grant_count": len(expired_grants),
        "revoked_grant_count": len(revoked_grants),
        "repository_count": len({g.repository_hash for g in active_grants}),
        "rate_limit_status": "unavailable",
        "live_network_enabled": live_configured,
        "live_configured": live_configured,
        "live_auth_available": live_configured,
        "content_light": True,
    }
