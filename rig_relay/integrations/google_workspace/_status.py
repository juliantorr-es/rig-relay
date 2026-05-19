"""Google Workspace status snapshot — local only, no live APIs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.integrations.google_workspace._capabilities import (
    load_capability_manifest,
)
from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceAuthState,
    GoogleWorkspaceCapabilityManifest,
    _now_iso,
)

_SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "docs" / "schemas"


def _hash_identifier(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate(data: dict[str, Any]) -> list[str]:
    import jsonschema

    path = _SCHEMAS_DIR / "rig.google_workspace.status_snapshot.v1.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    v = jsonschema.Draft7Validator(schema)
    return [e.message for e in v.iter_errors(data)]


def build_status_snapshot(
    auth: GoogleWorkspaceAuthState,
    manifest: GoogleWorkspaceCapabilityManifest | None = None,
) -> dict[str, Any]:
    if manifest is None:
        manifest = load_capability_manifest()
    caps = list(manifest.capabilities.keys())
    refused = [
        c.capability_id for c in manifest.capabilities.values() if not c.default_allowed
    ]
    active = auth.active_grants()
    expired = [g for g in auth.scope_grants if str(g.grant_status) == "expired"]
    revoked = [g for g in auth.scope_grants if str(g.grant_status) == "revoked"]
    restricted = [
        g for g in auth.scope_grants if str(g.scope_sensitivity) == "restricted"
    ]
    sensitive = [
        g for g in auth.scope_grants if str(g.scope_sensitivity) == "sensitive"
    ]
    return {
        "schema_version": "rig.google_workspace.status_snapshot.v1",
        "provider_id": "google_workspace",
        "generated_at": _now_iso(),
        "auth_state_hash": _hash_identifier(json.dumps(auth.to_dict(), sort_keys=True)),
        "capability_manifest_hash": _hash_identifier(
            json.dumps(
                {"provider_id": "google_workspace", "capabilities": caps},
                sort_keys=True,
            )
        ),
        "configured_auth_modes": [str(auth.auth_mode)],
        "available_capabilities": caps,
        "refused_capabilities": refused,
        "grant_count": len(active),
        "expired_grant_count": len(expired),
        "revoked_grant_count": len(revoked),
        "restricted_scope_count": len(restricted),
        "sensitive_scope_count": len(sensitive),
        "domain_wide_delegation_authorized": auth.domain_wide_delegation_authorized,
        "product_counts": {},
        "live_network_enabled": False,
        "content_light": True,
    }
