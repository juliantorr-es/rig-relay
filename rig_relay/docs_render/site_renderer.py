"""Static site renderer — reads markdown artifacts and generates HTML.

Output under site/ (not committed, for GitHub Pages deployment).
No external CDN, no JavaScript framework, safe HTML escaping.
"""

from __future__ import annotations

from datetime import UTC, datetime
import html
import json
from pathlib import Path
from typing import Any


def render_site(
    artifacts_dir: Path | None = None,
    output_dir: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Path]:
    root = (repo_root or Path.cwd()).resolve()
    artifacts = (artifacts_dir or root / "docs" / "artifacts" / "markdown").resolve()
    out = (output_dir or root / "site").resolve()

    docs = _load_docs(artifacts)
    out.mkdir(parents=True, exist_ok=True)
    (out / "assets").mkdir(exist_ok=True)

    (out / ".nojekyll").write_text("")

    written: dict[str, Path] = {}

    written["css"] = _write_css(out / "assets" / "site.css")
    written["index"] = _render_index(out / "index.html", docs)
    written["documents"] = _render_documents(out / "documents.html", docs)
    written["governance"] = _render_kind_page(
        out / "governance.html", docs, "governance"
    )
    written["audits"] = _render_kind_page(out / "audits.html", docs, "audit")
    written["demos"] = _render_kind_page(out / "demos.html", docs, "demo")
    written["fences"] = _render_fences(out / "code-fences.html", docs)
    written["links"] = _render_links(out / "links.html", docs)

    return written


def _load_docs(artifacts_dir: Path) -> list[dict[str, Any]]:
    path = artifacts_dir / "markdown_documents.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("documents", [])
    docs_path = artifacts_dir / "markdown_documents.jsonl"
    if docs_path.is_file():
        docs: list[dict[str, Any]] = []
        for line in docs_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                docs.append(json.loads(line))
        return docs
    return []


def _page(title: str, body: str, docs: list[dict] | None = None) -> str:
    nav = _nav(docs)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)} — Rig Relay Docs</title>
