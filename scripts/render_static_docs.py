#!/usr/bin/env python3
"""Render canonical JSON documentation to static HTML.

Loads docs/json/**/*.json, validates basic structure, builds navigation
from docs/json/site_manifest.v1.json, and renders static HTML into docs/.

Output:
  docs/index.html
  docs/pages/<document_id>.html
  docs/assets/site.css
  docs/search-index.json
  docs/render-manifest.json
  docs/.nojekyll

Usage:
  uv run python scripts/render_static_docs.py
"""

from __future__ import annotations

from datetime import UTC, datetime
import html
import json
from pathlib import Path
import subprocess
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_JSON = REPO_ROOT / "docs" / "json"
DOCS_OUT = REPO_ROOT / "docs"
PAGES_OUT = DOCS_OUT / "pages"
ASSETS_OUT = DOCS_OUT / "assets"
SITE_MANIFEST = DOCS_JSON / "site_manifest.v1.json"

_REQUIRED_PAGE_FIELDS = {"schema_version", "document_id", "title", "sections"}


class _SiteMeta(NamedTuple):
    """Site-wide metadata extracted from the manifest once per render."""

    base_url: str
    base_path: str
    site_title: str
    theme_color: str
    favicon: str
    og_image: str


def _extract_site_meta(site_manifest: dict | None) -> _SiteMeta:
    if site_manifest is None:
        return _SiteMeta("", "/rig-relay", "Rig Relay Docs", "#1e3a5f", "", "")
    metadata = site_manifest.get("metadata", {})
    return _SiteMeta(
        base_url=str(site_manifest.get("base_url", "")),
        base_path=str(site_manifest.get("base_path", "/rig-relay")),
        site_title=str(site_manifest.get("site_title", "Rig Relay Docs")),
        theme_color=metadata.get("theme_color", "#1e3a5f"),
        favicon=metadata.get("favicon", ""),
        og_image=metadata.get("og_image", ""),
    )


def _make_og_tags(
    canonical_url: str, title: str, description: str, og_type: str
) -> str:
    if not canonical_url:
        return ""
    return f"""<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="{og_type}">
<meta property="og:url" content="{canonical_url}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{description}">
"""


def _make_head_tags(sm: _SiteMeta, canonical_url: str, og_tags: str) -> str:
    canonical_link = (
        f'<link rel="canonical" href="{canonical_url}">' if canonical_url else ""
    )
    favicon_link = (
        f'<link rel="icon" href="{sm.favicon}" type="image/svg+xml">'
        if sm.favicon
        else ""
    )
    og_image_tags = ""
    if sm.og_image:
        og_image_tags = f'<meta property="og:image" content="{sm.og_image}">\n<meta name="twitter:image" content="{sm.og_image}">'
    return f"""{canonical_link}
{og_tags}{og_image_tags}
<meta name="theme-color" content="{sm.theme_color}">
{favicon_link}
<link rel="stylesheet" href="{sm.base_path}/assets/site.css">"""


def _build_disclosure(
    block: dict, doc_disc: dict | None
) -> tuple[bool, bool, bool, str, str]:
    """Return (collapsible, collapsed, visible, css_cls, data_attrs) for a block."""
    disc = block.get("disclosure", {})
    ddoc = doc_disc or {}
    level = disc.get("level") or ddoc.get("default_level", "standard")
    collapsible: bool = disc.get("collapsible", False)
    collapsed: bool = disc.get("collapsed_by_default", False)
    visible: bool = disc.get("initially_visible", True)
    audience: list[str] = disc.get("audience", [])
    hint = disc.get("render_hint", {})
    variant = hint.get("variant", "plain")
    emphasis = hint.get("emphasis", "normal")

    if (
        level in {"detailed", "exhaustive"}
        and not disc.get("collapsible")
        and not disc.get("initially_visible")
    ):
        collapsible = True
        collapsed = True

    css_parts = [f"disclosure-{level}"]
    if variant != "plain":
        css_parts.append(f"render-variant-{variant}")
    if emphasis != "normal":
        css_parts.append(f"emphasis-{emphasis}")
    css_cls = " ".join(css_parts)

    data_attrs = f' data-disclosure-level="{level}"'
    if audience:
        data_attrs += ' data-disclosure-audience="' + " ".join(audience) + '"'
    if collapsible:
        data_attrs += ' data-collapsible="true"'
    if collapsed:
        data_attrs += ' data-collapsed-default="true"'
    return collapsible, collapsed, visible, css_cls, data_attrs


