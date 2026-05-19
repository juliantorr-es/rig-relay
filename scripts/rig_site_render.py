#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import glob
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any

from rig_relay.site_renderer.loaders import (
    SchemaValidationError,
    get_git_sha,
    load_artifacts_for_page,
    load_input_manifest,
    load_page_model,
    validate_json_schema,
)
from rig_relay.site_renderer.normalizers import (
    normalize_artifacts_index,
    normalize_compiler,
    normalize_contracts,
    normalize_frontend,
    normalize_hardening,
    normalize_integrations,
    normalize_proof_chain,
    normalize_protocol,
    normalize_release_gate,
    normalize_seams,
    normalize_testing,
)
from rig_relay.site_renderer.renderer import render_index, render_page, write_page
from rig_relay.site_renderer.safety import (
    is_public_safe,
    scan_content,
    scan_rendered_site,
)

REPO_ROOT = Path(
    os.environ.get("RIG_SITE_REPO_ROOT", str(Path(__file__).resolve().parent.parent))
)
SITE_INPUT_DIR = Path(
    os.environ.get("RIG_SITE_INPUT_DIR", str(REPO_ROOT / "docs" / "json" / "site"))
)
MANIFEST_PATH = Path(
    os.environ.get(
        "RIG_SITE_MANIFEST_PATH", str(SITE_INPUT_DIR / "input_manifest.v1.json")
    )
)
OUTPUT_DIR = Path(
    os.environ.get(
        "RIG_SITE_OUTPUT_DIR", str(REPO_ROOT / ".build" / "rig-relay" / "site")
    )
)
ASSETS_SRC = (
    Path(__file__).resolve().parent.parent / "rig_relay" / "site_renderer" / "assets"
)
ASSETS_OUT = OUTPUT_DIR / "assets"
SITE_CSS_SRC = ASSETS_SRC / "site.css"
GITHUB_URL = "https://github.com/juliantorr-es/rig-relay"
OG_IMAGE_SRC = REPO_ROOT / "docs" / "assets" / "og" / "rig-relay-card.svg"


NORMALIZER_MAP: dict[str, Callable[[dict], list[dict]]] = {
    "release-candidate": normalize_release_gate,
    "testing": normalize_testing,
    "integrations": normalize_integrations,
    "frontend": normalize_frontend,
    "proof-chain": normalize_proof_chain,
    "contracts": normalize_contracts,
    "protocol": normalize_protocol,
    "compiler": normalize_compiler,
    "hardening": normalize_hardening,
    "seams": normalize_seams,
    "artifacts": normalize_artifacts_index,
}


def _artifact_source_paths(manifest: dict | None, page_id: str) -> list[str]:
    if not manifest:
        return []
    inputs = manifest.get("inputs", [])
    if not isinstance(inputs, list):
        return []
    return [
        e.get("source_path", "")
        for e in inputs
        if isinstance(e, dict) and e.get("page_id") == page_id
    ]


def _detect_stale(manifest: dict, page_id: str, head_sha: str) -> list[dict]:
    stale: list[dict] = []
    inputs = manifest.get("inputs", [])
    if not isinstance(inputs, list):
        return stale
    for entry in inputs:
        if not isinstance(entry, dict):
            continue
        if entry.get("page_id") != page_id:
            continue
        expected = entry.get("source_commit")
        if expected and expected != head_sha:
            stale.append({
                "source_path": entry.get("source_path", ""),
                "expected_sha": expected,
                "actual_sha": head_sha,
            })
    return stale


def _safe_relative_path(path: Path | str, start: Path | str) -> str:
    """Return a safe relative path string."""
    try:
        return str(Path(path).relative_to(start))
    except ValueError:
        return str(path)


