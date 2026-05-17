"""CLI entrypoint for the static documentation renderer."""

from __future__ import annotations

from rig_relay.tracing.golden_path import build_golden_path_event
from rig_relay.tracing.store import get_default_trace_store


def _emit_render_trace(event_type: str, *, payload: dict | None = None) -> None:
    """Emit a content-light render trace event. Non-fatal on error."""
    try:
        store = get_default_trace_store()
        event = build_golden_path_event(event_type=event_type, payload=payload or {})
        store.write(event)
    except Exception:
        pass


from pathlib import Path
import subprocess

from rig_relay.docs_renderer.archive import render_collection_page, render_index
from rig_relay.docs_renderer.css import CSS
from rig_relay.docs_renderer.homepage import render_homepage
from rig_relay.docs_renderer.loader import load_json, validate_page
from rig_relay.docs_renderer.manifest import load_site_manifest
from rig_relay.docs_renderer.pages import (
    render_code_schema,
    render_document_page,
    render_integration_audit,
    render_threat_model,
)
from rig_relay.docs_renderer.paths import (
    ASSETS_OUT,
    COLLECTIONS_OUT,
    DOCS_JSON,
    DOCS_OUT,
    NOJEKYLL,
    PAGES_OUT,
    RENDER_MANIFEST,
    SEARCH_INDEX,
)
from rig_relay.docs_renderer.writer import render_manifest, render_search_index


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=DOCS_OUT.parent,
        )
        return result.stdout.strip()[:12]
    except Exception:
        return "unknown"


def _register_and_render(
    data: dict,
    jf: Path,
    did: str,
    seen_ids: set[str],
    pages: list[dict],
    errors: list[str],
    html: str,
) -> bool:
    if did in seen_ids:
        errors.append(f"{jf.name}: duplicate document_id '{did}'")
        return False
    seen_ids.add(did)
    data.setdefault("document_id", did)
    data["_source_path"] = str(jf.relative_to(DOCS_JSON.parent))
    pages.append({
        "document_id": did,
        "title": data.get("title", did),
        "summary": data.get("summary", ""),
        "tags": data.get("tags", []),
        "_source_path": str(jf.relative_to(DOCS_JSON.parent)),
    })
    (PAGES_OUT / f"{did}.html").write_text(html, encoding="utf-8")
    return True


def _process_json_files(
    json_files: list[Path], manifest: dict
) -> tuple[list[dict], list[str]]:
    _emit_render_trace("docs.json_loaded", payload={"json_file_count": len(json_files)})
    errors: list[str] = []
    pages: list[dict] = []
    seen_ids: set[str] = set()

    for jf in json_files:
        try:
            data = load_json(jf)
            _emit_render_trace(
                "docs.schemas_loaded",
                payload={"file": jf.name, "document_id": data.get("document_id", "")},
            )
        except Exception as e:
            errors.append(f"{jf.name}: invalid JSON — {e}")
            continue

        sv = data.get("schema_version", "")
        if sv.startswith("rig.documentation.page.v"):
            verr = validate_page(data, jf)
            if verr:
                errors.extend(verr)
                continue
            did = data.get("document_id", "")
            html = render_document_page(data, manifest)
            if _register_and_render(data, jf, did, seen_ids, pages, errors, html):
                continue
        elif sv.startswith("rig.code_schema.v") or sv.startswith(
            "rig.code_schema.plan.v"
        ):
            did = data.get("document_id") or data.get("schema_id") or jf.stem
            html = render_code_schema(
                data, str(jf.relative_to(DOCS_JSON.parent)), manifest
            )
            _register_and_render(data, jf, did, seen_ids, pages, errors, html)
        elif sv.startswith("rig.security.threat_model.v"):
            did = data.get("threat_model_id") or jf.stem
            html = render_threat_model(
                data, str(jf.relative_to(DOCS_JSON.parent)), manifest
            )
            _register_and_render(data, jf, did, seen_ids, pages, errors, html)
        elif sv.startswith("rig.github_app.integration_audit.v"):
            did = data.get("audit_id") or jf.stem
            html = render_integration_audit(
                data, str(jf.relative_to(DOCS_JSON.parent)), manifest
            )
            _register_and_render(data, jf, did, seen_ids, pages, errors, html)

    return pages, errors


def main() -> int:
    _emit_render_trace("docs.render.started", payload={"phase": "start"})
    git_sha = _git_sha()

    DOCS_OUT.mkdir(parents=True, exist_ok=True)
    PAGES_OUT.mkdir(parents=True, exist_ok=True)
    ASSETS_OUT.mkdir(parents=True, exist_ok=True)

    json_files = sorted(DOCS_JSON.rglob("*.json"))
    if not json_files:
        print("No JSON doc files found in", DOCS_JSON)
        _emit_render_trace("docs.render.failed", payload={"status": "error"})
        return 1

    manifest = load_site_manifest()
    pages, errors = _process_json_files(json_files, manifest)

    if errors:
        print("Validation errors:")
        for e in errors:
            print(f"  - {e}")
        _emit_render_trace("docs.render.failed", payload={"status": "error"})
        return 1

    (DOCS_OUT / "index.html").write_text(render_homepage(manifest), encoding="utf-8")
    (ASSETS_OUT / "site.css").write_text(CSS, encoding="utf-8")

    src_js = DOCS_OUT / "assets" / "site.js"
    if src_js.is_file():
        (ASSETS_OUT / "site.js").write_text(src_js.read_text(encoding="utf-8"))

    # Write evidence archive index
    COLLECTIONS_OUT.mkdir(parents=True, exist_ok=True)
    (COLLECTIONS_OUT / "index.html").write_text(
        render_index(manifest), encoding="utf-8"
    )

    src_js = DOCS_OUT / "assets" / "site.js"
    if src_js.is_file():
        (ASSETS_OUT / "site.js").write_text(src_js.read_text(encoding="utf-8"))

    (SEARCH_INDEX).write_text(render_search_index(pages), encoding="utf-8")

    COLLECTIONS_OUT.mkdir(parents=True, exist_ok=True)
    collection_ids: list[str] = []
    for col in manifest.get("collections", []):
        cid = col.get("collection_id", "")
        if not cid:
            continue
        collection_ids.append(cid)
        (COLLECTIONS_OUT / f"{cid}.html").write_text(
            render_collection_page(col, manifest), encoding="utf-8"
        )

    (RENDER_MANIFEST).write_text(
        render_manifest(pages, collection_ids, git_sha), encoding="utf-8"
    )
    (NOJEKYLL).write_text("")

    print(f"Rendered {len(pages)} pages to {DOCS_OUT}/")
    print(f"  index: {DOCS_OUT}/index.html")
    print(f"  pages: {PAGES_OUT}/")
    print(f"  collections: {COLLECTIONS_OUT}/ ({len(collection_ids)} pages)")
    print(f"  assets: {ASSETS_OUT}/")
    print(f"  search: {SEARCH_INDEX}")
    print(f"  manifest: {RENDER_MANIFEST}")
    _emit_render_trace("docs.render.completed", payload={"status": "success"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
