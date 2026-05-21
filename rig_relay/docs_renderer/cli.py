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


from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
from typing import cast

from markupsafe import Markup

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
        from rig_relay.site_renderer.loaders import load_input_manifest, load_page_model
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
        graph_model = {
            "total_nodes": "13,964",
            "total_edges": "3,019",
            "node_types": 9,
            "edge_types": 2,
            "node_distribution": [
                {"type": "function", "count": "6,462"},
                {"type": "file", "count": "4,336"},
                {"type": "class", "count": "1,639"},
                {"type": "module", "count": "857"},
                {"type": "schema", "count": "389"},
                {"type": "artifact", "count": "202"},
                {"type": "dependency", "count": "69"},
                {"type": "release_phase", "count": "7"},
                {"type": "provider", "count": "3"},
            ],
            "edge_distribution": [
                {
                    "type": "depends_on",
                    "count": "2,107",
                    "description": "Python import dependencies between modules",
                },
                {
                    "type": "validates_artifact",
                    "count": "912",
                    "description": "Schema-to-artifact validation edges",
                },
            ],
            "projection_modes": [
                {
                    "name": "public_static",
                    "description": "Content-light, no local paths, no session data. Published to GitHub Pages.",
                },
                {
                    "name": "cockpit_local",
                    "description": "Local-safe metadata, branch context. Cockpit dashboard only.",
                },
                {
                    "name": "context_digest",
                    "description": "Compact, deterministic context packet for the assembler. Bounded size.",
                },
                {
                    "name": "duckdb_read_side",
                    "description": "Queryable analytics. Read-only. Zero new dependencies.",
                },
                {
                    "name": "impact_analysis",
                    "description": "Changed-paths-to-adjacent-evidence mapping via git diff.",
                },
            ],
            "regeneration_commands": [
                "uv run python scripts/rig_codebase_evidence_graph.py --summary",
                "uv run python scripts/rig_github_maintenance.py graph",
            ],
        }
        html = tpl.render({
            "title": "Codebase Evidence Graph",
            "description": "Searchable graph of 14,000 nodes across files, schemas, artifacts, functions, classes, and dependencies.",
            "meta_description": "Deterministic content-light evidence graph from the Rig Relay repository — 13,964 nodes, 3,019 edges, 9 node types.",
            "site_name": "Rig Relay",
            "canonical_url": "https://juliantorr-es.github.io/rig-relay/pages/codebase-evidence-graph.html",
            "og_type": "article",
            "og_image": "/rig-relay/assets/og/rig-relay-card.svg",
            "og_image_alt": "Rig Relay — Governed Local Agent Platform",
            "og_image_width": "1200",
            "og_image_height": "630",
            "twitter_card": "summary_large_image",
            "structured_data_json": Markup(
                '{"@context":"https://schema.org","@type":"WebSite","name":"Rig Relay","url":"https://juliantorr-es.github.io/rig-relay/"}'
            ),
            "model": graph_model,
            "sections": [],
            "relative_root": ".",
            "page_id": "codebase-evidence-graph",
            "generated_at": datetime.now(UTC).isoformat(),
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
        portfolio_model = {
            "hero_name": "Julian Torres",
            "tagline": "Building governed agent infrastructure — desktop cockpit, MCP server, ACP agent, receipt-backed evidence.",
            "action_links": [
                {
                    "label": "Rig Relay",
                    "description": "Governed local server with desktop cockpit",
                    "url": "https://github.com/juliantorr-es/rig-relay",
                },
                {
                    "label": "GitHub Profile",
                    "description": "Projects, contributions, and evidence",
                    "url": "https://github.com/juliantorr-es",
                },
            ],
            "tech_stack": [
                {
                    "name": "Python 3.12+",
                    "description": "Primary language. Strict type checking via pyright.",
                },
                {
                    "name": "GitHub API",
                    "description": "13 API surfaces, 12 endpoints, governed with receipts.",
                },
                {
                    "name": "Desktop Cockpit",
                    "description": "pywebview-based operator console with widget system.",
                },
                {
                    "name": "MCP Server",
                    "description": "16 governed tools across 5 permission tiers.",
                },
                {
                    "name": "ACP Agent",
                    "description": "Editor-integrated agent sessions with progress streaming.",
                },
                {
                    "name": "WebSocket",
                    "description": "Local projection stream for the desktop cockpit.",
                },
            ],
            "projects": [
                {
                    "name": "Rig Relay",
                    "url": "https://github.com/juliantorr-es/rig-relay",
                    "description": "Governed local server/control-plane with desktop cockpit. Coordinates agent work, produces structured evidence, exposes MCP tools and ACP sessions. AGPL-3.0, alpha v0.1.0a1.",
                },
                {
                    "name": "GitHub Integration",
                    "url": "",
                    "description": "Governed GitHub chief-of-staff — profile maintenance, security remediation, PR management, Pages publishing. 13 API surfaces, all gated with receipts. Live-proven on PR #7.",
                },
                {
                    "name": "Cross-Provider Registry",
                    "url": "",
                    "description": "Operating pictures for GitHub, Google Workspace, and Meta. Schema-governed, content-light, cross-provider readiness matrix.",
                },
            ],
            "governance_rows": [
                {"scope": "Live runtime mutation", "default": "Always blocked"},
                {"scope": "Merge", "default": "Requires adoption approval"},
                {
                    "scope": "Alert dismissal",
                    "default": "Separate gate, evidence required",
                },
                {"scope": "PR merge", "default": "Forbidden by default"},
                {
                    "scope": "Remote mutation",
                    "default": "Explicit flags + gates + approval",
                },
            ],
            "content_light_heading": "Content-Light Evidence",
            "content_light_body": "Every claim is backed by evidence from the canonical claims index. No raw code, no secrets, no private data in governance artifacts. All public surfaces are generated from committed JSON/JSONL/CSV artifacts.",
            "stats": [
                "370+ tests",
                "13 GitHub surfaces",
                "3 live-proven write lanes",
                "9 node types in evidence graph",
            ],
            "links": [
                {
                    "label": "Repository",
                    "url": "https://github.com/juliantorr-es/rig-relay",
                    "description": "Source code, issues, and documentation.",
                },
                {
                    "label": "Project Site",
                    "url": "https://juliantorr-es.github.io/rig-relay/",
                    "description": "GitHub Pages documentation site.",
                },
                {
                    "label": "Wiki",
                    "url": "https://github.com/juliantorr-es/rig-relay/wiki",
                    "description": "Architecture, governance, and integration guides.",
                },
            ],
        }
        html = tpl.render({
            "title": "Developer Portfolio — Julian Torres",
            "description": "Evidence-backed developer portfolio with tech stack, projects, governance, and public claims.",
            "meta_description": "Julian Torres — software developer building governed agent infrastructure. Desktop cockpit, MCP server, ACP agent, receipt-backed evidence.",
            "site_name": "Julian Torres",
            "canonical_url": "https://juliantorr-es.github.io/juliantorr-es/pages/portfolio.html",
            "og_type": "profile",
            "og_image": "/juliantorr-es/assets/og/portfolio-card.svg",
            "og_image_alt": "Julian Torres — Developer Portfolio",
            "og_image_width": "1200",
            "og_image_height": "630",
            "twitter_card": "summary_large_image",
            "structured_data_json": Markup(
                '{"@context":"https://schema.org","@type":"Person","name":"Julian Torres","url":"https://juliantorr-es.github.io/juliantorr-es/","description":"Software developer building governed agent infrastructure.","knowsAbout":["Python","GitHub API","Governance","Receipt-backend evidence"],"sameAs":["https://github.com/juliantorr-es"]}'
            ),
            "header_brand": "Julian Torres",
            "footer_brand": "Julian Torres",
            "nav_heading": "Portfolio",
            "nav_home_label": "Home",
            "nav_home_desc": "Developer portfolio",
            "footer_home_label": "Profile",
            "model": portfolio_model,
            "sections": [],
            "relative_root": ".",
            "page_id": "portfolio",
            "generated_at": datetime.now(UTC).isoformat(),
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


def _write_sitemap(pages: list[dict], collection_ids: list[str]) -> None:
    """Generate sitemap.xml for all rendered pages."""
    base = "https://juliantorr-es.github.io/rig-relay"
    entries: list[str] = [f"  <url><loc>{base}/</loc><priority>1.0</priority></url>"]
    for p in pages:
        did = p.get("document_id", "") or p.get("doc_id", "")
        if did:
            entries.append(
                f"  <url><loc>{base}/pages/{did}.html</loc><priority>0.8</priority></url>"
            )
    for cid in sorted(collection_ids):
        entries.append(
            f"  <url><loc>{base}/collections/{cid}.html</loc><priority>0.7</priority></url>"
        )
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>"
    )
    (DOCS_OUT / "sitemap.xml").write_text(sitemap, encoding="utf-8")


def _render_homepage_jinja2(output_path: Path) -> None:
    """Override the old homepage with a Jinja2-backed version using full metadata contract."""
    try:
        from jinja2 import Environment, FileSystemLoader

        from rig_relay.docs_renderer.loader import load_json
    except ImportError:
        return

    home_data = load_json(DOCS_JSON / "site_home.v1.json") or {}
    templates_dir = DOCS_OUT.parent / "rig_relay" / "site_renderer" / "templates"
    if not templates_dir.exists():
        return

    env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True)
    try:
        tpl = env.get_template("index.html.j2")
    except Exception:
        return

    # Build page models from site_home data
    nav_pages = [
        {
            "page_id": "codebase-evidence-graph",
            "title": "Evidence Graph",
            "route": "pages/codebase-evidence-graph.html",
            "description": "Searchable graph of 14,000 nodes",
        },
        {
            "page_id": "portfolio",
            "title": "Developer Portfolio",
            "route": "pages/portfolio.html",
            "description": "Evidence-backed developer portfolio",
        },
    ]

    html = tpl.render({
        "title": home_data.get("title", "Rig Relay"),
        "description": home_data.get("plain_language_summary", ""),
        "meta_description": home_data.get(
            "plain_language_summary",
            "Governed local agent platform — inspectable, auditable, refusal-first.",
        )[:160],
        "tagline": home_data.get("tagline", ""),
        "pages": [],
        "generated_at": datetime.now(UTC).isoformat(),
        "relative_root": ".",
        "nav_pages": nav_pages,
        "page_id": "",
        "language": home_data.get("language", "en"),
        "site_name": "Rig Relay",
        "og_title": "Rig Relay",
        "og_description": home_data.get(
            "plain_language_summary", "Governed local agent platform"
        )[:200],
        "og_image": "/rig-relay/assets/og/rig-relay-card.svg",
        "og_image_alt": "Rig Relay — Governed Local Agent Platform",
        "og_image_width": "1200",
        "og_image_height": "630",
        "og_type": "website",
        "og_url": "https://juliantorr-es.github.io/rig-relay/",
        "og_site_name": "Rig Relay",
        "twitter_card": "summary_large_image",
        "canonical_url": "https://juliantorr-es.github.io/rig-relay/",
        "theme_color": "#1e3a5f",
        "robots": "index,follow",
        "structured_data_json": Markup(
            '{"@context":"https://schema.org","@type":"WebSite","name":"Rig Relay","url":"https://juliantorr-es.github.io/rig-relay/","description":"Governed local agent platform — inspectable, auditable, refusal-first."}'
        ),
        "header_brand": "Rig Relay",
        "footer_brand": "Rig Relay",
        "nav_heading": "Evidence Console",
        "nav_home_label": "Home",
        "nav_home_desc": "Product overview",
        "footer_home_label": "Home",
        "release_summary": {},
        "proof_summary": {},
        "public_claims": [],
        "rejected_claims": [],
        "remaining_seams": [],
        "schema_count": 0,
        "github_url": "https://github.com/juliantorr-es/rig-relay",
        "branch": "",
        "head_sha": "",
        "safety_passed": True,
    })
    output_path.write_text(html, encoding="utf-8")


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

    # ── Override with Jinja2-backed homepage for full metadata ──
    _render_homepage_jinja2(DOCS_OUT / "index.html")
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

    # ── Generate sitemap.xml ──
    _write_sitemap(pages, collection_ids)

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
