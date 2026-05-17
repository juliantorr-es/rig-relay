from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INDEX = _REPO_ROOT / "docs" / "index.html"
_ARCHIVE = _REPO_ROOT / "docs" / "collections" / "index.html"
_PAGES_OUT = _REPO_ROOT / "docs" / "pages"


class TestHomepage:
    def test_homepage_contains_tagline(self) -> None:
        html = _INDEX.read_text()
        assert "Governed local runtime for agent work" in html

    def test_homepage_contains_plain_language(self) -> None:
        html = _INDEX.read_text()
        assert "AI agents can change code faster" in html

    def test_homepage_contains_what_works(self) -> None:
        html = _INDEX.read_text()
        assert "What Works Today" in html

    def test_homepage_contains_proof_metrics(self) -> None:
        html = _INDEX.read_text()
        assert "Proof Metrics" in html

    def test_homepage_links_to_archive(self) -> None:
        html = _INDEX.read_text()
        assert 'collections/index.html' in html

    def test_homepage_direct_document_links_under_limit(self) -> None:
        html = _INDEX.read_text()
        import re

        doc_links = re.findall(r'href="/rig-relay/pages/[^"]+\.html"', html)
        assert len(doc_links) <= 12, f"Homepage has {len(doc_links)} direct document links, max is 12"

    def test_homepage_does_not_list_all_collections(self) -> None:
        html = _INDEX.read_text()
        collection_links = html.count('href="/rig-relay/collections/')
        assert collection_links <= 3, "Homepage should not list all collections"


class TestArchive:
    def test_archive_index_exists(self) -> None:
        assert _ARCHIVE.is_file()

    def test_archive_title_is_evidence_archive(self) -> None:
        html = _ARCHIVE.read_text()
        assert "Evidence Archive" in html

    def test_archive_includes_collections(self) -> None:
        html = _ARCHIVE.read_text()
        assert "collection-card" in html


class TestMetadataAccessibility:
    def test_homepage_has_exactly_one_h1(self) -> None:
        html = _INDEX.read_text()
        assert html.count("<h1>") == 1

    def test_homepage_has_skip_link(self) -> None:
        html = _INDEX.read_text()
        assert 'class="skip-link"' in html

    def test_homepage_has_meta_csp(self) -> None:
        html = _INDEX.read_text()
        assert "Content-Security-Policy" in html

    def test_homepage_no_tokens_or_local_paths(self) -> None:
        html = _INDEX.read_text()
        import os

        home = os.path.expanduser("~")
        if home and len(home) > 2:
            assert home not in html
        assert "eyJ" not in html
        assert "sk-" not in html
