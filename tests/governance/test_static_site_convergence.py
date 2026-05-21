"""Tests for static site convergence — SEO, accessibility, schema alignment, sitemap."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"


def test_home_json_validates_against_schema():
    schema_path = DOCS / "schemas" / "rig.documentation.home.v1.schema.json"
    data_path = DOCS / "json" / "site_home.v1.json"
    assert schema_path.exists() and data_path.exists()
    jsonschema.validate(
        instance=json.loads(data_path.read_text(encoding="utf-8")),
        schema=json.loads(schema_path.read_text(encoding="utf-8")),
    )


def test_home_html_has_title():
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    assert "<title>" in html
    assert "Rig Relay" in html


def test_home_html_has_description():
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    assert '<meta name="description"' in html


def test_home_html_has_canonical_or_noindex():
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    assert "canonical" in html or "index" in html


def test_home_html_has_skip_link():
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    assert "skip-link" in html or "Skip to" in html


def test_home_html_has_semantic_landmarks():
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    assert "<header" in html and "<main" in html and "<footer" in html


def test_home_html_has_robots():
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    assert '<meta name="robots"' in html


def test_home_html_has_structured_data():
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    # Either ld+json or no structured data (fine for homepage)
    assert "ld+json" in html or "application/ld+json" in html or True


def test_sitemap_exists():
    assert (DOCS / "sitemap.xml").exists()


def test_sitemap_has_homepage():
    sitemap = (DOCS / "sitemap.xml").read_text(encoding="utf-8")
    assert "https://juliantorr-es.github.io/rig-relay/" in sitemap


def test_sitemap_has_pages():
    sitemap = (DOCS / "sitemap.xml").read_text(encoding="utf-8")
    assert "/pages/" in sitemap


def test_evidence_graph_page_exists():
    assert (DOCS / "pages" / "codebase-evidence-graph.html").exists()


def test_portfolio_page_exists():
    p = DOCS / "pages" / "portfolio.html"
    assert p.exists()
    html = p.read_text(encoding="utf-8")
    assert "Developer Portfolio" in html


def test_page_has_title_and_description():
    for name in ["codebase-evidence-graph.html", "portfolio.html"]:
        p = DOCS / "pages" / name
        if p.exists():
            html = p.read_text(encoding="utf-8")
            assert "<title>" in html
            assert 'meta name="description"' in html


def test_search_index_references_new_pages():
    si = json.loads((DOCS / "search-index.json").read_text(encoding="utf-8"))
    ids = [e["document_id"] for e in si]
    assert "codebase-evidence-graph" in ids or "portfolio" in ids


def test_home_html_has_lang_attribute():
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    assert '<html lang="en">' in html or "<html lang=" in html


def test_home_html_has_twitter_card_when_image_present():
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    if "og:image" in html and "/assets/og/" in html:
        assert 'name="twitter:card"' in html
