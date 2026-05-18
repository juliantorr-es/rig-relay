from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INTEGRATIONS_DIR = REPO_ROOT / "docs" / "json" / "integrations"

GITHUB_MANIFEST_PATH = INTEGRATIONS_DIR / "github_provider_manifest.v1.json"
GDRIVE_MANIFEST_PATH = INTEGRATIONS_DIR / "google_drive_provider_manifest.v1.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _all_string_values(obj, prefix=""):
    strings = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, str):
                strings[full_key] = value
            strings.update(_all_string_values(value, full_key))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            strings.update(_all_string_values(item, f"{prefix}[{i}]"))
    return strings


class TestTelemetryRedaction:
    def test_telemetry_constants_have_integration_events(self):
        from rig_relay.core.telemetry.constants import EventName

        events = list(EventName)
        assert "rig.relay.integration.status_checked" in events
        assert "rig.relay.integration.connection_state_changed" in events

    def test_integration_event_names_follow_convention(self):
        from rig_relay.core.telemetry.constants import EventName

        integration_events = [
            e for e in EventName if e.startswith("rig.relay.integration.")
        ]
        for event in integration_events:
            parts = event.split(".")
            assert len(parts) >= 4, (
                f"Event {event} must follow rig.relay.<domain>.<verb> convention"
            )
            assert parts[0] == "rig"
            assert parts[1] == "relay"
            assert parts[2] == "integration"

    def test_integration_state_serializes_with_hashed_ids(self):
        from rig_relay.core.integrations.models import (
            IntegrationAuthKind,
            IntegrationConnectionState,
            IntegrationProviderState,
        )

        state = IntegrationProviderState(
            provider_id="test_provider",
            display_name="Test Provider",
            auth_kind=IntegrationAuthKind.OAUTH,
            connection_state=IntegrationConnectionState.CONNECTED,
            account_id_hash=_sha256("test-account-123"),
            profile_gate_required=True,
        )
        dumped = state.model_dump(mode="json")
        assert "account_id_hash" in dumped
        assert dumped["account_id_hash"] == _sha256("test-account-123")
        assert "access_token" not in dumped
        assert "refresh_token" not in dumped
        assert "account_id" not in dumped

    def test_capability_state_serializes_without_secrets(self):
        from rig_relay.core.integrations.models import (
            IntegrationCapabilityKind,
            IntegrationCapabilityState,
        )

        cap = IntegrationCapabilityState(
            capability_id="test_cap",
            display_name="Test Capability",
            kind=IntegrationCapabilityKind.READ,
            gated=False,
            profile_gate_required=False,
        )
        dumped = cap.model_dump(mode="json")
        assert "capability_id" in dumped
        assert "access_token" not in dumped
        assert "secret" not in dumped

    def test_manifests_redaction_policy_hash_all_identifiers(self):
        gh = _load_json(GITHUB_MANIFEST_PATH)
        gd = _load_json(GDRIVE_MANIFEST_PATH)
        assert gh["redaction_policy"] == "hash_all_identifiers"
        assert gd["redaction_policy"] == "hash_all_identifiers"

    def test_telemetry_safety_class_content_light(self):
        gh = _load_json(GITHUB_MANIFEST_PATH)
        gd = _load_json(GDRIVE_MANIFEST_PATH)
        assert gh["telemetry_safety_class"] == "content_light"
        assert gd["telemetry_safety_class"] == "content_light"

    def test_sensitive_surfaces_do_not_contain_secret_names(self):
        gh = _load_json(GITHUB_MANIFEST_PATH)
        gd = _load_json(GDRIVE_MANIFEST_PATH)

        secret_patterns = {
            "token",
            "secret",
            "key",
            "password",
            "credential",
            "private",
        }
        for surface in gh.get("sensitive_surfaces", []):
            assert not any(p in surface for p in secret_patterns), (
                f"GitHub sensitive surface '{surface}' looks like a secret"
            )
        for surface in gd.get("sensitive_surfaces", []):
            assert not any(p in surface for p in secret_patterns), (
                f"Google Drive sensitive surface '{surface}' looks like a secret"
            )

    def test_capability_sensitive_surfaces_no_secrets(self):
        for manifest_path in [GITHUB_MANIFEST_PATH, GDRIVE_MANIFEST_PATH]:
            manifest = _load_json(manifest_path)
            secret_patterns = {
                "token",
                "secret",
                "key",
                "password",
                "credential",
                "private",
            }
            for cap in manifest.get("capabilities", []):
                for surface in cap.get("sensitive_surfaces", []):
                    assert not any(p in surface for p in secret_patterns), (
                        f"Capability {cap['capability_id']} sensitive surface '{surface}' looks like a secret"
                    )
