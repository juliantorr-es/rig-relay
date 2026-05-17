"""Archive index and collection page rendering."""

from __future__ import annotations

import html as _html

from rig_relay.docs_renderer.metadata import (
    extract_site_meta,
    make_head_tags,
    make_og_tags,
)


def render_index(manifest: dict) -> str:
    return _render_archive(manifest, is_archive=True)


def _render_archive(manifest: dict, is_archive: bool = False) -> str:
    from rig_relay.docs_renderer.paths import make_relative_link

    sm = extract_site_meta(manifest)
    if is_archive:
        title = "Evidence Archive"
        desc = "Full generated documentation archive for architecture, governance, audits, release proofs, security, and code schemas."
        relative_root = ".."
    else:
        title = _html.escape(sm.site_title)
        desc = _html.escape(str(manifest.get("site_description", "")))
        relative_root = "."
    canonical_url = f"{sm.base_url}/" if sm.base_url else ""
    og_tags = make_og_tags(canonical_url, title, desc, "website")
    head_tags = make_head_tags(sm, canonical_url, og_tags, relative_root=relative_root)

    collections_html = ""
    for col in manifest.get("collections", []):
        col_id = _html.escape(str(col.get("collection_id", "")))
        col_title = _html.escape(str(col.get("title", "")))
        col_desc = _html.escape(str(col.get("description", "")))
        doc_count = len(col.get("documents", []))
        count_label = f"{doc_count} document{'s' if doc_count != 1 else ''}"
        docs_html = ""
        for doc in col.get("documents", []):
            did = _html.escape(str(doc.get("document_id", "")))
            dtitle = _html.escape(str(doc.get("title_override", did)))
            page_href = make_relative_link(
                f"{sm.base_path}/pages/{did}.html", relative_root, sm.base_path
            )
            docs_html += f'<li><a href="{page_href}">{dtitle}</a></li>\n'

        col_href = make_relative_link(
            f"{sm.base_path}/collections/{col_id}.html", relative_root, sm.base_path
        )
        collections_html += (
            f'<section class="collection-card">'
            f'<h2><a href="{col_href}">{col_title}</a></h2>'
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
<div id="site-search"></div>
{collections_html}
</main>
<footer>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def render_collection_page(collection: dict, site_manifest: dict) -> str:
    from rig_relay.docs_renderer.paths import make_relative_link

    col_id = str(collection.get("collection_id", ""))
    col_title = _html.escape(str(collection.get("title", "")))
    col_desc = _html.escape(str(collection.get("description", "")))
    documents = collection.get("documents", [])
    doc_count = len(documents)
    sm = extract_site_meta(site_manifest)
    canonical_url = f"{sm.base_url}/collections/{col_id}.html" if sm.base_url else ""
    og_tags = make_og_tags(canonical_url, col_title, col_desc, "website")
    head_tags = make_head_tags(sm, canonical_url, og_tags, relative_root="..")
    count_label = f"{doc_count} document{'s' if doc_count != 1 else ''}"

    docs_html = ""
    for doc in documents:
        did = _html.escape(str(doc.get("document_id", "")))
        dtitle = _html.escape(str(doc.get("title_override", did)))
        page_href = make_relative_link(
            f"{sm.base_path}/pages/{did}.html", "..", sm.base_path
        )
        docs_html += f'<li><a href="{page_href}">{dtitle}</a></li>\n'

    home_href = make_relative_link(f"{sm.base_path}/", "..", sm.base_path)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{col_title} — {_html.escape(sm.site_title)}</title>
<meta name="description" content="{col_desc}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{home_href}">{_html.escape(sm.site_title)}</a>
  </nav>
  <p class="eyebrow"><a href="{home_href}">{_html.escape(sm.site_title)}</a> / Collection</p>
  <h1>{col_title}</h1>
  <p class="doc-summary">{col_desc}</p>
  <p class="meta">{count_label}</p>
</header>
<main id="main">
  <div id="site-search"></div>
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
