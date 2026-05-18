from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SITE_JS = _REPO_ROOT / "docs" / "assets" / "site.js"
_INDEX_HTML = _REPO_ROOT / "docs" / "index.html"
_PAGE_HTML = _REPO_ROOT / "docs" / "pages" / "security-policy.html"


class TestSiteJS:
    def test_site_js_exists(self) -> None:
        assert _SITE_JS.is_file()

    def test_no_eval_or_new_function(self) -> None:
        content = _SITE_JS.read_text()
        assert "eval(" not in content
        assert "new Function(" not in content

    def test_no_remote_urls(self) -> None:
        content = _SITE_JS.read_text()
        import re

        urls = re.findall(r'https?://[^\s"\'<>]+', content)
        assert len(urls) == 0, f"Found remote URLs: {urls}"

    def test_no_analytics_calls(self) -> None:
        content = _SITE_JS.read_text()
        assert "gtag" not in content.lower()
        assert "analytics" not in content.lower()
        assert "pixel" not in content.lower()
        assert "fbq" not in content.lower()

    def test_no_token_or_secret_literals(self) -> None:
        content = _SITE_JS.read_text()
        assert "token" not in content.lower() or "unexpected_token" in content.lower()
        for banned in ["/Users/", "/home/", "eyJ", "sk-"]:
            assert banned not in content

    def test_search_index_path_respects_base_path(self) -> None:
        content = _SITE_JS.read_text()
        assert "SEARCH_INDEX_URL = BASE_PATH + " in content

    def test_accessible_buttons_have_labels(self) -> None:
        content = _SITE_JS.read_text()
        assert "Search documentation" in content
        assert "Expand all collapsible sections" in content
        assert "Collapse all sections" in content


class TestSiteHTML:
    def test_index_includes_script_tag(self) -> None:
        html = _INDEX_HTML.read_text()
        assert '<script src="/rig-relay/assets/site.js" defer></script>' in html

    def test_index_includes_search_container(self) -> None:
        html = _INDEX_HTML.read_text()
        assert 'id="site-search"' in html

    def test_page_includes_disclosure_controls(self) -> None:
        html = _PAGE_HTML.read_text()
        assert 'class="disclosure-controls"' in html

    def test_page_includes_expand_collapse_controls(self) -> None:
        html = _PAGE_HTML.read_text()
        assert 'class="expand-collapse-controls"' in html

    def test_page_includes_script_tag(self) -> None:
        html = _PAGE_HTML.read_text()
        assert '<script src="/rig-relay/assets/site.js" defer></script>' in html

    def test_meta_base_path_present(self) -> None:
        html = _INDEX_HTML.read_text()
        assert '<meta name="base-path" content="/rig-relay">' in html
