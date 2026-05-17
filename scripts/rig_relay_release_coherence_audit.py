#!/usr/bin/env python3
"""Rig Relay Release Coherence Audit support script.

Generates a machine-readable audit support report with automated checks
on documentation, security, site structure, code schemas, and generated
output safety. Complements the human-expert audit JSON with programmatic
evidence.

Usage:
  uv run python scripts/rig_relay_release_coherence_audit.py
  uv run python scripts/rig_relay_release_coherence_audit.py --format json

Output:
  JSON audit support report to stdout.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_JSON = REPO_ROOT / "docs" / "json"
DOCS_PAGES = REPO_ROOT / "docs" / "pages"
DOCS_COLLECTIONS = REPO_ROOT / "docs" / "collections"
DOCS_INDEX = REPO_ROOT / "docs" / "index.html"
SITE_MANIFEST = DOCS_JSON / "site_manifest.v1.json"
RENDER_MANIFEST = REPO_ROOT / "docs" / "render-manifest.json"
SEARCH_INDEX = REPO_ROOT / "docs" / "search-index.json"
CODE_SCHEMAS_DIR = DOCS_JSON / "code_schemas"
THREAT_MODEL = DOCS_JSON / "security" / "threat_model_v0.v1.json"
SECURITY_POLICY = DOCS_JSON / "security" / "security_policy_v0.v1.json"
MIGRATION_MANIFEST = DOCS_JSON / "documentation_migration_manifest.v1.json"

LOCAL_PATH_PATTERNS = ["/Users/", "/home/", "C:\\Users"]
TOKEN_PATTERNS = ["sk-ant-", "sk-or-", "sk-", "ghp_", "gho_", "xai-", "hf_"]
_HOMEPAGE_LINK_DUMP_THRESHOLD = 20
_HOMEPAGE_H2_MINIMUM = 3
_AFFECTED_FILES_PREVIEW_LIMIT = 5


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def _file_exists(path: Path) -> bool:
    return path.exists()


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _count_html_pages(directory: Path) -> int:
    if not directory.exists():
        return 0
    return len(list(directory.glob("*.html")))


def _scan_patterns_in_html(
    directory: Path, patterns: list[str]
) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    if not directory.exists():
        return results
    for html_file in directory.glob("*.html"):
        try:
            content = html_file.read_text()
        except Exception:
            continue
        for pattern in patterns:
            if pattern in content:
                results.setdefault(pattern, []).append(
                    str(html_file.relative_to(REPO_ROOT))
                )
    return results


def _count_todos() -> int:
    try:
        output = subprocess.check_output(
            [
                "rg",
                "-c",
                "TODO|FIXME|XXX|HACK",
                "--type",
                "py",
                "--type",
                "ts",
                "--type",
                "html",
            ],
            cwd=REPO_ROOT,
            text=True,
        ).strip()
        if not output:
            return 0
        return sum(
            int(line.split(":")[-1]) for line in output.split("\n") if ":" in line
        )
    except Exception:
        return 0


def _check_homepage_link_dump(index_html: Path) -> bool:
    if not index_html.exists():
        return False
    try:
        content = index_html.read_text()
        page_links = content.count('href="/pages/')
        h2_count = content.count("<h2") + content.count("<h2 ")
        return (
            page_links > _HOMEPAGE_LINK_DUMP_THRESHOLD
            and h2_count < _HOMEPAGE_H2_MINIMUM
        )
    except Exception:
        return False


def _check_collection_existence(site_manifest: dict | None, collection_id: str) -> bool:
    if not site_manifest:
        return False
    for c in site_manifest.get("collections", []):
        if c.get("collection_id") == collection_id:
            return True
    return False


def _count_out_of_scope_findings() -> int:
    findings_file = REPO_ROOT / "docs" / "findings" / "out-of-scope-findings.jsonl"
    if not findings_file.exists():
        return 0
    try:
        return sum(1 for _ in findings_file.open())
    except Exception:
        return 0


def _detect_generated_html_in_context_exclusion() -> bool:
    router_script = REPO_ROOT / "scripts" / "rig_relay_select_code_schemas.py"
    if not router_script.exists():
        return False
    content = router_script.read_text()
    return "docs/pages/**" in content and "**/*.html" in content


def _detect_renderer_modularization() -> str:
    renderer_pkg = REPO_ROOT / "rig_relay" / "docs_renderer"
    return "modular" if renderer_pkg.exists() else "monolithic"


def _collect_test_counts() -> tuple[int, int]:
    try:
        output = subprocess.check_output(
            ["uv", "run", "pytest", "--collect-only", "-q"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
        for line in output.split("\n"):
            if "collected" in line and "errors" in line:
                parts = line.split()
                collected_idx = parts.index("collected")
                test_count = int(parts[collected_idx + 1])
                errors_idx = line.index("errors")
                error_count = int(line[errors_idx:].split()[0])
                return test_count, error_count
            if "collected" in line:
                parts = line.split()
                collected_idx = parts.index("collected")
                return int(parts[collected_idx + 1]), 0
        return 0, 0
    except Exception:
        return 0, 0


def _git_status_short() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "status", "--short"], cwd=REPO_ROOT, text=True
            ).strip()
            or "clean"
        )
    except Exception:
        return "unknown"


def _load_input_data() -> dict[str, Any]:
    return {
        "site_manifest": _load_json(SITE_MANIFEST),
        "threat_model": _load_json(THREAT_MODEL),
        "security_policy_data": _load_json(SECURITY_POLICY),
        "migration_manifest": _load_json(MIGRATION_MANIFEST),
        "code_schema_index": _load_json(CODE_SCHEMAS_DIR / "index.v1.json"),
        "doc_page_count": _count_html_pages(DOCS_PAGES),
        "collection_page_count": _count_html_pages(DOCS_COLLECTIONS),
        "local_path_hits": _scan_patterns_in_html(DOCS_PAGES, LOCAL_PATH_PATTERNS),
        "token_hits": _scan_patterns_in_html(DOCS_PAGES, TOKEN_PATTERNS),
    }


def _build_checks(data: dict[str, Any]) -> list[dict[str, Any]]:
    tm = data["threat_model"]
    sp = data["security_policy_data"]
    mm = data["migration_manifest"]
    csi = data["code_schema_index"]
    return [
        {
            "check_id": "site_manifest_exists",
            "description": "Site manifest exists",
            "pass": _file_exists(SITE_MANIFEST),
            "detail": str(SITE_MANIFEST.relative_to(REPO_ROOT)),
        },
        {
            "check_id": "render_manifest_exists",
            "description": "Render manifest exists",
            "pass": _file_exists(RENDER_MANIFEST),
            "detail": str(RENDER_MANIFEST.relative_to(REPO_ROOT)),
        },
        {
            "check_id": "search_index_exists",
            "description": "Search index exists",
            "pass": _file_exists(SEARCH_INDEX),
            "detail": f"{SEARCH_INDEX.relative_to(REPO_ROOT)!s} ({SEARCH_INDEX.stat().st_size if SEARCH_INDEX.exists() else 0} bytes)",
        },
        {
            "check_id": "index_html_exists",
            "description": "docs/index.html exists",
            "pass": _file_exists(DOCS_INDEX),
            "detail": str(DOCS_INDEX.relative_to(REPO_ROOT)),
        },
        {
            "check_id": "collections_index_exists",
            "description": "docs/collections/index.html exists (archive landing page)",
            "pass": _file_exists(DOCS_COLLECTIONS / "index.html"),
            "detail": str((DOCS_COLLECTIONS / "index.html").relative_to(REPO_ROOT))
            if (DOCS_COLLECTIONS / "index.html").exists()
            else "missing",
        },
        {
            "check_id": "threat_model_exists",
            "description": "Security threat model exists",
            "pass": _file_exists(THREAT_MODEL) and tm is not None,
            "detail": f"{tm.get('threats', []) if tm else 0} threats"
            if tm
            else "missing",
        },
        {
            "check_id": "security_policy_exists",
            "description": "Security policy exists",
            "pass": _file_exists(SECURITY_POLICY) and sp is not None,
            "detail": str(SECURITY_POLICY.relative_to(REPO_ROOT)),
        },
        {
            "check_id": "code_schema_index_exists",
            "description": "Code schema index exists",
            "pass": _file_exists(CODE_SCHEMAS_DIR / "index.v1.json")
            and csi is not None,
            "detail": str((CODE_SCHEMAS_DIR / "index.v1.json").relative_to(REPO_ROOT)),
        },
        {
            "check_id": "migration_manifest_exists",
            "description": "Documentation migration manifest exists",
            "pass": _file_exists(MIGRATION_MANIFEST) and mm is not None,
            "detail": f"{len(mm.get('migrations', []))} migrations"
            if mm
            else "missing",
        },
    ]


def _build_collection_checks(data: dict[str, Any]) -> list[dict[str, Any]]:
    sm = data["site_manifest"]
    return [
        {
            "check_id": "security_collection",
            "description": "Security collection exists in site manifest",
            "pass": _check_collection_existence(sm, "security"),
            "detail": "found"
            if _check_collection_existence(sm, "security")
            else "missing",
        },
        {
            "check_id": "code_schemas_collection",
            "description": "Code Schemas collection exists in site manifest",
            "pass": _check_collection_existence(sm, "code_schemas"),
            "detail": "found"
            if _check_collection_existence(sm, "code_schemas")
            else "missing",
        },
    ]


def _build_safety_checks(data: dict[str, Any]) -> list[dict[str, Any]]:
    local_hits = data["local_path_hits"]
    token_hits = data["token_hits"]
    return [
        {
            "check_id": "homepage_link_dump",
            "description": "Homepage is a link dump (not a product page)",
            "pass": not _check_homepage_link_dump(DOCS_INDEX),
            "detail": "Homepage has narrative structure (not a link dump)"
            if not _check_homepage_link_dump(DOCS_INDEX)
            else "Homepage appears to be a link dump",
        },
        {
            "check_id": "local_paths_in_generated_docs",
            "description": "No local absolute paths in generated HTML",
            "pass": sum(len(v) for v in local_hits.values()) == 0,
            "detail": f"{sum(len(v) for v in local_hits.values())} files with local paths"
            if local_hits
            else "clean",
        },
        {
            "check_id": "token_patterns_in_generated_docs",
            "description": "No token-like strings in generated HTML",
            "pass": sum(len(v) for v in token_hits.values()) == 0,
            "detail": f"{sum(len(v) for v in token_hits.values())} files with token-like strings (may be false positives)"
            if token_hits
            else "clean",
        },
        {
            "check_id": "generated_html_exclusion_in_context",
            "description": "Generated HTML paths excluded from context assembler",
            "pass": _detect_generated_html_in_context_exclusion(),
            "detail": "Exclude patterns found in code schema router"
            if _detect_generated_html_in_context_exclusion()
            else "No exclusion patterns found — generated HTML may enter agent context",
        },
        {
            "check_id": "renderer_modularization",
            "description": "Renderer modularization state",
            "pass": True,
            "detail": _detect_renderer_modularization(),
        },
    ]


def _build_findings(
    checks: list[dict[str, Any]],
    collection_checks: list[dict[str, Any]],
    safety_checks: list[dict[str, Any]],
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    local_hits = data["local_path_hits"]
    token_hits = data["token_hits"]

    for c in checks + collection_checks + safety_checks:
        if not c["pass"] and c["check_id"] not in {"renderer_modularization"}:
            findings.append({
                "finding_id": f"AUTO-{c['check_id']}",
                "check_id": c["check_id"],
                "description": c["description"],
                "detail": c["detail"],
                "severity": "medium",
            })

    for pattern, files in local_hits.items():
        findings.append({
            "finding_id": f"AUTO-LOCAL-PATH-{pattern.replace('/', '-').strip('-')}",
            "check_id": "local_paths_in_generated_docs",
            "description": f"Local path pattern '{pattern}' found in generated HTML",
            "detail": f"{len(files)} files: {', '.join(files[:_AFFECTED_FILES_PREVIEW_LIMIT])}{'...' if len(files) > _AFFECTED_FILES_PREVIEW_LIMIT else ''}",
            "severity": "low",
        })

    for pattern, files in token_hits.items():
        findings.append({
            "finding_id": f"AUTO-TOKEN-{pattern}",
            "check_id": "token_patterns_in_generated_docs",
            "description": f"Token-like pattern '{pattern}' found in generated HTML (may be false positive from security docs)",
            "detail": f"{len(files)} files",
            "severity": "high",
        })

    return findings


def _compute_orphan_count(site_manifest: dict | None, doc_page_count: int) -> int:
    if not site_manifest:
        return 0
    manifest_docs: set[str] = set()
    for c in site_manifest.get("collections", []):
        for d in c.get("documents", []):
            manifest_docs.add(d.get("document_id", ""))
    return max(0, doc_page_count - len(manifest_docs))


def _build_metrics(
    data: dict[str, Any], test_count: int, test_errors: int
) -> dict[str, Any]:
    sm = data["site_manifest"]
    tm = data["threat_model"]
    mm = data["migration_manifest"]
    return {
        "doc_page_count": data["doc_page_count"],
        "collection_page_count": data["collection_page_count"],
        "orphan_doc_count": _compute_orphan_count(sm, data["doc_page_count"]),
        "search_index_count": (
            len(_load_json(SEARCH_INDEX) or {}) if SEARCH_INDEX.exists() else 0
        ),
        "code_schema_count": (
            len(list(CODE_SCHEMAS_DIR.glob("*.json")))
            if CODE_SCHEMAS_DIR.exists()
            else 0
        ),
        "security_threat_count": len(tm.get("threats", [])) if tm else 0,
        "security_release_blocker_count": (
            sum(1 for t in tm["threats"] if t.get("release_blocker"))
            if tm and "threats" in tm
            else 0
        ),
        "test_count_collected": test_count,
        "known_test_failures": test_errors,
        "generated_site_public_ready": _file_exists(DOCS_INDEX),
        "homepage_link_dump": _check_homepage_link_dump(DOCS_INDEX),
        "has_security_collection": _check_collection_existence(sm, "security"),
        "has_code_schemas_collection": _check_collection_existence(sm, "code_schemas"),
        "generated_html_in_context_excluded": _detect_generated_html_in_context_exclusion(),
        "local_paths_in_generated_docs": sum(
            len(v) for v in data["local_path_hits"].values()
        ),
        "token_patterns_in_generated_docs": sum(
            len(v) for v in data["token_hits"].values()
        ),
        "todo_count": _count_todos(),
        "out_of_scope_findings_count": _count_out_of_scope_findings(),
        "migration_manifest_migrations": (len(mm.get("migrations", [])) if mm else 0),
    }


def run() -> dict[str, Any]:
    data = _load_input_data()
    test_count, test_errors = _collect_test_counts()

    checks = _build_checks(data)
    collection_checks = _build_collection_checks(data)
    safety_checks = _build_safety_checks(data)
    findings = _build_findings(checks, collection_checks, safety_checks, data)
    metrics = _build_metrics(data, test_count, test_errors)

    return {
        "schema_version": "rig.release_coherence_audit_support.v1",
        "source_commit": _git_sha(),
        "git_status": _git_status_short(),
        "metrics": metrics,
        "checks": checks + collection_checks + safety_checks,
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rig Relay Release Coherence Audit support script"
    )
    parser.add_argument(
        "--format",
        choices=["json"],
        default="json",
        help="Output format (only JSON supported)",
    )
    _ = parser.parse_args()

    report = run()
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
