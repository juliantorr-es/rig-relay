from __future__ import annotations

import json
from pathlib import Path

import jsonschema

_REPO_ROOT = Path(__file__).resolve().parents[2]
_THREAT_MODEL_SCHEMA = (
    _REPO_ROOT / "docs" / "schemas" / "rig.security.threat_model.v1.schema.json"
)
_THREAT_MODEL_JSON = (
    _REPO_ROOT / "docs" / "json" / "security" / "threat_model_v0.v1.json"
)
_SITE_MANIFEST = _REPO_ROOT / "docs" / "json" / "site_manifest.v1.json"
_PAGES_OUT = _REPO_ROOT / "docs" / "pages"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


class TestThreatModelSchema:
    def test_threat_model_schema_parses(self) -> None:
        schema = _load_json(_THREAT_MODEL_SCHEMA)
        assert schema["title"] == "Rig Security Threat Model"
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "$id" in schema

    def test_threat_model_json_parses_and_validates(self) -> None:
        schema = _load_json(_THREAT_MODEL_SCHEMA)
        data = _load_json(_THREAT_MODEL_JSON)
        jsonschema.validate(data, schema)
        assert data["schema_version"] == "rig.security.threat_model.v1"
        assert data["threat_model_id"] == "rig-relay-threat-model-v0"
        assert data["status"] == "draft"


class TestThreatModelAssets:
    def test_required_assets_exist(self) -> None:
        data = _load_json(_THREAT_MODEL_JSON)
        asset_ids = {a["asset_id"] for a in data["assets"]}
        required = {
            "local-auth-token",
            "frontend-runtime-config",
            "websocket-control-channel",
            "desktop-bridge-server",
            "trace-store",
            "receipts-evidence",
            "worktrees-user-files",
            "git-working-tree",
            "agent-prompt-context-envelope",
            "model-output-tool-calls",
            "code-schema-library",
            "context-assembler-output",
            "generated-docs-static-site",
            "contribution-license-governance",
        }
        missing = required - asset_ids
        assert not missing, f"Missing required assets: {missing}"

    def test_assets_count_meets_minimum(self) -> None:
        data = _load_json(_THREAT_MODEL_JSON)
        assert len(data["assets"]) >= 14


class TestThreatModelTrustBoundaries:
    def test_required_trust_boundaries_exist(self) -> None:
        data = _load_json(_THREAT_MODEL_JSON)
        boundary_ids = {b["boundary_id"] for b in data["trust_boundaries"]}
        required = {
            "user-prompt-to-agent-context",
            "repo-docs-context-to-agent-context",
            "external-web-uploaded-content-to-agent-context",
            "model-output-to-tool-execution",
            "frontend-browser-to-local-bridge",
            "http-static-to-websocket-route",
            "websocket-auth-to-projection-stream",
            "trace-payload-to-persisted-store",
            "json-docs-to-rendered-static-html",
            "code-schema-registry-to-context-assembler",
            "agent-worktree-to-main-repository",
        }
        missing = required - boundary_ids
        assert not missing, f"Missing required trust boundaries: {missing}"

    def test_trust_boundaries_count_meets_minimum(self) -> None:
        data = _load_json(_THREAT_MODEL_JSON)
        assert len(data["trust_boundaries"]) >= 11


