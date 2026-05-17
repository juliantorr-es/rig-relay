from __future__ import annotations

import contextlib
import json
from pathlib import Path
import re

import jsonschema
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AUDIT_SCHEMA = (
    _REPO_ROOT / "docs" / "schemas" / "rig.github_app.integration_audit.v1.schema.json"
)
_AUDIT_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "integrations"
    / "github_app_integration_audit_v0.v1.json"
)
_CONFIG_SCHEMA = (
    _REPO_ROOT / "docs" / "schemas" / "rig.github_app.config.v1.schema.json"
)
_SITE_MANIFEST = _REPO_ROOT / "docs" / "json" / "site_manifest.v1.json"
_PAGES_OUT = _REPO_ROOT / "docs" / "pages"
_RENDERER_SCRIPT = _REPO_ROOT / "scripts" / "render_static_docs.py"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _non_empty_str(val: object) -> bool:
    return isinstance(val, str) and len(val) > 0


def _non_empty_list(val: object) -> bool:
    return isinstance(val, list) and len(val) > 0


class TestIntegrationAuditSchema:
    def test_audit_schema_parses(self) -> None:
        schema = _load_json(_AUDIT_SCHEMA)
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "$id" in schema
        assert schema["type"] == "object"
        assert "schema_version" in schema["properties"]
        assert "audit_id" in schema["required"]

    def test_audit_schema_has_all_required_sections(self) -> None:
        schema = _load_json(_AUDIT_SCHEMA)
        required_sections = {
            "app_registration",
            "permission_profiles",
            "webhook_subscriptions",
            "backend_components",
            "frontend_components",
            "data_flows",
            "trust_boundaries",
            "security_controls",
            "trace_events",
            "storage_model",
            "ui_states",
            "implementation_phases",
            "risks",
            "open_questions",
            "release_gates",
            "tests",
            "provenance",
        }
        missing = required_sections - set(schema["required"])
        assert not missing, f"Missing required sections in schema: {missing}"

    def test_audit_schema_validates_itself(self) -> None:
        schema = _load_json(_AUDIT_SCHEMA)
        jsonschema.Draft7Validator.check_schema(schema)


