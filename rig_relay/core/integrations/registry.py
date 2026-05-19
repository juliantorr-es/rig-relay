from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

INTEGRATION_PROVIDER_REGISTRY = [
    {
        "provider_id": "github",
        "display_name": "GitHub",
        "auth_kind": "oauth",
        "manifest_path": "docs/json/integrations/github_provider_manifest.v1.json",
        "identity_provider_kind": "github",
    },
    {
        "provider_id": "google_drive",
        "display_name": "Google Drive",
        "auth_kind": "oauth",
        "manifest_path": "docs/json/integrations/google_drive_provider_manifest.v1.json",
        "identity_provider_kind": "google",
    },
]


def load_provider_manifest(provider_id: str) -> dict | None:
    for entry in INTEGRATION_PROVIDER_REGISTRY:
        if entry["provider_id"] == provider_id:
            manifest_path = REPO_ROOT / entry["manifest_path"]
            if manifest_path.is_file():
                try:
                    return json.loads(manifest_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    return None
    return None


def build_integration_projection() -> list[dict]:
    from rig_relay.core.integrations.models import IntegrationConnectionState
    from rig_relay.governance.service_state import get_capability_gate
    from rig_relay.identity.token_store import (
        DevFileTokenStore,
        enable_dev_file_token_store,
    )

    gate = get_capability_gate()
    # explicitly opt in to dev-only plaintext token storage
    enable_dev_file_token_store()
    store = DevFileTokenStore()
    statuses = store.all_statuses()

    projections: list[dict] = []
    for entry in INTEGRATION_PROVIDER_REGISTRY:
        provider_id = entry["provider_id"]
        manifest = load_provider_manifest(provider_id)

        identity_key = entry["identity_provider_kind"]
        identity_status = statuses.get(identity_key, {})
        is_signed_in = identity_status.get("status") == "signed_in"

        connection_state = IntegrationConnectionState.NOT_CONFIGURED
        if is_signed_in:
            connection_state = IntegrationConnectionState.CONNECTED
        elif identity_status:
            connection_state = IntegrationConnectionState.AUTH_REQUIRED

        capabilities: list[dict] = []
        if manifest:
            for cap in manifest.get("capabilities", []):
                profile_gate_ok = True
                if cap.get("profile_gate_required", False):
                    profile_gate_ok = gate.is_allowed(
                        f"integration:{provider_id}:{cap.get('capability_id', '')}"
                    )[0]
                cap_state = {
                    "capability_id": cap.get("capability_id", ""),
                    "display_name": cap.get("display_name", ""),
                    "kind": cap.get("kind", "read"),
                    "gated": cap.get("gated", False),
                    "profile_gate_required": cap.get("profile_gate_required", False),
                    "available": is_signed_in
                    and not cap.get("gated", False)
                    and profile_gate_ok,
                    "requires_approval": cap.get("gated", False),
                    "mcp_acp_exposable": cap.get("mcp_acp_exposable", False)
                    and not cap.get("gated", False)
                    and profile_gate_ok,
                }
                capabilities.append(cap_state)

        state = {
            "provider_id": provider_id,
            "display_name": entry["display_name"],
            "auth_kind": entry["auth_kind"],
            "connection_state": connection_state.value,
            "profile_gate_required": manifest.get("profile_gate_required", True)
            if manifest
            else True,
            "account_id_hash": identity_status.get("account_id_hash", ""),
            "granted_scopes": identity_status.get("scopes", []),
            "capabilities": capabilities,
            "last_checked_at": "",
            "degraded_reason": "",
            "warnings": [],
        }
        projections.append(state)

    return projections
