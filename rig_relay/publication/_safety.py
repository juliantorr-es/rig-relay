from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import re

from rig_relay.publication._models import PublicationSafetyReport

_SECRET_PATTERNS: list[tuple[str, str]] = [
    ("github_pat", r"ghp_[A-Za-z0-9]{36}"),
    ("github_oauth", r"gho_[A-Za-z0-9]{36}"),
    ("github_user", r"ghu_[A-Za-z0-9]{36}"),
    ("github_server", r"ghs_[A-Za-z0-9]{36}"),
    ("github_refresh", r"ghr_[A-Za-z0-9]{36}"),
    ("github_classic", r"github_pat_[A-Za-z0-9]{22,}"),
    ("openai_key", r"sk-(?:proj-)?[A-Za-z0-9]{32,}"),
    ("anthropic_key", r"sk-ant-[A-Za-z0-9]{32,}"),
    ("google_api", r"AIza[0-9A-Za-z\-_]{35}"),
    ("generic_api_key", r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9\-_]{20,}"),
    ("mistral_key", r"[A-Za-z0-9]{32,}"),
]

_RAW_PATH_PATTERN = re.compile(r"^(/[Uu]sers/|/[Hh]ome/|[A-Z]:\\)")

_FORBIDDEN_FIELD_NAMES: frozenset[str] = frozenset({
    "raw_prompt",
    "raw_completion",
    "raw_file_contents",
    "private_repo_contents",
    "access_token",
    "refresh_token",
    "api_key",
    "api_secret",
    "private_key",
    "oauth_code",
})

_PRIVACY_DISPOSITION_SAFE: frozenset[str] = frozenset({"public_safe", "redacted"})
_PRIVACY_DISPOSITION_FORBIDDEN: frozenset[str] = frozenset({
    "internal_only",
    "withheld",
})

_VALID_APPROVAL_STATUSES: frozenset[str] = frozenset({
    "proposed",
    "pending_review",
    "approved",
    "rejected",
    "superseded",
})

_DEPLOYMENT_OVERCLAIM_PATTERNS: list[str] = [
    "deploy to production",
    "published to pages",
    "live at https://",
    "deployed successfully",
    "auto-deploy",
    "CI/CD pipeline deployed",
    "publication complete",
]


def scan_text_for_secrets(text: str) -> list[str]:
    found: list[str] = []
    for label, pattern in _SECRET_PATTERNS:
        if re.search(pattern, text):
            found.append(label)
    return found


def scan_for_raw_paths(text: str) -> bool:
    return bool(_RAW_PATH_PATTERN.search(text))


def scan_dict_for_forbidden_fields(data: dict, prefix: str = "") -> list[str]:
    found: list[str] = []
    if not isinstance(data, dict):
        return found
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if key.lower() in _FORBIDDEN_FIELD_NAMES:
            found.append(path)
        if isinstance(value, dict):
            found.extend(scan_dict_for_forbidden_fields(value, path))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    found.extend(scan_dict_for_forbidden_fields(item, f"{path}[{i}]"))
    return found


def scan_text_for_private_disposition(content: str) -> bool:
    lowered = content.lower()
    for forbidden in _PRIVACY_DISPOSITION_FORBIDDEN:
        if forbidden in lowered:
            return True
    return False


def scan_for_deployment_overclaims(text: str) -> list[str]:
    """Detect language that falsely claims deployment has occurred."""
    found: list[str] = []
    lowered = text.lower()
    for pattern in _DEPLOYMENT_OVERCLAIM_PATTERNS:
        if pattern in lowered:
            found.append(pattern)
    return found


def validate_narrative_approval(narrative_key: str, approval_status: str) -> bool:
    if approval_status not in _VALID_APPROVAL_STATUSES:
        return False
    return True


def hash_content(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def scan_project_page_output(
    html_content: str, projection: dict, preview_report: dict
) -> PublicationSafetyReport:
    """Run comprehensive safety scan on compiled project page output.

    Checks:
    1. No secrets/tokens in HTML output
    2. No raw paths in HTML output
    3. No forbidden field names in projection
    4. No private dispositions in public projection
    5. Generated narrative sections not falsely marked approved
    6. Content-light guarantee preserved (no raw evidence in projection)
    7. No deployment overclaims in preview output
    """
    now = datetime.now(UTC).isoformat()
    scan_id = hash_content(f"scan:{now}")[:22]
    warnings: list[str] = []
    forbidden: list[str] = []
    secrets_detected = False
    raw_paths_detected = False
    private_content_detected = False
    proposed_as_approved = False

    secrets_found = scan_text_for_secrets(html_content)
    if secrets_found:
        secrets_detected = True
        for label in secrets_found:
            forbidden.append(f"secret_pattern:{label}")

    if scan_for_raw_paths(html_content):
        raw_paths_detected = True
        forbidden.append("raw_paths_in_html")

    forbidden_fields = scan_dict_for_forbidden_fields(projection)
    if forbidden_fields:
        private_content_detected = True
        for field_path in forbidden_fields:
            forbidden.append(f"forbidden_field:{field_path}")

    if "privacy_class" in projection:
        if projection["privacy_class"] in _PRIVACY_DISPOSITION_FORBIDDEN:
            private_content_detected = True
            forbidden.append("privacy_class_not_public_safe")

    generated_sections = projection.get("generated_narrative_sections", {})
    if isinstance(generated_sections, dict):
        for section_key, section_data in generated_sections.items():
            status = section_data.get("approval_status", "proposed")
            if status == "approved":
                if section_data.get("narrative", ""):
                    proposed_as_approved = True
                    forbidden.append(f"proposed_marked_approved:{section_key}")

    narrative_approvals = preview_report.get("proposed_content", {}).get("sections", [])
    for section in narrative_approvals:
        if (
            section.get("approval_status") == "approved"
            and section.get("source") == "generated"
        ):
            proposed_as_approved = True
            forbidden.append(
                f"generated_section_approved:{section.get('section_key', 'unknown')}"
            )

    deployment_claims = scan_for_deployment_overclaims(html_content)
    if deployment_claims:
        for claim in deployment_claims:
            forbidden.append(f"deployment_overclaim:{claim}")

    total_checked = len(html_content.splitlines()) + len(projection) + 5

    if forbidden:
        warnings.append(f"Safety scan found {len(forbidden)} issues")

    passed = not forbidden

    return PublicationSafetyReport(
        passed=passed,
        scan_id=scan_id,
        scanned_at=now,
        total_fields_checked=total_checked,
        forbidden_content_found=forbidden,
        secrets_detected=secrets_detected,
        raw_paths_detected=raw_paths_detected,
        private_content_detected=private_content_detected,
        proposed_marked_as_approved=proposed_as_approved,
        warnings=warnings,
    )


def validate_publication_policy(policy: str) -> bool:
    """Validate that the publication policy is recognized and safe."""
    valid_policies = {"preview_only", "developer_approved", "public_release"}
    return policy in valid_policies


def redact_unsafe_text(text: str) -> str:
    """Strip known secret patterns from text for safety. Returns cleaned text."""
    for _, pattern in _SECRET_PATTERNS:
        text = re.sub(pattern, "[REDACTED]", text)
    return text
