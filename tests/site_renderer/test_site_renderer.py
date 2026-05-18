from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.site_renderer.loaders import get_git_sha, load_json, load_page_model
from rig_relay.site_renderer.models import (
    InputEntry,
    InputManifest,
    PageModel,
    SectionKind,
)
from rig_relay.site_renderer.normalizers import build_page_model, normalize_release_gate
from rig_relay.site_renderer.renderer import render_index, render_page
from rig_relay.site_renderer.safety import (
    is_public_safe,
    redact_from_dict,
    scan_content,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _repo_artifact(rel_path: str) -> Path:
    return REPO_ROOT / rel_path


def _load_json_artifact(rel_path: str) -> dict | None:
    p = _repo_artifact(rel_path)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _page_model_dict(**overrides: object) -> dict:
    d: dict = {
        "page_id": "test-page",
        "title": "Test Page",
        "route": "/test/index.html",
        "source_artifact_paths": ["docs/json/test/test.v1.json"],
        "public_safety_status": "public_safe",
        "sections": [],
        "generated_at": "2026-05-18T00:00:00Z",
    }
    d.update(overrides)
    return d


# ---------------------------------------------------------------------------
# Schema & Model Tests (contract)
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestPageSchema:
    def test_page_schema_is_valid_json_schema(self):
        schema_path = _repo_artifact("docs/schemas/rig.site.page.v1.schema.json")
        assert schema_path.is_file(), f"Schema not found: {schema_path}"
        raw = schema_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert parsed["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert parsed.get("type") == "object"
        assert "properties" in parsed
        assert "sections" in parsed["properties"]
        assert "required" in parsed

    def test_input_manifest_schema_is_valid(self):
        schema_path = _repo_artifact(
            "docs/schemas/rig.site.input_manifest.v1.schema.json"
        )
        assert schema_path.is_file(), f"Schema not found: {schema_path}"
        parsed = json.loads(schema_path.read_text(encoding="utf-8"))
        assert parsed["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert parsed.get("type") == "object"
        assert "required" in parsed
        assert "inputs" in parsed["properties"]
        assert parsed["properties"]["inputs"]["type"] == "array"

    def test_render_report_schema_is_valid(self):
        schema_path = _repo_artifact(
            "docs/schemas/rig.site.render_report.v1.schema.json"
        )
        assert schema_path.is_file(), f"Schema not found: {schema_path}"
        parsed = json.loads(schema_path.read_text(encoding="utf-8"))
        assert parsed["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert parsed.get("type") == "object"
        assert "required" in parsed
        for field in (
            "render_duration_ms",
            "pages_rendered",
            "pages_failed",
            "safety_passed",
            "pages",
        ):
            assert field in parsed["properties"], f"Missing field: {field}"

    def test_page_models_validate_against_schema(self):
        schema_path = _repo_artifact("docs/schemas/rig.site.page.v1.schema.json")
        if not schema_path.is_file():
            pytest.skip("Page schema not found")

        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        site_dir = _repo_artifact("docs/json/site")
        page_files = sorted(site_dir.glob("page_*.v1.json"))
        if not page_files:
            pytest.skip("No page model files found in docs/json/site/")

        try:
            import jsonschema
        except ImportError:
            jsonschema = None

        for pf in page_files:
            model = json.loads(pf.read_text(encoding="utf-8"))
            if jsonschema is not None:
                jsonschema.validate(model, schema)
            else:
                for field in ("page_id", "title", "route", "sections"):
                    assert field in model, (
                        f"Missing required field '{field}' in {pf.name}"
                    )
                assert isinstance(model.get("sections"), list), (
                    f"sections is not a list in {pf.name}"
                )

    def test_input_manifest_page_models_exist(self):
        manifest = _load_json_artifact("docs/json/site/input_manifest.v1.json")
        if manifest is None:
            pytest.skip("Input manifest not found")
        inputs = manifest.get("inputs", [])
        assert len(inputs) > 0, "Input manifest has no entries"

        site_dir = _repo_artifact("docs/json/site")
        page_ids_seen: set[str] = set()
        for entry in inputs:
            pid = entry.get("page_id")
            if pid and pid not in page_ids_seen:
                page_ids_seen.add(pid)

        static_page_ids = {"home"}
        for pid in sorted(page_ids_seen):
            pid_underscore = pid.replace("-", "_")
            page_path = site_dir / f"page_{pid_underscore}.v1.json"
            if pid in static_page_ids:
                if not page_path.is_file():
                    continue
            assert page_path.is_file(), (
                f"Page model missing for page_id '{pid}' (looked for {page_path})"
            )

    def test_pydantic_page_model_parses_release_candidate(self):
        data = _load_json_artifact("docs/json/site/page_release_candidate.v1.json")
        if data is None:
            pytest.skip("Release candidate page model not found")
        if "$schema" in data:
            data["schema_version"] = data.pop("$schema")
        model = PageModel.model_validate(data)
        assert model.page_id == "release-candidate"
        assert len(model.sections) > 0
        hero_status = model.sections[0]
        assert hero_status.kind == SectionKind.HERO_STATUS
        assert hero_status.status_label in ("Hold", "Promote")

    def test_pydantic_input_manifest_parses(self):
        data = _load_json_artifact("docs/json/site/input_manifest.v1.json")
        if data is None:
            pytest.skip("Input manifest not found")
        if "$schema" in data:
            data["schema_version"] = data.pop("$schema")
        manifest = InputManifest.model_validate(data)
        assert len(manifest.inputs) > 0
        assert isinstance(manifest.inputs[0], InputEntry)
        assert manifest.inputs[0].source_path != ""


# ---------------------------------------------------------------------------
# Renderer Tests (integration)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRenderer:
    def test_render_page_produces_valid_html(self, tmp_path: Path):
        sections = [
            {
                "kind": "hero_status",
                "title": "Test Hero",
                "status_label": "Ready",
                "status_class": "ok",
                "summary": "All checks passed.",
                "blocker_count": 0,
                "ready_count": 5,
                "failed_count": 0,
            }
        ]
        page = _page_model_dict(sections=sections, page_id="test-hero")
        html = render_page(page)

        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert '<main id="main"' in html
        assert "<title>Test Page" in html
        assert 'class="skip-link"' in html
        assert "Ready" in html

    def test_render_page_all_section_kinds_render(self, tmp_path: Path):
        all_kinds: list[dict] = [
            {
                "kind": "hero_status",
                "title": "Hero",
                "status_label": "Alpha",
                "status_class": "info",
                "summary": "Summary text.",
                "blocker_count": 1,
                "ready_count": 3,
                "failed_count": 0,
            },
            {
                "kind": "card_grid",
                "title": "Cards",
                "cards": [
                    {
                        "title": "Card One",
                        "body_html": "Body content.",
                        "status": "ok",
                        "source_ref": "src/main.py",
                    }
                ],
            },
            {
                "kind": "table",
                "caption": "Data Table",
                "headers": ["Col A", "Col B"],
                "rows": [["a1", "b1"], ["a2", "b2"]],
            },
            {
                "kind": "timeline",
                "heading": "History",
                "entries": [
                    {
                        "timestamp": "2026-05-01",
                        "title": "Milestone",
                        "description": "Completed.",
                        "status": "ok",
                    }
                ],
            },
            {
                "kind": "artifact_nav",
                "heading": "Links",
                "links": [
                    {"label": "Doc", "href": "/doc", "description": "Read the doc."}
                ],
            },
            {
                "kind": "callout",
                "heading": "Note",
                "body_html": "Important info.",
                "callout_class": "info",
            },
            {
                "kind": "schema_index",
                "heading": "Schemas",
                "entries": [
                    {
                        "schema_id": "test.v1",
                        "file_path": "schemas/test.v1.json",
                        "description": "Test schema.",
                    }
                ],
            },
        ]

        for section in all_kinds:
            page = _page_model_dict(
                sections=[section], page_id=f"kind-{section['kind']}"
            )
            html = render_page(page)
            assert "<!DOCTYPE html>" in html, f"{section['kind']} produced invalid HTML"

        html = render_page(_page_model_dict(sections=all_kinds, page_id="all-kinds"))
        assert "<!DOCTYPE html>" in html
        for needle in (
            "<table>",
            "<time>",
            "<nav",
            "hero-status",
            "card-grid",
            "timeline",
            "callout",
        ):
            assert needle in html, f"Expected '{needle}' in rendered HTML"

    def test_render_page_missing_sections_produces_empty_page(self, tmp_path: Path):
        page = _page_model_dict(sections=[], page_id="empty")
        html = render_page(page)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html

    def test_render_index_produces_html(self, tmp_path: Path):
        pages = [
            {
                "title": "Page Alpha",
                "route": "/alpha/index.html",
                "description": "First page.",
                "safety_status": "public_safe",
            },
            {
                "title": "Page Beta",
                "route": "/beta/index.html",
                "description": "Second page.",
                "safety_status": "content_light",
            },
        ]
        site_meta: dict = {
            "generated_at": "2026-05-18T00:00:00Z",
            "branch": "main",
            "head_sha": "abc123def456",
            "safety_passed": True,
        }
        html = render_index(pages, site_meta)

        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "Page Alpha" in html
        assert "Page Beta" in html
        assert 'href="/alpha/index.html"' in html
        assert 'href="/beta/index.html"' in html

    def test_render_page_output_is_deterministic(self):
        sections = [
            {
                "kind": "hero_status",
                "title": "Deterministic",
                "status_label": "Ok",
                "status_class": "ok",
                "summary": "Same every time.",
                "blocker_count": 0,
                "ready_count": 0,
                "failed_count": 0,
            }
        ]
        page = _page_model_dict(
            sections=sections,
            page_id="deterministic",
            generated_at="2026-05-18T00:00:00Z",
        )
        first = render_page(page)
        second = render_page(page)
        assert first == second, "Same page model must produce identical HTML"

    def test_render_page_with_relative_root_nested(self, tmp_path: Path):
        sections = [
            {
                "kind": "card_grid",
                "title": "",
                "cards": [{"title": "Nested", "body_html": "", "status": "ok"}],
            }
        ]
        page = _page_model_dict(sections=sections, page_id="nested")
        html = render_page(page, relative_root="../..")

        assert 'href="../../assets/site.css"' in html
        assert 'href="../../index.html"' in html
        assert 'content="../.."' in html


# ---------------------------------------------------------------------------
# Safety Tests (adversarial)
# ---------------------------------------------------------------------------


@pytest.mark.adversarial
class TestSafetyBlocking:
    def test_scan_content_blocks_openai_key(self):
        text = "Here is my key: sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx"
        report = scan_content(text, source="test")
        assert not report.passed
        assert any(f.pattern_name == "openai_key" for f in report.findings)

    def test_scan_content_blocks_github_pat(self):
        text = "token: ghp_abcdefghijklmnopqrstuvwxyz1234567890AB"
        report = scan_content(text, source="test")
        assert not report.passed
        assert any(f.pattern_name == "github_pat" for f in report.findings)

    def test_scan_content_blocks_jwt(self):
        text = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0MTIzNDU2Nzg5MCJ9.abcdefghijklmnopqrstuvwxyz12345"
        report = scan_content(text, source="test")
        assert not report.passed
        assert any(f.pattern_name == "jwt_token" for f in report.findings)

    def test_scan_content_blocks_pem_private_key(self):
        text = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCnFakeKeyData+
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCnFakeKeyData=
-----END PRIVATE KEY-----"""
        report = scan_content(text, source="test")
        assert not report.passed
        assert any(f.pattern_name == "pem_key" for f in report.findings)

    def test_scan_content_allows_clean_text(self):
        text = "This is perfectly clean text with no secrets at all."
        report = scan_content(text, source="test")
        assert report.passed
        assert len(report.findings) == 0

    def test_scan_content_flags_hex_hashes_as_warnings(self):
        text = "checksum: a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3"
        report = scan_content(text, source="test")
        assert report.passed
        hex_findings = [f for f in report.findings if f.pattern_name == "hex_64"]
        assert len(hex_findings) > 0
        assert all(f.severity == "warn" for f in hex_findings)

    def test_redact_from_dict_replaces_sensitive_keys(self):
        data = {
            "username": "alice",
            "api_key": "secret123",
            "nested": {"auth_token": "bearer-xyz", "safe_field": "ok"},
        }
        result = redact_from_dict(data)
        assert result["api_key"] == "[REDACTED]"
        assert result["nested"]["auth_token"] == "[REDACTED]"
        assert result["nested"]["safe_field"] == "ok"
        assert result["username"] == "alice"

    def test_rendered_page_html_escapes_script_tags(self):
        sections = [
            {
                "kind": "hero_status",
                "title": "<script>alert(1)</script>",
                "status_label": "Test",
                "status_class": "info",
                "summary": "<script>alert(1)</script>",
                "blocker_count": 0,
                "ready_count": 0,
                "failed_count": 0,
            }
        ]
        page = _page_model_dict(sections=sections, page_id="xss-test")
        html = render_page(page)

        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_release_candidate_page_has_no_raw_tokens(self):
        model_path = _repo_artifact("docs/json/site/page_release_candidate.v1.json")
        if not model_path.is_file():
            pytest.skip("Release candidate page model not found")
        page = json.loads(model_path.read_text(encoding="utf-8"))
        html = render_page(page)
        report = scan_content(html, source="page_release_candidate")
        assert is_public_safe(report), (
            "Safety findings in release candidate page: "
            + ", ".join(f"{f.pattern_name}:{f.match_preview}" for f in report.findings)
        )


# ---------------------------------------------------------------------------
# Loader Tests (contract)
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestLoaders:
    def test_load_json_returns_dict_for_valid_path(self):
        path = _repo_artifact("docs/json/site/page_release_candidate.v1.json")
        if not path.is_file():
            pytest.skip("Release candidate page model not found")
        data = load_json(path)
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_load_json_returns_empty_dict_for_missing(self):
        data = load_json(Path("/nonexistent/path/to/file.json"))
        assert data == {}

    def test_get_git_sha_returns_string(self):
        sha = get_git_sha()
        assert isinstance(sha, str)
        assert len(sha) > 0

    def test_load_page_model_validates_required_fields(self):
        path = _repo_artifact("docs/json/site/page_release_candidate.v1.json")
        if not path.is_file():
            pytest.skip("Release candidate page model not found")
        data = load_page_model(path)
        assert data is not None
        assert data["page_id"] == "release-candidate"
        assert data["title"] == "Release Candidate Status"
        assert "route" in data
        assert "sections" in data
        assert isinstance(data["sections"], list)
        assert len(data["sections"]) > 0

    def test_load_input_manifest_loads_correctly(self):
        path = _repo_artifact("docs/json/site/input_manifest.v1.json")
        if not path.is_file():
            pytest.skip("Input manifest not found")
        data = load_json(path)
        assert isinstance(data, dict)
        assert len(data) > 0
        assert "inputs" in data
        assert isinstance(data["inputs"], list)
        assert len(data["inputs"]) > 0
        assert data["inputs"][0]["source_path"] != ""


# ---------------------------------------------------------------------------
# Normalizer Tests (integration)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestNormalizers:
    def test_normalize_release_gate_produces_sections(self):
        artifacts: dict = {
            "gate": {
                "gate_id": "rc-v1",
                "overall_status": "hold",
                "branch": "main",
                "head_sha": "a" * 40,
                "generated_at": "2026-05-18T00:00:00Z",
                "phases": [
                    {
                        "phase_id": "phase_1",
                        "title": "Governance",
                        "status": "ready",
                        "blocker_ids": [],
                        "remaining_seams": [],
                    }
                ],
            },
            "verdict": {
                "verdict": "HOLD",
                "gate_overall_status": "hold",
                "validator_result": "passed",
                "validator_error_count": "0",
                "open_blocker_ids": [],
                "promote_blockers": [],
                "required_next_actions": [],
            },
            "golden_path": {
                "overall_status": "not_verified",
                "steps": [
                    {
                        "step_id": "gp_install_sync",
                        "user_goal": "Install & Sync",
                        "status": "passing",
                        "expected_result": "uv sync completes",
                        "command_or_ui_action": "uv sync",
                        "phase_id": "phase_6",
                    }
                ],
            },
        }
        sections = normalize_release_gate(artifacts)
        assert len(sections) > 0
        kinds = [s.get("kind") for s in sections]
        assert "hero_status" in kinds

    def test_normalize_missing_artifacts_produces_callout(self):
        sections = normalize_release_gate({})
        assert len(sections) > 0
        first = sections[0]
        assert first.get("kind") == "callout"
        assert first.get("callout_class") == "warn"

    def test_build_page_model_produces_complete_dict(self):
        sections = [
            {
                "kind": "callout",
                "title": "Note",
                "body_html": "Test callout.",
                "callout_class": "info",
            }
        ]
        model = build_page_model(
            page_id="test-build",
            title="Build Test",
            route="/build/index.html",
            layout="default",
            source_paths=["docs/json/test.v1.json"],
            schema_versions=["test.v1"],
            safety_status="public_safe",
            sections=sections,
        )
        for field in (
            "page_id",
            "title",
            "route",
            "layout",
            "source_artifact_paths",
            "generated_from_schema_versions",
            "public_safety_status",
            "sections",
        ):
            assert field in model, f"Missing field: {field}"
        assert model["page_id"] == "test-build"
        assert len(model["sections"]) == 1


# ---------------------------------------------------------------------------
# Integration Tests (real_artifact)
# ---------------------------------------------------------------------------


@pytest.mark.real_artifact
class TestReleaseCandidatePage:
    _html: str | None = None

    @classmethod
    def _get_html(cls) -> str:
        if cls._html is None:
            model_path = _repo_artifact("docs/json/site/page_release_candidate.v1.json")
            if not model_path.is_file():
                pytest.skip("Release candidate page model not found")
            page = json.loads(model_path.read_text(encoding="utf-8"))
            cls._html = render_page(page)
        return cls._html

    def test_release_candidate_page_has_verdict_status(self):
        html = self._get_html()
        assert "Hold" in html or "Promote" in html, (
            "Verdict status not found in page HTML"
        )

    def test_release_candidate_page_has_phase_table(self):
        html = self._get_html()
        assert "phase_1" in html
        assert "phase_6" in html

    def test_release_candidate_page_has_golden_path_timeline(self):
        html = self._get_html()
        assert "gp_install_sync" in html
        assert "gp_clean_shutdown" in html

    def test_release_candidate_page_has_promote_requirements(self):
        html = self._get_html()
        assert "Promote Requirements" in html or "promote" in html.lower()

    def test_page_has_main_landmark(self):
        html = self._get_html()
        assert "<main" in html, "Page missing <main> landmark"

    def test_page_has_skip_link(self):
        html = self._get_html()
        assert "skip-link" in html, "Page missing skip-link"

    def test_page_has_source_artifact_references(self):
        html = self._get_html()
        assert "docs/json/release_gate/" in html or "source_artifact_paths" in html
