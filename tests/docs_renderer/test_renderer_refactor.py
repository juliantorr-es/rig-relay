from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rig_relay.docs_renderer.guard import (
    ALLOWED_MARKDOWN,
    check_input_manifest,
    check_input_path,
)
from rig_relay.docs_renderer.models import SiteMeta
from rig_relay.docs_renderer.paths import REPO_ROOT
from rig_relay.docs_renderer.release_gate import (
    load_release_artifacts,
    render_golden_path_page,
    render_rc_verdict_page,
    render_release_gate_page,
)
from rig_relay.docs_renderer.safety import (
    is_public_safe,
    redact_from_dict,
    scan_content,
    scan_rendered_site,
)
from rig_relay.docs_renderer.security import (
    render_schemas_page,
    render_security_hygiene_page,
)
from rig_relay.docs_renderer.telemetry_bridge import render_telemetry_policy_page
from rig_relay.docs_renderer.testing import render_test_inventory_page


def _repo_artifact(rel_path: str) -> Path:
    return REPO_ROOT / rel_path


def _load_json_artifact(rel_path: str) -> dict | None:
    p = _repo_artifact(rel_path)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _default_site_meta() -> SiteMeta:
    return SiteMeta("", "/rig-relay", "Rig Relay Docs", "#1e3a5f", "", "")


