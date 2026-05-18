from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INTEGRATIONS_DIR = REPO_ROOT / "docs" / "json" / "integrations"
RELEASE_GATE_DIR = REPO_ROOT / "docs" / "json" / "release_gate"

GITHUB_MANIFEST_PATH = INTEGRATIONS_DIR / "github_provider_manifest.v1.json"
GDRIVE_MANIFEST_PATH = INTEGRATIONS_DIR / "google_drive_provider_manifest.v1.json"
PERMISSION_POLICY_PATH = INTEGRATIONS_DIR / "integration_permission_policy.v1.json"
RC_BLOCKERS_PATH = RELEASE_GATE_DIR / "rc_blockers.v1.jsonl"
RC_READINESS_PATH = RELEASE_GATE_DIR / "rc_readiness_gate.v1.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestMCPACPReadiness:
    def test_mutation_capabilities_not_exposable_via_mcp_acp(self):
        gh = _load_json(GITHUB_MANIFEST_PATH)
        for cap in gh.get("capabilities", []):
            if cap["kind"] == "write":
                assert cap.get("mcp_acp_exposable") is False, (
                    f"Write capability {cap['capability_id']} must not be MCP/ACP exposable"
                )

    def test_write_capabilities_excluded_when_gated(self):
        gh = _load_json(GITHUB_MANIFEST_PATH)
        gd = _load_json(GDRIVE_MANIFEST_PATH)
        for manifest in [gh, gd]:
            for cap in manifest.get("capabilities", []):
                if cap["gated"]:
                    assert cap.get("mcp_acp_exposable") is False, (
                        f"Gated capability {cap['capability_id']} must not be MCP/ACP exposable"
                    )

    def test_read_capabilities_exposable_via_mcp_acp(self):
        gh = _load_json(GITHUB_MANIFEST_PATH)
        for cap in gh.get("capabilities", []):
            if cap["kind"] == "read" and not cap["gated"]:
                assert cap.get("mcp_acp_exposable") is True, (
                    f"Read capability {cap['capability_id']} should be MCP/ACP exposable"
                )

    def test_webhook_ingest_not_exposable_via_mcp_acp(self):
        gh = _load_json(GITHUB_MANIFEST_PATH)
        for cap in gh.get("capabilities", []):
            if cap["kind"] == "webhook_ingest":
                assert cap.get("mcp_acp_exposable") is False, (
                    f"Webhook ingest capability {cap['capability_id']} must not be MCP/ACP exposable"
                )

    def test_capability_export_preserves_gating_metadata(self):
        gh = _load_json(GITHUB_MANIFEST_PATH)
        for cap in gh.get("capabilities", []):
            assert "gated" in cap
            assert "profile_gate_required" in cap
            assert "mcp_acp_exposable" in cap


class TestReleaseGateGoldenPath:
    def test_integrations_not_rc_blockers(self):
        gh = _load_json(GITHUB_MANIFEST_PATH)
        gd = _load_json(GDRIVE_MANIFEST_PATH)
        assert gh.get("release_gate_required") is False, (
            "GitHub integration should not be an RC blocker"
        )
        assert gd.get("release_gate_required") is False, (
            "Google Drive integration should not be an RC blocker"
        )

    def test_rc_readiness_gate_does_not_reference_integration_phases(self):
        if RC_READINESS_PATH.is_file():
            gate = _load_json(RC_READINESS_PATH)
            phase_ids = {p.get("phase_id", "") for p in gate.get("phases", [])}
            integration_phases = {
                pid for pid in phase_ids if "integration" in pid.lower()
            }
            assert not integration_phases, (
                f"RC readiness gate should not have integration-specific phases: {integration_phases}"
            )

    def test_rc_blockers_do_not_reference_integration_artifacts(self):
        if not RC_BLOCKERS_PATH.is_file():
            pytest.skip("No RC blockers file")
        blockers = []
        for line in RC_BLOCKERS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                blockers.append(json.loads(line))
            except json.JSONDecodeError:
                pass

        for blocker in blockers:
            blk_id = blocker.get("blocker_id", "")
            assert "integration" not in blk_id.lower(), (
                f"RC blocker references integration: {blk_id}"
            )


