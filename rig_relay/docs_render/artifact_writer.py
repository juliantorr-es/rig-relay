"""Artifact writer — generates JSON/JSONL/CSV/HTML from markdown inventory.

Outputs under docs/artifacts/markdown/ (committed, used for GitHub Pages).
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rig_relay.docs_render.markdown_inventory import inventory_markdown


def write_all_artifacts(
    repo_root: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    root = (repo_root or Path.cwd()).resolve()
    out = (output_dir or root / "docs" / "artifacts" / "markdown").resolve()
    out.mkdir(parents=True, exist_ok=True)

    inventory = inventory_markdown(repo_root=root)
    docs = inventory["documents"]
    written: dict[str, Path] = {}

    written["inventory"] = _write_json(out / "markdown_documents.json", inventory)

    _write_jsonl(out / "markdown_documents.jsonl", docs)

    written["documents"] = _write_json(out / "markdown_documents.json", inventory)

    written["index_csv"] = _write_csv_index(out / "markdown_index.csv", docs)

    _write_links_jsonl(out / "markdown_links.jsonl", docs)

    _write_fences_jsonl(out / "markdown_code_fences.jsonl", docs)

    written["summary"] = _write_summary(out / "markdown_summary.json", inventory)

    return written


def _write_json(path: Path, data: Any) -> Path:
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _write_jsonl(path: Path, items: list[dict]) -> Path:
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n")
    return path


def _write_csv_index(path: Path, docs: list[dict]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "path", "title", "doc_kind", "directory", "sha256", "body_sha256",
            "line_count", "heading_count", "first_heading",
            "code_fence_count", "mermaid_fence_count",
            "link_count", "image_ref_count",
        ])
        for d in docs:
            writer.writerow([
                d["path"], d["title"], d["inferred_doc_kind"], d["directory"],
                d["sha256"][:16], d["body_sha256"][:16],
                d["line_count"], d["heading_count"], d["first_heading"][:80],
                d["code_fence_count"], d["mermaid_fence_count"],
                len(d["links"]), len(d["image_refs"]),
            ])
    return path


def _write_links_jsonl(path: Path, docs: list[dict]) -> Path:
    with open(path, "w", encoding="utf-8") as f:
        for d in docs:
            for link in d["links"]:
                row = {
                    "source_path": d["path"],
                    "link_text": link["text"][:120],
                    "href": link["href"][:200],
                    "link_kind": classify_link_static(link["href"]),
                }
                f.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    return path


def _write_fences_jsonl(path: Path, docs: list[dict]) -> Path:
    with open(path, "w", encoding="utf-8") as f:
        for d in docs:
            for fence in d.get("code_fences", []):
                row = {
                    "source_path": d["path"],
                    "language": fence["language"],
                    "fence_index": fence["fence_index"],
                    "line_start": fence["line_start"],
                    "line_end": fence["line_end"],
                    "code_sha256": fence["code_sha256"],
                    "is_mermaid": fence["is_mermaid"],
                    "is_json": fence["is_json"],
                    "is_schema": fence["is_schema"],
                    "is_shell": fence["is_shell"],
                }
                f.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    return path


def _write_summary(path: Path, inventory: dict) -> Path:
    docs = inventory["documents"]
    by_kind: dict[str, int] = {}
    by_dir: dict[str, int] = {}
    total_links = 0
    total_fences = 0
    total_mermaid = 0
    external_links = 0
    internal_links = 0

    for d in docs:
        kind = d["inferred_doc_kind"]
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_dir[d["directory"]] = by_dir.get(d["directory"], 0) + 1
        total_links += len(d["links"])
        total_fences += d["code_fence_count"]
        total_mermaid += d["mermaid_fence_count"]
        for link in d["links"]:
            if classify_link_static(link["href"]) == "external":
                external_links += 1
            else:
                internal_links += 1

    summary = {
        "schema_version": "rig.docs.markdown_summary.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "total_documents": inventory["document_count"],
        "by_doc_kind": by_kind,
        "by_directory": by_dir,
        "total_links": total_links,
        "total_code_fences": total_fences,
        "total_mermaid_fences": total_mermaid,
        "total_external_links": external_links,
        "total_internal_links": internal_links,
        "root_markdown_excluded": inventory["excluded_root_count"],
        "generated_artifacts": [
            "markdown_documents.json", "markdown_documents.jsonl",
            "markdown_index.csv", "markdown_links.jsonl",
            "markdown_code_fences.jsonl", "markdown_summary.json",
        ],
    }
    return _write_json(path, summary)


def classify_link_static(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return "external"
    if href.startswith("#"):
        return "anchor"
    if href.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
        return "image"
    if href.startswith((".", "/")) or not href.startswith(("http", "#")):
        return "internal"
    return "unknown"


__all__ = ["write_all_artifacts"]