class TestThreatModelThreats:
    def test_required_threats_exist(self) -> None:
        data = _load_json(_THREAT_MODEL_JSON)
        threat_ids = {t["threat_id"] for t in data["threats"]}
        required = {
            "T01",
            "T02",
            "T03",
            "T04",
            "T05",
            "T06",
            "T07",
            "T08",
            "T09",
            "T10",
            "T11",
            "T12",
            "T13",
            "T14",
            "T15",
            "T16",
            "T17",
        }
        missing = required - threat_ids
        assert not missing, f"Missing required threats: {missing}"

    def test_threats_count_meets_minimum(self) -> None:
        data = _load_json(_THREAT_MODEL_JSON)
        assert len(data["threats"]) >= 17

    def test_every_threat_has_required_fields(self) -> None:
        data = _load_json(_THREAT_MODEL_JSON)
        for threat in data["threats"]:
            assert threat.get("priority") in {"low", "medium", "high", "critical"}, (
                f"{threat['threat_id']}: missing or invalid priority"
            )
            assert threat.get("affected_assets"), (
                f"{threat['threat_id']}: missing affected_assets"
            )
            assert isinstance(threat.get("existing_mitigations"), list), (
                f"{threat['threat_id']}: missing existing_mitigations"
            )
            assert isinstance(threat.get("missing_mitigations"), list), (
                f"{threat['threat_id']}: missing missing_mitigations"
            )
            assert threat.get("status") in {
                "open",
                "mitigated",
                "accepted",
                "deferred",
            }, f"{threat['threat_id']}: missing or invalid status"

    def test_release_blocker_threats_have_tests_or_missing_mitigations(self) -> None:
        data = _load_json(_THREAT_MODEL_JSON)
        for threat in data["threats"]:
            if threat.get("release_blocker"):
                has_test = bool(threat.get("tests_or_proofs"))
                has_missing = bool(threat.get("missing_mitigations"))
                assert has_test or has_missing, (
                    f"{threat['threat_id']}: release_blocker but no tests/proofs and no missing_mitigations"
                )

    def test_websocket_threats_mention_origin_auth_message_validation(self) -> None:
        data = _load_json(_THREAT_MODEL_JSON)
        ws_threats = [
            t
            for t in data["threats"]
            if "websocket" in t.get("category", "").lower()
            or "websocket" in t.get("name", "").lower()
        ]
        assert len(ws_threats) >= 2
        for threat in ws_threats:
            combined = f"{threat.get('name', '')} {threat.get('description', '')} {' '.join(threat.get('existing_mitigations', []))} {' '.join(threat.get('missing_mitigations', []))}".lower()
            assert (
                "origin" in combined or "auth" in combined or "message" in combined
            ), (
                f"{threat['threat_id']}: WebSocket threat should mention origin/auth/message validation"
            )

    def test_prompt_injection_threats_mention_untrusted_context_separation(
        self,
    ) -> None:
        data = _load_json(_THREAT_MODEL_JSON)
        pi_threats = [
            t
            for t in data["threats"]
            if "prompt injection" in t.get("category", "").lower()
        ]
        assert len(pi_threats) >= 2
        for threat in pi_threats:
            combined = f"{threat.get('description', '')} {' '.join(threat.get('missing_mitigations', []))}".lower()
            assert (
                "untrusted" in combined
                or "separation" in combined
                or "sanitization" in combined
                or "sandbox" in combined
            ), (
                f"{threat['threat_id']}: prompt injection threat should mention untrusted content handling"
            )

    def test_token_leakage_threats_mention_trace_frontend_static_docs_redaction(
        self,
    ) -> None:
        data = _load_json(_THREAT_MODEL_JSON)
        token_threats = [
            t
            for t in data["threats"]
            if "token" in t.get("name", "").lower()
            or "sensitive data" in t.get("name", "").lower()
        ]
        assert len(token_threats) >= 2
        for threat in token_threats:
            combined = f"{threat.get('name', '')} {threat.get('description', '')} {' '.join(threat.get('existing_mitigations', []))} {' '.join(threat.get('missing_mitigations', []))}".lower()
            assert (
                "trace" in combined
                or "frontend" in combined
                or "redact" in combined
                or "static" in combined
                or "docs" in combined
            ), (
                f"{threat['threat_id']}: token leakage threat should mention trace/frontend/static docs"
            )

    def test_generated_docs_threats_mention_escaping_no_raw_script_no_local_paths(
        self,
    ) -> None:
        data = _load_json(_THREAT_MODEL_JSON)
        gen_threats = [
            t for t in data["threats"] if "generated" in t.get("name", "").lower()
        ]
        assert len(gen_threats) >= 2
        for threat in gen_threats:
            combined = f"{threat.get('name', '')} {threat.get('description', '')} {' '.join(threat.get('existing_mitigations', []))}".lower()
            assert (
                "escape" in combined
                or "script" in combined
                or "path" in combined
                or "xss" in combined
                or "unescape" in combined
            ), (
                f"{threat['threat_id']}: generated docs threat should mention escaping/script/path"
            )

    def test_code_schema_authority_threats_mention_source_hash_and_generated_html_exclusion(
        self,
    ) -> None:
        data = _load_json(_THREAT_MODEL_JSON)
        schema_threats = [
            t
            for t in data["threats"]
            if "code schema" in t.get("name", "").lower()
            or "schema authority" in t.get("name", "").lower()
        ]
        assert len(schema_threats) >= 1
        for threat in schema_threats:
            combined = f"{threat.get('description', '')} {' '.join(threat.get('existing_mitigations', []))} {' '.join(threat.get('missing_mitigations', []))}".lower()
            assert "hash" in combined or "html" in combined, (
                f"{threat['threat_id']}: code schema threat should mention source_hash or HTML exclusion"
            )


class TestSecuritySiteIntegration:
    def test_security_docs_in_site_manifest(self) -> None:
        site = _load_json(_SITE_MANIFEST)
        security_collection = next(
            (
                c
                for c in site.get("collections", [])
                if c["collection_id"] == "security"
            ),
            None,
        )
        assert security_collection is not None, (
            "Security collection missing from site manifest"
        )
        doc_ids = {d["document_id"] for d in security_collection.get("documents", [])}
        assert "security-policy" in doc_ids
        assert "rig-relay-threat-model-v0" in doc_ids

    def test_security_pages_rendered(self) -> None:
        security_policy_page = _PAGES_OUT / "security-policy.html"
        threat_model_page = _PAGES_OUT / "rig-relay-threat-model-v0.html"
        assert security_policy_page.is_file(), (
            f"Missing rendered page: {security_policy_page}"
        )
        assert threat_model_page.is_file(), (
            f"Missing rendered page: {threat_model_page}"
        )