# ---------------------------------------------------------------------------
# 1. Input Manifest Tests
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInputManifestSchema:
    def test_input_manifest_schema_is_valid_json(self):
        schema_path = _repo_artifact(
            "docs/schemas/rig.site_renderer.input_manifest.v1.schema.json"
        )
        raw = schema_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert parsed["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "title" in parsed
        assert parsed.get("type") == "object"
        assert "required" in parsed
        assert "properties" in parsed
        assert "inputs" in parsed["properties"]

    def test_input_manifest_validates_against_schema(self):
        import jsonschema

        schema = _load_json_artifact(
            "docs/schemas/rig.site_renderer.input_manifest.v1.schema.json"
        )
        manifest = _load_json_artifact("docs/json/site_renderer/input_manifest.v1.json")
        assert schema is not None, "Schema not found"
        assert manifest is not None, "Manifest not found"
        jsonschema.validate(manifest, schema)

    def test_input_manifest_all_inputs_have_required_fields(self):
        manifest = _load_json_artifact("docs/json/site_renderer/input_manifest.v1.json")
        required_fields = {
            "source_path",
            "source_type",
            "page_target",
            "safety_class",
            "public_safe",
            "redaction_required",
        }
        assert manifest is not None, "Input manifest not found"
        for entry in manifest["inputs"]:
            missing = required_fields - entry.keys()
            assert not missing, (
                f"Input missing fields {missing}: {entry.get('source_path', '?')}"
            )


# ---------------------------------------------------------------------------
# 2. Markdown Leak Guard
# ---------------------------------------------------------------------------


@pytest.mark.adversarial
class TestMarkdownLeakGuard:
    def test_check_input_path_allows_allowed_markdown(self):
        for name in sorted(ALLOWED_MARKDOWN):
            allowed, _reason = check_input_path(name)
            assert allowed, f"Expected {name} to be allowed"

    def test_check_input_path_rejects_audit_markdown(self):
        forbidden_paths = [
            "docs/audits/some-report.md",
            "docs/audits/release-candidate-convergence-spine.md",
        ]
        for path in forbidden_paths:
            allowed, reason = check_input_path(path)
            assert not allowed, f"Expected {path} to be rejected"
            assert "forbidden" in reason or "unlisted" in reason

    def test_check_input_path_rejects_findings_markdown(self):
        allowed, reason = check_input_path("docs/findings/out-of-scope-findings.md")
        assert not allowed
        assert reason == "markdown_evidence_forbidden"

    def test_check_input_path_allows_json_jsonl_csv(self):
        paths = [
            "docs/json/release_gate/rc_readiness_gate.v1.json",
            "data/reports.jsonl",
            "exports/summary.csv",
            "pages/index.html",
            "assets/site.css",
        ]
        for path in paths:
            allowed, reason = check_input_path(path)
            assert allowed, f"Expected {path} to be allowed, got reason={reason}"

    def test_check_input_manifest_accepts_valid_manifest(self, tmp_path: Path):
        manifest = {
            "inputs": [
                {
                    "source_path": "README.md",
                    "source_type": "static_asset",
                    "page_target": "home",
                    "freshness_policy": "always",
                    "safety_class": "public_safe",
                    "public_safe": True,
                    "redaction_required": False,
                },
                {
                    "source_path": "docs/json/release_gate/rc_readiness_gate.v1.json",
                    "source_type": "json",
                    "page_target": "release-candidate",
                    "freshness_policy": "always",
                    "safety_class": "public_safe",
                    "public_safe": True,
                    "redaction_required": False,
                },
            ]
        }
        report = check_input_manifest(manifest)
        assert report.passed
        assert len(report.blocked_paths) == 0

    def test_check_input_manifest_rejects_forbidden_markdown(self, tmp_path: Path):
        manifest = {
            "inputs": [
                {
                    "source_path": "README.md",
                    "source_type": "static_asset",
                    "page_target": "home",
                    "freshness_policy": "always",
                    "safety_class": "public_safe",
                    "public_safe": True,
                    "redaction_required": False,
                },
                {
                    "source_path": "docs/audits/some-audit.md",
                    "source_type": "static_asset",
                    "page_target": "security",
                    "freshness_policy": "always",
                    "safety_class": "public_safe",
                    "public_safe": True,
                    "redaction_required": False,
                },
            ]
        }
        report = check_input_manifest(manifest)
        assert not report.passed
        assert len(report.blocked_paths) == 1
        assert report.blocked_paths[0].name == "some-audit.md"


# ---------------------------------------------------------------------------
# 3. Public Safety Scanner
# ---------------------------------------------------------------------------


@pytest.mark.adversarial
class TestPublicSafetyScanner:
    def test_scan_content_blocks_openai_key(self):
        text = "Here is my key: sk-abc123def456ghi789jkl012mno345pqr678stu"
        report = scan_content(text, "test-source")
        assert not report.passed
        assert any("OpenAI" in b["pattern_name"] for b in report.blocked)

    def test_scan_content_blocks_jwt_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0.Gfx6VOvMJXrJ3aXqLkD8lMlMK1pWZt9cQx_hVz0YpBs"
        report = scan_content(text, "test-source")
        assert not report.passed
        assert any("JWT" in b["pattern_name"] for b in report.blocked)

    def test_scan_content_blocks_pem_key(self):
        text = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7
-----END PRIVATE KEY-----"""
        report = scan_content(text, "test-source")
        assert not report.passed
        assert any("PEM" in b["pattern_name"] for b in report.blocked)

    def test_scan_content_allows_content_hashes(self):
        text = "sha256: " + hashlib.sha256(b"some file content").hexdigest()
        report = scan_content(text, "test-source")
        assert report.passed

    def test_scan_content_allows_clean_text(self):
        text = "This is clean documentation with no secrets or tokens."
        report = scan_content(text, "test-source")
        assert report.passed
        assert len(report.blocked) == 0

    def test_redact_from_dict_strips_sensitive_keys(self):
        data = {"api_key": "sk-secret-value", "name": "public-info"}
        result = redact_from_dict(data)
        assert result["api_key"] == "[REDACTED]"
        assert result["name"] == "public-info"

    def test_redact_from_dict_deep_nested(self):
        data = {"config": {"outer": {"token": "abc123secret", "safe_field": "hello"}}}
        result = redact_from_dict(data)
        assert result["config"]["outer"]["token"] == "[REDACTED]"
        assert result["config"]["outer"]["safe_field"] == "hello"

    def test_redact_from_dict_handles_lists(self):
        data = {
            "users": [
                {"name": "alice", "password": "s3cret"},
                {"name": "bob", "credential": "xyz"},
            ]
        }
        result = redact_from_dict(data)
        assert result["users"][0]["password"] == "[REDACTED]"
        assert result["users"][1]["credential"] == "[REDACTED]"
        assert result["users"][0]["name"] == "alice"

    def test_redact_from_dict_preserves_non_sensitive(self):
        data = {
            "title": "Release Gate",
            "description": "A public artifact",
            "status": "ready",
            "phases": ["phase_1", "phase_2"],
        }
        result = redact_from_dict(data)
        assert result == data

    def test_is_public_safe_true_for_clean_html(self):
        report = scan_content("<html><body>Hello</body></html>", "test.html")
        assert is_public_safe(report)

    def test_scan_rendered_site_detects_leaks(self, tmp_path: Path):
        site_dir = tmp_path / "site"
        site_dir.mkdir()
        (site_dir / "clean.html").write_text(
            "<html><body>Public page</body></html>", encoding="utf-8"
        )
        (site_dir / "leaky.html").write_text(
            "<html>sk-abc123def456ghi789jkl012mno345pqr678stu</html>", encoding="utf-8"
        )
        report = scan_rendered_site(site_dir)
        assert not report.passed
        assert report.file_count == 2
        assert len(report.blocked) >= 1


# ---------------------------------------------------------------------------
# 4. Domain Renderer Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.real_artifact
class TestDomainRenderers:
    def test_render_release_gate_page_produces_html(self):
        artifacts = load_release_artifacts()
        gate = artifacts.get("gate")
        if gate is None:
            pytest.skip("Release gate artifact not available")
        manifest = {"site_title": "Rig Relay Docs"}
        sm = _default_site_meta()
        html = render_release_gate_page(manifest, gate, sm)
        assert "<main" in html
        assert "release" in html.lower() or "gate" in html.lower()
        assert "<table" in html
        assert "phases" in html.lower() or "<tr>" in html

    def test_render_release_gate_missing_artifact_returns_warning(self):
        sm = _default_site_meta()
        html = render_release_gate_page({}, {}, sm)
        assert "<main" in html
        assert "not available" in html.lower() or "warning" in html.lower()

    def test_render_rc_verdict_page_shows_verdict(self):
        verdict = _load_json_artifact(
            "docs/json/release_gate/rc_candidate_verdict.v1.json"
        )
        if verdict is None:
            pytest.skip("Verdict artifact not available")
        sm = _default_site_meta()
        html = render_rc_verdict_page(verdict, sm)
        assert "<main" in html
        assert any(
            term in html.lower() for term in ["hold", "promote", "blocked", "verdict"]
        )

    def test_render_golden_path_page_shows_steps(self):
        golden = _load_json_artifact(
            "docs/json/release_candidate/rc_reviewer_golden_path.v1.json"
        )
        if golden is None:
            pytest.skip("Golden path artifact not available")
        sm = _default_site_meta()
        html = render_golden_path_page(golden, sm)
        assert "<main" in html
        assert "gp_install_sync" in html or "<section" in html

    def test_render_test_inventory_missing_artifact_returns_warning(self):
        sm = _default_site_meta()
        html = render_test_inventory_page(None, sm)
        assert "not available" in html.lower() or "warning" in html.lower()

    def test_render_telemetry_policy_missing_returns_warning(self):
        sm = _default_site_meta()
        html = render_telemetry_policy_page(None, sm)
        assert "not available" in html.lower() or "warning" in html.lower()

    def test_render_security_hygiene_missing_returns_warning(self):
        sm = _default_site_meta()
        html = render_security_hygiene_page(None, sm)
        assert "not available" in html.lower() or "warning" in html.lower()

    def test_render_schemas_page_discovers_json_files(self):
        sm = _default_site_meta()
        html = render_schemas_page(sm)
        assert "<main" in html
        schemas_dir = _repo_artifact("docs/schemas")
        if not schemas_dir.is_dir():
            pytest.skip("Schemas directory not available")
        json_files = list(schemas_dir.rglob("*.json"))
        if json_files:
            sample = json_files[0].name
            assert sample in html or any(f.name in html for f in json_files[:5])


# ---------------------------------------------------------------------------
# 5. Safety Integration
# ---------------------------------------------------------------------------


@pytest.mark.adversarial
class TestSafetyIntegration:
    def test_rendered_release_gate_has_no_tokens(self):
        artifacts = load_release_artifacts()
        gate = artifacts.get("gate")
        if gate is None:
            pytest.skip("Release gate artifact not available")
        sm = _default_site_meta()
        html = render_release_gate_page({}, gate, sm)
        report = scan_content(html, "rc_readiness.html")
        assert is_public_safe(report), (
            f"Blocked: {report.blocked}\nWarnings: {report.warnings}"
        )

    def test_rendered_html_has_main_landmark(self):
        artifacts = load_release_artifacts()
        gate = artifacts.get("gate")
        if gate is None:
            pytest.skip("Release gate artifact not available")
        sm = _default_site_meta()
        html = render_release_gate_page({}, gate, sm)
        assert "<main " in html

    def test_rendered_html_has_source_reference(self):
        artifacts = load_release_artifacts()
        gate = artifacts.get("gate")
        if gate is None:
            pytest.skip("Release gate artifact not available")
        sm = _default_site_meta()
        html = render_release_gate_page({}, gate, sm)
        assert "source-ref" in html or "Source:" in html


# ---------------------------------------------------------------------------
# 6. Structural Tests
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestPageModelSchema:
    def test_page_model_schema_is_valid_json(self):
        schema_path = _repo_artifact(
            "docs/schemas/rig.site_renderer.page_model.v1.schema.json"
        )
        raw = schema_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert parsed["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "title" in parsed
        assert parsed.get("type") == "object"
        assert "required" in parsed
        for field in [
            "page_id",
            "title",
            "route",
            "section_order",
            "generated_at",
            "source_commit",
            "source_artifact_paths",
            "public_safety_status",
        ]:
            assert field in parsed["required"], f"Missing required field: {field}"


@pytest.mark.adversarial
class TestHtmlEscaping:
    def test_all_renderers_use_html_escape(self):
        sm = _default_site_meta()
        script_tag = "<script>alert(1)</script>"
        malicious_data = {
            "gate_id": script_tag,
            "overall_status": "blocked",
            "head_sha": "a" * 40,
            "branch": script_tag,
            "generated_at": "2026-01-01T00:00:00Z",
            "phases": [
                {
                    "phase_id": script_tag,
                    "title": "Phase <evil>",
                    "status": "ready",
                    "blocker_ids": ["<img src=x>"],
                    "remaining_seams": ["seam <b>bold</b>"],
                    "owner_surface": "test",
                }
            ],
            "policy": {"key": script_tag},
        }
        html = render_release_gate_page({}, malicious_data, sm)
        assert script_tag not in html
        assert "&lt;script&gt;" in html

    def test_rendered_page_has_no_raw_angle_brackets_from_escaped_source(self):
        sm = _default_site_meta()
        malicious_phase = {
            "phase_id": "phase_test",
            "title": "Test <iframe src=evil> Phase",
            "status": "ready",
            "blocker_ids": [],
            "remaining_seams": [],
            "owner_surface": "test",
        }
        gate_data = {
            "gate_id": "test_gate",
            "overall_status": "blocked",
            "head_sha": "a" * 40,
            "branch": "main",
            "generated_at": "2026-01-01T00:00:00Z",
            "phases": [malicious_phase],
        }
        html = render_release_gate_page({}, gate_data, sm)
        assert "<iframe" not in html
        assert "&lt;iframe" in html


# ---------------------------------------------------------------------------
# 7. Edge case: MarkdownLeakReport for rendered site
# ---------------------------------------------------------------------------


@pytest.mark.substrate
class TestRenderedSiteGuard:
    def test_check_rendered_site_no_markdown_leaks(self, tmp_path: Path):
        from rig_relay.docs_renderer.guard import check_rendered_site

        site_dir = tmp_path / "rendered_site"
        site_dir.mkdir()
        (site_dir / "index.html").write_text(
            '<html><a href="README.md">README</a></html>', encoding="utf-8"
        )
        report = check_rendered_site(site_dir)
        assert report.passed or "README.md" in str(report.allowed_paths)

    def test_check_rendered_site_blocks_forbidden_href(self, tmp_path: Path):
        from rig_relay.docs_renderer.guard import check_rendered_site

        site_dir = tmp_path / "rendered_site"
        site_dir.mkdir()
        (site_dir / "bad.html").write_text(
            '<html><a href="docs/audits/bad.md">audit</a></html>', encoding="utf-8"
        )
        (site_dir / "docs").mkdir(exist_ok=True)
        (site_dir / "docs" / "audits").mkdir(exist_ok=True, parents=True)
        (site_dir / "docs" / "audits" / "bad.md").write_text("leaked", encoding="utf-8")
        report = check_rendered_site(site_dir)
        assert not report.passed or len(report.blocked_paths) > 0
