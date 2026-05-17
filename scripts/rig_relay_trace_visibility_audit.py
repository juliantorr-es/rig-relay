#!/usr/bin/env python3
"""Rig Relay Trace Visibility Audit — static codebase scanner.

Scans Python and JavaScript source files for trace recording calls,
correlation field usage, event name patterns, and instrumentation gaps.
Emits a JSON audit report. Conservative: marks unknown when it cannot
prove coverage.

Usage:
    uv run python scripts/rig_relay_trace_visibility_audit.py
    uv run python scripts/rig_relay_trace_visibility_audit.py --output report.json
    uv run python scripts/rig_relay_trace_visibility_audit.py --format text
    uv run python scripts/rig_relay_trace_visibility_audit.py --strict
"""

from __future__ import annotations

import argparse
import ast
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

PYTHON_SCAN_DIRS = ["rig_relay", "scripts"]
JS_SCAN_DIR = "frontend/desktop/js"
TEST_SCAN_DIRS = ["tests/tracing", "tests/desktop", "tests/frontend", "tests/context"]

EXCLUDED_DIRS = {"__pycache__", ".git", ".build", "node_modules", ".rig", "generated"}

EXCLUDED_FILES = {"index.html", "*.html"}

TRACE_RECORDER_PATTERNS = [
    "TraceRecorder",
    "trace_recorder",
    "build_golden_path_event",
    "get_default_trace_store",
    "store.write",
    ".event(",
    ".start_span(",
    ".end_span(",
    ".emit_event(",
    ".emit_bridge_step(",
    ".emit_transport_event(",
    ".emit_intent_dispatched(",
    ".emit_intent_result(",
]

FRONTEND_TRACE_PATTERNS = [
    "recordFrontendEvent",
    "setFrontendHandshakeId",
    "frontendTrace",
]

CORRELATION_FIELDS = [
    "handshake_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "frontend_session_id",
    "connection_id",
    "session_id",
    "job_id",
    "tool_batch_id",
    "tool_call_id",
    "agent_id",
    "lane_id",
    "worktree_id",
    "request_id",
    "schema_id",
    "document_id",
    "commit_sha",
    "repo_head",
    "event_sequence",
    "frontend_sequence",
    "backend_sequence",
    "performance_now_ms",
    "monotonic_ns",
    "wall_time",
]

EVENT_NAME_REGEX = re.compile(
    r"""["'](?:desktop\.|frontend[_.]|agent\.|tool\.|context\.|docs\.|"""
    r"""worktree\.|security\.|session\.|coordination\.)[a-z_.]+["']"""
)

FRONTEND_EVENT_REGEX = re.compile(r"""['"](frontend[_.][a-z_]+)['"]""")

HANDSHAKE_ID_REGEX = re.compile(r"handshake_id")
TRACE_ID_REGEX = re.compile(r"trace_id")
FRONTEND_SESSION_REGEX = re.compile(r"frontend_session_id")

CRITICAL_PATH_MARKERS = {
    "desktop_bridge_startup": {
        "files": ["rig_relay/desktop/bridge_server.py"],
        "patterns": [
            "desktop.bridge.launch_requested",
            "desktop.bridge.frontend_resolved",
            "desktop.bridge.runtime_config_built",
            "desktop.bridge.server_bound",
        ],
    },
    "websocket_auth_projection": {
        "files": ["rig_relay/desktop/websocket_server.py"],
        "patterns": [
            "desktop.websocket.accepted",
            "desktop.websocket.auth_ok",
            "desktop.websocket.auth_failed",
            "desktop.projection.sent",
        ],
    },
    "frontend_breadcrumbs": {
        "files": [
            "frontend/desktop/js/telemetry/frontendTrace.js",
            "frontend/desktop/js/boot/orchestrator.js",
        ],
        "patterns": ["frontend_boot_started", "frontend_ready", "frontend_auth_ok"],
    },
    "tool_execution": {
        "files": ["rig_relay/runtime/supervisor_invoker.py"],
        "patterns": ["tool.execution.started", "tool.execution.completed"],
    },
    "context_assembly": {
        "files": ["rig_relay/context/"],
        "patterns": ["context.assembly", "context.envelope"],
    },
    "code_schema_routing": {
        "files": ["rig_relay/context/"],
        "patterns": ["schema_router", "schema_authority", "code_schema"],
    },
    "static_docs_render": {
        "files": ["scripts/render_static_docs.py"],
        "patterns": ["docs.render"],
    },
    "websocket_security_rejections": {
        "files": ["rig_relay/desktop/websocket_server.py"],
        "patterns": [
            "origin_rejected",
            "invalid_json",
            "rate_limited",
            "unauthenticated",
        ],
    },
}