<link rel="stylesheet" href="assets/site.css">
</head>
<body>
<header><h1>Rig Relay Documentation</h1>{nav}</header>
<main>{body}</main>
<footer>
  <p>Generated {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")} |
  <a href="index.html">Home</a> |
  <a href="documents.html">Documents</a></p>
</footer>
</body>
</html>"""


def _nav(docs: list[dict] | None = None) -> str:
    return """
<nav>
  <a href="index.html">Home</a>
  <a href="documents.html">Documents</a>
  <a href="governance.html">Governance</a>
  <a href="audits.html">Audits</a>
  <a href="demos.html">Demos</a>
  <a href="code-fences.html">Code</a>
  <a href="links.html">Links</a>
</nav>"""


def _render_index(path: Path, docs: list[dict]) -> Path:
    kinds: dict[str, int] = {}
    dirs: dict[str, int] = {}
    total_links = 0
    total_fences = 0

    for d in docs:
        kinds[d["inferred_doc_kind"]] = kinds.get(d["inferred_doc_kind"], 0) + 1
        dirs[d["directory"]] = dirs.get(d["directory"], 0) + 1
        total_links += len(d["links"])
        total_fences += d["code_fence_count"]

    body = f"""
<h2>Documentation Overview</h2>
<table class="kv">
<tr><td>Total documents</td><td>{len(docs)}</td></tr>
<tr><td>Total links</td><td>{total_links}</td></tr>
<tr><td>Total code fences</td><td>{total_fences}</td></tr>
</table>

<h3>By Kind</h3>
<table class="kv">
{"".join(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>" for k, v in sorted(kinds.items()))}
</table>

<h3>By Directory</h3>
<table class="kv">
{"".join(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>" for k, v in sorted(dirs.items())[:20])}
</table>

<h3>Recent Documents</h3>
<table>
<tr><th>Title</th><th>Kind</th><th>Path</th></tr>
{"".join(_doc_row(d) for d in docs[:30])}
</table>
"""
    path.write_text(_page("Home", body, docs), encoding="utf-8")
    return path


def _render_documents(path: Path, docs: list[dict]) -> Path:
    body = f"<h2>All Documents ({len(docs)})</h2>\n<table>\n<tr><th>Title</th><th>Kind</th><th>Path</th><th>Lines</th><th>Links</th></tr>\n"
    body += "".join(_doc_full_row(d) for d in docs)
    body += "</table>"
    path.write_text(_page("Documents", body, docs), encoding="utf-8")
    return path


def _render_kind_page(path: Path, docs: list[dict], kind: str) -> Path:
    filtered = [d for d in docs if d["inferred_doc_kind"] == kind]
    title = kind.capitalize()
    body = f"<h2>{title} ({len(filtered)})</h2>\n<table>\n<tr><th>Title</th><th>Path</th><th>Lines</th></tr>\n"
    body += "".join(
        f"<tr><td>{html.escape(d['title'])}</td><td><code>{html.escape(d['path'])}</code></td><td>{d['line_count']}</td></tr>"
        for d in filtered
    )
    body += "</table>"
    path.write_text(_page(title, body, docs), encoding="utf-8")
    return path


def _render_fences(path: Path, docs: list[dict]) -> Path:
    all_fences: list[dict] = []
    for d in docs:
        for f in d.get("code_fences", []):
            f["_source_path"] = d["path"]
            all_fences.append(f)

    mermaid = [f for f in all_fences if f["is_mermaid"]]
    body = f"""
<h2>Code Fences</h2>
<p>Total: {len(all_fences)} | Mermaid: {len(mermaid)}</p>
<table>
<tr><th>Source</th><th>Language</th><th>Lines</th><th>SHA</th></tr>
{"".join(f"<tr><td><code>{html.escape(f['_source_path'])}</code></td><td>{html.escape(f['language'])}</td><td>{f['line_end'] - f['line_start'] + 1}</td><td><code>{f['code_sha256'][:12]}</code></td></tr>" for f in all_fences[:100])}
</table>
"""
    path.write_text(_page("Code Fences", body, docs), encoding="utf-8")
    return path


def _render_links(path: Path, docs: list[dict]) -> Path:
    all_links: list[dict] = []
    for d in docs:
        for l in d["links"]:
            from rig_relay.docs_render.markdown_inventory import classify_link

            l["_source"] = d["path"]
            l["_kind"] = classify_link(l["href"])
            all_links.append(l)

    external = [l for l in all_links if l["_kind"] == "external"]
    body = f"""
<h2>Links</h2>
<p>Total: {len(all_links)} | External: {len(external)}</p>

<h3>External Links</h3>
<table>
<tr><th>Source</th><th>Text</th><th>URL</th></tr>
{"".join(f'<tr><td><code>{html.escape(l["_source"])}</code></td><td>{html.escape(l["text"][:80])}</td><td><a href="{html.escape(l["href"])}">{html.escape(l["href"][:80])}</a></td></tr>' for l in external[:50])}
</table>
"""
    path.write_text(_page("Links", body, docs), encoding="utf-8")
    return path


def _doc_row(d: dict) -> str:
    return f"<tr><td>{html.escape(d['title'])}</td><td>{html.escape(d['inferred_doc_kind'])}</td><td><code>{html.escape(d['path'])}</code></td></tr>"


def _doc_full_row(d: dict) -> str:
    return f"<tr><td>{html.escape(d['title'])}</td><td>{html.escape(d['inferred_doc_kind'])}</td><td><code>{html.escape(d['path'])}</code></td><td>{d['line_count']}</td><td>{len(d['links'])}</td></tr>"


def _write_css(path: Path) -> Path:
    css = """body{font-family:system-ui,-apple-system,sans-serif;max-width:960px;margin:0 auto;padding:20px;background:#0d1117;color:#c9d1d9;line-height:1.6}
header,footer{padding:12px 0;border-bottom:1px solid #30363d}footer{border-top:1px solid #30363d;margin-top:40px;font-size:.85em;color:#8b949e}
nav{display:flex;gap:12px;margin:8px 0}nav a{color:#58a6ff;text-decoration:none}nav a:hover{text-decoration:underline}
h1,h2,h3{color:#f0f6fc}table{width:100%;border-collapse:collapse;margin:12px 0}
th,td{padding:6px 10px;text-align:left;border-bottom:1px solid #30363d}th{background:#161b22;color:#8b949e}
code{background:#161b22;padding:1px 5px;border-radius:3px;font-size:.9em}
a{color:#58a6ff}tr:hover{background:#161b22}
pre{background:#161b22;padding:12px;border-radius:6px;overflow-x:auto;font-size:.85em;max-height:400px}
"""
    path.write_text(css, encoding="utf-8")
    return path


__all__ = ["render_site"]
