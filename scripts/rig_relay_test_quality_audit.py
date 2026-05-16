#!/usr/bin/env python3
"""Test quality audit tool — canonicalize per docs/governance/test-suite-doctrine.md.

Produces:
  docs/audits/test-suite/test_quality_report.json
  docs/audits/test-suite/test_quality_report.jsonl
  docs/audits/test-suite/test_quality_summary.md
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"
OUTPUT_DIR = REPO_ROOT / "docs" / "audits" / "test-suite"

_MIN_RIG_MODULE_DEPTH = 2  # rig_relay.<domain>.<module>

BAD_NAME_PATTERNS = [
    "test_basic",
    "test_works",
    "test_stuff",
    "test_sanity",
    "test_thing",
    "test_something",
    "test_test",
    "test_run",
    "test_main",
    "test_default",
    "test_simple",
]

DOMAIN_TO_TEST_DIR: dict[str, str] = {
    "rig_relay.desktop": "tests/desktop",
    "rig_relay.evidence": "tests/evidence",
    "rig_relay.identity": "tests/identity",
    "rig_relay.core": "tests/core",
    "rig_relay.ralph": "tests/ralph",
    "rig_relay.governance": "tests/governance",
    "rig_relay.coordination": "tests/coordination",
    "rig_relay.telemetry": "tests/telemetry",
    "rig_relay.bash": "tests/bash",
    "rig_relay.analytics": "tests/analytics",
    "rig_relay.providers": "tests/providers",
    "rig_relay.runtime": "tests/runtime",
    "rig_relay.reports": "tests/reports",
    "rig_relay.acp": "tests/acp",
    "rig_relay.cli": "tests/cli",
    "rig_relay.context": "tests/context",
    "rig_relay.extensions": "tests/extensions",
    "scripts": "tests/scripts",
}

KNOWN_DUPLICATE_PAIRS: list[tuple[str, str]] = [
    (
        "tests/telemetry/test_observability.py",
        "tests/telemetry/test_observability_e2e.py",
    ),
    ("tests/tools/test_bash.py", "tests/tools/test_bash_hardening.py"),
]

ROOT_LEVEL_ALLOWLIST: set[str] = {"tests/test_tagged_text.py"}


class Finding:
    __slots__ = (
        "finding_id",
        "severity",
        "rule_id",
        "path",
        "line",
        "message",
        "suggested_fix",
        "status",
        "autofixable",
    )

    def __init__(
        self,
        severity: str,
        rule_id: str,
        path: str,
        line: int | None,
        message: str,
        suggested_fix: str = "",
        autofixable: bool = False,
    ) -> None:
        self.severity = severity
        self.rule_id = rule_id
        self.path = path
        self.line = line
        self.message = message
        self.suggested_fix = suggested_fix
        self.status = "open"
        self.autofixable = autofixable
        raw = f"{rule_id}:{path}:{line or 0}:{message}"
        self.finding_id = f"F-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "severity": self.severity,
            "rule_id": self.rule_id,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "suggested_fix": self.suggested_fix,
            "status": self.status,
            "autofixable": self.autofixable,
        }


def collect_test_files() -> list[Path]:
    result: list[Path] = []
    for p in TESTS_DIR.rglob("test_*.py"):
        if p.is_file():
            result.append(p.relative_to(REPO_ROOT))
    return sorted(result)


def extract_imports(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def extract_function_names(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return []
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]


def _is_scripts_target(imports: list[str], file_rel: str) -> bool:
    if "/scripts/" in file_rel or file_rel.startswith("tests/scripts/"):
        return True
    return False


def count_markers(path: Path) -> dict[str, int]:
    """Count pytest marker decorators in a file."""
    try:
        source = path.read_text()
    except (OSError, UnicodeDecodeError):
        return {}
    markers: dict[str, int] = {}
    for marker_name in [
        "smoke",
        "contract",
        "integration",
        "e2e",
        "packaging",
        "slow",
        "legacy",
        "flaky",
        "network",
        "provider",
        "destructive",
    ]:
        count = source.count(f"@pytest.mark.{marker_name}")
        if count > 0:
            markers[marker_name] = count
    return markers


def check_conftest() -> list[Finding]:
    findings: list[Finding] = []
    conftest_py = TESTS_DIR / "conftest.py"
    pycache_conftest = list((TESTS_DIR / "__pycache__").glob("conftest*.pyc"))

    if pycache_conftest and not conftest_py.exists():
        findings.append(
            Finding(
                severity="critical",
                rule_id="DETERM_CONFTEST_PYCACHE_ONLY",
                path=str(conftest_py.relative_to(REPO_ROOT)),
                line=None,
                message=f"__pycache__/conftest*.pyc exists ({len(pycache_conftest)} file(s)) "
                "but tests/conftest.py source is missing. "
                "Collection will fail on a clean clone.",
                suggested_fix="Restore tests/conftest.py from version control or regenerate from pycache source.",
                autofixable=False,
            )
        )

    conftest_imports = list(TESTS_DIR.rglob("*.py"))
    conftest_importer_count = 0
    for p in conftest_imports:
        if p.name == "__init__.py" or p.parent == TESTS_DIR / "__pycache__":
            continue
        try:
            content = p.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if "tests.conftest" in content or "from tests.conftest" in content:
            conftest_importer_count += 1

    if conftest_importer_count > 0 and not conftest_py.exists():
        findings.append(
            Finding(
                severity="critical",
                rule_id="DETERM_CONFTEST_IMPORTERS_NO_SOURCE",
                path="tests/conftest.py",
                line=None,
                message=f"{conftest_importer_count} test files import tests.conftest "
                "but tests/conftest.py does not exist.",
                suggested_fix="Restore tests/conftest.py source file.",
                autofixable=False,
            )
        )

    if conftest_py.exists() and pycache_conftest and conftest_importer_count == 0:
        findings.append(
            Finding(
                severity="info",
                rule_id="DETERM_CONFTEST_PYCACHE_STALE",
                path="tests/__pycache__",
                line=None,
                message="__pycache__/conftest*.pyc exists alongside source. "
                "Harmless but should be cleaned in CI.",
                suggested_fix="Add __pycache__ to .gitignore or clean in CI.",
                autofixable=True,
            )
        )

    return findings


def check_root_level_tests(test_files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for f in test_files:
        rel = str(f)
        if rel.startswith("tests/") and "/" not in rel[6:]:
            if rel in ROOT_LEVEL_ALLOWLIST:
                continue
            findings.append(
                Finding(
                    severity="medium",
                    rule_id="LAYOUT_ROOT_LEVEL",
                    path=rel,
                    line=None,
                    message=f"Root-level test file '{rel}' — should be moved to a domain subdirectory.",
                    suggested_fix="Move to appropriate tests/ subdirectory matching its source domain.",
                    autofixable=False,
                )
            )
    return findings


def check_mis_scoped_scripts(test_files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for f in test_files:
        rel = str(f)
        if not rel.startswith("tests/scripts/"):
            continue
        imports = extract_imports(f)
        matched_domain = None
        matched_prefix = ""
        for domain_prefix, test_dir in DOMAIN_TO_TEST_DIR.items():
            if domain_prefix == "scripts":
                continue
            for imp in imports:
                if imp == domain_prefix or imp.startswith(domain_prefix + "."):
                    matched_domain = test_dir
                    matched_prefix = domain_prefix
                    break
            if matched_domain:
                break
        if matched_domain:
            findings.append(
                Finding(
                    severity="medium",
                    rule_id="LAYOUT_MIS_SCOPED_SCRIPTS",
                    path=rel,
                    line=None,
                    message=f"Test in tests/scripts/ imports {matched_prefix} — "
                    f"should live in {matched_domain}/.",
                    suggested_fix=f"Move to {matched_domain}/ with an appropriate name.",
                    autofixable=False,
                )
            )
    return findings


def check_naming(test_files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for f in test_files:
        func_names = extract_function_names(f)
        for func_name in func_names:
            # Check for exact bad patterns or patterns like test_basic, test_works
            if func_name in BAD_NAME_PATTERNS:
                findings.append(
                    Finding(
                        severity="low",
                        rule_id="NAMING_VAGUE",
                        path=str(f),
                        line=None,
                        message=f"Test function '{func_name}' uses a vague name. "
                        "Rename to describe behavior/outcome.",
                        suggested_fix=f"Rename '{func_name}' to describe the behavior it protects.",
                        autofixable=False,
                    )
                )
    return findings


def check_duplicates(test_files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []

    for pair in KNOWN_DUPLICATE_PAIRS:
        p1 = REPO_ROOT / pair[0]
        p2 = REPO_ROOT / pair[1]
        if p1.exists() and p2.exists():
            findings.append(
                Finding(
                    severity="medium",
                    rule_id="DUPLICATE_KNOWN_PAIR",
                    path=pair[0],
                    line=None,
                    message=f"Known duplicate pair: {pair[0]} and {pair[1]}. "
                    "Review for merge or deduplication.",
                    suggested_fix=f"Review overlap between {pair[0]} and {pair[1]}; merge or delete redundant tests.",
                    autofixable=False,
                )
            )

    module_to_files: dict[str, list[str]] = {}
    for f in test_files:
        imports = extract_imports(f)
        for imp in imports:
            if imp.startswith("rig_relay.") and imp.count(".") >= _MIN_RIG_MODULE_DEPTH:
                module_to_files.setdefault(imp, []).append(str(f))

    for module, files in module_to_files.items():
        if len(files) > 1:
            findings.append(
                Finding(
                    severity="info",
                    rule_id="DUPLICATE_SAME_MODULE",
                    path=files[0],
                    line=None,
                    message=f"Module '{module}' imported by {len(files)} test files: {', '.join(files)}. "
                    "Review for overlapping coverage.",
                    suggested_fix="Review test coverage; merge overlapping assertions or split by concern.",
                    autofixable=False,
                )
            )

    func_name_to_files: dict[str, list[str]] = {}
    for f in test_files:
        for name in extract_function_names(f):
            func_name_to_files.setdefault(name, []).append(str(f))

    for name, files in func_name_to_files.items():
        if len(files) > 1:
            dirs = {str(Path(f).parent) for f in files}
            if len(dirs) > 1:
                findings.append(
                    Finding(
                        severity="low",
                        rule_id="DUPLICATE_SAME_NAME_CROSS_DIR",
                        path=files[0],
                        line=None,
                        message=f"Test function '{name}' appears in multiple directories: {', '.join(sorted(dirs))}. "
                        "Possible duplicate — verify.",
                        suggested_fix="Check whether these test the same behavior; remove or rename duplicates.",
                        autofixable=False,
                    )
                )

    return findings


def check_determinism_risks(test_files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for f in test_files:
        try:
            content = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(f)

        if "/Users/" in content:
            findings.append(
                Finding(
                    severity="high",
                    rule_id="DETERM_HARDCODED_PATH",
                    path=rel,
                    line=None,
                    message="File contains absolute /Users/ path — will fail on other machines.",
                    suggested_fix="Use tmp_path fixture or pathlib relative paths.",
                    autofixable=False,
                )
            )

        if "time.sleep(" in content:
            findings.append(
                Finding(
                    severity="low",
                    rule_id="DETERM_SLEEP",
                    path=rel,
                    line=None,
                    message="Uses time.sleep() — may cause flaky timing-dependent failures.",
                    suggested_fix="Use event-based waiting, pytest-timeout, or asyncio.sleep with controlled clocks.",
                    autofixable=False,
                )
            )

    return findings


def check_marker_coverage(test_files: list[Path]) -> dict:
    tier_counts: dict[str, int] = {}
    for f in test_files:
        markers = count_markers(f)
        for marker, count in markers.items():
            tier_counts[marker] = tier_counts.get(marker, 0) + count
    return tier_counts


def run_audit() -> tuple[list[Finding], dict]:
    test_files = collect_test_files()
    all_findings: list[Finding] = []

    all_findings.extend(check_conftest())
    all_findings.extend(check_root_level_tests(test_files))
    all_findings.extend(check_mis_scoped_scripts(test_files))
    all_findings.extend(check_naming(test_files))
    all_findings.extend(check_duplicates(test_files))
    all_findings.extend(check_determinism_risks(test_files))

    marker_coverage = check_marker_coverage(test_files)

    stats = {
        "total_test_files": len(test_files),
        "total_findings": len(all_findings),
        "by_severity": {
            sev: len([f for f in all_findings if f.severity == sev])
            for sev in ["critical", "high", "medium", "low", "info"]
        },
        "by_rule": {},
        "marker_coverage": marker_coverage,
        "conftest_exists": (TESTS_DIR / "conftest.py").exists(),
        "conftest_pycache_count": len(
            list((TESTS_DIR / "__pycache__").glob("conftest*.pyc"))
        )
        if (TESTS_DIR / "__pycache__").exists()
        else 0,
    }

    for f in all_findings:
        stats["by_rule"][f.rule_id] = stats["by_rule"].get(f.rule_id, 0) + 1

    return all_findings, stats


def write_outputs(findings: list[Finding], stats: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON report
    report = {
        "doctrine_version": "1.0.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo_root": str(REPO_ROOT),
        "stats": stats,
        "findings": [f.to_dict() for f in findings],
    }
    json_path = OUTPUT_DIR / "test_quality_report.json"
    json_path.write_text(json.dumps(report, indent=2) + "\n")

    # JSONL report
    jsonl_path = OUTPUT_DIR / "test_quality_report.jsonl"
    with jsonl_path.open("w") as fh:
        for finding in findings:
            fh.write(json.dumps(finding.to_dict()) + "\n")

    # Markdown summary
    md_path = OUTPUT_DIR / "test_quality_summary.md"
    lines: list[str] = [
        "# Test Quality Audit Summary",
        "",
        f"**Generated**: {report['generated_at']}",
        "**Doctrine**: docs/governance/test-suite-doctrine.md",
        "",
        "## Statistics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total test files | {stats['total_test_files']} |",
        f"| Total findings | {stats['total_findings']} |",
        f"| conftest.py exists | {stats['conftest_exists']} |",
        f"| __pycache__/conftest*.pyc | {stats['conftest_pycache_count']} |",
        "",
        "## Findings by Severity",
        "",
    ]
    for sev in ["critical", "high", "medium", "low", "info"]:
        count = stats["by_severity"].get(sev, 0)
        lines.append(f"- **{sev}**: {count}")

    lines.extend(["", "## Findings by Rule", ""])
    for rule, count in sorted(stats["by_rule"].items()):
        lines.append(f"- **{rule}**: {count}")

    lines.extend(["", "## Marker Coverage", "", "| Marker | Count |", "|---|---|"])
    for marker, count in sorted(stats["marker_coverage"].items()):
        lines.append(f"| {marker} | {count} |")
    if not stats["marker_coverage"]:
        lines.append("| *(none)* | 0 |")

    if stats["by_severity"].get("critical", 0) > 0:
        lines.extend(["", "## ⚠️ Critical Findings", ""])
        for f in findings:
            if f.severity == "critical":
                lines.append(f"- **{f.rule_id}**: {f.message}")

    lines.extend([
        "",
        "## Commands",
        "",
        "```bash",
        "# Smoke suite (fastest confidence)",
        "uv run pytest -m smoke",
        "",
        "# Default developer suite (no slow/legacy/flaky/network/provider/destructive)",
        'uv run pytest -m "not slow and not legacy and not flaky and not network and not provider and not destructive"',
        "",
        "# Full suite",
        "uv run pytest",
        "",
        "# Test quality audit",
        "uv run python scripts/rig_relay_test_quality_audit.py",
        "```",
        "",
    ])

    md_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    findings, stats = run_audit()
    write_outputs(findings, stats)

    print(
        f"Audit complete: {stats['total_findings']} findings across {stats['total_test_files']} test files"
    )
    for sev in ["critical", "high", "medium", "low", "info"]:
        count = stats["by_severity"].get(sev, 0)
        if count:
            print(f"  {sev}: {count}")

    if stats["by_severity"].get("critical", 0) > 0:
        print("\n⚠️ Critical findings detected!")
        return_code = 1
    else:
        return_code = 0

    sys.exit(return_code)


if __name__ == "__main__":
    main()