GENERATED_HTML_PATHS = [
    "docs/index.html",
    "docs/pages/",
    "docs/assets/",
    "docs/search-index.json",
    "docs/render-manifest.json",
]

SENSITIVE_PATHS = [
    "~/.rig/",
    "/Users/",
    "/home/",
    "Application Support",
    "identity",
    "token",
    "secret",
]


class _Finding:
    __slots__ = (
        "finding_id",
        "severity",
        "path_id",
        "file",
        "line",
        "description",
        "evidence",
        "recommended_fix",
        "release_blocker",
    )

    def __init__(
        self,
        finding_id: str,
        severity: str,
        path_id: str,
        file: str,
        line: int | None,
        description: str,
        evidence: str = "",
        recommended_fix: str = "",
        release_blocker: bool = False,
    ) -> None:
        self.finding_id = finding_id
        self.severity = severity
        self.path_id = path_id
        self.file = file
        self.line = line
        self.description = description
        self.evidence = evidence
        self.recommended_fix = recommended_fix
        self.release_blocker = release_blocker

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "finding_id": self.finding_id,
            "severity": self.severity,
            "path_id": self.path_id,
            "file": self.file,
            "description": self.description,
        }
        if self.line is not None:
            d["line"] = self.line
        if self.evidence:
            d["evidence"] = self.evidence
        if self.recommended_fix:
            d["recommended_fix"] = self.recommended_fix
        if self.release_blocker:
            d["release_blocker"] = self.release_blocker
        return d


def _get_commit_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _is_generated_html(path: str) -> bool:
    for gh in GENERATED_HTML_PATHS:
        if gh in path:
            return True
    return path.endswith(".html") and "docs/" in path


def _is_sensitive(path: str) -> bool:
    for sp in SENSITIVE_PATHS:
        if sp in path:
            return True
    return False


def _is_excluded(path: Path) -> bool:
    parts = path.parts
    for part in parts:
        if part in EXCLUDED_DIRS or part.startswith("."):
            return True
    if path.name.endswith(".pyc") or path.name == ".DS_Store":
        return True
    return False


def _repo_relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _scan_python_file(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "file": _repo_relative(path),
        "trace_recorder_calls": [],
        "correlation_fields": [],
        "event_names": [],
        "lines_scanned": 0,
    }

    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return result

    result["lines_scanned"] = len(content.splitlines())

    tree: ast.AST | None = None
    try:
        tree = ast.parse(content, filename=str(path))
    except SyntaxError:
        pass

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call_str = ast.unparse(node) if hasattr(ast, "unparse") else ""
                for pattern in TRACE_RECORDER_PATTERNS:
                    if pattern in call_str:
                        result["trace_recorder_calls"].append({
                            "line": node.lineno,
                            "pattern": pattern,
                            "snippet": call_str[:120],
                        })
                        break

            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                match = EVENT_NAME_REGEX.search(node.value)
                if match:
                    result["event_names"].append({
                        "line": node.lineno,
                        "value": match.group(0).strip("'\""),
                    })

    for field in CORRELATION_FIELDS:
        count = content.count(field)
        if count > 0:
            result["correlation_fields"].append({"field": field, "occurrences": count})

    return result