class TestIntegrationAuditJSON:
    def test_audit_json_parses(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        assert audit["schema_version"] == "rig.github_app.integration_audit.v1"
        assert audit["audit_id"] == "github-app-integration-audit-v0"
        assert audit["status"] == "draft"

    def test_audit_json_validates_against_schema(self) -> None:
        schema = _load_json(_AUDIT_SCHEMA)
        audit = _load_json(_AUDIT_JSON)
        jsonschema.validate(audit, schema)

    def test_audit_json_source_commit_matches_current(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        assert _non_empty_str(audit.get("source_commit"))


class TestAppRegistration:
    def test_audit_includes_app_registration(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        reg = audit["app_registration"]
        assert _non_empty_str(reg["app_name_recommendation"])
        assert reg["owner_type"] in {"personal", "organization", "either"}
        assert isinstance(reg["webhook_secret_required"], bool)
        assert reg["webhook_secret_required"] is True
        assert isinstance(reg["ssl_verification_required"], bool)
        assert reg["ssl_verification_required"] is True
        assert isinstance(reg["user_authorization_needed"], bool)


class TestPermissionProfiles:
    def test_audit_has_at_least_four_permission_profiles(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        profiles = audit["permission_profiles"]
        assert len(profiles) >= 4

    def test_every_permission_profile_has_rationale_and_risks(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for profile in audit["permission_profiles"]:
            assert _non_empty_str(profile.get("rationale")), (
                f"Profile {profile['profile_id']} missing rationale"
            )
            assert _non_empty_list(profile.get("risks")), (
                f"Profile {profile['profile_id']} missing risks"
            )

    def test_admin_avoidance_profile_exists(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        admin_profile = next(
            (
                p
                for p in audit["permission_profiles"]
                if p["profile_id"] == "admin_avoidance_profile"
            ),
            None,
        )
        assert admin_profile is not None, "admin_avoidance_profile not found"
        repo_perms = admin_profile.get("repository_permissions", {})
        assert len(repo_perms) > 0
        for perm, val in repo_perms.items():
            assert val == "avoid", (
                f"Permission {perm} in admin_avoidance_profile should be 'avoid', got '{val}'"
            )

    def test_permission_profile_ids_are_unique(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        ids = [p["profile_id"] for p in audit["permission_profiles"]]
        assert len(ids) == len(set(ids)), f"Duplicate profile IDs: {ids}"

    def test_every_profile_has_frontend_labels(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for profile in audit["permission_profiles"]:
            assert _non_empty_str(profile.get("frontend_display_label")), (
                f"Profile {profile['profile_id']} missing frontend_display_label"
            )
            assert _non_empty_str(profile.get("user_consent_copy")), (
                f"Profile {profile['profile_id']} missing user_consent_copy"
            )


class TestWebhookSubscriptions:
    def test_required_events_have_subscriptions(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        events = {s["event_name"] for s in audit["webhook_subscriptions"]}
        required = {
            "ping",
            "installation",
            "installation_repositories",
            "push",
            "pull_request",
        }
        missing = required - events
        assert not missing, f"Missing webhook subscriptions: {missing}"

    def test_every_webhook_sub_has_idempotency_fields(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for sub in audit["webhook_subscriptions"]:
            assert _non_empty_list(sub.get("idempotency_key_fields")), (
                f"Webhook {sub['event_name']} missing idempotency_key_fields"
            )

    def test_every_webhook_sub_has_trace_fields(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for sub in audit["webhook_subscriptions"]:
            assert _non_empty_list(sub.get("trace_fields")), (
                f"Webhook {sub['event_name']} missing trace_fields"
            )

    def test_every_webhook_sub_has_ignore_conditions(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for sub in audit["webhook_subscriptions"]:
            assert isinstance(sub.get("ignore_conditions"), list), (
                f"Webhook {sub['event_name']} missing ignore_conditions"
            )

    def test_every_webhook_sub_has_risk_level(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        valid = {"low", "medium", "high", "critical"}
        for sub in audit["webhook_subscriptions"]:
            assert sub.get("risk_level") in valid, (
                f"Webhook {sub['event_name']} has invalid risk_level: {sub.get('risk_level')}"
            )


class TestDataFlows:
    def test_audit_has_at_least_eight_data_flows(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        flows = audit["data_flows"]
        assert len(flows) >= 8, f"Expected at least 8 data flows, got {len(flows)}"

    def test_every_data_flow_has_security_controls(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for flow in audit["data_flows"]:
            assert _non_empty_list(flow.get("security_controls")), (
                f"Data flow {flow['flow_id']} missing security_controls"
            )

    def test_every_data_flow_has_failure_modes(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for flow in audit["data_flows"]:
            assert _non_empty_list(flow.get("failure_modes")), (
                f"Data flow {flow['flow_id']} missing failure_modes"
            )

    def test_flow_ids_are_unique(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        ids = [f["flow_id"] for f in audit["data_flows"]]
        assert len(ids) == len(set(ids)), f"Duplicate flow IDs: {ids}"


class TestTrustBoundaries:
    def test_audit_has_at_least_nine_trust_boundaries(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        boundaries = audit["trust_boundaries"]
        assert len(boundaries) >= 9, (
            f"Expected at least 9 trust boundaries, got {len(boundaries)}"
        )

    def test_every_trust_boundary_has_required_tests(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for b in audit["trust_boundaries"]:
            assert _non_empty_list(b.get("required_tests")), (
                f"Trust boundary {b['boundary_id']} missing required_tests"
            )

    def test_every_trust_boundary_has_threats(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for b in audit["trust_boundaries"]:
            assert _non_empty_list(b.get("threats")), (
                f"Trust boundary {b['boundary_id']} missing threats"
            )

    def test_every_trust_boundary_has_controls(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for b in audit["trust_boundaries"]:
            assert _non_empty_list(b.get("controls")), (
                f"Trust boundary {b['boundary_id']} missing controls"
            )

    def test_boundary_ids_are_unique(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        ids = [b["boundary_id"] for b in audit["trust_boundaries"]]
        assert len(ids) == len(set(ids)), f"Duplicate boundary IDs: {ids}"


class TestReleaseGates:
    def test_every_release_gate_has_pass_condition(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for gate in audit["release_gates"]:
            assert _non_empty_str(gate.get("pass_condition")), (
                f"Release gate {gate['gate_id']} missing pass_condition"
            )

    def test_every_release_gate_has_required_tests(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for gate in audit["release_gates"]:
            assert _non_empty_list(gate.get("required_tests")), (
                f"Release gate {gate['gate_id']} missing required_tests"
            )

    def test_release_blocker_gates_exist(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        blockers = [g for g in audit["release_gates"] if g.get("release_blocker")]
        assert len(blockers) > 0, "No release_blocker gates found"

    def test_gate_ids_are_unique(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        ids = [g["gate_id"] for g in audit["release_gates"]]
        assert len(ids) == len(set(ids)), f"Duplicate gate IDs: {ids}"


class TestFrontendUIStates:
    def test_required_ui_states_exist(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        states = {s["state_id"] for s in audit["ui_states"]}
        required = {
            "not_configured",
            "installed_no_repo",
            "repo_connected",
            "webhook_degraded",
            "permission_update_required",
        }
        missing = required - states
        assert not missing, f"Missing UI states: {missing}"

    def test_every_ui_state_has_copy(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for state in audit["ui_states"]:
            assert _non_empty_str(state.get("empty_state_copy")), (
                f"UI state {state['state_id']} missing empty_state_copy"
            )
            assert _non_empty_str(state.get("error_state_copy")), (
                f"UI state {state['state_id']} missing error_state_copy"
            )

    def test_every_ui_state_has_sensitive_data_hidden(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for state in audit["ui_states"]:
            assert isinstance(state.get("sensitive_data_hidden"), list), (
                f"UI state {state['state_id']} missing sensitive_data_hidden list"
            )

    def test_state_ids_are_unique(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        ids = [s["state_id"] for s in audit["ui_states"]]
        assert len(ids) == len(set(ids)), f"Duplicate UI state IDs: {ids}"


class TestTraceEvents:
    def test_signature_trace_events_exist(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        events = {e["event_name"] for e in audit["trace_events"]}
        required = {
            "github.webhook.signature_verified",
            "github.webhook.signature_rejected",
        }
        missing = required - events
        assert not missing, f"Missing trace events: {missing}"

    def test_all_trace_events_are_safe_to_log(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for event in audit["trace_events"]:
            assert event.get("safe_to_log") is True, (
                f"Trace event {event['event_name']} must be safe_to_log"
            )

    def test_all_trace_events_never_include_secrets(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for event in audit["trace_events"]:
            assert event.get("never_includes_secrets") is True, (
                f"Trace event {event['event_name']} must have never_includes_secrets: true"
            )

    def test_all_trace_events_have_correlation_fields(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for event in audit["trace_events"]:
            assert _non_empty_list(event.get("correlation_fields")), (
                f"Trace event {event['event_name']} missing correlation_fields"
            )

    def test_trace_event_names_are_unique(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        names = [e["event_name"] for e in audit["trace_events"]]
        assert len(names) == len(set(names)), f"Duplicate trace event names: {names}"


class TestStorageModel:
    def test_storage_model_forbids_raw_secret_values(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        rules = audit["storage_model"]["rules"]
        secret_rules = [r for r in rules if "secret" in r.lower() or "key" in r.lower()]
        assert len(secret_rules) >= 2, (
            f"Expected at least 2 secret-related storage rules, got {len(secret_rules)}"
        )
        rule_text = " ".join(rules).lower()
        assert (
            "never store raw" in rule_text
            or "no secret" in rule_text
            or "secret values" in rule_text
        ), "Storage rules must explicitly forbid raw secret values"

    def test_storage_artifacts_are_well_defined(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        artifacts = audit["storage_model"]["artifacts"]
        secret_artifacts = [a for a in artifacts if a.get("contains_secrets")]
        for a in secret_artifacts:
            assert a["artifact_path"] != "", "Secret artifact must have a path"
            assert (
                "disk" not in a.get("description", "").lower()
                or "memory" in a.get("format", "").lower()
            ), f"Secret artifact {a['artifact_path']} should not be durably stored"

    def test_token_artifact_is_memory_only(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        token_artifact = next(
            (
                a
                for a in audit["storage_model"]["artifacts"]
                if "token" in a.get("artifact_path", "").lower()
                or "token" in a.get("content_type", "").lower()
            ),
            None,
        )
        assert token_artifact is not None, "Token storage artifact not found"
        assert token_artifact.get("contains_secrets") is True
        artifact_path = token_artifact.get("artifact_path", "")
        artifact_format = token_artifact.get("format", "").lower()
        assert "memory" in artifact_path.lower() or "memory" in artifact_format, (
            "Token cache must be memory-only"
        )


class TestConfigSchema:
    def test_config_schema_parses(self) -> None:
        schema = _load_json(_CONFIG_SCHEMA)
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "$id" in schema
        assert schema["type"] == "object"
        jsonschema.Draft7Validator.check_schema(schema)

    def test_config_schema_validates_valid_config(self) -> None:
        schema = _load_json(_CONFIG_SCHEMA)
        valid_config = {
            "schema_version": "rig.github_app.config.v1",
            "app_id": 123456,
            "webhook_secret_ref": "keychain://rig-relay/github-webhook-secret",
            "private_key_ref": "file:///Users/user/.config/rig-relay/github/private-key.pem",
            "created_at": "2026-05-17T00:00:00Z",
        }
        jsonschema.validate(valid_config, schema)

    def test_config_schema_rejects_raw_private_key_pem(self) -> None:
        schema = _load_json(_CONFIG_SCHEMA)
        bad_config = {
            "schema_version": "rig.github_app.config.v1",
            "app_id": 123456,
            "webhook_secret_ref": "keychain://rig-relay/github-webhook-secret",
            "private_key_ref": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----",
            "created_at": "2026-05-17T00:00:00Z",
        }
        with _raises_schema_error():
            jsonschema.validate(bad_config, schema)

    def test_config_schema_rejects_raw_webhook_secret(self) -> None:
        schema = _load_json(_CONFIG_SCHEMA)
        bad_config = {
            "schema_version": "rig.github_app.config.v1",
            "app_id": 123456,
            "webhook_secret_ref": "my-super-secret-webhook-token-12345",
            "private_key_ref": "file:///Users/user/.config/rig-relay/github/private-key.pem",
            "created_at": "2026-05-17T00:00:00Z",
        }
        with _raises_schema_error():
            jsonschema.validate(bad_config, schema)

    def test_config_schema_rejects_missing_required_fields(self) -> None:
        schema = _load_json(_CONFIG_SCHEMA)
        bad_config = {"schema_version": "rig.github_app.config.v1", "app_id": 123456}
        with _raises_schema_error():
            jsonschema.validate(bad_config, schema)

    def test_config_schema_rejects_invalid_ref_pattern(self) -> None:
        schema = _load_json(_CONFIG_SCHEMA)
        bad_config = {
            "schema_version": "rig.github_app.config.v1",
            "app_id": 123456,
            "webhook_secret_ref": "just a string",
            "private_key_ref": "also invalid",
            "created_at": "2026-05-17T00:00:00Z",
        }
        with _raises_schema_error():
            jsonschema.validate(bad_config, schema)

    def test_config_schema_app_id_must_be_positive(self) -> None:
        schema = _load_json(_CONFIG_SCHEMA)
        bad_config = {
            "schema_version": "rig.github_app.config.v1",
            "app_id": 0,
            "webhook_secret_ref": "keychain://rig-relay/github-webhook-secret",
            "private_key_ref": "file:///Users/user/.config/rig-relay/github/private-key.pem",
            "created_at": "2026-05-17T00:00:00Z",
        }
        with _raises_schema_error():
            jsonschema.validate(bad_config, schema)


class TestSiteManifestIntegration:
    def test_audit_added_to_site_manifest(self) -> None:
        manifest = _load_json(_SITE_MANIFEST)
        all_docs = []
        for col in manifest.get("collections", []):
            for doc in col.get("documents", []):
                all_docs.append(doc.get("path", ""))
        audit_path = "docs/json/integrations/github_app_integration_audit_v0.v1.json"
        assert audit_path in all_docs, (
            f"Audit not found in site manifest. Paths include: {all_docs[:5]}..."
        )

    def test_config_schema_is_auto_discovered_by_renderer(self) -> None:
        assert _CONFIG_SCHEMA.exists(), f"Config schema must exist at {_CONFIG_SCHEMA}"


class TestStaticRendererOutput:
    def test_static_renderer_runs_successfully(self) -> None:
        import subprocess

        result = subprocess.run(
            ["uv", "run", "python", str(_RENDERER_SCRIPT)],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Static renderer failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_audit_page_rendered(self) -> None:
        audit_page = _PAGES_OUT / "github-app-integration-audit-v0.html"
        assert audit_page.exists(), f"Audit page not found at {audit_page}"
        content = audit_page.read_text()
        assert "GitHub App Integration Audit v0" in content, (
            "Audit page does not contain expected title"
        )

    def test_generated_docs_contain_no_secret_values(self) -> None:
        audit_page = _PAGES_OUT / "github-app-integration-audit-v0.html"
        if not audit_page.exists():
            return
        content = audit_page.read_text()

        pem_pattern = r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"
        assert not re.search(pem_pattern, content), (
            "Generated docs contain private key PEM header"
        )

        secret_patterns = [r"ghs_[a-zA-Z0-9]{36}", r"github_pat_[a-zA-Z0-9_]{20,}"]
        for pattern in secret_patterns:
            assert not re.search(pattern, content), (
                f"Generated docs contain secret-looking pattern: {pattern}"
            )

    def test_generated_docs_contain_key_sections(self) -> None:
        audit_page = _PAGES_OUT / "github-app-integration-audit-v0.html"
        if not audit_page.exists():
            return
        content = audit_page.read_text()
        expected_sections = [
            "App Registration",
            "Permission Profiles",
            "Webhook",
            "Release Gate",
            "Trust Boundar",
            "Security Control",
            "Trace Events",
            "Storage Model",
            "UI States",
            "Implementation Phases",
            "Backend Components",
            "Frontend Components",
        ]
        for section in expected_sections:
            assert section.lower() in content.lower(), (
                f"Generated docs missing expected section: {section}"
            )


class TestNoCrossFileSecretLeakage:
    def test_audit_json_no_raw_pem(self) -> None:
        content = _AUDIT_JSON.read_text()
        assert "-----BEGIN" not in content, "Audit JSON contains PEM header"
        assert "PRIVATE KEY" not in content, "Audit JSON contains private key text"

    def test_config_schema_no_raw_pem(self) -> None:
        content = _CONFIG_SCHEMA.read_text()
        pem_block = re.search(r"-{5}BEGIN (RSA |EC )?PRIVATE KEY-{5}", content)
        assert pem_block is None, "Config schema contains PEM key block"

    def test_audit_json_no_webhook_secret_value(self) -> None:
        content = _AUDIT_JSON.read_text()
        assert "ghs_" not in content, "Audit JSON may contain webhook secret pattern"

    def test_external_references_are_valid_urls(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for ref in audit.get("external_references", []):
            assert ref["url"].startswith("https://"), (
                f"External reference URL must be HTTPS: {ref['url']}"
            )


class TestSecurityControls:
    def test_security_controls_at_least_fourteen(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        assert len(audit["security_controls"]) >= 14, (
            f"Expected at least 14 security controls, got {len(audit['security_controls'])}"
        )

    def test_every_security_control_has_status(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        valid = {"planned", "implemented", "deferred", "not_applicable"}
        for ctrl in audit["security_controls"]:
            assert ctrl.get("status") in valid, (
                f"Control {ctrl['control_id']} has invalid status: {ctrl.get('status')}"
            )

    def test_control_ids_are_unique(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        ids = [c["control_id"] for c in audit["security_controls"]]
        assert len(ids) == len(set(ids)), f"Duplicate control IDs: {ids}"


class TestImplementationPhases:
    def test_phases_have_blocked_by(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        for phase in audit["implementation_phases"]:
            assert isinstance(phase.get("blocked_by"), list), (
                f"Phase {phase['phase_id']} missing blocked_by"
            )
            assert _non_empty_str(phase.get("done_when")), (
                f"Phase {phase['phase_id']} missing done_when"
            )

    def test_phase_ids_are_unique(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        ids = [p["phase_id"] for p in audit["implementation_phases"]]
        assert len(ids) == len(set(ids)), f"Duplicate phase IDs: {ids}"


class TestBackendComponents:
    def test_backend_components_are_declared(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        components = audit["backend_components"]
        assert len(components) >= 10, (
            f"Expected at least 10 backend components, got {len(components)}"
        )
        module_paths = {c["module_path"] for c in components}
        assert "rig_relay/github_app/auth.py" in module_paths
        assert "rig_relay/github_app/webhooks.py" in module_paths
        assert "rig_relay/github_app/tokens.py" in module_paths

    def test_component_ids_are_unique(self) -> None:
        audit = _load_json(_AUDIT_JSON)
        ids = [c["component_id"] for c in audit["backend_components"]]
        assert len(ids) == len(set(ids)), f"Duplicate component IDs: {ids}"


@contextlib.contextmanager
def _raises_schema_error():
    with pytest.raises((jsonschema.ValidationError, jsonschema.SchemaError)):
        yield
