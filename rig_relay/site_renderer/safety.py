from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

TOKEN_PATTERNS: list[tuple[str, str, str]] = [
    ("openai_key", r"\bsk-[A-Za-z0-9-_]{20,}\b", "block"),
    ("google_key", r"\bAIza[SY][A-Za-z0-9\-_]{35,}\b", "block"),
    ("github_pat", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", "block"),
    ("slack_token", r"\bxox[bpras]-[A-Za-z0-9\-]{10,}\b", "block"),
    (
        "jwt_token",
        r"\beyJ[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{10,}\b",
        "block",
    ),
    (
        "pem_key",
        r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----[\s\S]*?-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----",
        "block",
    ),
    ("aws_key", r"\bAKIA[0-9A-Z]{16}\b", "block"),
    ("home_dir", r"(?:/home/\w+|/Users/\w+|C:\\Users\\\w+)", "block"),
    ("hex_64", r"\b[0-9a-fA-F]{64,}\b", "warn"),
    ("oauth_code", r"\b[A-Za-z0-9\-_]{40,}\b", "warn"),
]

REDACT_KEY_PATTERNS: list[str] = [
    r"token",
    r"secret",
    r"password",
    r"credential",
    r"api_key",
    r"private_key",
    r"access_key",
    r"auth_token",
    r"bearer",
    r"oauth_code",
]

_OAUTH_CONTEXT_WINDOW = 200


@dataclass
class SafetyFinding:
    source: str
    pattern_name: str
    severity: str
    match_preview: str
    line: int = 0


@dataclass
class SafetyReport:
    passed: bool = True
    findings: list[SafetyFinding] = field(default_factory=list)
    file_count: int = 0
    total_matches: int = 0


def _line_number(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


def _match_preview(match_text: str, max_chars: int = 20) -> str:
    if len(match_text) <= max_chars:
        return match_text
    return match_text[:max_chars] + "..."


def _oauth_proximity_pass(text: str, start: int, end: int) -> bool:
    ctx_start = max(0, start - _OAUTH_CONTEXT_WINDOW)
    ctx_end = min(len(text), end + _OAUTH_CONTEXT_WINDOW)
    ctx = text[ctx_start:ctx_end]
    return bool(re.search(r"\bcode\b", ctx, re.IGNORECASE)) or bool(
        re.search(r"\boauth\b", ctx, re.IGNORECASE)
    )


def scan_content(text: str, source: str = "") -> SafetyReport:
    findings: list[SafetyFinding] = []
    passed = True

    for name, pattern, severity in TOKEN_PATTERNS:
        regex = re.compile(pattern)
        for match in regex.finditer(text):
            if name == "oauth_code" and not _oauth_proximity_pass(
                text, match.start(), match.end()
            ):
                continue
            findings.append(
                SafetyFinding(
                    source=source,
                    pattern_name=name,
                    severity=severity,
                    match_preview=_match_preview(match.group()),
                    line=_line_number(text, match.start()),
                )
            )
            if severity == "block":
                passed = False

    return SafetyReport(
        passed=passed,
        findings=findings,
        file_count=1 if source else 0,
        total_matches=len(findings),
    )


def scan_rendered_site(site_dir: Path) -> SafetyReport:
    aggregated = SafetyReport(passed=True)
    html_files = sorted(site_dir.rglob("*.html"))
    aggregated.file_count = len(html_files)

    for html_file in html_files:
        text = html_file.read_text(encoding="utf-8")
        source = str(html_file.relative_to(site_dir))
        report = scan_content(text, source)
        aggregated.findings.extend(report.findings)
        if not report.passed:
            aggregated.passed = False
        aggregated.total_matches += report.total_matches

    return aggregated


def redact_from_dict(data: dict, max_depth: int = 10) -> dict:
    compiled = [re.compile(p, re.IGNORECASE) for p in REDACT_KEY_PATTERNS]

    def _walk(obj: object, depth: int, seen: set[int]) -> object:
        if depth > max_depth:
            return "[MAX_DEPTH]"
        oid = id(obj)
        if oid in seen:
            return "[CIRCULAR]"
        if isinstance(obj, dict):
            seen.add(oid)
            result: dict[str, object] = {}
            for k, v in obj.items():
                if any(p.fullmatch(str(k)) for p in compiled):
                    result[k] = "[REDACTED]"
                else:
                    result[k] = _walk(v, depth + 1, seen)
            seen.discard(oid)
            return result
        if isinstance(obj, list):
            seen.add(oid)
            lst = [_walk(item, depth + 1, seen) for item in obj]
            seen.discard(oid)
            return lst
        return obj

    result = _walk(data, 0, set())
    if isinstance(result, dict):
        return result
    return {}


def is_public_safe(report: SafetyReport) -> bool:
    if not report.passed:
        return False
    return not any(f.severity == "block" for f in report.findings)