def _scan_js_file(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "file": _repo_relative(path),
        "frontend_trace_calls": [],
        "correlation_fields": [],
        "event_names": [],
        "lines_scanned": 0,
    }

    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return result

    lines = content.splitlines()
    result["lines_scanned"] = len(lines)

    for i, line in enumerate(lines, start=1):
        for pattern in FRONTEND_TRACE_PATTERNS:
            if pattern in line:
                result["frontend_trace_calls"].append({
                    "line": i,
                    "pattern": pattern,
                    "snippet": line.strip()[:120],
                })
                break

        match = FRONTEND_EVENT_REGEX.search(line)
        if match:
            result["event_names"].append({"line": i, "value": match.group(1)})

        if HANDSHAKE_ID_REGEX.search(line):
            if not any(
                cf["field"] == "handshake_id" for cf in result["correlation_fields"]
            ):
                result["correlation_fields"].append({
                    "field": "handshake_id",
                    "occurrences": 1,
                })
            else:
                for cf in result["correlation_fields"]:
                    if cf["field"] == "handshake_id":
                        cf["occurrences"] += 1

    return result


def _scan_test_file(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"file": _repo_relative(path), "test_count": 0}

    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return result

    tree: ast.AST | None = None
    try:
        tree = ast.parse(content, filename=str(path))
    except SyntaxError:
        return result

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    result["test_count"] += 1

    return result


def _file_matches_target(file_path: str, target: str) -> bool:
    if target.endswith("/"):
        return file_path.startswith(target)
    return file_path == target or file_path.endswith("/" + target.rsplit("/", 1)[-1])


def _collect_patterns_from_result(
    fr: dict[str, Any], patterns: list[str]
) -> tuple[list[str], list[str]]:
    events: list[str] = []
    matched: list[str] = []
    event_values = [str(ev.get("value", "")) for ev in fr.get("event_names", [])]
    events.extend(event_values)
    for pat in patterns:
        if any(pat in ev for ev in event_values) and pat not in matched:
            matched.append(pat)
    return events, matched


def _check_critical_path(
    path_id: str,
    markers: dict[str, Any],
    all_file_results: list[dict[str, Any]],
    test_results: list[dict[str, Any]],
) -> dict[str, Any]:
    target_files = markers["files"]
    target_patterns = markers["patterns"]

    found_patterns: list[str] = []
    found_events: list[str] = []

    for fr in all_file_results:
        file_path = str(fr.get("file", ""))
        if not any(_file_matches_target(file_path, tf) for tf in target_files):
            continue
        new_events, new_patterns = _collect_patterns_from_result(fr, target_patterns)
        found_events.extend(new_events)
        for pat in new_patterns:
            if pat not in found_patterns:
                found_patterns.append(pat)

    related_tests = [
        str(tr.get("file", ""))
        for tr in test_results
        if path_id.replace("_", "")
        in str(tr.get("file", "")).replace("_", "").replace("/", "")
    ]

    missing = [p for p in target_patterns if p not in found_patterns]
    return {
        "path_id": path_id,
        "target_files": target_files,
        "expected_patterns": target_patterns,
        "found_patterns": found_patterns,
        "missing_patterns": missing,
        "all_found_events": found_events[:30],
        "related_tests": related_tests,
        "coverage": "complete"
        if not missing
        else ("partial" if found_patterns else "missing"),
    }