def _make_breadcrumb(
    sm: _SiteMeta, site_manifest: dict | None, collection_title: str, did: str
) -> str:
    if not collection_title:
        return ""
    site_title_html = html.escape(sm.site_title)
    cid = ""
    if site_manifest:
        for col in site_manifest.get("collections", []):
            if col.get("title") == collection_title:
                cid = col.get("collection_id", "")
                break
    if cid:
        return f'<p class="eyebrow"><a href="{sm.base_path}/">{site_title_html}</a> / <a href="{sm.base_path}/collections/{cid}.html">{html.escape(collection_title)}</a></p>\n'
    return f'<p class="eyebrow"><a href="{sm.base_path}/">{site_title_html}</a> / {html.escape(collection_title)}</p>\n'


def _build_toc(data: dict) -> str:
    doc_disc = data.get("disclosure", {})
    if not doc_disc.get("show_table_of_contents", False):
        return ""
    headings: list[tuple[int, str, str]] = []
    for s in data.get("sections", []):
        if s.get("type") == "heading":
            hlevel = s.get("level", 2)
            hcontent = str(s.get("content", ""))
            hid = str(s.get("block_id", ""))
            if hcontent and hid:
                headings.append((hlevel, hcontent, hid))
    if not headings:
        return ""
    toc_items = "\n".join(
        f'<li><a href="#{html.escape(h[2], quote=True)}">{html.escape(h[1])}</a></li>'
        for h in headings
    )
    return (
        f'<nav class="doc-toc" aria-label="Table of contents">\n'
        f"  <h2>On this page</h2>\n"
        f"  <ol>\n{toc_items}\n  </ol>\n"
        f"</nav>\n"
    )


def _find_collection_title(site_manifest: dict | None, did: str) -> str:
    if not site_manifest:
        return ""
    for col in site_manifest.get("collections", []):
        for doc in col.get("documents", []):
            if doc.get("document_id") == did:
                return str(col.get("title", ""))
    return ""


# ── Block render dispatch ──────────────────────────────────────


