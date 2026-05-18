from __future__ import annotations

from rig_relay.docs_renderer.paths import (
    DOCS_OUT,
    get_relative_root,
    make_relative_link,
)


def test_get_relative_root_returns_correct_depth():
    assert get_relative_root(DOCS_OUT / "index.html", DOCS_OUT) == "."
    assert get_relative_root(DOCS_OUT / "pages" / "doc.html", DOCS_OUT) == ".."
    assert get_relative_root(DOCS_OUT / "a" / "b" / "c.html", DOCS_OUT) == "../.."


def test_make_relative_link_transforms_absolute_paths():
    base = "/rig-relay"
    assert (
        make_relative_link("/rig-relay/assets/site.css", ".", base) == "assets/site.css"
    )
    assert (
        make_relative_link("/rig-relay/assets/site.css", "..", base)
        == "../assets/site.css"
    )
    assert (
        make_relative_link("/rig-relay/pages/123.html", "..", base)
        == "../pages/123.html"
    )
    assert (
        make_relative_link("https://example.com/doc", "..", base)
        == "https://example.com/doc"
    )
    assert make_relative_link("#section", "..", base) == "#section"


def test_generated_html_has_no_absolute_rig_relay_navigation_prefixes():
    html_files = list(DOCS_OUT.rglob("*.html"))
    assert len(html_files) > 0, "No HTML files found in DOCS_OUT"

    for html_file in html_files:
        content = html_file.read_text(encoding="utf-8")
        assert 'href="/rig-relay' not in content, f"Found absolute href in {html_file}"
        assert 'src="/rig-relay' not in content, f"Found absolute src in {html_file}"

        rel_root = get_relative_root(html_file, DOCS_OUT)
        if rel_root == ".":
            assert 'href="assets/site.css"' in content
            assert 'src="assets/site.js"' in content
        else:
            assert f'href="{rel_root}/assets/site.css"' in content
            assert f'src="{rel_root}/assets/site.js"' in content