def _build_structured_data_homepage(
    schema_count: int, head_sha: str, description: str
) -> str:
    """Build JSON-LD structured data for the homepage."""
    data = [
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": "Rig Relay",
            "description": description,
            "url": GITHUB_URL,
        },
        {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": "Rig Relay",
            "applicationCategory": "DeveloperApplication",
            "operatingSystem": "macOS, Linux",
            "description": description,
            "url": GITHUB_URL,
            "license": "https://www.gnu.org/licenses/agpl-3.0.html",
        },
    ]
    res = json.dumps(data, separators=(",", ":"))
    return res.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _build_structured_data_evidence(title: str, description: str, route: str) -> str:
    """Build JSON-LD structured data for an evidence page."""
    data = {
        "@context": "https://schema.org",
        "@type": "TechArticle",
        "headline": title,
        "description": description or f"Evidence page: {title}",
        "url": route,
        "isPartOf": {"@type": "WebSite", "name": "Rig Relay"},
    }
    res = json.dumps(data, separators=(",", ":"))
    return res.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _count_schemas(repo_root: Path) -> int:
    """Count JSON schema files in docs/schemas/."""
    schemas_dir = repo_root / "docs" / "schemas"
    if not schemas_dir.exists():
        return 0
    return len(glob.glob(str(schemas_dir / "*.schema.json")))


def _load_governance_claims(repo_root: Path) -> tuple[list[str], list[str], list[str]]:
    """Load public claims, rejected claims, and remaining seams from governance artifacts."""
    supported: list[str] = []
    rejected: list[str] = []
    seams: list[str] = []

    # Cross-surface convergence review
    conv_path = (
        repo_root
        / "docs"
        / "json"
        / "governance"
        / "cross_surface_v1_convergence_review.v1.json"
    )
    if conv_path.exists():
        try:
            conv = json.loads(conv_path.read_text(encoding="utf-8"))
            supported.extend(conv.get("release_paper_claims_supported", []))
            rejected.extend(conv.get("release_paper_claims_rejected", []))
        except Exception:
            pass

    # Hardening artifact
    hard_path = (
        repo_root
        / "docs"
        / "json"
        / "governance"
        / "cross_surface_v1_1_hardening.v1.json"
    )
    if hard_path.exists():
        try:
            hard = json.loads(hard_path.read_text(encoding="utf-8"))
            for cb in hard.get("remaining_claim_boundaries", []):
                if isinstance(cb, str):
                    rejected.append(cb)
                elif isinstance(cb, dict) and "boundary" in cb:
                    rejected.append(cb["boundary"])
        except Exception:
            pass

    # Agent execution readiness
    exec_path = (
        repo_root
        / "docs"
        / "json"
        / "governance"
        / "agent_execution_readiness_v1.v1.json"
    )
    if exec_path.exists():
        try:
            ex = json.loads(exec_path.read_text(encoding="utf-8"))
            seams.extend(ex.get("remaining_seams", []))
        except Exception:
            pass

    # Deduplicate while preserving order
    seen_s: set[str] = set()
    unique_supported = []
    for c in supported:
        key = str(c) if isinstance(c, str) else json.dumps(c)
        if key not in seen_s:
            seen_s.add(key)
            if isinstance(c, dict):
                unique_supported.append(c.get("claim", str(c)))
            else:
                unique_supported.append(c)

    seen_r: set[str] = set()
    unique_rejected = []
    for c in rejected:
        key = str(c) if isinstance(c, str) else json.dumps(c)
        if key not in seen_r:
            seen_r.add(key)
            if isinstance(c, dict):
                unique_rejected.append(c.get("boundary", str(c)))
            else:
                unique_rejected.append(c)

    return unique_supported, unique_rejected, seams


