#!/usr/bin/env python3
"""Rig Relay Dependency Surface Audit.

Reads pyproject.toml, maps every declared dependency against a pre-computed
import scan, and produces a structured JSON audit + CSV export.

Output files:
  docs/json/governance/dependency_surface_audit_v1.v1.json
  .build/rig-relay/derived/dependency_surface_audit_v1.csv

Usage:
    uv run python scripts/rig_relay_dependency_audit.py
    uv run python scripts/rig_relay_dependency_audit.py --json
    uv run python scripts/rig_relay_dependency_audit.py --output-dir /tmp/audit

Content-light: no source code, no secrets, no absolute paths in output.
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import tomllib
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

DEFAULT_JSON_OUT = (
    REPO_ROOT / "docs" / "json" / "governance" / "dependency_surface_audit_v1.v1.json"
)
DEFAULT_CSV_OUT = (
    REPO_ROOT / ".build" / "rig-relay" / "derived" / "dependency_surface_audit_v1.csv"
)

# ── Pre-computed import scan classification ─────────────────────────────
# Each entry: (import_count, import_locations, classification, decision, reason, risk_surface)
# fmt: off
_DIRECT: dict[str, tuple[int, str, str, str, str, list[str]]] = {
    "agent-client-protocol":               (47,  "rig_relay+tests", "canonical_keep",       "keep",     "Protocol surface dependency — ACP agent sessions, progress events, edit proposals, permission gating.", ["network"]),
    "anyio":                               (7,   "rig_relay",       "canonical_keep",       "keep",     "Async file I/O and path operations across the agent loop and tool execution paths.", ["none"]),
    "cachetools":                          (1,   "rig_relay",       "canonical_keep",       "keep",     "Cache decorators for provider capability discovery.", ["none"]),
    "certifi":                             (1,   "rig_relay",       "canonical_keep",       "keep",     "TLS certificate bundle for outbound HTTPS to LLM providers.", ["network"]),
    "charset-normalizer":                  (1,   "rig_relay",       "canonical_keep",       "keep",     "Safe text decoding in file I/O utilities.", ["none"]),
    "cryptography":                        (7,   "rig_relay+tests", "canonical_keep",       "keep",     "HMAC-SHA256 attestation signing for live mutation readiness, evidence integrity.", ["crypto"]),
    "gitpython":                           (3,   "rig_relay",       "canonical_keep",       "keep",     "Git worktree isolation, branch management, dirty guard.", ["subprocess", "filesystem_mutation"]),
    "giturlparse":                         (1,   "rig_relay",       "canonical_keep",       "keep",     "Git URL parsing for provider integrations.", ["none"]),
    "google-auth":                         (4,   "rig_relay",       "canonical_keep",       "keep",     "OAuth consent flow and credential acquisition for Google integrations.", ["network", "credential_adjacent"]),
    "google-api-python-client":            (4,   "tests",           "test_only_keep",       "keep",     "Only used in scripts and tests — not imported in production rig_relay path.", ["network", "credential_adjacent"]),
    "google-auth-httplib2":                (0,   "none",            "remove_candidate",     "remove",   "Zero imports found — httplib2 transport is not used; google-auth uses requests/urllib3 internally.", ["network", "credential_adjacent"]),
    "google-auth-oauthlib":                (3,   "tests",           "test_only_keep",       "keep",     "Only used in scripts and tests — OAuth flow testing.", ["network", "credential_adjacent"]),
    "httpx":                               (61,  "rig_relay+tests", "canonical_keep",       "keep",     "Primary HTTP client for all LLM provider backends, MCP transport, and tool HTTP calls.", ["network"]),
    "jinja2":                              (3,   "rig_relay",       "canonical_keep",       "keep",     "Static site renderer templates for documentation site.", ["none"]),
    "jsonpatch":                           (1,   "rig_relay",       "canonical_keep",       "keep",     "JSON Patch operations in coordination and tool execution.", ["none"]),
    "keyring":                             (5,   "rig_relay+tests", "canonical_keep",       "keep",     "Credential storage backend for provider API keys (macOS Keychain, freedesktop Secret Service, Windows Credential Manager).", ["credential_adjacent"]),
    "markdownify":                         (1,   "rig_relay",       "canonical_keep",       "keep",     "HTML-to-Markdown conversion for web-fetched context.", ["none"]),
    "mcp":                                 (4,   "rig_relay+tests", "canonical_keep",       "keep",     "MCP server transport — exposes governed tools to Antigravity, VS Code, Zed.", ["network"]),
    "mistralai":                           (21,  "rig_relay+tests", "canonical_keep",       "keep",     "Mistral provider backend LLM client (pinned version).", ["network"]),
    "opentelemetry-api":                   (8,   "rig_relay",       "canonical_keep",       "keep",     "OpenTelemetry spans and metrics for session observability.", ["telemetry"]),
    "opentelemetry-exporter-otlp-proto-http": (3,   "rig_relay",       "canonical_keep",       "keep",     "OTLP HTTP exporter for telemetry (opt-in remote export).", ["telemetry", "network"]),
    "opentelemetry-sdk":                   (3,   "rig_relay",       "canonical_keep",       "keep",     "OpenTelemetry SDK — span processors, resource detection.", ["telemetry"]),
    "opentelemetry-semantic-conventions":  (1,   "rig_relay",       "canonical_keep",       "keep",     "Semantic convention constants for telemetry attributes.", ["telemetry"]),
    "packaging":                           (1,   "scripts",         "test_only_keep",       "keep",     "Only used in scripts — version comparison utilities.", ["none"]),
    "pexpect":                             (9,   "tests",           "test_only_keep",       "keep",     "Terminal interaction testing — only used in test suite.", ["subprocess"]),
    "pydantic":                            (207, "rig_relay+tests", "canonical_keep",       "keep",     "Core data modeling — every config, tool args, protocol message, and event uses Pydantic.", ["none"]),
    "pydantic-settings":                   (1,   "rig_relay",       "canonical_keep",       "keep",     "Settings management with env-var binding for Rig Relay configuration.", ["none"]),
    "pyperclip":                           (0,   "none",            "remove_candidate",     "remove",   "No imports found — clipboard functionality is unused.", ["none"]),
    "python-dotenv":                       (7,   "rig_relay",       "canonical_keep",       "keep",     ".env file loading for API keys and local configuration.", ["filesystem_mutation"]),
    "pyyaml":                              (8,   "rig_relay+tests", "canonical_keep",       "keep",     "YAML config parsing (legacy config paths, test fixtures).", ["none"]),
    "requests":                            (0,   "none",            "remove_candidate",     "remove",   "Zero imports — replaced by httpx across the entire codebase.", ["network"]),
    "rich":                                (6,   "rig_relay",       "canonical_keep",       "keep",     "Console formatting for CLI output and script reports.", ["none"]),
    "sounddevice":                         (6,   "rig_relay+tests", "needs_justification",  "review",   "Audio I/O for a coding assistant — warrants architect review for scope creep.", ["native_extensions"]),
    "textual":                             (4,   "rig_relay+tests", "canonical_keep",       "keep",     "Legacy TUI framework retained for compatibility during migration.", ["none"]),
    "textual-speedups":                    (0,   "none",            "remove_candidate",     "remove",   "Zero imports — transitive acceleration library auto-detected by textual; not directly imported.", ["native_extensions"]),
    "tiktoken":                            (1,   "scripts",         "test_only_keep",       "keep",     "Only used in scripts — token counting utilities.", ["none"]),
    "tomli-w":                             (11,  "rig_relay+tests", "canonical_keep",       "keep",     "TOML writing for config persistence and tool output serialization.", ["none"]),
    "tree-sitter":                         (1,   "rig_relay",       "canonical_keep",       "keep",     "AST parsing for bash analytics and code structure indexing.", ["native_extensions"]),
    "tree-sitter-bash":                    (1,   "rig_relay",       "canonical_keep",       "keep",     "Bash grammar for tree-sitter AST parsing of shell scripts.", ["native_extensions"]),
    "watchfiles":                          (1,   "rig_relay",       "canonical_keep",       "keep",     "File system watching for hot-reload in desktop cockpit.", ["filesystem_mutation"]),
    "websockets":                          (14,  "rig_relay+tests", "canonical_keep",       "keep",     "WebSocket server for desktop cockpit projection stream and sidecar IPC.", ["network"]),
    "duckdb":                              (13,  "rig_relay+tests", "canonical_keep",       "keep",     "Read-side analytics over event fabric JSONL — per doctrine, no write path.", ["native_extensions"]),
    "jsonschema":                          (235, "rig_relay+tests", "canonical_keep",       "keep",     "JSON Schema validation for all structured artifacts, protocol messages, and configuration.", ["none"]),
    "pywebview":                           (3,   "rig_relay",       "canonical_keep",       "keep",     "Desktop window shell for the cockpit — wraps HTML/JS frontend in native window.", ["native_extensions"]),
    "zstandard":                           (2,   "rig_relay+tests", "canonical_keep",       "keep",     "Zstandard compression for telemetry bundles and artifact compaction.", ["native_extensions"]),
    "pyobjc-framework-LocalAuthentication": (2,   "rig_relay",       "canonical_keep",       "keep",     "macOS biometric auth (Touch ID) for credential unlock — platform-gated.", ["native_extensions", "credential_adjacent"]),
    "pyrefly":                             (0,   "none",            "remove_candidate",     "remove",   "Zero imports — appears unused in current codebase.", ["none"]),
    "ast-grep-py":                         (0,   "none",            "remove_candidate",     "remove",   "CLI tool only — never imported as a Python library.", ["subprocess"]),
    "platformdirs":                        (1,   "rig_relay",       "canonical_keep",       "keep",     "Platform-appropriate config/data/cache directory resolution.", ["none"]),
}

_DEV: dict[str, tuple[int, str, str, str, str, list[str]]] = {
    "debugpy":               (1, "rig_relay", "test_only_keep", "keep", "Conditional import for debugger attach — production no-op.", ["subprocess"]),
    "pre-commit":            (0, "none",      "test_only_keep", "keep", "CLI tool — never imported as a Python library.", ["subprocess"]),
    "pyinstaller":           (0, "none",      "test_only_keep", "keep", "CLI tool — never imported as a Python library.", ["subprocess"]),
    "pyinstrument":          (0, "none",      "test_only_keep", "keep", "CLI tool — never imported as a Python library.", ["none"]),
    "pyright":               (0, "none",      "test_only_keep", "keep", "CLI tool — never imported as a Python library.", ["subprocess"]),
    "pytest":                (585, "tests",   "test_only_keep", "keep", "Test framework — 585 test files depend on it.", ["subprocess"]),
    "pytest-asyncio":        (1, "tests",     "test_only_keep", "keep", "Async test support — plugin auto-loaded by pytest.", ["none"]),
    "pytest-playwright":     (0, "none",      "test_only_keep", "keep", "Browser automation test plugin — auto-loaded by pytest.", ["browser_automation"]),
    "pytest-textual-snapshot": (0, "none",    "test_only_keep", "keep", "Textual UI snapshot testing plugin — auto-loaded by pytest.", ["none"]),
    "pytest-timeout":        (0, "none",      "test_only_keep", "keep", "Test timeout enforcement plugin — auto-loaded by pytest.", ["none"]),
    "pytest-xdist":          (1, "rig_relay", "test_only_keep", "keep", "Lazy gate for parallel test execution — only in test harness.", ["none"]),
    "respx":                 (15, "tests",    "test_only_keep", "keep", "HTTP mocking for tests — 15 test files depend on it.", ["network"]),
    "ruff":                  (0, "none",      "test_only_keep", "keep", "CLI linter/formatter — never imported as a Python library.", ["subprocess"]),
    "twine":                 (0, "none",      "test_only_keep", "keep", "CLI tool — never imported as a Python library.", ["network"]),
    "typos":                 (0, "none",      "test_only_keep", "keep", "CLI tool — never imported as a Python library.", ["subprocess"]),
    "vulture":               (0, "none",      "test_only_keep", "keep", "CLI tool — never imported as a Python library.", ["subprocess"]),
}

_OPTIONAL: dict[str, tuple[int, str, str, str, str, list[str]]] = {
    "marimo":  (1, "none",    "test_only_keep", "keep", "Notebook environment — only imported in notebooks/ directory.", ["network"]),
    "altair":  (1, "none",    "test_only_keep", "keep", "Declarative visualization — only imported in notebooks/ directory.", ["none"]),
    "pandas":  (1, "none",    "test_only_keep", "keep", "Data analysis — only imported in notebooks/ directory.", ["native_extensions"]),
}

_BUILD: dict[str, tuple[int, str, str, str, str, list[str]]] = {
    "pyinstaller": (0, "none",       "test_only_keep", "keep", "Build-time bundler — not imported at runtime.", ["subprocess"]),
    "truststore":  (1, "none",       "test_only_keep", "keep", "PyInstaller hook for TLS trust store injection — packaging only.", ["network", "credential_adjacent"]),
}
# fmt: on


def _parse_version_spec(dep_line: str) -> tuple[str, str]:
    """Split a dependency line into (package_name, version_spec)."""
    match = re.match(
        r"^([a-zA-Z0-9][-a-zA-Z0-9_.]*)\s*((?:[><=!~]=|[><]\s*)[^;]*|(?:\[[^\]]*\])*\s*(?:;.*)?)$",
        dep_line.strip(),
    )
    if match:
        name = match.group(1)
        spec = match.group(2).strip() if match.group(2) else ""
        return name, spec
    return dep_line.strip(), ""


def _parse_deps_from_toml(deps_list: list[str] | None) -> dict[str, str]:
    """Parse a TOML dependency array into {package_name: version_spec}."""
    if not deps_list:
        return {}
    result: dict[str, str] = {}
    for dep in deps_list:
        name, spec = _parse_version_spec(dep)
        result[name] = spec
    return result


def _parse_pyproject_toml(path: Path) -> dict[str, dict[str, str]]:
    """Extract all dependency groups from pyproject.toml.

    Returns: {"direct": {name: spec}, "dev": {name: spec}, "optional": {name: spec}, "build": {name: spec}}
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)

    result: dict[str, dict[str, str]] = {
        "direct": {},
        "dev": {},
        "optional": {},
        "build": {},
    }

    project = data.get("project", {})
    result["direct"] = _parse_deps_from_toml(project.get("dependencies", []))

    optional_deps = project.get("optional-dependencies", {})
    for _group_name, deps in optional_deps.items():
        parsed = _parse_deps_from_toml(deps)
        result["optional"].update(parsed)

    dev_groups = data.get("dependency-groups", {})
    result["dev"] = _parse_deps_from_toml(dev_groups.get("dev", []))

    # Build group may also exist
    build_deps = _parse_deps_from_toml(dev_groups.get("build", []))
    result["build"].update(build_deps)

    return result


