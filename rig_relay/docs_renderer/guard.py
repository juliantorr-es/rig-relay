from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

ALLOWED_MARKDOWN = frozenset({
    "AGENTS.md",
    "README.md",
    "CONTRIBUTING.md",
    "CONTRIBUTOR_LICENSE_AGREEMENT.md",
    "LICENSE",
    "ATTRIBUTION.md",
    "UPSTREAM.md",
    "THIRD_PARTY_NOTICES.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
})

FORBIDDEN_MARKDOWN_DIRS = frozenset({
    "docs/audits/",
    "docs/reports/",
    "docs/roadmaps/",
    "docs/findings/out-of-scope-findings",
})

_NON_MARKDOWN_EXTENSIONS = frozenset({
    ".json",
    ".jsonl",
    ".csv",
    ".html",
    ".css",
    ".js",
    ".svg",
    ".png",
})


@dataclass
class MarkdownLeakReport:
    passed: bool
    blocked_paths: list[Path] = field(default_factory=list)
    allowed_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _norm_rel_path(p: Path) -> str:
    name = p.name
    parent = p.parent
    parts: list[str] = []
    seen: set[str] = set()
    for part in parent.parts:
        if part in seen or part == name:
            break
        seen.add(part)
        parts.append(part)
    parts.append(name)
    return "/".join(parts)


def check_input_path(path: Path | str) -> tuple[bool, str]:
    p = Path(path) if isinstance(path, str) else path

    if p.name.lower().endswith(".md"):
        rel = _norm_rel_path(p)
        parent_str = str(p.parent) + "/"

        if rel in ALLOWED_MARKDOWN:
            return True, "allowed_exception"

        for forbidden in FORBIDDEN_MARKDOWN_DIRS:
            if parent_str.startswith(forbidden):
                return False, "markdown_evidence_forbidden"
            if rel == forbidden + ".md":
                return False, "markdown_evidence_forbidden"

        return False, "unlisted_markdown"

    suffix = p.suffix.lower()
    if suffix in _NON_MARKDOWN_EXTENSIONS:
        return True, "non_markdown"

    return True, "unknown_format_allowed"


def check_input_manifest(manifest: dict) -> MarkdownLeakReport:
    report = MarkdownLeakReport(passed=True)

    for entry in manifest.get("inputs", []):
        source_path = entry.get("source_path")
        if not source_path:
            continue
        allowed, reason = check_input_path(source_path)
        sp = Path(source_path)
        if allowed:
            report.allowed_paths.append(sp)
        else:
            report.blocked_paths.append(sp)
            report.passed = False

    return report


def check_rendered_site(site_dir: Path) -> MarkdownLeakReport:
    report = MarkdownLeakReport(passed=True)

    for md_file in sorted(site_dir.rglob("*.md")):
        rel = md_file.relative_to(site_dir)
        rel_str = str(rel)
        for forbidden in FORBIDDEN_MARKDOWN_DIRS:
            if rel_str.startswith(forbidden) or rel_str == forbidden + ".md":
                report.blocked_paths.append(md_file)
                report.passed = False
                break

    _HREF_PATTERN = re.compile(r'href="([^"]*\.md)"', re.IGNORECASE)

    for html_file in sorted(site_dir.rglob("*.html")):
        try:
            content = html_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in _HREF_PATTERN.finditer(content):
            linked = m.group(1)
            if linked in ALLOWED_MARKDOWN:
                continue
            report.blocked_paths.append(html_file)
            report.passed = False

    return report