def _render_heading_block(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    hlevel = min(max(block.get("level", 2), 1), 6)
    return f'<h{hlevel} id="{bid}" class="{css_cls}"{data_attrs}>{content}</h{hlevel}>'


def _render_paragraph_block(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    return f'<p id="{bid}" class="{css_cls}"{data_attrs}>{content}</p>'


def _render_callout_block(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    severity = block.get("severity", "info")
    return (
        f'<div class="callout callout-{severity} {css_cls}" id="{bid}"{data_attrs}>\n'
        f"  {f'<strong>{title}</strong>' if title else ''}\n"
        f"  <p>{content}</p>\n"
        f"</div>"
    )


def _render_list_block(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    tag = "ol" if block.get("ordered") else "ul"
    items = block.get("items", [])
    items_html = "\n".join(f"  <li>{html.escape(str(i))}</li>" for i in items)
    return f'<{tag} id="{bid}" class="{css_cls}"{data_attrs}>\n{items_html}\n</{tag}>'


def _render_table_block(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    columns = block.get("columns", [])
    rows = block.get("rows", [])
    head = (
        "<thead><tr>"
        + "".join(f"<th>{html.escape(str(c))}</th>" for c in columns)
        + "</tr></thead>"
    )
    tbody = (
        "<tbody>\n"
        + "\n".join(
            "<tr>"
            + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row)
            + "</tr>"
            for row in rows
        )
        + "\n</tbody>"
    )
    return (
        f'<table id="{bid}" class="{css_cls}"{data_attrs}>\n{head}\n{tbody}\n</table>'
    )


def _render_code_block(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    language = block.get("language", "")
    lang_attr = f' class="language-{html.escape(language)}"' if language else ""
    return f'<pre id="{bid}"><code{lang_attr}>{content}</code></pre>\n'


def _render_json_block(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    return f'<pre id="{bid}"><code class="language-json">{content}</code></pre>\n'


def _render_evidence_block(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    btype = block.get("type", "risk")
    return (
        f'<div class="{btype} {css_cls}" id="{bid}"{data_attrs}>\n'
        f"  {f'<h4>{title}</h4>' if title else ''}\n"
        f"  <p>{content}</p>\n"
        f"</div>"
    )


def _render_link_block(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    href = html.escape(str(block.get("href", "")), quote=True)
    return f'<p id="{bid}" class="{css_cls}"{data_attrs}><a href="{href}">{content}</a></p>'


def _render_file_ref_block(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    path = html.escape(str(block.get("path", "")))
    return (
        f'<p class="file-ref {css_cls}" id="{bid}"{data_attrs}><code>{path}</code></p>'
    )


_BLOCK_RENDERERS: dict[str, object] = {
    "heading": _render_heading_block,
    "paragraph": _render_paragraph_block,
    "callout": _render_callout_block,
    "list": _render_list_block,
    "table": _render_table_block,
    "code": _render_code_block,
    "json": _render_json_block,
    "risk": _render_evidence_block,
    "decision": _render_evidence_block,
    "test_evidence": _render_evidence_block,
    "link": _render_link_block,
    "file_reference": _render_file_ref_block,
}


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT
        )
        return result.stdout.strip()[:12]
    except Exception:
        return "unknown"


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _validate_page(data: dict, path: Path) -> list[str]:
    errors: list[str] = []
    for field in _REQUIRED_PAGE_FIELDS:
        if field not in data:
            errors.append(f"{path.name}: missing required field '{field}'")
    if "schema_version" in data:
        sv = data["schema_version"]
        if not sv.startswith("rig.documentation.page.v"):
            errors.append(f"{path.name}: unexpected schema_version '{sv}'")
    if "document_id" in data:
        did = data["document_id"]
        if not did or not isinstance(did, str):
            errors.append(f"{path.name}: invalid document_id")
    if "sections" in data:
        sections = data["sections"]
        if not isinstance(sections, list) or len(sections) == 0:
            errors.append(f"{path.name}: sections must be non-empty array")
    return errors


def _wrap_collapsible(
    body: str,
    bid: str,
    css_cls: str,
    data_attrs: str,
    collapsible: bool,
    visible: bool,
    collapsed: bool,
    title: str,
    content: str,
) -> str:
    """Wrap body in details/summary if collapsible."""
    if not collapsible:
        return body + "\n"
    summary_text = html.escape(title or content[:100])
    open_attr = " open" if visible and not collapsed else ""
    return (
        f'<details id="{bid}" class="disclosure-collapsible {css_cls}"'
        f"{data_attrs}{open_attr}>"
        f"<summary>{summary_text}</summary>"
        f"{body}"
        f"</details>\n"
    )


def _render_block(block: dict, doc_disc: dict | None = None) -> str:
    btype = block.get("type", "paragraph")
    content = html.escape(str(block.get("content", "")))
    title = html.escape(str(block.get("title", "")))
    bid = html.escape(str(block.get("block_id", "")), quote=True)

    collapsible, collapsed, visible, css_cls, data_attrs = _build_disclosure(
        block, doc_disc
    )

    renderer = _BLOCK_RENDERERS.get(btype)
    if renderer is None:
        body = f'<p id="{bid}" class="{css_cls}"{data_attrs}>{content}</p>'
    else:
        body = renderer(block, content, title, bid, css_cls, data_attrs)  # type: ignore[operator]

    if btype in {"code", "json"}:
        return body

    return _wrap_collapsible(
        body, bid, css_cls, data_attrs, collapsible, visible, collapsed, title, content
    )


def _render_page(data: dict, site_manifest: dict | None = None) -> str:
    title = html.escape(str(data.get("title", "Untitled")))
    summary = html.escape(str(data.get("summary", "")))
    did = str(data.get("document_id", ""))
    status = html.escape(str(data.get("status", "draft")))
    updated = html.escape(str(data.get("updated_at", data.get("created_at", ""))))
    source_path = str(data.get("_source_path", data.get("canonical_path", "")))
    doc_disc = data.get("disclosure", {})

    sm = _extract_site_meta(site_manifest)
    canonical_url = f"{sm.base_url}/pages/{did}.html" if sm.base_url else ""

    collection_title = _find_collection_title(site_manifest, did)
    breadcrumb = _make_breadcrumb(sm, site_manifest, collection_title, did)
    toc_html = _build_toc(data)

    sections_html = "\n".join(
        _render_block(s, doc_disc) for s in data.get("sections", [])
    )
    og_tags = _make_og_tags(canonical_url, title, summary, "article")
    head_tags = _make_head_tags(sm, canonical_url, og_tags)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rig Relay Docs</title>
<meta name="description" content="{summary}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{sm.base_path}/">{html.escape(sm.site_title)}</a>
  </nav>
  {breadcrumb}  <h1>{title}</h1>
  <p class="doc-summary">{summary}</p>
  <dl class="doc-meta">
    <dt>Status</dt><dd>{status}</dd>
    {"<dt>Updated</dt><dd>" + updated + "</dd>" if updated else ""}
    {"<dt>Source</dt><dd><code>" + html.escape(source_path) + "</code></dd>" if source_path else ""}
  </dl>
</header>
<main
  id="main"
  class="doc-page"
  data-render-strategy="{doc_disc.get("render_strategy", "linear")}"
  data-default-disclosure-level="{doc_disc.get("default_level", "standard")}"
  data-initial-mode="{doc_disc.get("initial_mode", "reviewer")}">
  <article>
{toc_html}{sections_html}
  </article>
</main>
<footer>
  {"<p>Generated from <code>" + html.escape(source_path) + "</code></p>" if source_path else ""}
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def _render_code_schema(
    data: dict, source_path: str, site_manifest: dict | None = None
) -> str:
    title = html.escape(str(data.get("title", "Untitled")))
    summary = html.escape(str(data.get("summary", "")))
    status = html.escape(str(data.get("status", "draft")))
    updated = html.escape(str(data.get("updated_at", data.get("created_at", ""))))
    schema_id = html.escape(str(data.get("schema_id", "")))
    change_kind = html.escape(str(data.get("change_kind", "")))
    model_summary = html.escape(str(data.get("model_facing_summary", "")))

    sm = _extract_site_meta(site_manifest)
    did = str(data.get("document_id", ""))
    head_tags = _make_head_tags(
        sm,
        f"{sm.base_url}/pages/{did}.html" if sm.base_url else "",
        _make_og_tags(
            f"{sm.base_url}/pages/{did}.html" if sm.base_url else "",
            title,
            summary,
            "article",
        ),
    )

    def _list(items: object) -> str:
        if not isinstance(items, list) or not items:
            return "<li>None</li>"
        return "\n".join(f"<li>{html.escape(str(item))}</li>" for item in items)

    authority = data.get("authority", {})
    context_pack = data.get("context_pack", {})

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rig Relay Docs</title>
<meta name="description" content="{summary}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{sm.base_path}/">{html.escape(sm.site_title)}</a>
  </nav>
  <h1>{title}</h1>
  <p class="doc-summary">{summary}</p>
  <dl class="doc-meta">
    <dt>Status</dt><dd>{status}</dd>
    {"<dt>Updated</dt><dd>" + updated + "</dd>" if updated else ""}
    <dt>Source</dt><dd><code>{html.escape(source_path)}</code></dd>
  </dl>
</header>
<main id="main" class="doc-page">
  <article>
    <h2>Metadata</h2>
    <table>
      <tr><th>Schema ID</th><td>{schema_id}</td></tr>
      <tr><th>Change kind</th><td>{change_kind}</td></tr>
      <tr><th>Source</th><td class="file-ref"><code>{html.escape(source_path)}</code></td></tr>
    </table>
  </section>
  <section>
    <h2>Authority</h2>
    <table>
      <tr><th>Authority kind</th><td>{html.escape(str(authority.get("authority_kind", "")))}</td></tr>
      <tr><th>Trusted</th><td>{html.escape(str(authority.get("trusted", False)))}</td></tr>
      <tr><th>Source path</th><td class="file-ref"><code>{html.escape(str(authority.get("source_path", "")))}</code></td></tr>
      <tr><th>Review status</th><td>{html.escape(str(authority.get("review_status", "")))}</td></tr>
      <tr><th>Last reviewed</th><td>{html.escape(str(authority.get("last_reviewed_at", "")))}</td></tr>
    </table>
  </section>
  <section>
    <h2>Model Summary</h2>
    <p>{model_summary}</p>
  </section>
  <section>
    <h2>Required Invariants</h2>
    <ul>{_list(data.get("required_invariants", []))}</ul>
  </section>
  <section>
    <h2>Forbidden Patterns</h2>
    <ul>{_list(data.get("forbidden_patterns", []))}</ul>
  </section>
  <section>
    <h2>Required Files</h2>
    <ul>{_list(data.get("required_files", []))}</ul>
  </section>
  <section>
    <h2>Required Tests</h2>
    <ul>{_list(data.get("required_tests", []))}</ul>
  </section>
  <section>
    <h2>Required Trace Events</h2>
    <ul>{_list(data.get("required_trace_events", []))}</ul>
  </section>
  <section>
    <h2>Validation Commands</h2>
    <ul>{_list(data.get("validation_commands", []))}</ul>
  </section>
  <section>
    <h2>Context Pack</h2>
    <h3>Include Files</h3>
    <ul>{_list(context_pack.get("include_files", []))}</ul>
    <h3>Include Docs</h3>
    <ul>{_list(context_pack.get("include_docs", []))}</ul>
    <h3>Include Schemas</h3>
    <ul>{_list(context_pack.get("include_schemas", []))}</ul>
    <h3>Exclude Patterns</h3>
    <ul>{_list(context_pack.get("exclude_patterns", []))}</ul>
  </section>
</article>
</main>
<footer>
  <p>Generated from <code>{html.escape(data.get("canonical_path", source_path))}</code></p>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def _load_site_manifest() -> dict:
    if SITE_MANIFEST.is_file():
        return _load_json(SITE_MANIFEST)
    return {
        "schema_version": "rig.documentation.site_manifest.v1",
        "site_title": "Rig Relay Docs",
        "collections": [],
    }


def _render_index(manifest: dict) -> str:
    sm = _extract_site_meta(manifest)
    title = html.escape(sm.site_title)
    desc = html.escape(str(manifest.get("site_description", "")))
    canonical_url = f"{sm.base_url}/" if sm.base_url else ""
    og_tags = _make_og_tags(canonical_url, title, desc, "website")
    head_tags = _make_head_tags(sm, canonical_url, og_tags)

    collections_html = ""
    for col in manifest.get("collections", []):
        col_id = html.escape(str(col.get("collection_id", "")))
        col_title = html.escape(str(col.get("title", "")))
        col_desc = html.escape(str(col.get("description", "")))
        doc_count = len(col.get("documents", []))
        count_label = f"{doc_count} document{'s' if doc_count != 1 else ''}"
        docs_html = ""
        for doc in col.get("documents", []):
            did = html.escape(str(doc.get("document_id", "")))
            dtitle = html.escape(str(doc.get("title_override", did)))
            docs_html += (
                f'<li><a href="{sm.base_path}/pages/{did}.html">{dtitle}</a></li>\n'
            )
        collections_html += (
            f'<section class="collection-card">'
            f'<h2><a href="{sm.base_path}/collections/{col_id}.html">{col_title}</a></h2>'
            f"{'<p>' + col_desc + '</p>' if col_desc else ''}"
            f'<p class="meta">{count_label}</p>'
            f"<ul>{docs_html}</ul></section>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{desc}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <h1>{title}</h1>
  <p class="doc-summary">{desc}</p>
</header>
<main id="main">
{collections_html}
</main>
<footer>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def _render_collection_page(collection: dict, site_manifest: dict) -> str:
    col_id = str(collection.get("collection_id", ""))
    col_title = html.escape(str(collection.get("title", "")))
    col_desc = html.escape(str(collection.get("description", "")))
    documents = collection.get("documents", [])
    doc_count = len(documents)
    sm = _extract_site_meta(site_manifest)
    canonical_url = f"{sm.base_url}/collections/{col_id}.html" if sm.base_url else ""
    og_tags = _make_og_tags(canonical_url, col_title, col_desc, "website")
    head_tags = _make_head_tags(sm, canonical_url, og_tags)
    count_label = f"{doc_count} document{'s' if doc_count != 1 else ''}"

    docs_html = ""
    for doc in documents:
        did = html.escape(str(doc.get("document_id", "")))
        dtitle = html.escape(str(doc.get("title_override", did)))
        docs_html += (
            f'<li><a href="{sm.base_path}/pages/{did}.html">{dtitle}</a></li>\n'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{col_title} — {html.escape(sm.site_title)}</title>
<meta name="description" content="{col_desc}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{sm.base_path}/">{html.escape(sm.site_title)}</a>
  </nav>
  <p class="eyebrow"><a href="{sm.base_path}/">{html.escape(sm.site_title)}</a> / Collection</p>
  <h1>{col_title}</h1>
  <p class="doc-summary">{col_desc}</p>
  <p class="meta">{count_label}</p>
</header>
<main id="main">
  <section class="collection-card">
    <h2>Documents</h2>
    <ul class="collection-doc-list">
{docs_html}    </ul>
  </section>
</main>
<footer>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def _render_search_index(pages: list[dict]) -> str:
    entries = []
    for p in pages:
        entries.append({
            "document_id": p.get("document_id", ""),
            "title": p.get("title", ""),
            "summary": p.get("summary", ""),
            "tags": p.get("tags", []),
            "path": f"pages/{p.get('document_id', '')}.html",
        })
    return json.dumps(entries, indent=2)


def _render_manifest(pages: list[dict], collections: list[str], git_sha: str) -> str:
    return json.dumps(
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "git_commit": git_sha,
            "page_count": len(pages),
            "collection_page_count": len(collections),
            "pages": [
                {
                    "document_id": p.get("document_id", ""),
                    "title": p.get("title", ""),
                    "source_json_path": p.get("_source_path", ""),
                }
                for p in pages
            ],
            "collections": collections,
        },
        indent=2,
    )


_CSS = """body{font-family:system-ui,sans-serif;max-width:900px;margin:0 auto;padding:1rem;line-height:1.6;color:#111827;background:#f9fafb}
a{color:#1d4ed8}
a:focus-visible,summary:focus-visible,button:focus-visible{outline:3px solid #2563eb;outline-offset:3px;border-radius:2px}
.skip-link{position:absolute;top:-100px;left:0;background:#1e3a5f;color:#fff;padding:.5rem 1rem;z-index:100;border-radius:0 0 .25rem 0}
.skip-link:focus{top:0}
.site-header{border-bottom:2px solid #2563eb;padding-bottom:.5rem;margin-bottom:2rem}
.site-header nav a{color:#2563eb;text-decoration:none;font-weight:600;margin-right:1.5rem}
.eyebrow{font-size:.85rem;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.25rem}
.eyebrow a{color:#6b7280;text-decoration:none}
.eyebrow a:hover{text-decoration:underline}
h1{color:#1e3a5f;margin-top:0}
h2,h3,h4{color:#1e3a5f}
.doc-summary{color:#374151;font-size:1.05rem;margin-bottom:1rem}
.doc-meta{display:grid;grid-template-columns:auto 1fr;gap:.25rem 1rem;font-size:.9rem;color:#6b7280;margin:1rem 0}
.doc-meta dt{font-weight:600}
.doc-meta dd{margin:0}
.doc-toc{background:#f3f4f6;padding:.75rem 1rem;border-radius:.25rem;margin-bottom:1.5rem}
.doc-toc h2{font-size:1rem;margin-top:0}
.doc-toc ol{padding-left:1.5rem;margin-bottom:0}
.doc-toc a{text-decoration:none}
.collection-card{background:#fff;border:1px solid #e5e7eb;border-radius:.25rem;padding:1rem;margin-bottom:1rem}
.collection-card h2{margin-top:0;font-size:1.1rem}
.collection-card ul{list-style:none;padding-left:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:.25rem}
.collection-card li{margin:0}
.collection-doc-list{list-style:none;padding-left:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:.25rem}
.collection-doc-list li{margin:0}
.disclosure-collapsible{margin:.5rem 0}
.disclosure-collapsible summary{cursor:pointer;padding:.25rem 0;color:#1d4ed8;font-weight:500}
.disclosure-collapsible summary:hover{text-decoration:underline}
.disclosure-standard{border-left:3px solid #d1d5db;padding-left:1rem}
.disclosure-detailed{border-left:3px solid #2563eb;padding-left:1rem}
.disclosure-exhaustive{border-left:3px solid #1e3a5f;padding-left:1rem;font-size:.95rem}
.render-variant-risk_panel{background:#fef2f2;border-left:4px solid #dc2626}
.render-variant-evidence_panel{background:#eff6ff;border-left:4px solid #2563eb}
.render-variant-decision_panel{background:#ecfdf5;border-left:4px solid #059669}
.emphasis-important{font-weight:600}
.emphasis-subtle{font-size:.95rem;color:#6b7280}
.callout{padding:.75rem 1rem;border-left:4px solid;margin:1rem 0;border-radius:0 .25rem .25rem 0}
.callout-info{background:#dbeafe;border-color:#2563eb}
.callout-warning{background:#fef3c7;border-color:#d97706}
.callout-error{background:#fee2e2;border-color:#dc2626}
.callout-critical{background:#fecaca;border-color:#b91c1c;font-weight:600}
pre{background:#1e293b;color:#e2e8f0;padding:1rem;border-radius:.25rem;overflow-x:auto}
code{font-family:monospace;font-size:.9rem}
table{border-collapse:collapse;width:100%;margin:1rem 0}
th,td{border:1px solid #d1d5db;padding:.5rem;text-align:left}
th{background:#f3f4f6;font-weight:600}
footer{margin-top:3rem;padding-top:1rem;border-top:1px solid #d1d5db;font-size:.85rem;color:#6b7280}
.meta{color:#6b7280;font-size:.9rem}
.risk,.decision,.test_evidence{padding:.75rem 1rem;margin:1rem 0;border-radius:.25rem}
.risk{background:#fef2f2;border:1px solid #fecaca}
.decision{background:#ecfdf5;border:1px solid #a7f3d0}
.test_evidence{background:#eff6ff;border:1px solid #bfdbfe}
.file-ref{font-family:monospace;color:#6b7280}
"""


def _process_json_files(
    json_files: list[Path], manifest: dict
) -> tuple[list[dict], list[str]]:
    """Process all JSON doc files, returning (pages, errors)."""
    errors: list[str] = []
    pages: list[dict] = []
    seen_ids: set[str] = set()

    for jf in json_files:
        try:
            data = _load_json(jf)
        except json.JSONDecodeError as e:
            errors.append(f"{jf.name}: invalid JSON — {e}")
            continue

        sv = data.get("schema_version", "")
        if sv.startswith("rig.documentation.page.v"):
            verr = _validate_page(data, jf)
            if verr:
                errors.extend(verr)
                continue

            did = data.get("document_id", "")
            if did in seen_ids:
                errors.append(f"{jf.name}: duplicate document_id '{did}'")
                continue
            seen_ids.add(did)

            data["_source_path"] = str(jf.relative_to(REPO_ROOT))
            pages.append(data)

            html_content = _render_page(data, manifest)
            (PAGES_OUT / f"{did}.html").write_text(html_content, encoding="utf-8")
        elif sv.startswith("rig.code_schema.v") or sv.startswith(
            "rig.code_schema.plan.v"
        ):
            did = data.get("document_id") or data.get("schema_id") or jf.stem
            if did in seen_ids:
                errors.append(f"{jf.name}: duplicate document_id '{did}'")
                continue
            seen_ids.add(did)

            data.setdefault("document_id", did)
            data["_source_path"] = str(jf.relative_to(REPO_ROOT))
            pages.append({
                "document_id": did,
                "title": data.get("title", did),
                "summary": data.get("summary", ""),
                "tags": data.get("tags", []),
                "_source_path": str(jf.relative_to(REPO_ROOT)),
            })

            html_content = _render_code_schema(
                data, str(jf.relative_to(REPO_ROOT)), manifest
            )
            (PAGES_OUT / f"{did}.html").write_text(html_content, encoding="utf-8")

    return pages, errors


def main() -> int:
    git_sha = _git_sha()

    DOCS_OUT.mkdir(parents=True, exist_ok=True)
    PAGES_OUT.mkdir(parents=True, exist_ok=True)
    ASSETS_OUT.mkdir(parents=True, exist_ok=True)

    json_files = sorted(DOCS_JSON.rglob("*.json"))
    if not json_files:
        print("No JSON doc files found in", DOCS_JSON)
        return 1

    manifest = _load_site_manifest()
    pages, errors = _process_json_files(json_files, manifest)

    if errors:
        print("Validation errors:")
        for e in errors:
            print(f"  - {e}")
        return 1

    # Render index
    (DOCS_OUT / "index.html").write_text(_render_index(manifest), encoding="utf-8")

    # Assets
    (ASSETS_OUT / "site.css").write_text(_CSS, encoding="utf-8")

    # Search index
    (DOCS_OUT / "search-index.json").write_text(
        _render_search_index(pages), encoding="utf-8"
    )

    # Render collection pages
    COLLECTIONS_OUT = DOCS_OUT / "collections"
    COLLECTIONS_OUT.mkdir(parents=True, exist_ok=True)
    collection_ids: list[str] = []
    for col in manifest.get("collections", []):
        cid = col.get("collection_id", "")
        if not cid:
            continue
        collection_ids.append(cid)
        (COLLECTIONS_OUT / f"{cid}.html").write_text(
            _render_collection_page(col, manifest), encoding="utf-8"
        )

    # Render manifest
    (DOCS_OUT / "render-manifest.json").write_text(
        _render_manifest(pages, collection_ids, git_sha), encoding="utf-8"
    )

    # .nojekyll
    (DOCS_OUT / ".nojekyll").write_text("")

    print(f"Rendered {len(pages)} pages to {DOCS_OUT}/")
    print(f"  index: {DOCS_OUT}/index.html")
    print(f"  pages: {PAGES_OUT}/")
    print(f"  collections: {COLLECTIONS_OUT}/ ({len(collection_ids)} pages)")
    print(f"  assets: {ASSETS_OUT}/")
    print(f"  search: {DOCS_OUT}/search-index.json")
    print(f"  manifest: {DOCS_OUT}/render-manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
