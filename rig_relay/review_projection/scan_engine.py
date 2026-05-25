from __future__ import annotations

import re


class ScanFinding:
    """Content-light finding — describes what was found without reproducing it."""

    __slots__ = ("category", "severity", "description")

    def __init__(self, category: str, severity: str, description: str) -> None:
        self.category = category
        self.severity = severity
        self.description = description


# ---------------------------------------------------------------------------
# Pre-scan patterns — content-blocking rules
# ---------------------------------------------------------------------------

_PRE_SCAN_SECRET_PATTERNS: list[tuple[str, str, str]] = [
    # (regex pattern, category, description)
    (r"sk-[A-Za-z0-9_]{30,}", "api_key", "OpenAI-style API key pattern"),
    (r"sk-ant-[A-Za-z0-9_]{30,}", "api_key", "Anthropic API key pattern"),
    (r"ghp_[A-Za-z0-9_]{30,}", "github_token", "GitHub personal access token"),
    (r"gho_[A-Za-z0-9_]{30,}", "github_token", "GitHub OAuth token"),
    (r"ghu_[A-Za-z0-9_]{30,}", "github_token", "GitHub user token"),
    (r"ghs_[A-Za-z0-9_]{30,}", "github_token", "GitHub server token"),
    (r"ghr_[A-Za-z0-9_]{30,}", "github_token", "GitHub refresh token"),
    (
        r"(?i)-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        "private_key",
        "Private key material",
    ),
    (r"(?i)-----BEGIN CERTIFICATE-----", "certificate", "Certificate material"),
    (
        r"(?i)client_secret\s*[:=]\s*['\"][^'\"]{8,}['\"]",
        "credential",
        "Client secret assignment",
    ),
    (r"(?i)password\s*[:=]\s*['\"][^'\"]{3,}['\"]", "credential", "Hardcoded password"),
    (r"(?i)api_key\s*[:=]\s*['\"][^'\"]{8,}['\"]", "credential", "Hardcoded API key"),
    (
        r"(?i)access_key\s*[:=]\s*['\"][^'\"]{8,}['\"]",
        "credential",
        "Hardcoded access key",
    ),
    (
        r"(?i)secret_key\s*[:=]\s*['\"][^'\"]{8,}['\"]",
        "credential",
        "Hardcoded secret key",
    ),
    (
        r"(?i)token\s*[:=]\s*['\"][A-Za-z0-9_\-.]{20,}['\"]",
        "credential",
        "Bearer token assignment",
    ),
    (
        r"(?i)mongodb(\+srv)?://[^'\"]{3,}",
        "connection_string",
        "Database connection string",
    ),
    (
        r"(?i)postgres(ql)?://[^'\"]{3,}",
        "connection_string",
        "Database connection string",
    ),
    (r"(?i)mysql://[^'\"]{3,}", "connection_string", "Database connection string"),
    (r"(?i)redis://[^'\"]{3,}", "connection_string", "Database connection string"),
]

_PRE_SCAN_PATH_PATTERNS: list[tuple[str, str, str]] = [
    (r"/home/\w+", "user_path", "Absolute home directory path"),
    (r"/Users/\w+", "user_path", "Absolute macOS user path"),
    (r"C:\\Users\\\w+", "user_path", "Absolute Windows user path"),
]

_PRE_SCAN_CONFIDENTIAL_TERM_PATTERNS: list[tuple[str, str, str]] = [
    (
        r"(?i)\bproprietary\s+algorithm\b",
        "confidential_term",
        "Proprietary algorithm description",
    ),
    (r"(?i)\binternal\s+only\b", "confidential_term", "Internal-only marker"),
    (
        r"(?i)\bconfidential\s+do\s+not\s+share\b",
        "confidential_term",
        "Confidentiality directive",
    ),
]


class ProjectionScanner:
    """Pre-transform gate and post-transform verification scanner."""

    def __init__(
        self, repo_root_str: str = "", confidential_terms: list[str] | None = None
    ) -> None:
        self._repo_root_str = repo_root_str
        self._extra_confidential_terms = confidential_terms or []

    # ------------------------------------------------------------------
    # Pre-scan: content-blocking gate
    # ------------------------------------------------------------------

    def pre_scan(self, content: str, rel_path: str) -> list[ScanFinding]:
        """Check whether content should enter the projection pipeline.

        Returns findings list. Any SECRET or CREDENTIAL finding means REFUSE.
        """
        findings: list[ScanFinding] = []

        # 1. Secret/credential detection
        for pattern, category, desc in _PRE_SCAN_SECRET_PATTERNS:
            if re.search(pattern, content):
                findings.append(ScanFinding(category, "block", desc))

        # 2. Absolute user paths
        for pattern, category, desc in _PRE_SCAN_PATH_PATTERNS:
            if re.search(pattern, content):
                findings.append(ScanFinding(category, "block", desc))

        # 3. Configured confidential terms
        for pattern, category, desc in _PRE_SCAN_CONFIDENTIAL_TERM_PATTERNS:
            if re.search(pattern, content):
                findings.append(ScanFinding(category, "block", desc))

        # 4. Custom confidential terms from policy
        for term in self._extra_confidential_terms:
            if term in content:
                findings.append(
                    ScanFinding(
                        "confidential_term",
                        "block",
                        f"Configured confidential term: {term[:40]}",
                    )
                )

        # 5. Local absolute path check
        if self._repo_root_str and self._repo_root_str in content:
            findings.append(
                ScanFinding(
                    "local_path",
                    "block",
                    "Projected content contains absolute repo root path",
                )
            )

        return findings

    def should_refuse(self, findings: list[ScanFinding]) -> bool:
        """Any block-severity finding means refuse the projection."""
        return any(f.severity == "block" for f in findings)

    # ------------------------------------------------------------------
    # Post-scan: residual disclosure check
    # ------------------------------------------------------------------

    def post_scan(
        self, content: str, original_symbols: set[str], ledger_mapping: dict[str, str]
    ) -> list[ScanFinding]:
        """Check transformed content for residual disclosure."""
        findings: list[ScanFinding] = []

        # 1. Re-check secret patterns (transformation could reintroduce them)
        for pattern, category, desc in _PRE_SCAN_SECRET_PATTERNS:
            if re.search(pattern, content):
                findings.append(
                    ScanFinding(category, "block", f"Residual {desc} after projection")
                )

        # 2. Absolute path check
        if self._repo_root_str and self._repo_root_str in content:
            findings.append(
                ScanFinding(
                    "local_path",
                    "block",
                    "Residual absolute repo root path after projection",
                )
            )

        # 3. Original symbol leakage — check if any original symbols survived
        pseudonyms = set(ledger_mapping.values())
        for sym in sorted(original_symbols, key=len, reverse=True):
            if len(sym) < 5:
                continue  # skip short symbols to avoid false positives
            if sym in pseudonyms:
                continue
            if re.search(r"\b" + re.escape(sym) + r"\b", content):
                findings.append(
                    ScanFinding(
                        "semantic_leak",
                        "warn",
                        "Original symbol may have survived pseudonymization",
                    )
                )
                break  # One finding is enough to flag the issue

        return findings
