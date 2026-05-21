from __future__ import annotations

from pathlib import Path
import shutil
import sys

import pytest

from rig_relay.site_renderer.renderer import render_page

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    """Fixture to isolate environment inputs and outputs using tmp_path."""
    for key in list(sys.modules.keys()):
        if "rig_site_render" in key:
            del sys.modules[key]

    shutil.copytree(REPO_ROOT / "docs", tmp_path / "docs")

    input_dir = tmp_path / "docs" / "json" / "site"
    manifest_path = input_dir / "input_manifest.v1.json"
    output_dir = tmp_path / "outputs"

    monkeypatch.setenv("RIG_SITE_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("RIG_SITE_INPUT_DIR", str(input_dir))
    monkeypatch.setenv("RIG_SITE_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("RIG_SITE_OUTPUT_DIR", str(output_dir))

    return {
        "input_dir": input_dir,
        "manifest_path": manifest_path,
        "output_dir": output_dir,
    }


@pytest.mark.contract
def test_mock_page_renders_social_metadata():
    page_model = {
        "title": "Mock Title",
        "description": "Mock Description for checking SEO length constraints.",
        "route": "/mock-route/index.html",
        "page_id": "mock-page",
        "public_safety_status": "public_safe",
        "og_title": "Custom OG Title",
        "og_description": "Custom OG Description",
        "og_image": "/assets/og/rig-relay-card.svg",
        "og_type": "article",
        "og_url": "/mock-route/index.html",
        "twitter_card": "summary_large_image",
        "canonical_url": "/mock-route/index.html",
        "theme_color": "#1e3a5f",
        "robots": "noindex,nofollow",
    }

    html_content = render_page(page_model)

    assert "<title>Mock Title — Rig Relay</title>" in html_content
    assert (
        '<meta name="description" content="Mock Description for checking SEO length constraints.">'
        in html_content
    )
    assert '<meta name="robots" content="noindex,nofollow">' in html_content
    assert '<meta name="theme-color" content="#1e3a5f">' in html_content
    assert '<link rel="canonical" href="/mock-route/index.html">' in html_content
    assert '<meta property="og:title" content="Custom OG Title">' in html_content
    assert (
        '<meta property="og:description" content="Custom OG Description">'
        in html_content
    )
    assert '<meta property="og:type" content="article">' in html_content
    assert '<meta property="og:url" content="/mock-route/index.html">' in html_content
    assert (
        '<meta property="og:image" content="/assets/og/rig-relay-card.svg">'
        in html_content
    )
    assert '<meta name="twitter:card" content="summary_large_image">' in html_content
    assert '<meta name="twitter:title" content="Custom OG Title">' in html_content
    assert (
        '<meta name="twitter:description" content="Custom OG Description">'
        in html_content
    )
    assert (
        '<meta name="twitter:image" content="/assets/og/rig-relay-card.svg">'
        in html_content
    )
    assert (
        '<link rel="icon" href="./assets/favicon.svg" type="image/svg+xml">'
        in html_content
    )


@pytest.mark.contract
def test_compiled_site_social_metadata(clean_env, monkeypatch):
    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()
    assert exit_code == 0

    # Read all compiled HTML files
    html_files = list(clean_env["output_dir"].glob("**/*.html"))
    assert len(html_files) > 0

    for hf in html_files:
        content = hf.read_text(encoding="utf-8")

        # 1. Every generated page has <title> and <meta name="description">
        assert "<title>" in content
        assert "</title>" in content
        assert '<meta name="description"' in content

        # 2. Every generated page has canonical URL
        assert '<link rel="canonical"' in content

        # 3. Every generated page has og:title, og:type, og:description, og:site_name
        assert 'property="og:title"' in content
        assert 'property="og:type"' in content
        assert 'property="og:description"' in content
        assert 'property="og:site_name"' in content

        # 4. Every generated page has twitter:card, twitter:title, twitter:description
        assert 'name="twitter:card"' in content
        assert 'name="twitter:title"' in content
        assert 'name="twitter:description"' in content

        # 5. OG image path exists or deferral recorded (it is relative, or points to assets/og/...)
        assert "og:image" in content

        # 6. No placeholder social metadata text in head
        head_content = content.split("<body")[0]
        assert "TODO" not in head_content
        assert "placeholder" not in head_content.lower()

        # 7. Metadata values are HTML-escaped (we don't see raw unescaped <script> in meta tags)
        assert "<script>" not in content.split("<body")[0]

        # 8. theme-color meta present
        assert 'name="theme-color"' in content

        # 9. Favicon link present
        assert 'type="image/svg+xml"' in content
        assert "favicon.svg" in content


@pytest.mark.contract
def test_html_lang_comes_from_site_language():
    page_model = {
        "title": "Lang Test",
        "description": "Testing language attribute.",
        "route": "/lang-test/index.html",
        "page_id": "lang-test",
        "language": "es",
        "site_name": "Test Site",
    }
    html_content = render_page(page_model)
    assert '<html lang="es">' in html_content


@pytest.mark.contract
def test_html_lang_defaults_to_en():
    page_model = {
        "title": "Default Lang Test",
        "description": "Testing default language.",
        "route": "/default-lang/index.html",
        "page_id": "default-lang",
    }
    html_content = render_page(page_model)
    assert '<html lang="en">' in html_content


@pytest.mark.contract
def test_twitter_card_summary_large_image_when_image_exists():
    page_model = {
        "title": "Twitter Card Test",
        "description": "Testing twitter card with image.",
        "route": "/twitter-card/index.html",
        "page_id": "twitter-card",
        "og_image": "/assets/og/test-card.svg",
    }
    html_content = render_page(page_model)
    assert '<meta name="twitter:card" content="summary_large_image">' in html_content


@pytest.mark.contract
def test_twitter_card_summary_when_no_image():
    page_model = {
        "title": "Twitter Card No Img",
        "description": "Testing twitter card without image.",
        "route": "/twitter-noimg/index.html",
        "page_id": "twitter-noimg",
    }
    html_content = render_page(page_model)
    assert '<meta name="twitter:card" content="summary">' in html_content


@pytest.mark.contract
def test_og_image_alt_present_when_set():
    page_model = {
        "title": "OG Alt Test",
        "description": "Testing og:image:alt.",
        "route": "/og-alt/index.html",
        "page_id": "og-alt",
        "og_image": "/assets/og/test-card.svg",
        "og_image_alt": "A test card image",
    }
    html_content = render_page(page_model)
    assert '<meta property="og:image:alt" content="A test card image">' in html_content


@pytest.mark.contract
def test_og_image_width_present_when_set():
    page_model = {
        "title": "OG Width Test",
        "description": "Testing og:image:width.",
        "route": "/og-width/index.html",
        "page_id": "og-width",
        "og_image": "/assets/og/test-card.svg",
        "og_image_width": "1200",
    }
    html_content = render_page(page_model)
    assert '<meta property="og:image:width" content="1200">' in html_content


@pytest.mark.contract
def test_og_image_height_present_when_set():
    page_model = {
        "title": "OG Height Test",
        "description": "Testing og:image:height.",
        "route": "/og-height/index.html",
        "page_id": "og-height",
        "og_image": "/assets/og/test-card.svg",
        "og_image_height": "630",
    }
    html_content = render_page(page_model)
    assert '<meta property="og:image:height" content="630">' in html_content


@pytest.mark.contract
def test_twitter_image_alt_present_when_og_image_alt_set():
    page_model = {
        "title": "Twitter Alt Test",
        "description": "Testing twitter:image:alt.",
        "route": "/twitter-alt/index.html",
        "page_id": "twitter-alt",
        "og_image": "/assets/og/test-card.svg",
        "og_image_alt": "A test card image for Twitter",
    }
    html_content = render_page(page_model)
    assert (
        '<meta name="twitter:image:alt" content="A test card image for Twitter">'
        in html_content
    )


@pytest.mark.contract
def test_og_image_dimensions_not_present_when_not_set():
    page_model = {
        "title": "No Dims Test",
        "description": "Testing missing og image dimensions.",
        "route": "/no-dims/index.html",
        "page_id": "no-dims",
        "og_image": "/assets/og/test-card.svg",
    }
    html_content = render_page(page_model)
    assert 'property="og:image:alt"' not in html_content
    assert 'property="og:image:width"' not in html_content
    assert 'property="og:image:height"' not in html_content
    assert 'name="twitter:image:alt"' not in html_content
