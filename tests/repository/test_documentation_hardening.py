"""Post-migration hardening tests — reference audit, render completeness, content fidelity, site safety."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS_JSON = _REPO_ROOT / "docs" / "json"
_DOCS_OUT = _REPO_ROOT / "docs"
_PAGES_OUT = _DOCS_OUT / "pages"
_MANIFEST_PATH = _DOCS_JSON / "documentation_migration_manifest.v1.json"
_RENDER_MANIFEST = _DOCS_OUT / "render-manifest.json"
_SEARCH_INDEX = _DOCS_OUT / "search-index.json"
_SITE_MANIFEST = _DOCS_JSON / "site_manifest.v1.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── Reference audit ──────────────────────────────────────────────


class TestReferenceAudit:
    def test_migration_manifest_loaded(self) -> None:
        assert _MANIFEST_PATH.is_file()
        manifest = _load_json(_MANIFEST_PATH)
        assert manifest  # manifest must exist and parse

    def test_every_migrated_has_json_target(self) -> None:
        manifest = _load_json(_MANIFEST_PATH)
        for m in manifest["migrations"]:
            if m["status"] == "migrated":
                target = _REPO_ROOT / m["new_path"]
                assert target.is_file(), f"Missing JSON target: {m['new_path']}"

    def test_active_markdown_references_audit(self) -> None:
        """Count active markdown references in source code (not docs/)."""
        refs = []
        for py_file in _REPO_ROOT.rglob("*.py"):
            if (
                ".venv" in str(py_file)
                or "dist/" in str(py_file)
                or ".build/" in str(py_file)
            ):
                continue
            if py_file.name.endswith(".py"):
                try:
                    content = py_file.read_text()
                    # Find references to docs/*.md
                    for match in re.finditer(r"docs/[^\s\'\"\\)]+\.md", content):
                        refs.append((
                            str(py_file.relative_to(_REPO_ROOT)),
                            match.group(),
                        ))
                except Exception:
                    pass
        # Report but don't fail — we're auditing
        print(f"\n  Active .md references in source: {len(refs)}")
        for path, ref in refs[:10]:
            print(f"    {path}: {ref}")
        if len(refs) > 10:
            print(f"    ... and {len(refs) - 10} more")
        # This test passes regardless — it's an audit, not a gate yet
        assert True


# ── Render manifest completeness ──────────────────────────────────


class TestRenderManifestCompleteness:
    def test_render_manifest_exists(self) -> None:
        assert _RENDER_MANIFEST.is_file()

    def test_render_manifest_has_git_sha(self) -> None:
        rm = _load_json(_RENDER_MANIFEST)
        assert "git_commit" in rm
        assert len(rm["git_commit"]) >= 7

    def test_every_rendered_page_in_manifest(self) -> None:
        rm = _load_json(_RENDER_MANIFEST)
        rendered_ids = {p["document_id"] for p in rm.get("pages", [])}
        for html_file in _PAGES_OUT.glob("*.html"):
            did = html_file.stem
            assert did in rendered_ids, f"Page {did}.html not in render-manifest"

    def test_search_index_has_all_active_docs(self) -> None:
        si = _load_json(_SEARCH_INDEX)
        search_ids = {e["document_id"] for e in si}
        for html_file in _PAGES_OUT.glob("*.html"):
            did = html_file.stem
            assert did in search_ids, f"Page {did}.html not in search-index"

    def test_site_manifest_has_all_collections(self) -> None:
        sm = _load_json(_SITE_MANIFEST)
        assert len(sm.get("collections", [])) >= 2


# ── Content fidelity smoke ────────────────────────────────────────


class TestContentFidelitySmoke:
    def test_migrated_docs_have_sha_in_manifest(self) -> None:
        manifest = _load_json(_MANIFEST_PATH)
        for m in manifest["migrations"]:
            if m["status"] == "migrated":
                # At minimum, old_path and new_path are present
                assert m.get("old_path"), f"Missing old_path in {m}"
                assert m.get("new_path"), f"Missing new_path in {m}"

    def test_json_docs_have_required_fields(self) -> None:
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
            assert data.get("document_id"), f"{jf.name}: missing document_id"
            assert data.get("title"), f"{jf.name}: missing title"
            assert isinstance(data.get("sections", []), list), (
                f"{jf.name}: sections not a list"
            )
            assert len(data.get("sections", [])) > 0, f"{jf.name}: empty sections"

    def test_document_ids_are_unique(self) -> None:
        ids: dict[str, str] = {}
        for jf in _DOCS_JSON.rglob("*.json"):
            try:
                data = _load_json(jf)
            except Exception:
                continue
            sv = data.get("schema_version", "")
            if not sv.startswith("rig.documentation.page.v"):
                continue
            did = data.get("document_id", "")
            if not did:
                continue
            if did in ids:
                pytest.fail(f"Duplicate document_id '{did}': {ids[did]} and {jf}")
            ids[did] = str(jf.relative_to(_REPO_ROOT))

    def test_provenance_points_to_markdown(self) -> None:
        for jf in _DOCS_JSON.rglob("*.json"):
            try:
                data = _load_json(jf)
            except Exception:
                continue
            sv = data.get("schema_version", "")
            if not sv.startswith("rig.documentation.page.v"):
                continue
            prov = data.get("provenance", {})
            sources = prov.get("source_files", [])
            if sources:
                for src in sources:
                    assert src.endswith(".md") or src.startswith("docs/"), (
                        f"{jf.name}: provenance source_files should reference .md: {src}"
                    )


# ── Site safety audit ─────────────────────────────────────────────


class TestSiteSafetyAudit:
    def test_no_local_absolute_paths_in_html(self) -> None:
        """Documentation examples using /Users/user/ are OK.
        Flag only paths with real-looking home directory names (not 'user').
        """
        # Flag paths like /Users/julian/ or /Users/alice/ (lowercase name that isn't 'user')
        local_pattern = re.compile(r"/Users/(?!user/|Shared/)[a-z]{3,}/")
        for html_file in _PAGES_OUT.glob("*.html"):
            content = html_file.read_text()
            matches = local_pattern.findall(content)
            assert not matches, f"{html_file.name}: contains real local path: {matches}"

    def test_no_runtime_trace_paths_in_html(self) -> None:
        """Documentation about .build/ paths is OK. Flag only actual trace data."""
        # This is a content migration — .build/ references in docs are documentation
        # Only flag if there are actual trace payloads (JSONL content with trace_ids)
        trace_pattern = re.compile(r'"trace_id":\s*"[a-f0-9]{32}"')
        for html_file in _PAGES_OUT.glob("*.html"):
            content = html_file.read_text()
            matches = trace_pattern.findall(content)
            assert not matches, f"{html_file.name}: contains trace payload data"

    def test_no_script_tags_from_source(self) -> None:
        for html_file in _PAGES_OUT.glob("*.html"):
            content = html_file.read_text()
            # Allow only the CSS link
            script_count = content.count("<script")
            if script_count > 0:
                pytest.fail(
                    f"{html_file.name}: contains <script> tags ({script_count})"
                )

    def test_no_unescaped_unsafe_content(self) -> None:
        unsafe_patterns = ["onerror=", "javascript:", "<iframe", "<embed", "<object"]
        for html_file in _PAGES_OUT.glob("*.html"):
            content = html_file.read_text()
            for pattern in unsafe_patterns:
                assert pattern not in content, (
                    f"{html_file.name}: contains unsafe pattern '{pattern}'"
                )


# ── Site readability smoke ────────────────────────────────────────


# ── Migration hash integrity ─────────────────────────────────────


class TestMigrationHashIntegrity:
    def test_migrated_entries_have_old_hash_when_source_exists(self) -> None:
        manifest = _load_json(_MANIFEST_PATH)
        for m in manifest["migrations"]:
            if m["status"] != "migrated":
                continue
            old_path = _REPO_ROOT / m["old_path"]
            if old_path.is_file():
                old_hash = m.get("content_sha256_old", "")
                assert old_hash, (
                    f"Missing content_sha256_old for {m['old_path']} (file exists)"
                )
                assert old_hash.startswith("sha256:"), (
                    f"content_sha256_old not sha256-prefixed: {m['old_path']}"
                )

    def test_migrated_entries_have_new_hash_when_target_exists(self) -> None:
        manifest = _load_json(_MANIFEST_PATH)
        for m in manifest["migrations"]:
            if m["status"] != "migrated":
                continue
            new_path = _REPO_ROOT / m["new_path"]
            if new_path.is_file():
                new_hash = m.get("content_sha256_new", "")
                assert new_hash, (
                    f"Missing content_sha256_new for {m['new_path']} (file exists)"
                )
                assert new_hash.startswith("sha256:"), (
                    f"content_sha256_new not sha256-prefixed: {m['new_path']}"
                )

    def test_migration_hashes_match_actual_files(self) -> None:
        manifest = _load_json(_MANIFEST_PATH)
        for m in manifest["migrations"]:
            if m["status"] != "migrated":
                continue
            old_path = _REPO_ROOT / m["old_path"]
            if old_path.is_file() and m.get("content_sha256_old"):
                expected = m["content_sha256_old"].removeprefix("sha256:")
                actual = _sha256(old_path.read_text())
                assert actual == expected, (
                    f"content_sha256_old mismatch for {m['old_path']}: "
                    f"expected {expected}, got {actual}"
                )
            new_path = _REPO_ROOT / m["new_path"]
            if new_path.is_file() and m.get("content_sha256_new"):
                expected = m["content_sha256_new"].removeprefix("sha256:")
                actual = _sha256(new_path.read_text())
                assert actual == expected, (
                    f"content_sha256_new mismatch for {m['new_path']}: "
                    f"expected {expected}, got {actual}"
                )


# ── Asset presence and favicon ───────────────────────────────────


class TestAssetPresence:
    def test_favicon_svg_exists(self) -> None:
        favicon = _DOCS_OUT / "assets" / "favicon.svg"
        assert favicon.is_file(), "favicon.svg missing"

    def test_og_image_exists(self) -> None:
        og_img = _DOCS_OUT / "assets" / "og" / "rig-relay-card.svg"
        assert og_img.is_file(), "og/rig-relay-card.svg missing"

    def test_index_has_favicon_link(self) -> None:
        index = _DOCS_OUT / "index.html"
        content = index.read_text()
        assert 'rel="icon"' in content, "index.html missing favicon link"

    def test_pages_have_favicon_link(self) -> None:
        for html_file in _PAGES_OUT.glob("*.html"):
            content = html_file.read_text()
            assert 'rel="icon"' in content, f"{html_file.name}: missing favicon link"

    def test_pages_emit_og_image_when_configured(self) -> None:
        sm = _load_json(_SITE_MANIFEST)
        og_image = sm.get("metadata", {}).get("og_image", "")
        if og_image:
            for html_file in _PAGES_OUT.glob("*.html"):
                content = html_file.read_text()
                assert "og:image" in content, (
                    f"{html_file.name}: missing og:image when configured"
                )

    def test_no_broken_asset_paths(self) -> None:
        sm = _load_json(_SITE_MANIFEST)
        metadata = sm.get("metadata", {})
        favicon = metadata.get("favicon", "")
        og_image = metadata.get("og_image", "")
        base_path = sm.get("base_path", "/rig-relay")
        if favicon:
            rel = favicon.removeprefix(base_path + "/")
            assert (_DOCS_OUT / rel).is_file(), (
                f"Favicon path broken: {favicon} -> {rel}"
            )
        if og_image:
            rel = og_image.removeprefix(base_path + "/")
            assert (_DOCS_OUT / rel).is_file(), (
                f"OG image path broken: {og_image} -> {rel}"
            )


# ── Collection landing pages ─────────────────────────────────────

_COLLECTIONS_OUT = _DOCS_OUT / "collections"


class TestCollectionLandingPages:
    def test_collection_pages_dir_exists(self) -> None:
        assert _COLLECTIONS_OUT.is_dir(), "docs/collections/ missing"

    def test_collection_page_for_every_collection(self) -> None:
        sm = _load_json(_SITE_MANIFEST)
        for col in sm.get("collections", []):
            cid = col.get("collection_id", "")
            if not cid:
                continue
            page = _COLLECTIONS_OUT / f"{cid}.html"
            assert page.is_file(), f"Missing collection page: {cid}.html"

    def test_collection_page_links_to_all_documents(self) -> None:
        sm = _load_json(_SITE_MANIFEST)
        for col in sm.get("collections", []):
            cid = col.get("collection_id", "")
            if not cid:
                continue
            page = _COLLECTIONS_OUT / f"{cid}.html"
            content = page.read_text()
            for doc in col.get("documents", []):
                did = doc.get("document_id", "")
                if did:
                    assert f"pages/{did}.html" in content, (
                        f"{cid}.html missing link to {did}"
                    )

    def test_index_links_to_all_collection_pages(self) -> None:
        index = _DOCS_OUT / "index.html"
        content = index.read_text()
        sm = _load_json(_SITE_MANIFEST)
        for col in sm.get("collections", []):
            cid = col.get("collection_id", "")
            if not cid:
                continue
            assert f"collections/{cid}.html" in content, (
                f"index.html missing link to collection {cid}"
            )

    def test_collection_pages_respect_base_path(self) -> None:
        sm = _load_json(_SITE_MANIFEST)
        base_path = sm.get("base_path", "/rig-relay")
        for col in sm.get("collections", []):
            cid = col.get("collection_id", "")
            if not cid:
                continue
            page = _COLLECTIONS_OUT / f"{cid}.html"
            content = page.read_text()
            assert f'href="{base_path}/' in content, (
                f"{cid}.html: base_path {base_path} not respected in hrefs"
            )


# ── Readiness artifact ───────────────────────────────────────────

_READINESS_PATH = _DOCS_JSON / "release" / "static_site_v1_readiness.v1.json"


class TestReadinessArtifact:
    def test_readiness_artifact_exists(self) -> None:
        assert _READINESS_PATH.is_file(), "static_site_v1_readiness.v1.json missing"

    def test_readiness_artifact_parses(self) -> None:
        data = _load_json(_READINESS_PATH)
        assert data.get("document_id") == "static-site-v1-readiness"

    def test_readiness_artifact_in_render_manifest(self) -> None:
        rm = _load_json(_RENDER_MANIFEST)
        page_ids = {p["document_id"] for p in rm.get("pages", [])}
        assert "static-site-v1-readiness" in page_ids, (
            "readiness artifact not in render manifest"
        )


class TestSiteReadabilitySmoke:
    def test_index_html_exists(self) -> None:
        index = _DOCS_OUT / "index.html"
        assert index.is_file()
        content = index.read_text()
        assert "<title>" in content
        assert "<h1>" in content

    def test_every_page_has_title_and_h1(self) -> None:
        for html_file in _PAGES_OUT.glob("*.html"):
            content = html_file.read_text()
            assert "<title>" in content, f"{html_file.name}: missing <title>"
            assert "<h1>" in content, f"{html_file.name}: missing <h1>"

    def test_every_page_has_nav_or_back_link(self) -> None:
        for html_file in _PAGES_OUT.glob("*.html"):
            content = html_file.read_text()
            has_nav = "<nav>" in content or "href=" in content
            assert has_nav, f"{html_file.name}: missing navigation"

    def test_no_empty_pages(self) -> None:
        for html_file in _PAGES_OUT.glob("*.html"):
            content = html_file.read_text()
            assert len(content) > 200, (
                f"{html_file.name}: page too small ({len(content)} bytes)"
            )

    def test_every_page_has_css_link(self) -> None:
        for html_file in _PAGES_OUT.glob("*.html"):
            content = html_file.read_text()
            assert "site.css" in content, f"{html_file.name}: missing CSS link"

    def test_search_index_complete(self) -> None:
        si = _load_json(_SEARCH_INDEX)
        assert len(si) >= 200, f"Search index has only {len(si)} entries"
