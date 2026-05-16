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

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_JSON = REPO_ROOT / "docs" / "json"
DOCS_OUT = REPO_ROOT / "docs"
PAGES_OUT = DOCS_OUT / "pages"
ASSETS_OUT = DOCS_OUT / "assets"
SITE_MANIFEST = DOCS_JSON / "site_manifest.v1.json"

_REQUIRED_PAGE_FIELDS = {"schema_version", "document_id", "title", "sections"}


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


def _render_block(block: dict) -> str:  # noqa: PLR0911, PLR0914
    btype = block.get("type", "paragraph")
    content = html.escape(str(block.get("content", "")))
    title = html.escape(str(block.get("title", "")))
    bid = html.escape(str(block.get("block_id", "")), quote=True)

    if btype == "heading":
        level = min(max(block.get("level", 2), 1), 6)
        return f'<h{level} id="{bid}">{content}</h{level}>\n'

    if btype == "paragraph":
        return f'<p id="{bid}">{content}</p>\n'

    if btype == "callout":
        severity = block.get("severity", "info")
        return (
            f'<div class="callout callout-{severity}" id="{bid}">\n'
            f"  {f'<strong>{title}</strong>' if title else ''}\n"
            f"  <p>{content}</p>\n"
            f"</div>\n"
        )

    if btype == "list":
        tag = "ol" if block.get("ordered") else "ul"
        items = block.get("items", [])
        items_html = "\n".join(f"  <li>{html.escape(str(i))}</li>" for i in items)
        return f'<{tag} id="{bid}">\n{items_html}\n</{tag}>\n'

    if btype == "table":
        columns = block.get("columns", [])
        rows = block.get("rows", [])
        head = (
            "<thead><tr>"
            + "".join(f"<th>{html.escape(str(c))}</th>" for c in columns)
            + "</tr></thead>"
        )
        body = (
            "<tbody>\n"
            + "\n".join(
                "<tr>"
                + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row)
                + "</tr>"
                for row in rows
            )
            + "\n</tbody>"
        )
        return f'<table id="{bid}">\n{head}\n{body}\n</table>\n'

    if btype == "code":
        language = block.get("language", "")
        lang_attr = f' class="language-{html.escape(language)}"' if language else ""
        return f'<pre id="{bid}"><code{lang_attr}>{content}</code></pre>\n'

    if btype == "json":
        return f'<pre id="{bid}"><code class="language-json">{content}</code></pre>\n'

    if btype in {"risk", "decision", "test_evidence"}:
        return (
            f'<div class="{btype}" id="{bid}">\n'
            f"  {f'<h4>{title}</h4>' if title else ''}\n"
            f"  <p>{content}</p>\n"
            f"</div>\n"
        )

    if btype == "link":
        href = html.escape(str(block.get("href", "")), quote=True)
        return f'<p id="{bid}"><a href="{href}">{content}</a></p>\n'

    if btype == "file_reference":
        path = html.escape(str(block.get("path", "")))
        return f'<p class="file-ref" id="{bid}"><code>{path}</code></p>\n'

    return f'<p id="{bid}">{content}</p>\n'


def _render_page(data: dict) -> str:
    title = html.escape(str(data.get("title", "Untitled")))
    summary = html.escape(str(data.get("summary", "")))
    # document_id available via data(str(data.get("document_id", "")))
    status = html.escape(str(data.get("status", "draft")))
    updated = html.escape(str(data.get("updated_at", data.get("created_at", ""))))

    sections_html = "\n".join(_render_block(s) for s in data.get("sections", []))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rig Relay Docs</title>
<link rel="stylesheet" href="/rig-relay/assets/site.css">
<meta name="description" content="{summary}">
</head>
<body>
<header>
  <nav><a href="/rig-relay/">Home</a></nav>
  <h1>{title}</h1>
  <p class="meta">Status: {status} | Updated: {updated}</p>
</header>
<main>
{sections_html}
</main>
<footer>
  <p>Generated from <code>{html.escape(data.get("canonical_path", ""))}</code></p>
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
    title = html.escape(str(manifest.get("site_title", "Rig Relay Docs")))
    desc = html.escape(str(manifest.get("site_description", "")))

    collections_html = ""
    for col in manifest.get("collections", []):
        col_title = html.escape(str(col.get("title", "")))
        docs_html = ""
        for doc in col.get("documents", []):
            did = html.escape(str(doc.get("document_id", "")))
            dtitle = html.escape(str(doc.get("title_override", did)))
            docs_html += (
                f'<li><a href="/rig-relay/pages/{did}.html">{dtitle}</a></li>\n'
            )
        collections_html += (
            f"<section><h2>{col_title}</h2><ul>{docs_html}</ul></section>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="stylesheet" href="/rig-relay/assets/site.css">
<meta name="description" content="{desc}">
</head>
<body>
<header>
  <h1>{title}</h1>
  <p>{desc}</p>
</header>
<main>
{collections_html}
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


def _render_manifest(pages: list[dict], git_sha: str) -> str:
    return json.dumps(
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "git_commit": git_sha,
            "page_count": len(pages),
            "pages": [
                {
                    "document_id": p.get("document_id", ""),
                    "title": p.get("title", ""),
                    "source": p.get("_source_path", ""),
                }
                for p in pages
            ],
        },
        indent=2,
    )


