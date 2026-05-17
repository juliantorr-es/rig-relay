"""Shared paths for the static documentation renderer."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_JSON = REPO_ROOT / "docs" / "json"
DOCS_OUT = REPO_ROOT / "docs"
PAGES_OUT = DOCS_OUT / "pages"
COLLECTIONS_OUT = DOCS_OUT / "collections"
ASSETS_OUT = DOCS_OUT / "assets"
SITE_MANIFEST = DOCS_JSON / "site_manifest.v1.json"
CSS_OUT = ASSETS_OUT / "site.css"
JS_OUT = ASSETS_OUT / "site.js"
SEARCH_INDEX = DOCS_OUT / "search-index.json"
RENDER_MANIFEST = DOCS_OUT / "render-manifest.json"
NOJEKYLL = DOCS_OUT / ".nojekyll"

_REQUIRED_PAGE_FIELDS = {"schema_version", "document_id", "title", "sections"}
