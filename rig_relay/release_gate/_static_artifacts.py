"""Static artifact validation checks for the Release Evidence Gate.

Checks cover docs JSON schema validation, schema registry coverage,
generated site presence, secret leakage scanning, diagram source safety,
and cache/generated-artifact hygiene.

Each check is a standalone function returning CheckResult.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from rig_relay.release_gate.models import (
    CheckResult,
    CheckSeverity,
    CheckStatus,
    Finding,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS_JSON_DIR = _REPO_ROOT / "docs" / "json"
_DOCS_SCHEMAS_DIR = _REPO_ROOT / "docs" / "schemas"
_DOCS_DIR = _REPO_ROOT / "docs"

# ── Schema mapping helpers ──────────────────────────────────────────────


def _build_schema_map() -> dict[str, str]:
    """Map schema_version const values to schema file names."""
    mapping: dict[str, str] = {}
    if not _DOCS_SCHEMAS_DIR.is_dir():
        return mapping
    for sf in sorted(_DOCS_SCHEMAS_DIR.glob("*.json")):
        try:
            schema = json.loads(sf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        props = schema.get("properties", {})
        sv = props.get("schema_version", {})
        const_val = sv.get("const") if isinstance(sv, dict) else None
        if isinstance(const_val, str):
            mapping[const_val] = sf.name
    return mapping


def _schema_file_for_version(version: str) -> Path | None:
    candidate = _DOCS_SCHEMAS_DIR / f"{version}.schema.json"
    if candidate.is_file():
        return candidate
    return None


def _collect_docs_json_files() -> list[Path]:
    if not _DOCS_JSON_DIR.is_dir():
        return []
    return sorted(
        p
        for p in _DOCS_JSON_DIR.rglob("*.json")
        if p.is_file() and ".DS_Store" not in p.name
    )


def _hash_content(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Check: valid JSON documents ─────────────────────────────────────────


_SchemaCounts = tuple[int, int, int, int]  # valid, invalid, no_schema, parse_error


def _validate_single_doc(
    doc_path: Path, findings: list[Finding], error_details: list[dict[str, object]]
) -> _SchemaCounts:
    rel = str(doc_path.relative_to(_REPO_ROOT))
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        findings.append(
            Finding(
                finding_id=f"static.schema.json_parse_error.{_hash_content(rel)[:12]}",
                category="schema_validation",
                description=f"Invalid JSON in {rel}: {exc}",
                severity=CheckSeverity.BLOCKER,
                source=rel,
                recommendation="Fix JSON syntax errors before proceeding.",
            )
        )
        return (0, 0, 0, 1)

    schema_version = doc.get("schema_version")
    if not isinstance(schema_version, str):
        findings.append(
            Finding(
                finding_id=f"static.schema.no_version.{_hash_content(rel)[:12]}",
                category="schema_validation",
                description=f"No valid schema_version in {rel}",
                severity=CheckSeverity.MEDIUM,
                source=rel,
                recommendation="Add a valid schema_version field.",
            )
        )
        return (0, 0, 1, 0)

    schema_file = _schema_file_for_version(schema_version)
    if schema_file is None:
        findings.append(
            Finding(
                finding_id=f"static.schema.no_schema_file.{_hash_content(rel)[:12]}",
                category="schema_validation",
                description=f"No schema file found for schema_version '{schema_version}' in {rel}",
                severity=CheckSeverity.HIGH,
                source=rel,
                recommendation=f"Create docs/schemas/{schema_version}.schema.json or correct schema_version.",
            )
        )
        return (0, 0, 1, 0)

    return _validate_doc_against_schema(
        doc_path, doc, schema_file, rel, findings, error_details
    )


def _validate_doc_against_schema(
    doc_path: Path,
    doc: object,
    schema_file: Path,
    rel: str,
    findings: list[Finding],
    error_details: list[dict[str, object]],
) -> _SchemaCounts:
    try:
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        findings.append(
            Finding(
                finding_id=f"static.schema.bad_schema_file.{_hash_content(str(schema_file))[:12]}",
                category="schema_validation",
                description=f"Schema file {schema_file.name} is not valid JSON: {exc}",
                severity=CheckSeverity.BLOCKER,
                source=str(schema_file.relative_to(_REPO_ROOT)),
                recommendation="Fix or remove the broken schema file.",
            )
        )
        return (0, 1, 0, 0)

    if not isinstance(doc, dict):
        findings.append(
            Finding(
                finding_id=f"static.schema.not_object.{_hash_content(rel)[:12]}",
                category="schema_validation",
                description=f"Document {rel} is not a JSON object",
                severity=CheckSeverity.BLOCKER,
                source=rel,
                recommendation="JSON documents must be objects at the top level.",
            )
        )
        return (0, 1, 0, 0)

    try:
        import jsonschema

        validator = jsonschema.Draft7Validator(schema)
        instance: Any = doc
        errors = list(validator.iter_errors(instance))
    except Exception as exc:
        findings.append(
            Finding(
                finding_id=f"static.schema.validation_error.{_hash_content(rel)[:12]}",
                category="schema_validation",
                description=f"Validation error for {rel}: {exc}",
                severity=CheckSeverity.HIGH,
                source=rel,
                recommendation="Fix document to match its declared schema.",
            )
        )
        return (0, 1, 0, 0)

    if not errors:
        return (1, 0, 0, 0)

    error_msgs: list[str] = []
    for err in errors:
        path_str = ".".join(str(p) for p in err.absolute_path) or "(root)"
        error_msgs.append(f"{path_str}: {err.message}")
    all_errors = "; ".join(error_msgs)
    findings.append(
        Finding(
            finding_id=f"static.schema.validation_errors.{_hash_content(rel)[:12]}",
            category="schema_validation",
            description=f"Schema validation errors in {rel}: {all_errors[:300]}",
            severity=CheckSeverity.HIGH,
            source=rel,
            recommendation="Fix document to match its declared schema.",
        )
    )
    error_details.append({
        "path": rel,
        "error_count": len(errors),
        "errors": error_msgs,
    })
    return (0, 1, 0, 0)


def check_schema_validation() -> CheckResult:
    result = CheckResult(
        check_id="static.schemas.valid_json_documents",
        title="Schema-backed docs JSON documents validated",
        status=CheckStatus.PASS,
    )
    findings: list[Finding] = []
    valid_count = 0
    invalid_count = 0
    no_schema_count = 0
    parse_error_count = 0
    error_details: list[dict[str, object]] = []

    for doc_path in _collect_docs_json_files():
        v, i, n, p = _validate_single_doc(doc_path, findings, error_details)
        valid_count += v
        invalid_count += i
        no_schema_count += n
        parse_error_count += p

    result.evidence = {
        "total_docs": len(_collect_docs_json_files()),
        "valid": valid_count,
        "invalid": invalid_count,
        "no_schema": no_schema_count,
        "parse_errors": parse_error_count,
    }
    if error_details:
        result.evidence["error_details"] = error_details

    if parse_error_count > 0:
        result.status = CheckStatus.FAIL
        result.severity = CheckSeverity.BLOCKER
    elif invalid_count > 0 or no_schema_count > 0:
        result.status = CheckStatus.FAIL
        result.severity = CheckSeverity.HIGH

    total_docs = len(_collect_docs_json_files())
    result.summary = (
        f"Schema validation: {valid_count} valid, {invalid_count} invalid, "
        f"{no_schema_count} missing schema, {parse_error_count} parse errors "
        f"across {total_docs} documents"
    )
    result.findings = findings
    return result


# ── Check: schema registry coverage ─────────────────────────────────────


def check_schema_coverage() -> CheckResult:
    result = CheckResult(
        check_id="static.schemas.schema_registry_coverage",
        title="Schema registry coverage for rendered doc types",
        status=CheckStatus.PASS,
    )
    findings: list[Finding] = []

    schema_map = _build_schema_map()
    available_versions = set(schema_map.keys())
    used_versions: dict[str, int] = {}

    docs_files = _collect_docs_json_files()
    for doc_path in docs_files:
        try:
            doc = json.loads(doc_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        sv = doc.get("schema_version")
        if isinstance(sv, str):
            used_versions[sv] = used_versions.get(sv, 0) + 1

    result.evidence = {
        "available_schemas": len(available_versions),
        "used_schema_versions": len(used_versions),
        "schema_versions": sorted(used_versions.keys()),
    }

    orphan_versions = set(used_versions.keys()) - available_versions
    for sv in sorted(orphan_versions):
        findings.append(
            Finding(
                finding_id=f"static.coverage.orphan_schema.{_hash_content(sv)[:12]}",
                category="schema_coverage",
                description=f"Schema version '{sv}' used by {used_versions[sv]} docs has no corresponding schema file",
                severity=CheckSeverity.HIGH,
                source=f"docs/schemas/{sv}.schema.json",
                recommendation=f"Create docs/schemas/{sv}.schema.json or remove the schema_version usage.",
            )
        )

    renderable_kinds = {
        "rig.documentation.page.v1",
        "rig.documentation.home.v1",
        "rig.documentation.collection.v1",
        "rig.documentation.site_manifest.v1",
        "rig.documentation.migration_manifest.v1",
        "rig.diagram.v1",
    }
    missing_renderable = renderable_kinds - available_versions
    for sv in sorted(missing_renderable):
        findings.append(
            Finding(
                finding_id=f"static.coverage.missing_renderable_schema.{_hash_content(sv)[:12]}",
                category="schema_coverage",
                description=f"Renderable doc kind '{sv}' has no schema registered",
                severity=CheckSeverity.HIGH,
                source="docs/schemas/",
                recommendation=f"Create docs/schemas/{sv}.schema.json to ensure renderable types are governed.",
            )
        )

    if orphan_versions:
        result.status = CheckStatus.FAIL
        result.severity = CheckSeverity.HIGH
    elif missing_renderable:
        result.status = CheckStatus.WARN
        result.severity = CheckSeverity.MEDIUM
    else:
        result.status = CheckStatus.PASS

    result.summary = (
        f"Schema coverage: {len(available_versions)} schemas available, "
        f"{len(used_versions)} versions in use, "
        f"{len(orphan_versions)} orphans, {len(missing_renderable)} missing renderable schemas"
    )
    result.findings = findings
    return result


# ── Check: generated site present ───────────────────────────────────────


_GENERATED_ASSET_NAMES = [
    "site_home",
    "search_index",
    "render_manifest",
    "site_css",
    "site_js",
    "favicon",
    "nojekyll",
    "pages_dir",
    "collections_dir",
]


def _get_generated_assets() -> dict[str, Path]:
    docs = _DOCS_DIR
    return {
        "site_home": docs / "index.html",
        "search_index": docs / "search-index.json",
        "render_manifest": docs / "render-manifest.json",
        "site_css": docs / "assets" / "site.css",
        "site_js": docs / "assets" / "site.js",
        "favicon": docs / "assets" / "favicon.svg",
        "nojekyll": docs / ".nojekyll",
        "pages_dir": docs / "pages",
        "collections_dir": docs / "collections",
    }


_EXPECTED_COLLECTION_PAGES = [
    "index",
    "audits",
    "security",
    "architecture",
    "governance",
]


def check_generated_site_present() -> CheckResult:
    result = CheckResult(
        check_id="static.renderer.generated_site_present",
        title="Generated static site artifacts present",
        status=CheckStatus.PASS,
    )
    findings: list[Finding] = []
    presence: dict[str, bool] = {}

    assets = _get_generated_assets()
    for name, path in assets.items():
        if name.endswith("_dir"):
            exists = path.is_dir() and any(path.iterdir())
        else:
            exists = path.is_file()
        presence[name] = exists
        if not exists:
            severity = (
                CheckSeverity.HIGH
                if name in {"site_home", "search_index", "render_manifest"}
                else CheckSeverity.MEDIUM
            )
            findings.append(
                Finding(
                    finding_id=f"static.site.missing_{name}",
                    category="generated_site",
                    description=f"Expected generated asset missing: {path.relative_to(_REPO_ROOT)}",
                    severity=severity,
                    source=str(path.relative_to(_REPO_ROOT)),
                    recommendation="Run the static site renderer to regenerate.",
                )
            )

    pages_dir = assets["pages_dir"]
    pages_count = 0
    if pages_dir.is_dir():
        pages_count = len(list(pages_dir.glob("*.html")))
    result.evidence["pages_count"] = pages_count

    collections_dir = assets["collections_dir"]
    collections_count = 0
    if collections_dir.is_dir():
        collections_count = len(list(collections_dir.glob("*.html")))
    result.evidence["collections_count"] = collections_count

    if pages_count == 0:
        findings.append(
            Finding(
                finding_id="static.site.empty_pages",
                category="generated_site",
                description="No HTML pages found in docs/pages/",
                severity=CheckSeverity.BLOCKER,
                source="docs/pages/",
                recommendation="Run the static site renderer.",
            )
        )

    if collections_count == 0:
        findings.append(
            Finding(
                finding_id="static.site.empty_collections",
                category="generated_site",
                description="No collection pages found in docs/collections/",
                severity=CheckSeverity.MEDIUM,
                source="docs/collections/",
                recommendation="Run the static site renderer.",
            )
        )

    missing_any = any(not v for v in presence.values())
    if missing_any:
        result.status = CheckStatus.FAIL
        for f in findings:
            if f.severity == CheckSeverity.BLOCKER:
                result.severity = CheckSeverity.BLOCKER
                break
        else:
            result.severity = CheckSeverity.HIGH
    else:
        result.status = CheckStatus.PASS

    result.evidence["presence"] = presence

    missing_count = sum(1 for v in presence.values() if not v)
    result.summary = (
        f"Generated site: {len(presence) - missing_count}/{len(presence)} assets present, "
        f"{pages_count} pages, {collections_count} collections"
    )
    result.findings = findings
    return result


# ── Check: no secret leakage ────────────────────────────────────────────

_SECRET_PATTERNS: list[tuple[str, str, str]] = [
    (
        "secret.pem_private_key",
        r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----",
        "PEM private key",
    ),
    (
        "secret.github_pat",
        r"github_pat_[a-zA-Z0-9_]{20,}",
        "GitHub personal access token",
    ),
    ("secret.github_classic_token", r"ghp_[a-zA-Z0-9]{36}", "GitHub classic PAT"),
    (
        "secret.github_installation_token",
        r"ghs_[a-zA-Z0-9]{36}",
        "GitHub installation token",
    ),
    (
        "secret.bearer_token_header",
        r"Authorization:\s*Bearer\s+[a-zA-Z0-9\-_\.]{20,}",
        "Bearer token in header",
    ),
    (
        "secret.webhook_secret",
        r"(?:webhook[_-]?secret|WEBHOOK_SECRET)\s*[:=]\s*['\"]?[a-zA-Z0-9\-_]{8,}",
        "Webhook secret assignment",
    ),
    (
        "secret.home_path_absolute",
        r"(?:^|\s)(/Users/|/home/)[a-zA-Z0-9_\-\./]+",
        "Local home directory path",
    ),
    (
        "secret.env_dump",
        r"(?:^|\n)(?:AWS_|GITHUB_|GITLAB_|DOCKER_|NPM_|PYPI_|TWINE_)(?:[A-Z0-9_]+)\s*=\s*['\"]?[^\s'\"]{8,}",
        "Environment variable dump",
    ),
]

_SCAN_GLOBS = ["**/*.html", "search-index.json", "render-manifest.json"]

_SCAN_SKIP_PREFIXES = {"docs/assets/og/"}


def _collect_scan_targets() -> list[Path]:
    targets: list[Path] = []
    for pattern in _SCAN_GLOBS:
        for p in _DOCS_DIR.glob(pattern):
            if not p.is_file():
                continue
            rel = str(p.relative_to(_REPO_ROOT))
            if any(rel.startswith(prefix) for prefix in _SCAN_SKIP_PREFIXES):
                continue
            targets.append(p)
    return sorted(set(targets))


def check_secret_leakage() -> CheckResult:
    result = CheckResult(
        check_id="static.renderer.no_secret_leakage",
        title="No secret leakage in generated static site",
        status=CheckStatus.PASS,
    )
    findings: list[Finding] = []

    targets = _collect_scan_targets()
    compiled = [
        (pid, label, re.compile(pattern, re.IGNORECASE | re.MULTILINE))
        for pid, pattern, label in _SECRET_PATTERNS
    ]
    hit_count = 0

    for file_path in targets:
        rel = str(file_path.relative_to(_REPO_ROOT))
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for pid, label, regex in compiled:
            for match in regex.finditer(content):
                hit_count += 1
                matched_text = match.group(0)
                matched_hash = _hash_content(matched_text)[:16]
                line_num = content[: match.start()].count("\n") + 1
                findings.append(
                    Finding(
                        finding_id=f"static.secret.{pid}.{matched_hash}",
                        category="secret_leakage",
                        description=f"Potential {label} detected in {rel}",
                        severity=CheckSeverity.BLOCKER,
                        source=f"{rel}:{line_num}",
                        recommendation=f"Remove {label} from generated output. Use placeholder values. SHA256 of matched content: {matched_hash}",
                    )
                )

    result.evidence = {"files_scanned": len(targets), "pattern_hits": hit_count}

    if hit_count > 0:
        result.status = CheckStatus.FAIL
        result.severity = CheckSeverity.BLOCKER
        result.summary = f"Secret leakage: {hit_count} potential secrets found across {len(targets)} generated files"
    else:
        result.summary = (
            f"Secret leakage: 0 secrets found across {len(targets)} generated files"
        )

    result.findings = findings
    return result


# ── Check: diagram safe sources ─────────────────────────────────────────


def _collect_diagram_files() -> list[Path]:
    diagrams: list[Path] = []
    docs_files = _collect_docs_json_files()
    for doc_path in docs_files:
        try:
            doc = json.loads(doc_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if doc.get("schema_version") == "rig.diagram.v1":
            diagrams.append(doc_path)
    return diagrams


_SCRIPT_INJECTION_PATTERNS = [
    (re.compile(r"<script[\s>]", re.IGNORECASE), "raw script tag"),
    (re.compile(r"on\w+\s*=", re.IGNORECASE), "event handler attribute"),
    (re.compile(r"javascript\s*:", re.IGNORECASE), "javascript: URI"),
    (re.compile(r"<iframe[\s>]", re.IGNORECASE), "iframe tag"),
    (re.compile(r"<embed[\s>]", re.IGNORECASE), "embed tag"),
    (re.compile(r"<object[\s>]", re.IGNORECASE), "object tag"),
]


def _scan_text_for_injection(text: str) -> list[str]:
    hits: list[str] = []
    for regex, label in _SCRIPT_INJECTION_PATTERNS:
        if regex.search(text):
            hits.append(label)
    return hits


def _check_diagram_source(
    source_data: dict[str, object], diag_id: str, rel: str, findings: list[Finding]
) -> bool:
    src_type = source_data.get("type", "inline")
    src_path_raw = source_data.get("path", "")
    src_path = str(src_path_raw) if isinstance(src_path_raw, str) else ""
    if src_type == "inline":
        return True
    if not src_path:
        findings.append(
            Finding(
                finding_id=f"static.diagram.missing_source_path.{_hash_content(diag_id)[:12]}",
                category="diagram_safety",
                description=f"Diagram '{diag_id}' has source_data with no path",
                severity=CheckSeverity.MEDIUM,
                source=rel,
                recommendation="Provide a valid source_data.path or use type=inline.",
            )
        )
        return False
    if "://" in src_path or src_path.startswith("//"):
        findings.append(
            Finding(
                finding_id=f"static.diagram.remote_source.{_hash_content(diag_id)[:12]}",
                category="diagram_safety",
                description=f"Diagram '{diag_id}' references remote URL: {src_path}",
                severity=CheckSeverity.BLOCKER,
                source=rel,
                recommendation="Use local relative paths only. Remote URLs are not permitted in diagram source data.",
            )
        )
        return False
    if src_path.startswith("/") or src_path.startswith(".."):
        findings.append(
            Finding(
                finding_id=f"static.diagram.absolute_path.{_hash_content(diag_id)[:12]}",
                category="diagram_safety",
                description=f"Diagram '{diag_id}' uses absolute or parent-relative path: {src_path}",
                severity=CheckSeverity.HIGH,
                source=rel,
                recommendation="Use repo-relative paths without leading / or ..",
            )
        )
        return False
    if src_path.endswith(".html") or src_path.startswith((
        "docs/pages/",
        "docs/assets/",
        "docs/collections/",
    )):
        findings.append(
            Finding(
                finding_id=f"static.diagram.generated_source.{_hash_content(diag_id)[:12]}",
                category="diagram_safety",
                description=f"Diagram '{diag_id}' references generated HTML/asset as data source: {src_path}",
                severity=CheckSeverity.HIGH,
                source=rel,
                recommendation="Use raw data files (JSON/JSONL/CSV), not generated HTML or assets.",
            )
        )
        return False
    return True


def _collect_diagram_text_fields(spec: dict[str, object]) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    _collect_node_text_fields(spec, fields)
    _collect_edge_text_fields(spec, fields)
    _collect_row_text_fields(spec, fields)
    _collect_accessibility_text_fields(spec, fields)
    return fields


def _collect_node_text_fields(
    spec: dict[str, object], fields: list[tuple[str, str]]
) -> None:
    nodes = spec.get("nodes", [])
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node.get("id", "?")
        for key in ("label", "description"):
            val = node.get(key, "")
            if isinstance(val, str) and val:
                fields.append((f"node.{nid}.{key}", val))


def _collect_edge_text_fields(
    spec: dict[str, object], fields: list[tuple[str, str]]
) -> None:
    edges = spec.get("edges", [])
    if not isinstance(edges, list):
        return
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        val = edge.get("label", "")
        if isinstance(val, str) and val:
            fields.append(("edge.label", val))


def _collect_row_text_fields(
    spec: dict[str, object], fields: list[tuple[str, str]]
) -> None:
    rows = spec.get("rows", [])
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        for k, v in row.items():
            if isinstance(v, str) and v:
                fields.append((f"row.{k}", v))


def _collect_accessibility_text_fields(
    spec: dict[str, object], fields: list[tuple[str, str]]
) -> None:
    acc = spec.get("accessibility", {})
    if not isinstance(acc, dict):
        return
    for key in ("alt", "summary", "long_description"):
        val = acc.get(key, "")
        if isinstance(val, str) and val:
            fields.append((f"accessibility.{key}", val))


def check_diagram_safety() -> CheckResult:
    result = CheckResult(
        check_id="static.diagrams.safe_sources",
        title="Diagram source data and content safety",
        status=CheckStatus.PASS,
    )
    findings: list[Finding] = []
    diagram_files = _collect_diagram_files()
    safe_count = 0
    unsafe_count = 0

    for diag_path in diagram_files:
        rel = str(diag_path.relative_to(_REPO_ROOT))
        try:
            spec = json.loads(diag_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            findings.append(
                Finding(
                    finding_id=f"static.diagram.parse_error.{_hash_content(rel)[:12]}",
                    category="diagram_safety",
                    description=f"Invalid JSON in diagram {rel}: {exc}",
                    severity=CheckSeverity.HIGH,
                    source=rel,
                    recommendation="Fix JSON syntax.",
                )
            )
            unsafe_count += 1
            continue

        diag_id = spec.get("diagram_id", rel)
        source_data = spec.get("source_data")

        if isinstance(source_data, dict):
            if _check_diagram_source(source_data, diag_id, rel, findings):
                safe_count += 1
            else:
                unsafe_count += 1
        else:
            safe_count += 1

        for field_name, text in _collect_diagram_text_fields(spec):
            injection_hits = _scan_text_for_injection(text)
            if injection_hits:
                findings.append(
                    Finding(
                        finding_id=f"static.diagram.injection.{_hash_content(diag_id + field_name)[:12]}",
                        category="diagram_safety",
                        description=f"Diagram '{diag_id}' field '{field_name}' contains: {', '.join(injection_hits)}",
                        severity=CheckSeverity.BLOCKER,
                        source=rel,
                        recommendation="Remove script/event-handler/injection content from diagram text fields.",
                    )
                )
                unsafe_count += 1

    result.evidence = {
        "diagram_count": len(diagram_files),
        "safe": safe_count,
        "unsafe": unsafe_count,
    }

    if unsafe_count > 0:
        result.status = CheckStatus.FAIL
        blocker_count = sum(1 for f in findings if f.severity == CheckSeverity.BLOCKER)
        result.severity = (
            CheckSeverity.BLOCKER if blocker_count > 0 else CheckSeverity.HIGH
        )
    else:
        result.status = CheckStatus.PASS

    result.summary = (
        f"Diagram safety: {safe_count} safe, {unsafe_count} unsafe "
        f"across {len(diagram_files)} diagrams"
    )
    result.findings = findings
    return result


# ── Check: cache policy ─────────────────────────────────────────────────

_CACHE_LIKE_PATHS = [".pi-lens/", "__pycache__/", "*.pyc", ".DS_Store", ".build/"]

_CACHE_ALLOWLIST = {
    "__pycache__/": "Python bytecode cache — gitignored by default",
    "*.pyc": "Python bytecode — gitignored by default",
    ".build/": "Build artifacts directory — gitignored",
}


def _committed_cache_files() -> list[Path]:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", ".pi-lens/"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        if result.returncode != 0:
            return []
        lines = result.stdout.strip().split("\n")
        return [Path(line) for line in lines if line.strip()]
    except Exception:
        return []


def check_cache_policy() -> CheckResult:
    result = CheckResult(
        check_id="static.generated_artifacts.cache_policy",
        title="Committed cache and generated artifact hygiene",
        status=CheckStatus.PASS,
    )
    findings: list[Finding] = []

    pi_lens_files = _committed_cache_files()
    result.evidence["committed_pi_lens_files"] = [str(f) for f in pi_lens_files]

    if pi_lens_files:
        findings.append(
            Finding(
                finding_id="static.cache.pi_lens_committed",
                category="cache_policy",
                description=f"{len(pi_lens_files)} .pi-lens/ files committed to repository",
                severity=CheckSeverity.MEDIUM,
                source=".pi-lens/",
                recommendation="Add .pi-lens/ to .gitignore unless a documented policy entry (e.g., in docs/json/) explicitly declares .pi-lens as canonical artifact storage. Tool-state cache files should not ship in the repository.",
            )
        )
        result.status = CheckStatus.WARN
        result.severity = CheckSeverity.MEDIUM

    # Check gitignore for expected cache patterns
    gitignore_path = _REPO_ROOT / ".gitignore"
    gitignore_missing: list[str] = []
    if gitignore_path.is_file():
        gitignore = gitignore_path.read_text(encoding="utf-8")
        for pattern in _CACHE_LIKE_PATHS:
            if pattern in _CACHE_ALLOWLIST:
                continue
            if pattern not in gitignore:
                gitignore_missing.append(pattern)
    else:
        gitignore_missing = list(_CACHE_LIKE_PATHS)

    if gitignore_missing:
        for pattern in gitignore_missing:
            if pattern in _CACHE_ALLOWLIST:
                continue
            findings.append(
                Finding(
                    finding_id=f"static.cache.gitignore_missing.{_hash_content(pattern)[:12]}",
                    category="cache_policy",
                    description=f"Cache-like pattern '{pattern}' not in .gitignore",
                    severity=CheckSeverity.MEDIUM,
                    source=".gitignore",
                    recommendation=f"Add '{pattern}' to .gitignore or document the intentional commit policy.",
                )
            )
        if result.status == CheckStatus.PASS:
            result.status = CheckStatus.WARN
            result.severity = CheckSeverity.MEDIUM

    if not findings:
        result.summary = "Cache policy: no committed cache files, .gitignore covers expected patterns"
    else:
        result.summary = f"Cache policy: {len(findings)} findings ({len(pi_lens_files)} committed .pi-lens files)"

    result.findings = findings
    return result


# ── Convenience runner ──────────────────────────────────────────────────


def run_static_artifact_checks() -> list[CheckResult]:
    return [
        check_schema_validation(),
        check_schema_coverage(),
        check_generated_site_present(),
        check_secret_leakage(),
        check_diagram_safety(),
        check_cache_policy(),
    ]
