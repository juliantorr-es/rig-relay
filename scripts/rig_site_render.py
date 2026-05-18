#!/usr/bin/env python3
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import time

from rig_relay.site_renderer.loaders import (
    get_git_sha,
    load_input_manifest,
    load_page_model,
)
from rig_relay.site_renderer.renderer import render_index, render_page, write_page
from rig_relay.site_renderer.safety import (
    is_public_safe,
    scan_content,
    scan_rendered_site,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_INPUT_DIR = REPO_ROOT / "docs" / "json" / "site"
MANIFEST_PATH = SITE_INPUT_DIR / "input_manifest.v1.json"
OUTPUT_DIR = REPO_ROOT / ".build" / "rig-relay" / "site"
ASSETS_SRC = (
    Path(__file__).resolve().parent.parent / "rig_relay" / "site_renderer" / "assets"
)
ASSETS_OUT = OUTPUT_DIR / "assets"
SITE_CSS_SRC = ASSETS_SRC / "site.css"


def main() -> int:
    t0 = time.perf_counter()

    print("Rig Relay — Site Renderer v1")
    print(f"  Output: {OUTPUT_DIR}")

    head_sha = get_git_sha()
    branch = "main"
    generated_at = datetime.now(UTC).isoformat()

    manifest = load_input_manifest(MANIFEST_PATH)
    if not manifest:
        print("  ✗ Input manifest missing or invalid")
        return 1
    print(f"  ✓ Input manifest: {len(manifest.get('inputs', []))} entries")

    page_models: dict[str, dict] = {}
    for pm_path in sorted(SITE_INPUT_DIR.glob("page_*.v1.json")):
        pm = load_page_model(pm_path)
        if pm:
            page_models[pm["page_id"]] = pm
            print(f"  ✓ Page model: {pm['page_id']}")
        else:
            print(f"  ⚠ Skipped invalid page model: {pm_path.name}")

    if not page_models:
        print("  ✗ No valid page models found")
        return 1

    rendered: list[dict] = []
    failed: list[dict] = []

    for page_id, pm in page_models.items():
        try:
            route = pm.get("route", f"/{page_id}/index.html")
            depth = route.strip("/").count("/")
            relative_root = ".." * depth if depth > 0 else "."

            html = render_page(pm, relative_root=relative_root)

            rel_path = route.lstrip("/")
            output_path = OUTPUT_DIR / rel_path
            write_page(output_path, html)

            safety = scan_content(html, source=str(output_path))
            safety_notes = ""
            if not is_public_safe(safety):
                safety_notes = f"{len(safety.findings)} potential secrets detected"
                print(f"  ⚠ {page_id}: {safety_notes}")

            rendered.append({
                "page_id": page_id,
                "title": pm.get("title", ""),
                "route": route,
                "status": "rendered" if is_public_safe(safety) else "warning",
                "source_artifact_paths": pm.get("source_artifact_paths", []),
                "safety_notes": safety_notes,
            })
            print(f"  ✓ {page_id} → {route}")
        except Exception as e:
            print(f"  ✗ {page_id}: render failed — {e}")
            failed.append({
                "page_id": page_id,
                "title": pm.get("title", ""),
                "route": pm.get("route", ""),
                "status": "failed",
                "source_artifact_paths": [],
                "safety_notes": str(e),
            })

    all_pages = rendered + failed
    site_meta = {
        "generated_at": generated_at,
        "branch": branch,
        "head_sha": head_sha,
        "safety_passed": all(r["status"] == "rendered" for r in rendered),
    }
    index_html = render_index(all_pages, site_meta, relative_root=".")
    write_page(OUTPUT_DIR / "index.html", index_html)
    print("  ✓ index.html")

    print("\n  Safety scan…")
    safety_report = scan_rendered_site(OUTPUT_DIR)
    safety_passed = is_public_safe(safety_report)
    if safety_passed:
        print(
            f"  ✓ Public safe — no token/secret leaks detected ({safety_report.file_count} files)"
        )
    else:
        print(
            f"  ⚠ {len(safety_report.findings)} potential leaks in {safety_report.file_count} files:"
        )
        for f in safety_report.findings[:5]:
            print(f"    - {f.pattern_name}: {f.match_preview} ({f.source})")

    ASSETS_OUT.mkdir(parents=True, exist_ok=True)
    if SITE_CSS_SRC.exists():
        ASSETS_OUT.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SITE_CSS_SRC, ASSETS_OUT / "site.css")
        print("  ✓ assets/site.css copied")

    favicon_src = REPO_ROOT / "docs" / "assets" / "favicon.svg"
    if favicon_src.exists():
        shutil.copy2(favicon_src, ASSETS_OUT / "favicon.svg")

    duration_ms = int((time.perf_counter() - t0) * 1000)

    render_report = {
        "schema_version": "rig.site.render_report.v1",
        "generated_at": generated_at,
        "head_sha": head_sha,
        "branch": branch,
        "render_duration_ms": duration_ms,
        "pages_rendered": len(rendered),
        "pages_failed": len(failed),
        "safety_passed": safety_passed,
        "pages": rendered + failed,
    }
    report_path = OUTPUT_DIR / "site_render_report.v1.json"
    report_path.write_text(
        json.dumps(render_report, indent=2, default=str), encoding="utf-8"
    )

    site_manifest = {
        "schema_version": "rig.site.manifest.v1",
        "generated_at": generated_at,
        "head_sha": head_sha,
        "site_title": "Rig Relay Evidence Site",
        "routes": [
            {"route": r["route"], "title": r["title"], "page_id": r["page_id"]}
            for r in rendered + failed
        ],
        "assets": ["assets/site.css"],
    }
    manifest_path = OUTPUT_DIR / "site_manifest.v1.json"
    manifest_path.write_text(
        json.dumps(site_manifest, indent=2, default=str), encoding="utf-8"
    )

    print(
        f"\n  Render complete: {len(rendered)} pages, {len(failed)} failed, {duration_ms}ms"
    )
    print(f"  Report: {report_path}")

    return 0 if not failed and safety_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
