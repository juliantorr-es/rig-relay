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


import json
from pathlib import Path
import subprocess
from typing import cast

from rig_relay.docs_renderer.archive import render_collection_page, render_index
from rig_relay.docs_renderer.css import CSS
from rig_relay.docs_renderer.guard import check_input_manifest
from rig_relay.docs_renderer.homepage import render_homepage
from rig_relay.docs_renderer.loader import load_json, validate_page
from rig_relay.docs_renderer.manifest import load_site_manifest
from rig_relay.docs_renderer.metadata import extract_site_meta
from rig_relay.docs_renderer.models import SiteMeta
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
    REPO_ROOT,
    SEARCH_INDEX,
)
from rig_relay.docs_renderer.release_gate import (
    load_release_artifacts,
    render_golden_path_page,
    render_rc_verdict_page,
    render_release_gate_page,
)
from rig_relay.docs_renderer.safety import SafetyReport, is_public_safe, scan_content
from rig_relay.docs_renderer.security import (
    load_security_artifacts,
    render_schemas_page,
    render_security_hygiene_page,
    render_security_policy_page,
)
from rig_relay.docs_renderer.telemetry_bridge import (
    load_telemetry_bridge_artifacts,
    render_bridge_lifecycle_page,
    render_frontend_maturity_page,
    render_telemetry_policy_page,
)
from rig_relay.docs_renderer.testing import (
    load_test_artifacts,
    render_known_seams_page,
    render_test_classifications_page,
    render_test_inventory_page,
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


def _render_new_system_pages(manifest: dict) -> list[dict]:
    """Render pages using the Jinja2-backed site_renderer system.

    Processes pages defined in the site_renderer input manifest (if present).
    Falls back gracefully if any dependencies are unavailable.
    Returns list of page dicts for the search index and render manifest.
    """
    try:
        from rig_relay.site_renderer.loaders import (
            load_artifacts_for_page,
            load_input_manifest,
            load_page_model,
        )
        from rig_relay.site_renderer.renderer import render_page, write_page
    except ImportError:
        return []

    input_manifest = load_input_manifest(
        PAGES_OUT / ".." / "json" / "site_renderer_input_manifest.v1.json"
    )
    if not input_manifest:
        return []

    new_pages: list[dict] = []
    for entry in input_manifest.get("entries", []):
        page_id = entry.get("page_id", "")
        if not page_id:
            continue
        try:
            page_model = load_page_model(page_id)
            if not page_model:
                continue
            html = render_page(page_model)
            output_path = PAGES_OUT / f"{page_id}.html"
            write_page(output_path, html)
            new_pages.append({
                "document_id": page_id,
                "title": page_model.get("title", page_id),
                "summary": page_model.get("description", ""),
                "_source_path": str(output_path),
            })
        except Exception:
            continue
    return new_pages


def _render_jinja2_pages() -> list[dict]:
    """Render evidence graph and developer portfolio pages using Jinja2 templates.

    These are product pages (not doc pages). They use the site_renderer
    base layout for consistent UI.
    """
    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        return []

    templates_dir = (
        PAGES_OUT.parent.parent / "rig_relay" / "site_renderer" / "templates"
    )
    if not templates_dir.exists():
        return []

    env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True)
    new_pages: list[dict] = []

    # Evidence graph page
    try:
        tpl = env.get_template("codebase_evidence_graph.html.j2")
        html = tpl.render({
            "title": "Codebase Evidence Graph",
            "description": "Searchable graph of 14,000 nodes",
            "sections": [],
        })
        (PAGES_OUT / "codebase-evidence-graph.html").write_text(html, encoding="utf-8")
        new_pages.append({
            "document_id": "codebase-evidence-graph",
            "title": "Codebase Evidence Graph",
            "summary": "Searchable graph of 14,000 nodes across files, schemas, artifacts, functions, classes, and dependencies",
            "_source_path": "docs/pages/codebase-evidence-graph.html",
        })
    except Exception:
        pass

    # Developer portfolio page
    try:
        tpl = env.get_template("portfolio.html.j2")
        html = tpl.render({
            "title": "Developer Portfolio — Julian Torres",
            "description": "Evidence-backed developer portfolio",
            "sections": [],
        })
        (PAGES_OUT / "portfolio.html").write_text(html, encoding="utf-8")
        new_pages.append({
            "document_id": "portfolio",
            "title": "Developer Portfolio",
            "summary": "Evidence-backed developer portfolio — tech stack, projects, governance, and public claims",
            "_source_path": "docs/pages/portfolio.html",
        })
    except Exception:
        pass

    return new_pages