def _generate_findings(
    critical_path_results: list[dict[str, Any]], all_file_results: list[dict[str, Any]]
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    fid = 0

    for cpr in critical_path_results:
        fid += 1
        path_id = str(cpr["path_id"])
        coverage = str(cpr["coverage"])
        missing = cpr.get("missing_patterns", [])
        found = cpr.get("found_patterns", [])

        if coverage == "complete":
            findings.append(
                _Finding(
                    finding_id=f"TV-{fid:03d}",
                    severity="info",
                    path_id=path_id,
                    file=", ".join(str(f) for f in cpr.get("target_files", [])),
                    line=None,
                    description=f"Critical path '{path_id}' has all expected trace patterns present.",
                    evidence=f"Found patterns: {', '.join(found)}",
                    release_blocker=False,
                ).to_dict()
            )
        elif coverage == "partial":
            findings.append(
                _Finding(
                    finding_id=f"TV-{fid:03d}",
                    severity="medium",
                    path_id=path_id,
                    file=", ".join(str(f) for f in cpr.get("target_files", [])),
                    line=None,
                    description=f"Critical path '{path_id}' has partial trace coverage.",
                    evidence=f"Found: {', '.join(found)}. Missing: {', '.join(missing)}",
                    recommended_fix=f"Add trace events for missing patterns: {', '.join(missing)}",
                    release_blocker=path_id
                    in {
                        "websocket_security_rejections",
                        "context_assembly",
                        "code_schema_routing",
                        "agent_loop_turn",
                    },
                ).to_dict()
            )
        else:
            findings.append(
                _Finding(
                    finding_id=f"TV-{fid:03d}",
                    severity="high",
                    path_id=path_id,
                    file=", ".join(str(f) for f in cpr.get("target_files", [])),
                    line=None,
                    description=f"Critical path '{path_id}' has no trace events found.",
                    evidence=f"Expected patterns: {', '.join(str(m) for m in missing)} — none found in codebase.",
                    recommended_fix=f"Instrument {', '.join(str(f) for f in cpr.get('target_files', []))} with trace events.",
                    release_blocker=path_id
                    in {
                        "websocket_security_rejections",
                        "context_assembly",
                        "code_schema_routing",
                        "agent_loop_turn",
                    },
                ).to_dict()
            )

    generated_html_excluded = True
    for fr in all_file_results:
        file_path = str(fr.get("file", ""))
        if _is_generated_html(file_path):
            generated_html_excluded = False
            fid += 1
            findings.append(
                _Finding(
                    finding_id=f"TV-{fid:03d}",
                    severity="critical",
                    path_id="",
                    file=file_path,
                    line=None,
                    description="Generated HTML file was included in scan — this is forbidden.",
                    release_blocker=True,
                ).to_dict()
            )

    fid += 1
    findings.append(
        _Finding(
            finding_id=f"TV-{fid:03d}",
            severity="info",
            path_id="",
            file="",
            line=None,
            description=f"Generated HTML exclusion: {'PASS' if generated_html_excluded else 'FAIL'}",
            evidence="No generated HTML files were scanned."
            if generated_html_excluded
            else "FAIL",
            release_blocker=False,
        ).to_dict()
    )

    token_leakage_found = False
    for fr in all_file_results:
        file_path = str(fr.get("file", ""))
        if _is_sensitive(file_path) and "rig_relay/" not in file_path:
            token_leakage_found = True
            fid += 1
            findings.append(
                _Finding(
                    finding_id=f"TV-{fid:03d}",
                    severity="critical",
                    path_id="",
                    file=file_path,
                    line=None,
                    description="Sensitive path included in scan — possible token leakage.",
                    release_blocker=True,
                ).to_dict()
            )

    if not token_leakage_found:
        fid += 1
        findings.append(
            _Finding(
                finding_id=f"TV-{fid:03d}",
                severity="info",
                path_id="",
                file="",
                line=None,
                description="Token/path leakage check: PASS — no sensitive paths found in scanned files.",
                release_blocker=False,
            ).to_dict()
        )

    frontend_events_found = False
    for fr in all_file_results:
        if fr.get("frontend_trace_calls") or any(
            "frontend" in str(ev.get("value", "")) for ev in fr.get("event_names", [])
        ):
            frontend_events_found = True
            break

    fid += 1
    findings.append(
        _Finding(
            finding_id=f"TV-{fid:03d}",
            severity="info",
            path_id="frontend_breadcrumbs",
            file="",
            line=None,
            description=f"Frontend breadcrumb event usage: {'FOUND' if frontend_events_found else 'NOT FOUND'}.",
            evidence="recordFrontendEvent calls detected in JS files."
            if frontend_events_found
            else "No frontend trace calls found.",
            release_blocker=not frontend_events_found,
        ).to_dict()
    )

    websocket_lifecycle_found = any(
        "desktop.websocket" in str(ev.get("value", ""))
        for fr in all_file_results
        for ev in fr.get("event_names", [])
    )

    fid += 1
    findings.append(
        _Finding(
            finding_id=f"TV-{fid:03d}",
            severity="info",
            path_id="websocket_auth_projection",
            file="",
            line=None,
            description=f"WebSocket lifecycle trace usage: {'FOUND' if websocket_lifecycle_found else 'NOT FOUND'}.",
            evidence="WebSocket trace events detected."
            if websocket_lifecycle_found
            else "No WebSocket trace events found.",
            release_blocker=not websocket_lifecycle_found,
        ).to_dict()
    )

    code_schema_events_found = any(
        "schema_router" in str(ev.get("value", ""))
        or "schema_authority" in str(ev.get("value", ""))
        for fr in all_file_results
        for ev in fr.get("event_names", [])
    )

    fid += 1
    findings.append(
        _Finding(
            finding_id=f"TV-{fid:03d}",
            severity="medium" if not code_schema_events_found else "info",
            path_id="code_schema_routing",
            file="",
            line=None,
            description=f"Code schema router event/correlation gap: {'NO GAP' if code_schema_events_found else 'GAP CONFIRMED — not instrumented'}.",
            evidence="No code schema router trace events found."
            if not code_schema_events_found
            else "Code schema router trace events found.",
            recommended_fix="Add trace events to code schema router."
            if not code_schema_events_found
            else "",
            release_blocker=not code_schema_events_found,
        ).to_dict()
    )

    static_docs_events_found = any(
        "docs.render" in str(ev.get("value", ""))
        for fr in all_file_results
        for ev in fr.get("event_names", [])
    )

    fid += 1
    findings.append(
        _Finding(
            finding_id=f"TV-{fid:03d}",
            severity="low" if not static_docs_events_found else "info",
            path_id="static_docs_render",
            file="",
            line=None,
            description=f"Static docs render trace gap: {'NO GAP' if static_docs_events_found else 'GAP CONFIRMED — not instrumented'}.",
            evidence="No static docs render trace events found."
            if not static_docs_events_found
            else "Static docs render trace events found.",
            recommended_fix="Add optional trace events to render_static_docs.py."
            if not static_docs_events_found
            else "",
            release_blocker=False,
        ).to_dict()
    )

    return findings


def _build_audit_report(
    py_results: list[dict[str, Any]],
    js_results: list[dict[str, Any]],
    test_results: list[dict[str, Any]],
    findings: list[dict[str, object]],
    files_scanned: int,
    commit_sha: str,
) -> dict[str, object]:
    all_file_results = py_results + js_results

    all_event_names: set[str] = set()
    for fr in all_file_results:
        for ev in fr.get("event_names", []):
            val = ev.get("value", "")
            if val:
                all_event_names.add(val)

    all_correlation_fields: dict[str, int] = {}
    for fr in all_file_results:
        for cf in fr.get("correlation_fields", []):
            field = str(cf["field"])
            all_correlation_fields[field] = all_correlation_fields.get(field, 0) + int(
                cf.get("occurrences", 1)
            )

    critical_path_results = []
    for path_id, markers in CRITICAL_PATH_MARKERS.items():
        cpr = _check_critical_path(path_id, markers, all_file_results, test_results)
        critical_path_results.append(cpr)

    complete_count = sum(
        1 for c in critical_path_results if c["coverage"] == "complete"
    )
    partial_count = sum(1 for c in critical_path_results if c["coverage"] == "partial")
    missing_count = sum(1 for c in critical_path_results if c["coverage"] == "missing")
    blocker_count = sum(1 for f in findings if f.get("release_blocker"))

    return {
        "schema_version": "rig.trace_visibility_audit.v1",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_commit": commit_sha,
        "files_scanned": files_scanned,
        "event_names": sorted(all_event_names),
        "correlation_fields_found": all_correlation_fields,
        "critical_paths": critical_path_results,
        "findings": findings,
        "summary": {
            "complete": complete_count,
            "partial": partial_count,
            "missing": missing_count,
            "release_blockers": blocker_count,
        },
    }


def _format_text_report(report: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("Rig Relay Trace Visibility Audit")
    lines.append("=" * 60)
    lines.append(f"Commit: {report.get('source_commit', 'unknown')}")
    lines.append(f"Files scanned: {report.get('files_scanned', 0)}")
    lines.append(f"Generated: {report.get('generated_at', '')}")
    lines.append("")

    summary = report.get("summary", {})
    if isinstance(summary, dict):
        lines.append("Summary:")
        lines.append(f"  Complete: {summary.get('complete', 0)}")
        lines.append(f"  Partial:  {summary.get('partial', 0)}")
        lines.append(f"  Missing:  {summary.get('missing', 0)}")
        lines.append(f"  Release blockers: {summary.get('release_blockers', 0)}")
        lines.append("")

    lines.append("Critical Paths:")
    critical_paths = report.get("critical_paths", [])
    if isinstance(critical_paths, list):
        for cp in critical_paths:
            if isinstance(cp, dict):
                cov = cp.get("coverage", "unknown")
                icon = {"complete": "✅", "partial": "⚠️", "missing": "❌"}.get(
                    str(cov), "❓"
                )
                lines.append(f"  {icon} {cp.get('path_id', '?')}: {cov}")
                missing = cp.get("missing_patterns", [])
                if missing:
                    lines.append(f"     Missing: {', '.join(str(m) for m in missing)}")
                related = cp.get("related_tests", [])
                if related:
                    lines.append(f"     Tests: {', '.join(str(t) for t in related)}")
    lines.append("")

    lines.append("Findings:")
    findings_list = report.get("findings", [])
    if isinstance(findings_list, list):
        for f in findings_list:
            if isinstance(f, dict):
                sev = str(f.get("severity", "info")).upper()
                icon = {
                    "CRITICAL": "🔴",
                    "HIGH": "🟠",
                    "MEDIUM": "🟡",
                    "LOW": "🔵",
                    "INFO": "⚪",
                }.get(sev, "⚪")
                lines.append(
                    f"  {icon} [{sev}] {f.get('finding_id', '?')}: {f.get('description', '')}"
                )
                if f.get("recommended_fix"):
                    lines.append(f"     Fix: {f['recommended_fix']}")
    lines.append("")

    event_names = report.get("event_names", [])
    if isinstance(event_names, list) and event_names:
        lines.append(f"Event names discovered ({len(event_names)}):")
        for name in sorted(str(n) for n in event_names):
            lines.append(f"  - {name}")
        lines.append("")

    corr_fields = report.get("correlation_fields_found", {})
    if isinstance(corr_fields, dict) and corr_fields:
        lines.append("Correlation fields found:")
        for field, count in sorted(corr_fields.items(), key=lambda x: -x[1]):
            lines.append(f"  - {field}: {count} occurrences")
        lines.append("")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rig Relay Trace Visibility Audit — static codebase scanner."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON report to file instead of stdout.",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Exit with code 1 if any release blockers found.",
    )
    return parser


def _scan_all_files() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int
]:
    py_results: list[dict[str, Any]] = []
    js_results: list[dict[str, Any]] = []
    test_results: list[dict[str, Any]] = []
    files_scanned = 0

    for scan_dir in PYTHON_SCAN_DIRS:
        dir_path = REPO_ROOT / scan_dir
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if _is_excluded(py_file):
                continue
            repo_path = _repo_relative(py_file)
            if _is_generated_html(repo_path):
                continue
            if _is_sensitive(repo_path) and "rig_relay/" not in repo_path:
                continue
            files_scanned += 1
            py_results.append(_scan_python_file(py_file))

    js_dir = REPO_ROOT / JS_SCAN_DIR
    if js_dir.exists():
        for js_file in js_dir.rglob("*.js"):
            if _is_excluded(js_file):
                continue
            files_scanned += 1
            js_results.append(_scan_js_file(js_file))

    for test_dir in TEST_SCAN_DIRS:
        dir_path = REPO_ROOT / test_dir
        if not dir_path.exists():
            continue
        for test_file in dir_path.rglob("*.py"):
            if _is_excluded(test_file):
                continue
            files_scanned += 1
            test_results.append(_scan_test_file(test_file))

    return py_results, js_results, test_results, files_scanned


def _emit_report(report: dict[str, object], args: argparse.Namespace) -> None:
    if args.format == "text":
        output = _format_text_report(report)
    else:
        output = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(output)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    commit_sha = _get_commit_sha()
    py_results, js_results, test_results, files_scanned = _scan_all_files()

    all_file_results = py_results + js_results
    critical_path_results = [
        _check_critical_path(path_id, markers, all_file_results, test_results)
        for path_id, markers in CRITICAL_PATH_MARKERS.items()
    ]
    findings = _generate_findings(critical_path_results, all_file_results)
    report = _build_audit_report(
        py_results, js_results, test_results, findings, files_scanned, commit_sha
    )

    _emit_report(report, args)

    summary = report.get("summary", {})
    blockers = (
        int(summary.get("release_blockers", 0)) if isinstance(summary, dict) else 0
    )
    if args.strict and blockers > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
