"""Markdown inventory — scan all non-root .md files, extract metadata.

Excludes root-level Markdown, vendor/cache dirs, and private .rig state.
Produces deterministic sorted inventory with front matter parsing,
heading extraction, link extraction, and code fence counting.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
import re
from typing import Any

import yaml

EXCLUDE_DIRS = frozenset({
    ".git", ".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".build", "node_modules", "dist", "build", "public", "site",
    "htmlcov", "__pycache__", ".rig",
})

ROOT_EXCLUDE = frozenset({
    "README.md", "AGENTS.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
    "SECURITY.md", "LICENSE", "UPSTREAM.md", "THIRD_PARTY_NOTICES.md",
    "CHANGELOG.md", "analysis_results.md",
})

FRONT_MATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)
HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')
IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
CODE_FENCE_RE = re.compile(r'^```(\w*)$', re.MULTILINE)
MERMAID_RE = re.compile(r'^```mermaid', re.MULTILINE)
SCHEMA_REF_RE = re.compile(r'schemas?/([^\s\)]+\.schema\.json)')
JSON_REF_RE = re.compile(r'\.json[\s\)\],;]')


def classify_link(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return "external"
    if href.startswith("#"):
        return "anchor"
    if href.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
        return "image"
    if href.startswith((".", "/")) or not href.startswith(("http", "#")):
        return "internal"
    return "unknown"


def infer_doc_kind(path: str, front_matter: dict[str, Any] | None = None) -> str:
    fm_kind = (front_matter or {}).get("kind", "")
    p = path.lower()

    if fm_kind:
        return fm_kind

    if "/governance/" in p:
        return "governance"
    if "/audits/" in p:
        return "audit"
    if "/demo/" in p:
        return "demo"
    if "/roadmap" in p:
        return "roadmap"
    if "/schemas/" in p:
        return "schema_doc"
    if "/dogfood/" in p:
        return "dogfood_proof"
    if "/evidence/" in p:
        return "evidence"
    if "/conversations/" in p:
        return "conversation"
    if "/protocols/" in p:
        return "protocol"
    if "/publishing/" in p:
        return "publishing"
    if "/agents/" in p:
        return "agent_doc"
    if "/architecture/" in p:
        return "architecture"
    if "/ui/" in p:
        return "ui_guide"
    if "/proxy" in p:
        return "guide"

    return "unknown"


def infer_audience(path: str, front_matter: dict[str, Any] | None = None) -> str:
    fm_aud = (front_matter or {}).get("audience", "")
    if fm_aud:
        return fm_aud

    p = path.lower()
    if "/audits/" in p:
        return "maintainer"
    if "/governance/" in p:
        return "contributor"
    if "/demo/" in p:
        return "user"
    if "/evidence/" in p:
        return "maintainer"
    if "/protocols/" in p:
        return "integrator"
    if "/architecture/" in p:
        return "contributor"
    if "/ui/" in p:
        return "developer"
    return "general"


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    m = FRONT_MATTER_RE.match(text)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
            body = text[m.end():]
            return fm, body
        except yaml.YAMLError:
            pass
    return {}, text


def extract_headings(text: str) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
    for m in HEADING_RE.finditer(text):
        level = len(m.group(1))
        title = m.group(2).strip()
        headings.append((level, title))
    return headings


def extract_links(text: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for m in LINK_RE.finditer(text):
        links.append({
            "text": m.group(1).strip(),
            "href": m.group(2).strip(),
        })
    return links


def extract_images(text: str) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    for m in IMAGE_RE.finditer(text):
        images.append({
            "alt": m.group(1).strip(),
            "src": m.group(2).strip(),
        })
    return images


def extract_code_fences(text: str) -> list[dict[str, Any]]:
    fences: list[dict[str, Any]] = []
    lines = text.split("\n")
    in_fence = False
    language = ""
    fence_start = 0
    fence_content: list[str] = []
    fence_index = 0

    for i, line in enumerate(lines):
        m = CODE_FENCE_RE.match(line.strip())
        if m:
            if not in_fence:
                in_fence = True
                language = m.group(1) or ""
                fence_start = i + 1
                fence_content = []
            else:
                in_fence = False
                content = "\n".join(fence_content)
                content_sha = hashlib.sha256(content.encode()).hexdigest()
                fences.append({
                    "language": language,
                    "fence_index": fence_index,
                    "line_start": fence_start,
                    "line_end": i + 1,
                    "content": content,
                    "code_sha256": content_sha,
                    "is_mermaid": language.lower() == "mermaid",
                    "is_json": language.lower() in ("json", "jsonc"),
                    "is_schema": "schema" in language.lower() or "schema" in content[:200].lower(),
                    "is_shell": language.lower() in ("bash", "sh", "shell", "console", "zsh"),
                })
                fence_index += 1
        elif in_fence:
            fence_content.append(line)
    return fences


def derive_title(front_matter: dict[str, Any], headings: list[tuple[int, str]], stem: str) -> str:
    if fm_title := front_matter.get("title", "").strip():
        return fm_title
    for level, text in headings:
        if level == 1:
            return text
    return stem.replace("-", " ").replace("_", " ").title()


def scan_file(path: Path, repo_root: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        text = raw.decode("utf-8", errors="replace")
    except OSError:
        return None

    front_matter, body = parse_front_matter(text)
    headings = extract_headings(body)
    links = extract_links(body)
    images = extract_images(body)
    fences = extract_code_fences(body)
    rel = str(path.relative_to(repo_root)).replace("\\", "/")

    title = derive_title(front_matter, headings, path.stem)

    body_sha = hashlib.sha256(body.encode()).hexdigest()

    return {
        "path": rel,
        "directory": str(path.parent.relative_to(repo_root)).replace("\\", "/"),
        "filename": path.name,
        "stem": path.stem,
        "extension": path.suffix,
        "size_bytes": len(raw),
        "sha256": sha,
        "line_count": text.count("\n") + 1,
        "heading_count": len(headings),
        "first_heading": headings[0][1] if headings else "",
        "title": title,
        "front_matter": front_matter,
        "body_markdown": body,
        "body_sha256": body_sha,
        "links": links,
        "image_refs": images,
        "code_fence_count": len(fences),
        "mermaid_fence_count": sum(1 for f in fences if f["is_mermaid"]),
        "schema_refs": [m.group(1) for m in SCHEMA_REF_RE.finditer(body)],
        "json_refs": len(JSON_REF_RE.findall(body)),
        "status_markers": front_matter.get("status", ""),
        "inferred_doc_kind": infer_doc_kind(rel, front_matter),
        "inferred_audience": infer_audience(rel, front_matter),
        "source_root": str(repo_root),
        "code_fences": fences,
    }


def inventory_markdown(repo_root: Path | None = None) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    documents: list[dict[str, Any]] = []
    excluded_root: list[str] = []

    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        parts = rel.parts

        if len(parts) == 1 and path.name in ROOT_EXCLUDE:
            excluded_root.append(path.name)
            continue

        if any(p in EXCLUDE_DIRS for p in parts):
            continue

        if any(p.startswith(".") and p not in (".github",) for p in parts if p != "."):
            continue

        doc = scan_file(path, root)
        if doc:
            documents.append(doc)

    return {
        "schema_version": "rig.docs.markdown_inventory.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_repo_root": str(root),
        "document_count": len(documents),
        "excluded_root_count": len(excluded_root),
        "excluded_root_files": sorted(excluded_root),
        "documents": sorted(documents, key=lambda d: d["path"]),
    }


__all__ = [
    "classify_link",
    "derive_title",
    "extract_code_fences",
    "extract_headings",
    "extract_images",
    "extract_links",
    "infer_audience",
    "infer_doc_kind",
    "inventory_markdown",
    "parse_front_matter",
    "scan_file",
]
