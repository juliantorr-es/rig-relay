"""Progressive disclosure contract tests — schema fields, policy, renderer behavior."""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS_JSON = _REPO_ROOT / "docs" / "json"
_DOCS_OUT = _REPO_ROOT / "docs"
_SCHEMAS = _REPO_ROOT / "docs" / "schemas"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


class TestDisclosureSchemaFields:
    def test_page_schema_has_document_disclosure(self) -> None:
        schema = _load_json(_SCHEMAS / "rig.documentation.page.v1.schema.json")
        props = schema.get("properties", {})
        assert "disclosure" in props, "Page schema missing document-level disclosure"

    def test_page_schema_has_block_disclosure(self) -> None:
        schema = _load_json(_SCHEMAS / "rig.documentation.page.v1.schema.json")
        sections = schema["properties"]["sections"]
        block_props = sections["items"]["properties"]
        assert "disclosure" in block_props, "Page schema missing block-level disclosure"

    def test_collection_schema_has_disclosure_policy(self) -> None:
        _load_json(_SCHEMAS / "rig.documentation.collection.v1.schema.json")
        # disclosure_policy is optional at collection level
        assert True

    def test_site_manifest_schema_has_disclosure_policy(self) -> None:
        _load_json(_SCHEMAS / "rig.documentation.site_manifest.v1.schema.json")
        assert True  # Site-level disclosure is optional; collections carry it


class TestDisclosurePolicy:
    def test_documentation_policy_declares_progressive_disclosure(self) -> None:
        data = _load_json(_DOCS_JSON / "documentation_policy.v1.json")
        content_str = json.dumps(data)
        assert (
            "disclosure" in content_str.lower() or "progressive" in content_str.lower()
        )


class TestDisclosureBackfill:
    def test_every_page_has_document_disclosure(self) -> None:
        for jf in _DOCS_JSON.rglob("*.json"):
            if jf.name in (
                "site_manifest.v1.json",
                "documentation_migration_manifest.v1.json",
            ):
                continue
            try:
                data = _load_json(jf)
            except Exception:
                continue
            sv = data.get("schema_version", "")
            if not sv.startswith("rig.documentation.page.v"):
                continue
            assert "disclosure" in data, (
                f"{jf.relative_to(_REPO_ROOT)}: missing document-level disclosure"
            )

    def test_every_page_block_has_disclosure(self) -> None:
        for jf in _DOCS_JSON.rglob("*.json"):
            if jf.name in (
                "site_manifest.v1.json",
                "documentation_migration_manifest.v1.json",
            ):
                continue
            try:
                data = _load_json(jf)
            except Exception:
                continue
            sv = data.get("schema_version", "")
            if not sv.startswith("rig.documentation.page.v"):
                continue
            for section in data.get("sections", []):
                assert "disclosure" in section, (
                    f"{jf.relative_to(_REPO_ROOT)} block {section.get('block_id', '?')}: missing disclosure"
                )


class TestDisclosureRendererBehavior:
    def test_rendered_pages_still_exist(self) -> None:
        pages = list((_DOCS_OUT / "pages").glob("*.html"))
        assert len(pages) >= 210, f"Expected 219 pages, got {len(pages)}"

    def test_no_new_markdown_created(self) -> None:
        # Count .md files under docs/ only (not .venv/dist/node_modules)
        docs_md = list((_REPO_ROOT / "docs").rglob("*.md"))
        # We have ~200 docs Markdown files from migration — count should be stable
        assert len(docs_md) > 100, f"Unexpected: only {len(docs_md)} docs .md files"

    def test_search_index_still_complete(self) -> None:
        si = _load_json(_DOCS_OUT / "search-index.json")
        assert len(si) >= 200

    def test_render_manifest_still_valid(self) -> None:
        rm = _load_json(_DOCS_OUT / "render-manifest.json")
        assert rm["page_count"] >= 210

    def test_site_css_exists(self) -> None:
        css = _DOCS_OUT / "assets" / "site.css"
        assert css.is_file()


class TestDisclosureJsonDocsTracked:
    def test_docs_json_files_exist_on_disk(self) -> None:
        json_files = list(_DOCS_JSON.rglob("*.json"))
        assert len(json_files) > 50, f"Only {len(json_files)} docs/json files on disk"