_CSS = """body{font-family:system-ui,sans-serif;max-width:900px;margin:0 auto;padding:1rem;line-height:1.6;color:#1a1a1a;background:#fafafa}
header{border-bottom:2px solid #2563eb;padding-bottom:.5rem;margin-bottom:2rem}
nav a{color:#2563eb;text-decoration:none;font-weight:600}
h1,h2,h3{color:#1e3a5f}
.callout{padding:.75rem 1rem;border-left:4px solid;margin:1rem 0;border-radius:0 .25rem .25rem 0}
.callout-info{background:#dbeafe;border-color:#2563eb}
.callout-warning{background:#fef3c7;border-color:#d97706}
.callout-error{background:#fee2e2;border-color:#dc2626}
.callout-critical{background:#fecaca;border-color:#b91c1c;font-weight:600}
pre{background:#1e293b;color:#e2e8f0;padding:1rem;border-radius:.25rem;overflow-x:auto}
code{font-family:monospace;font-size:.9rem}
table{border-collapse:collapse;width:100%;margin:1rem 0}
th,td{border:1px solid #d1d5db;padding:.5rem;text-align:left}
th{background:#f3f4f6}
footer{margin-top:3rem;padding-top:1rem;border-top:1px solid #d1d5db;font-size:.85rem;color:#6b7280}
.meta{color:#6b7280;font-size:.9rem}
.risk,.decision,.test_evidence{padding:.75rem 1rem;margin:1rem 0;border-radius:.25rem}
.risk{background:#fef2f2;border:1px solid #fecaca}
.decision{background:#ecfdf5;border:1px solid #a7f3d0}
.test_evidence{background:#eff6ff;border:1px solid #bfdbfe}
.file-ref{font-family:monospace;color:#6b7280}
"""


def main() -> int:
    git_sha = _git_sha()
    errors: list[str] = []
    pages: list[dict] = []

    DOCS_OUT.mkdir(parents=True, exist_ok=True)
    PAGES_OUT.mkdir(parents=True, exist_ok=True)
    ASSETS_OUT.mkdir(parents=True, exist_ok=True)

    # Collect all JSON doc files
    json_files = sorted(DOCS_JSON.rglob("*.json"))
    if not json_files:
        print("No JSON doc files found in", DOCS_JSON)
        return 1

    seen_ids: set[str] = set()

    for jf in json_files:
        try:
            data = _load_json(jf)
        except json.JSONDecodeError as e:
            errors.append(f"{jf.name}: invalid JSON — {e}")
            continue

        # Skip non-documentation-page JSON files (governance artifacts, manifests, etc.)
        sv = data.get("schema_version", "")
        if not sv.startswith("rig.documentation.page.v"):
            continue

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

        html_content = _render_page(data)
        out_path = PAGES_OUT / f"{did}.html"
        out_path.write_text(html_content, encoding="utf-8")

    if errors:
        print("Validation errors:")
        for e in errors:
            print(f"  - {e}")
        return 1

    # Render index
    manifest = _load_site_manifest()
    index_html = _render_index(manifest)
    (DOCS_OUT / "index.html").write_text(index_html, encoding="utf-8")

    # Assets
    (ASSETS_OUT / "site.css").write_text(_CSS, encoding="utf-8")

    # Search index
    (DOCS_OUT / "search-index.json").write_text(
        _render_search_index(pages), encoding="utf-8"
    )

    # Render manifest
    (DOCS_OUT / "render-manifest.json").write_text(
        _render_manifest(pages, git_sha), encoding="utf-8"
    )

    # .nojekyll
    (DOCS_OUT / ".nojekyll").write_text("")

    print(f"Rendered {len(pages)} pages to {DOCS_OUT}/")
    print(f"  index: {DOCS_OUT}/index.html")
    print(f"  pages: {PAGES_OUT}/")
    print(f"  assets: {ASSETS_OUT}/")
    print(f"  search: {DOCS_OUT}/search-index.json")
    print(f"  manifest: {DOCS_OUT}/render-manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