class TestIntegrationEvidence:
    def test_manifests_declare_evidence_paths(self):
        gh = _load_json(GITHUB_MANIFEST_PATH)
        gd = _load_json(GDRIVE_MANIFEST_PATH)
        assert len(gh.get("evidence_paths", [])) > 0, (
            "GitHub manifest must declare evidence paths"
        )
        assert len(gd.get("evidence_paths", [])) > 0, (
            "Google Drive manifest must declare evidence paths"
        )

    def test_evidence_paths_under_rig_directory(self):
        gh = _load_json(GITHUB_MANIFEST_PATH)
        gd = _load_json(GDRIVE_MANIFEST_PATH)
        for manifest in [gh, gd]:
            for evidence_path in manifest.get("evidence_paths", []):
                assert ".rig/" in evidence_path, (
                    f"Evidence path must be under .rig/: {evidence_path}"
                )

    def test_permission_policy_requires_content_light_evidence(self):
        policy = _load_json(PERMISSION_POLICY_PATH)
        found = False
        for rule in policy.get("global_rules", []):
            if rule["rule_id"] == "content_light_evidence_default":
                assert rule["enforcement"] == "hard_block"
                found = True
        assert found, "content_light_evidence_default global rule not found"

    def test_integration_state_no_raw_content_capability(self):
        from rig_relay.core.integrations.models import IntegrationProviderState

        fields = set(IntegrationProviderState.model_fields.keys())
        raw_content_fields = {
            "raw_output",
            "file_content",
            "document_text",
            "source_code",
            "payload",
        }
        for field in raw_content_fields:
            assert field not in fields, (
                f"IntegrationProviderState has raw content field: {field}"
            )


class TestFrontendProjectionSafety:
    def test_projection_widget_registered_for_integration_status(self):
        from rig_relay.desktop.projection_widgets import ALL_WIDGETS, INTEGRATION_STATUS

        assert INTEGRATION_STATUS in ALL_WIDGETS

    def test_integration_status_in_system_widgets(self):
        from rig_relay.desktop.projection_widgets import (
            INTEGRATION_STATUS,
            SYSTEM_WIDGETS,
        )

        assert INTEGRATION_STATUS in SYSTEM_WIDGETS

    def test_projection_field_maps_to_integration_widget(self):
        from rig_relay.desktop.projection_widgets import (
            INTEGRATION_STATUS,
            PROJECTION_FIELD_TO_WIDGET,
        )

        assert PROJECTION_FIELD_TO_WIDGET.get("integrations") == INTEGRATION_STATUS

    def test_projection_build_integrations_available(self):
        from rig_relay.desktop.projection import _build_integrations

        result = _build_integrations()
        assert "available" in result
        if result["available"]:
            assert "providers" in result
            for provider in result.get("providers", []):
                assert "access_token" not in provider
                assert "refresh_token" not in provider
                assert "private_key" not in provider

    def test_projection_providers_has_no_secret_fields(self):
        from rig_relay.desktop.projection import _build_integrations

        result = _build_integrations()
        if result.get("available") and result.get("providers"):
            for provider in result["providers"]:
                secret_names = {
                    "access_token",
                    "refresh_token",
                    "id_token",
                    "private_key",
                    "client_secret",
                    "api_key",
                }
                for key in provider:
                    assert key not in secret_names, (
                        f"Provider projection has secret field: {key}"
                    )
                    if isinstance(provider[key], dict):
                        for subkey in provider[key]:
                            assert subkey not in secret_names, (
                                f"Provider projection has secret field: {subkey}"
                            )

    def test_projection_build_integrations_no_exception(self):
        from rig_relay.desktop.projection import _build_integrations

        result = _build_integrations()
        assert isinstance(result, dict)
        assert "available" in result