def main() -> int:
    t0 = time.perf_counter()

    import argparse

    parser = argparse.ArgumentParser(description="Rig Relay Static Site Renderer")
    parser.add_argument(
        "--candidate-id", default="default", help="Candidate ID for the run"
    )
    args = parser.parse_args()

    candidate_id = args.candidate_id
    print("Rig Relay — Site Renderer v2")
    print(f"  Candidate ID: {candidate_id}")
    print(f"  Output: {OUTPUT_DIR}")

    head_sha = get_git_sha()
    branch = "main"
    generated_at = datetime.now(UTC).isoformat()

    failed_gates: list[str] = []
    failure_reasons: list[str] = []

    manifest: dict | None = None
    page_models: dict[str, dict] = {}
    page_sections: dict[str, list[dict]] = {}

    all_loaded: list[str] = []
    all_missing: list[str] = []
    all_stale: list[dict] = []

    # 1. Load manifest
    try:
        manifest = load_input_manifest(MANIFEST_PATH, REPO_ROOT)
        if not manifest:
            raise SchemaValidationError("Input manifest was empty or invalid")
    except Exception as e:
        failed_gates.append(_safe_relative_path(MANIFEST_PATH, REPO_ROOT))
        failure_reasons.append(f"manifest_load_error: {e}")

    # 2. Safety scan manifest
    if manifest:
        manifest_str = json.dumps(manifest)
        safety_rep = scan_content(
            manifest_str, source=_safe_relative_path(MANIFEST_PATH, REPO_ROOT)
        )
        if not is_public_safe(safety_rep):
            failed_gates.append(_safe_relative_path(MANIFEST_PATH, REPO_ROOT))
            failure_reasons.append("safety_block_in_manifest")

    # 3. Load page models & scan safety
    if not failure_reasons:
        for pm_path in sorted(SITE_INPUT_DIR.glob("page_*.v1.json")):
            try:
                pm = load_page_model(pm_path, REPO_ROOT)
                if pm:
                    page_models[pm["page_id"]] = pm

                    pm_str = json.dumps(pm)
                    safety_rep = scan_content(
                        pm_str, source=_safe_relative_path(pm_path, REPO_ROOT)
                    )
                    if not is_public_safe(safety_rep):
                        failed_gates.append(_safe_relative_path(pm_path, REPO_ROOT))
                        failure_reasons.append(
                            f"safety_block_in_page_model: {pm['page_id']}"
                        )
                else:
                    raise SchemaValidationError(
                        f"Page model {pm_path.name} was invalid"
                    )
            except Exception as e:
                failed_gates.append(_safe_relative_path(pm_path, REPO_ROOT))
                failure_reasons.append(f"page_model_load_error: {e}")

    # 4. Load artifacts, scan safety & normalize
    inputs = manifest.get("inputs", []) if manifest else []
    release_summary = {}
    proof_summary = {}
    if not failure_reasons:
        for page_id, pm in page_models.items():
            loaded: list[str] = []
            missing: list[str] = []
            try:
                artifacts = load_artifacts_for_page(pm, manifest, REPO_ROOT)

                # Check loaded vs missing source artifacts
                for entry in inputs:
                    if isinstance(entry, dict) and entry.get("page_id") == page_id:
                        sp = entry.get("source_path", "")
                        st = entry.get("source_type", "")
                        rk = entry.get("renderer_kind", "")
                        if st == "static_asset":
                            continue
                        if sp and rk and rk in artifacts:
                            loaded.append(sp)
                        elif sp and st in ("json", "jsonl", "schema"):
                            missing.append(sp)

                # Safety scan source artifacts
                for kind, artifact in artifacts.items():

                    def _strip_repository(obj: Any) -> Any:
                        if isinstance(obj, dict):
                            return {
                                k: _strip_repository(v)
                                for k, v in obj.items()
                                if k != "repository"
                            }
                        elif isinstance(obj, list):
                            return [_strip_repository(x) for x in obj]
                        return obj

                    scanned_art = _strip_repository(artifact)
                    art_str = json.dumps(scanned_art)
                    safety_rep = scan_content(
                        art_str, source=f"artifact:{page_id}:{kind}"
                    )
                    if not is_public_safe(safety_rep):
                        failed_gates.append(f"artifact:{page_id}:{kind}")
                        failure_reasons.append(
                            f"safety_block_in_artifact: {page_id}/{kind}"
                        )

                stale = _detect_stale(manifest, page_id, head_sha)
                all_loaded.extend(loaded)
                all_missing.extend(missing)
                all_stale.extend(stale)

                normalizer = NORMALIZER_MAP.get(page_id)
                if normalizer is not None:
                    sections = normalizer(artifacts)
                else:
                    sections = pm.get("sections", [])

                for kind, artifact in sorted(artifacts.items()):

                    def _strip_repo_local(obj: Any) -> Any:
                        if isinstance(obj, dict):
                            return {
                                k: _strip_repo_local(v)
                                for k, v in obj.items()
                                if k != "repository"
                            }
                        elif isinstance(obj, list):
                            return [_strip_repo_local(x) for x in obj]
                        return obj

                    clean_artifact = _strip_repo_local(artifact)
                    payload_str = json.dumps(clean_artifact, indent=2)
                    meta = {"artifact_kind": kind}
                    if (
                        isinstance(clean_artifact, dict)
                        and "schema_version" in clean_artifact
                    ):
                        meta["schema_version"] = clean_artifact["schema_version"]
                    if (
                        isinstance(clean_artifact, dict)
                        and "generated_at" in clean_artifact
                    ):
                        meta["generated_at"] = clean_artifact["generated_at"]

                    sections.append({
                        "kind": "raw_json",
                        "title": f"Raw Artifact: {kind}",
                        "metadata": meta,
                        "payload": payload_str,
                    })

                page_sections[page_id] = sections

                if page_id == "release-candidate":
                    gate = artifacts.get("release_gate") or artifacts.get("gate")
                    verdict = artifacts.get("rc_verdict") or artifacts.get("verdict")
                    blockers = (
                        artifacts.get("rc_blockers") or artifacts.get("blockers") or []
                    )

                    status = "unknown"
                    if gate and isinstance(gate, dict):
                        status = gate.get("overall_status", "unknown")
                    if verdict and isinstance(verdict, dict):
                        status = verdict.get(
                            "verdict", verdict.get("gate_overall_status", status)
                        )

                    blockers_count = len(blockers)

                    release_summary = {
                        "status": status,
                        "blocker_count": blockers_count,
                        "gate_id": gate.get("gate_id", "unknown")
                        if gate and isinstance(gate, dict)
                        else "unknown",
                        "ready_count": sum(
                            1
                            for b in blockers
                            if isinstance(b, dict) and b.get("resolved", False)
                        )
                        if isinstance(blockers, list)
                        else 0,
                    }

                if page_id == "proof-chain":
                    verdict = artifacts.get("rc_verdict")
                    inventory = artifacts.get("test_inventory")

                    open_blockers = 0
                    resolved_blockers = 0
                    if verdict and isinstance(verdict, dict):
                        open_blockers = len(verdict.get("open_blocker_ids", []))
                        resolved_blockers = len(verdict.get("resolved_blocker_ids", []))

                    test_count = 0
                    test_files = 0
                    if inventory and isinstance(inventory, dict):
                        summary = inventory.get("summary", {})
                        test_count = summary.get("total_test_functions", 0)
                        test_files = summary.get("total_test_files", 0)

                    proof_summary = {
                        "open_blockers": open_blockers,
                        "resolved_blockers": resolved_blockers,
                        "test_count": test_count,
                        "test_files": test_files,
                    }
            except Exception as e:
                failed_gates.append(f"page_artifacts:{page_id}")
                failure_reasons.append(f"artifact_validation_error: {e}")

    # 5. Compute deterministic digest
    deterministic_digest = ""
    if not failure_reasons:
        hasher = hashlib.sha256()
        for page_id in sorted(page_models.keys()):
            sections = page_sections.get(page_id, [])
            sections_str = json.dumps(sections, sort_keys=True)
            hasher.update(page_id.encode("utf-8"))
            hasher.update(sections_str.encode("utf-8"))
        deterministic_digest = hasher.hexdigest()

    # 6. Check for bypass
    output_exists = (OUTPUT_DIR / "index.html").exists()
    prev_report_path = OUTPUT_DIR / "site_render_report.v1.json"
    bypass_regeneration = False

    if not failure_reasons and prev_report_path.exists() and output_exists:
        try:
            prev_report = json.loads(prev_report_path.read_text(encoding="utf-8"))
            if (
                prev_report.get("verdict") == "success"
                and prev_report.get("deterministic_digest") == deterministic_digest
            ):
                bypass_regeneration = True
                print(
                    f"  ✓ Output is up-to-date (deterministic digest: {deterministic_digest}). Skipping regeneration."
                )
        except Exception:
            pass

    # 7. Render pages
    rendered: list[dict] = []
    failed: list[dict] = []

    if not failure_reasons and not bypass_regeneration:
        if OUTPUT_DIR.exists():
            shutil.rmtree(OUTPUT_DIR)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        nav_pages = []
        for p_id in sorted(page_models.keys()):
            pm_entry = page_models[p_id]
            nav_pages.append({
                "page_id": p_id,
                "title": pm_entry.get("title", "Untitled"),
                "route": pm_entry.get("route", f"/{p_id}/index.html"),
                "description": pm_entry.get("description", ""),
            })
        nav_pages.sort(key=lambda x: x["route"])

        for page_id, pm in page_models.items():
            sections = page_sections.get(page_id, [])
            route = pm.get("route", f"/{page_id}/index.html")
            depth = route.strip("/").count("/")
            relative_root = ".." * depth if depth > 0 else "."

            page_title = pm.get("title", "Untitled")
            page_desc = pm.get("description", "")
            page = {
                **pm,
                "sections": sections,
                "generated_at": generated_at,
                "og_title": page_title,
                "og_description": page_desc[:200]
                if page_desc
                else f"Evidence: {page_title}",
                "og_image": f"{relative_root}/assets/og/rig-relay-card.svg",
                "og_type": "article",
                "og_url": route,
                "canonical_url": route,
                "twitter_card": "summary",
                "theme_color": "#1e3a5f",
                "robots": "index,follow",
                "structured_data_json": _build_structured_data_evidence(
                    page_title, page_desc, route
                ),
            }
            source_artifact_paths = _artifact_source_paths(manifest, page_id)

            try:
                html = render_page(
                    page, nav_pages=nav_pages, relative_root=relative_root
                )

                rel_path = route.lstrip("/")
                output_path = OUTPUT_DIR / rel_path
                write_page(output_path, html)

                safety = scan_content(
                    html, source=str(output_path.relative_to(OUTPUT_DIR))
                )
                safety_notes = ""
                if not is_public_safe(safety):
                    safety_notes = f"{len(safety.findings)} potential secrets detected"
                    failed_gates.append(route)
                    failure_reasons.append(f"safety_block_in_rendered_html: {page_id}")

                rendered.append({
                    "page_id": page_id,
                    "title": pm.get("title", ""),
                    "route": route,
                    "status": "rendered" if is_public_safe(safety) else "failed",
                    "source_artifact_paths": source_artifact_paths,
                    "safety_notes": safety_notes,
                })
            except Exception as e:
                failed_gates.append(route)
                failure_reasons.append(f"render_error: {e}")
                failed.append({
                    "page_id": page_id,
                    "title": pm.get("title", ""),
                    "route": route,
                    "status": "failed",
                    "source_artifact_paths": source_artifact_paths,
                    "safety_notes": str(e),
                })
    elif not failure_reasons and bypass_regeneration:
        try:
            prev_report = json.loads(prev_report_path.read_text(encoding="utf-8"))
            rendered = prev_report.get("pages", [])
        except Exception:
            bypass_regeneration = False

    # 8. Render Index, copy assets, run final scan
    safety_passed = True
    safety_finding_count = 0

    if not failure_reasons and not bypass_regeneration:
        # Index Page
        all_pages = rendered + failed
        schema_count = _count_schemas(REPO_ROOT)
        public_claims, rejected_claims, remaining_seams_list = _load_governance_claims(
            REPO_ROOT
        )
        homepage_desc = (
            "Rig Relay is a governed local agent platform that turns agent execution "
            "into schema-governed, trace-correlated, content-light, refusal-first local evidence."
        )
        site_meta = {
            "generated_at": generated_at,
            "branch": branch,
            "head_sha": head_sha,
            "safety_passed": all(r["status"] == "rendered" for r in rendered),
            "release_summary": release_summary,
            "proof_summary": proof_summary,
            "public_claims": public_claims,
            "rejected_claims": rejected_claims,
            "remaining_seams": remaining_seams_list,
            "schema_count": schema_count,
            "github_url": GITHUB_URL,
            "og_title": "Rig Relay",
            "og_description": homepage_desc[:200],
            "og_image": "./assets/og/rig-relay-card.svg",
            "og_type": "website",
            "og_url": "./index.html",
            "twitter_card": "summary",
            "canonical_url": "./index.html",
            "theme_color": "#1e3a5f",
            "robots": "index,follow",
            "public_description": homepage_desc,
            "structured_data_json": _build_structured_data_homepage(
                schema_count, head_sha, homepage_desc
            ),
        }

        # Build nav_pages for index as well
        nav_pages = []
        for p_id in sorted(page_models.keys()):
            pm_entry = page_models[p_id]
            nav_pages.append({
                "page_id": p_id,
                "title": pm_entry.get("title", "Untitled"),
                "route": pm_entry.get("route", f"/{p_id}/index.html"),
                "description": pm_entry.get("description", ""),
            })
        nav_pages.sort(key=lambda x: x["route"])

        index_html = render_index(
            all_pages, site_meta, nav_pages=nav_pages, relative_root="."
        )
        write_page(OUTPUT_DIR / "index.html", index_html)

        # Copy Assets
        ASSETS_OUT.mkdir(parents=True, exist_ok=True)
        if SITE_CSS_SRC.exists():
            shutil.copy2(SITE_CSS_SRC, ASSETS_OUT / "site.css")
        favicon_src = REPO_ROOT / "docs" / "assets" / "favicon.svg"
        if favicon_src.exists():
            shutil.copy2(favicon_src, ASSETS_OUT / "favicon.svg")
        # Copy OG image
        og_out_dir = ASSETS_OUT / "og"
        og_out_dir.mkdir(parents=True, exist_ok=True)
        if OG_IMAGE_SRC.exists():
            shutil.copy2(OG_IMAGE_SRC, og_out_dir / "rig-relay-card.svg")

        # Generate sitemap.xml
        sitemap_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            "  <url><loc>./index.html</loc></url>",
        ]
        for p in sorted(all_pages, key=lambda x: x.get("route", "")):
            route_val = p.get("route", "")
            if route_val:
                sitemap_lines.append(f"  <url><loc>.{route_val}</loc></url>")
        sitemap_lines.append("</urlset>")
        sitemap_path = OUTPUT_DIR / "sitemap.xml"
        sitemap_path.write_text("\n".join(sitemap_lines), encoding="utf-8")

        # Generate robots.txt
        robots_content = "User-agent: *\nAllow: /\nSitemap: ./sitemap.xml\n"
        robots_path = OUTPUT_DIR / "robots.txt"
        robots_path.write_text(robots_content, encoding="utf-8")

        # Full Site Safety Scan
        safety_report = scan_rendered_site(OUTPUT_DIR)
        safety_passed = is_public_safe(safety_report)
        safety_finding_count = len(safety_report.findings)
        if not safety_passed:
            failed_gates.append("site_safety")
            failure_reasons.append("safety_block_in_rendered_site")

    elif not failure_reasons and bypass_regeneration:
        safety_passed = True
        safety_finding_count = 0

    # 9. Verdict and Cleanup
    verdict = "fail" if (failure_reasons or failed_gates or failed) else "success"

    if verdict == "fail":
        # Clear output directory except for the report
        if OUTPUT_DIR.exists():
            for child in OUTPUT_DIR.iterdir():
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    shutil.rmtree(child)
        else:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    duration_ms = int((time.perf_counter() - t0) * 1000)

    stale_warnings_mapped = []
    for sw in all_stale:
        stale_warnings_mapped.append({
            "source_path": sw.get("source_path", ""),
            "expected_sha": sw.get("expected_sha", ""),
            "artifact_sha": sw.get("actual_sha", ""),
        })

    # Construct report
    render_report = {
        "$schema": "rig.site.render_report.v1",
        "candidate_id": candidate_id,
        "verdict": verdict,
        "deterministic_digest": deterministic_digest,
        "generated_at": generated_at,
        "head_sha": head_sha,
        "branch": branch,
        "render_duration_ms": duration_ms,
        "pages_rendered": len(rendered),
        "pages_failed": len(failed),
        "safety_passed": safety_passed,
        "safety_scan_passed": safety_passed,
        "safety_finding_count": safety_finding_count,
        "source_artifacts_loaded": sorted(set(all_loaded)),
        "source_artifacts_missing": sorted(set(all_missing)),
        "stale_warnings": stale_warnings_mapped,
        "failed_gates": failed_gates,
        "failure_reasons": failure_reasons,
        "pages": rendered + failed,
    }

    # Safety scan the report JSON itself
    report_json_str = json.dumps(render_report, indent=2)
    report_safety = scan_content(
        report_json_str, source="report:site_render_report.v1.json"
    )
    if not is_public_safe(report_safety):
        if "site_render_report.v1.json" not in failed_gates:
            failed_gates.append("site_render_report.v1.json")
            failure_reasons.append("safety_block_in_render_report")
            verdict = "fail"
            render_report["verdict"] = "fail"
            render_report["safety_passed"] = False
            render_report["safety_scan_passed"] = False
            render_report["failed_gates"] = failed_gates
            render_report["failure_reasons"] = failure_reasons

            # Clean up other files again
            if OUTPUT_DIR.exists():
                for child in OUTPUT_DIR.iterdir():
                    if child.is_file():
                        child.unlink()
                    elif child.is_dir():
                        shutil.rmtree(child)
            else:
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            report_json_str = json.dumps(render_report, indent=2)

    # Validate final report against its schema
    try:
        is_valid, err = validate_json_schema(
            render_report, "rig.site.render_report.v1", REPO_ROOT
        )
        if not is_valid:
            print(f"  ⚠ Render report failed schema validation: {err}")
    except Exception as e:
        print(f"  ⚠ Error validating render report schema: {e}")

    report_path = OUTPUT_DIR / "site_render_report.v1.json"
    report_path.write_text(report_json_str, encoding="utf-8")

    # If successful, write manifest
    if verdict == "success":
        site_manifest_out = {
            "schema_version": "rig.site.manifest.v1",
            "generated_at": generated_at,
            "head_sha": head_sha,
            "site_title": "Rig Relay — Governed Local Agent Platform",
            "routes": [
                {"route": r["route"], "title": r["title"], "page_id": r["page_id"]}
                for r in rendered + failed
            ],
            "assets": [
                "assets/site.css",
                "assets/favicon.svg",
                "assets/og/rig-relay-card.svg",
            ],
        }
        manifest_out_path = OUTPUT_DIR / "site_manifest.v1.json"
        manifest_out_path.write_text(
            json.dumps(site_manifest_out, indent=2, default=str), encoding="utf-8"
        )

    print(
        f"\n  Render complete: verdict={verdict}, "
        f"{len(rendered)} pages, {len(failed)} failed, {duration_ms}ms"
    )
    print(f"  Report: {report_path}")

    return 0 if verdict == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