def _build_audit(
    version_specs: dict[str, dict[str, str]], audit_id: str, generated_at: str
) -> dict[str, Any]:
    """Construct the full audit object from pre-computed classifications and TOML version specs."""
    all_groups: list[
        tuple[str, str, dict[str, tuple[int, str, str, str, str, list[str]]]]
    ] = [
        ("direct", "direct", _DIRECT),
        ("dev", "dev", _DEV),
        ("optional", "optional", _OPTIONAL),
        ("build", "build", _BUILD),
    ]

    dependencies: list[dict[str, Any]] = []
    stats = {
        "total_direct": len(_DIRECT),
        "total_dev": len(_DEV),
        "total_optional": len(_OPTIONAL),
        "production_used": 0,
        "test_only": 0,
        "unused_direct": 0,
        "remove_candidates": 0,
        "needs_justification": 0,
    }

    recommendations: list[str] = []

    for declared_group_key, classification_group, classification_map in all_groups:
        for pkg_name, (
            import_count,
            import_locations,
            classification,
            decision,
            reason,
            risk_surface,
        ) in classification_map.items():
            version_spec = version_specs.get(declared_group_key, {}).get(pkg_name, "")

            entry: dict[str, Any] = {
                "package": pkg_name,
                "version_spec": version_spec,
                "declared_group": classification_group,
                "import_count": import_count,
                "import_locations": import_locations,
                "classification": classification,
                "decision": decision,
                "reason": reason,
                "risk_surface": risk_surface,
            }

            dependencies.append(entry)

            match classification:
                case "canonical_keep":
                    stats["production_used"] += 1
                case "test_only_keep":
                    stats["test_only"] += 1
                case "remove_candidate":
                    stats["unused_direct"] += 1
                    stats["remove_candidates"] += 1
                    recommendations.append(
                        f"Remove {pkg_name} ({declared_group_key}) — {reason}"
                    )
                case "needs_justification":
                    stats["needs_justification"] += 1
                    recommendations.append(
                        f"Review {pkg_name} ({declared_group_key}) — {reason}"
                    )
                case "replace_with_stdlib_candidate":
                    stats["unused_direct"] += 1
                    recommendations.append(
                        f"Replace {pkg_name} ({declared_group_key}) with stdlib — {reason}"
                    )
                case "replace_with_existing_dependency_candidate":
                    stats["unused_direct"] += 1
                    recommendations.append(
                        f"Replace {pkg_name} ({declared_group_key}) with existing dep — {reason}"
                    )

    dependencies.sort(key=lambda d: (d["declared_group"], d["package"]))

    return {
        "schema_version": "rig.relay.dependency_surface_audit.v1",
        "audit_id": audit_id,
        "generated_at": generated_at,
        "summary": stats,
        "dependencies": dependencies,
        "recommendations": recommendations,
    }