def _render_domain_pages(site_meta: SiteMeta) -> tuple[list[dict], SafetyReport]:
    manifest = load_site_manifest()
    new_pages: list[dict] = []
    aggregated = SafetyReport(passed=True)

    def _write_and_check(html: str, page_name: str, title: str, summary: str) -> dict:
        (PAGES_OUT / f"{page_name}.html").write_text(html, encoding="utf-8")
        sr = scan_content(html, f"pages/{page_name}.html")
        if not is_public_safe(sr):
            print(
                f"  ⚠ Safety warning in {page_name}.html: "
                f"{len(sr.blocked)} potential leaks"
            )
        aggregated.blocked.extend(sr.blocked)
        aggregated.warnings.extend(sr.warnings)
        aggregated.total_matches += sr.total_matches
        if not sr.passed:
            aggregated.passed = False
        return {
            "document_id": page_name,
            "title": title,
            "path": f"pages/{page_name}.html",
            "summary": summary,
            "tags": [],
        }

    release = load_release_artifacts()
    new_pages.append(
        _write_and_check(
            render_release_gate_page(
                manifest, cast(dict, release.get("gate")), site_meta
            ),
            "release-candidate",
            "Release Gate Readiness",
            "Phase-by-phase release gate readiness assessment with blocker and seam tracking.",
        )
    )
    new_pages.append(
        _write_and_check(
            render_rc_verdict_page(cast(dict, release.get("verdict")), site_meta),
            "rc-verdict",
            "RC Candidate Verdict",
            "Current release candidate verdict with promote blockers, phase status, and evidence references.",
        )
    )
    new_pages.append(
        _write_and_check(
            render_golden_path_page(cast(dict, release.get("golden_path")), site_meta),
            "golden-path",
            "Golden Path — Dogfood Operational Readiness",
            "Step-by-step dogfood operational readiness checklist with blocking failure conditions and evidence references.",
        )
    )

    test_artifacts = load_test_artifacts()
    new_pages.append(
        _write_and_check(
            render_test_inventory_page(test_artifacts.get("inventory"), site_meta),
            "testing",
            "Test Inventory",
            "Structured evidence of test coverage across all stress surfaces.",
        )
    )
    new_pages.append(
        _write_and_check(
            render_test_classifications_page(
                test_artifacts.get("classifications"), site_meta
            ),
            "test-classifications",
            "Test Classifications",
            "Taxonomy of test classification markers used across the project.",
        )
    )
    seams = None
    seams_path = REPO_ROOT / "docs" / "json" / "testing" / "known_test_seams.v1.jsonl"
    if seams_path.is_file():
        try:
            seams = [
                json.loads(line)
                for line in seams_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (json.JSONDecodeError, OSError):
            pass
    new_pages.append(
        _write_and_check(
            render_known_seams_page(seams, site_meta),
            "known-seams",
            "Known Test Seams",
            "Known gaps in test coverage that have been intentionally deferred.",
        )
    )

    telemetry_artifacts = load_telemetry_bridge_artifacts()
    new_pages.append(
        _write_and_check(
            render_telemetry_policy_page(telemetry_artifacts, site_meta),
            "telemetry",
            "Telemetry & Privacy Policy",
            "Telemetry consent enforcement, tracing policy, degradation behavior, and redaction rules.",
        )
    )
    new_pages.append(
        _write_and_check(
            render_bridge_lifecycle_page(
                telemetry_artifacts.get("projection_contract"), site_meta
            ),
            "bridge-lifecycle",
            "Desktop Bridge Lifecycle",
            "Desktop bridge lifecycle projection contract and state machine.",
        )
    )
    new_pages.append(
        _write_and_check(
            render_frontend_maturity_page(telemetry_artifacts, site_meta),
            "frontend",
            "Frontend Maturity Evidence",
            "Frontend maturity evidence from desktop golden path exercises.",
        )
    )

    security_artifacts = load_security_artifacts()
    new_pages.append(
        _write_and_check(
            render_security_policy_page(security_artifacts.get("policy"), site_meta),
            "security",
            "Security Policy",
            "Security policy, posture, reporting procedures, and code schema trust rules.",
        )
    )
    new_pages.append(
        _write_and_check(
            render_security_hygiene_page(security_artifacts.get("hygiene"), site_meta),
            "security-hygiene",
            "Repository Security Hygiene",
            "Security repository hygiene checks, release gate alignment, and tally.",
        )
    )
    new_pages.append(
        _write_and_check(
            render_schemas_page(site_meta),
            "schemas",
            "Schema Index",
            "Index of all JSON schemas in the project with validation status.",
        )
    )

    return new_pages, aggregated


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

    # Check for Markdown evidence leaks
    md_report = check_input_manifest(load_site_manifest())
    if not md_report.passed:
        print(
            f"  ⚠ Markdown leak guard: "
            f"{len(md_report.blocked_paths)} forbidden .md evidence inputs detected"
        )
        for p in md_report.blocked_paths:
            print(f"    - {p}")

    pages, errors = _process_json_files(json_files, manifest)

    if errors:
        print("Validation errors:")
        for e in errors:
            print(f"  - {e}")
        _emit_render_trace("docs.render.failed", payload={"status": "error"})
        return 1

    site_meta = extract_site_meta(manifest)
    domain_pages, safety_report = _render_domain_pages(site_meta)
    pages.extend(domain_pages)

    # ── New Jinja2-backed site renderer — evidence graph + portfolio pages ──
    new_pages = _render_new_system_pages(manifest)
    pages.extend(new_pages)

    # ── Render Jinja2-backed evidence graph and portfolio pages directly ──
    _new_pages = _render_jinja2_pages()
    pages.extend(_new_pages)

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

    if not is_public_safe(safety_report):
        print(
            f"  ⚠ Safety: {len(safety_report.blocked)} potential leaks, "
            f"{len(safety_report.warnings)} warnings"
        )
    else:
        print("  ✓ Safety: public safe — no token/secret leaks detected")

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
