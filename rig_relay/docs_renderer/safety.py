from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import cast

TOKEN_PATTERNS: list[tuple[str, str, str]] = [
    ("OpenAI API key", r"\bsk-[A-Za-z0-9-_]{20,}\b", "block"),
    ("Google API key", r"\bAIza[SY][A-Za-z0-9\-_]{35,}\b", "block"),
    ("GitHub PAT", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", "block"),
    ("Slack bot token", r"\bxox[bpras]-[A-Za-z0-9\-]{10,}\b", "block"),
    (
        "JWT token",
        r"\beyJ[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{10,}\b",
        "block",
    ),
    (
        "PEM private key",
        r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----[\s\S]*?-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----",
        "block",
    ),
    ("OAuth code", r"\b[A-Za-z0-9\-_]{40,}\b", "warn"),
    ("Generic hex > 64 chars", r"\b[0-9a-fA-F]{64,}\b", "warn"),
    ("Home directory path", r"(?:/home/\w+|/Users/\w+|C:\\Users\\\w+)", "block"),
    ("AWS access key", r"\bAKIA[0-9A-Z]{16}\b", "block"),
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
class SafetyReport:
    passed: bool
    blocked: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
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


def scan_content(text: str, source: str) -> SafetyReport:
    blocked: list[dict] = []
    warnings: list[dict] = []
    passed = True

    for name, pattern, severity in TOKEN_PATTERNS:
        regex = re.compile(pattern)
        for match in regex.finditer(text):
            if name == "OAuth code" and not _oauth_proximity_pass(
                text, match.start(), match.end()
            ):
                continue
            entry = {
                "source": source,
                "pattern_name": name,
                "match_preview": _match_preview(match.group()),
                "line": _line_number(text, match.start()),
            }
            if severity == "block":
                blocked.append(entry)
                passed = False
            else:
                warnings.append(entry)

    return SafetyReport(
        passed=passed,
        blocked=blocked,
        warnings=warnings,
        file_count=1,
        total_matches=len(blocked) + len(warnings),
    )


def scan_rendered_site(site_dir: Path) -> SafetyReport:
    aggregated = SafetyReport(passed=True)
    html_files = sorted(site_dir.rglob("*.html"))
    aggregated.file_count = len(html_files)

    for html_file in html_files:
        text = html_file.read_text(encoding="utf-8")
        source = str(html_file.relative_to(site_dir))
        report = scan_content(text, source)
        aggregated.blocked.extend(report.blocked)
        aggregated.warnings.extend(report.warnings)
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

    return cast(dict, _walk(data, 0, set()))


def is_public_safe(report: SafetyReport) -> bool:
    return report.passed and len(report.blocked) == 0