def _write_json(audit: dict[str, Any], path: Path) -> Path:
    """Write the audit as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def _write_csv(dependencies: list[dict[str, Any]], path: Path) -> Path:
    """Write dependencies as CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "package",
        "version_spec",
        "declared_group",
        "import_count",
        "classification",
        "decision",
        "reason",
        "risk_surface",
    ]

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for dep in dependencies:
            row = {**dep}
            row["risk_surface"] = ";".join(row.get("risk_surface", ["none"]))
            writer.writerow(row)

    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Rig Relay Dependency Surface Audit")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Override output directory for both JSON and CSV files.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON audit to stdout instead of writing files.",
    )
    args = parser.parse_args()

    generated_at = datetime.now(UTC).isoformat()
    audit_id = f"dep-audit-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"

    version_specs = _parse_pyproject_toml(PYPROJECT_PATH)

    audit = _build_audit(version_specs, audit_id, generated_at)

    if args.json:
        print(json.dumps(audit, indent=2, ensure_ascii=False))
        return 0

    json_out = (
        args.output_dir / "dependency_surface_audit_v1.v1.json"
        if args.output_dir
        else DEFAULT_JSON_OUT
    )
    csv_out = (
        args.output_dir / "dependency_surface_audit_v1.csv"
        if args.output_dir
        else DEFAULT_CSV_OUT
    )

    json_path = _write_json(audit, json_out)
    csv_path = _write_csv(audit["dependencies"], csv_out)

    summary = audit["summary"]
    print(f"Dependency surface audit: {audit_id}")
    print(f"  Direct:       {summary['total_direct']:>3d}")
    print(f"  Dev:          {summary['total_dev']:>3d}")
    print(f"  Optional:     {summary['total_optional']:>3d}")
    print("  ─────────────────────")
    print(f"  Production:   {summary['production_used']:>3d}")
    print(f"  Test only:    {summary['test_only']:>3d}")
    print(f"  Unused:       {summary['unused_direct']:>3d}")
    print(f"  Remove:       {summary['remove_candidates']:>3d}")
    print(f"  Needs review: {summary['needs_justification']:>3d}")
    print()
    print(f"Written: {json_path}")
    print(f"Written: {csv_path}")

    return 0


__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
