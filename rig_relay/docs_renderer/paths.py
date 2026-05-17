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


def get_relative_root(output_path: Path | str, base_out: Path | str = DOCS_OUT) -> str:
    """Compute the relative root prefix (e.g. '.' or '..') from an output path to DOCS_OUT."""
    try:
        p = Path(output_path).resolve()
        b = Path(base_out).resolve()
        if p == b or p.parent == b:
            return "."
        rel = p.parent.relative_to(b)
        parts = len(rel.parts)
        return "/".join([".."] * parts)
    except Exception:
        return "."


def make_relative_link(
    href: str, relative_root: str, base_path: str = "/rig-relay"
) -> str:
    """Convert a root-relative link (e.g. /rig-relay/assets/site.css) to a portable relative link."""
    if not href:
        return ""
    if href.startswith(("http://", "https://", "mailto:", "data:", "#")):
        return href

    if href == base_path or href == f"{base_path}/":
        return "index.html" if relative_root == "." else f"{relative_root}/index.html"

    prefix = f"{base_path}/"
    if href.startswith(prefix):
        sub = href[len(prefix) :]
        if relative_root == ".":
            return sub
        return f"{relative_root}/{sub}"

    if href.startswith("/"):
        sub = href.lstrip("/")
        if relative_root == ".":
            return sub
        return f"{relative_root}/{sub}"

    return href
