"""Output writers: search index, render manifest, file output."""

from __future__ import annotations

from datetime import UTC, datetime
import json


def render_search_index(pages: list[dict]) -> str:
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


def render_manifest(pages: list[dict], collections: list[str], git_sha: str) -> str:
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
