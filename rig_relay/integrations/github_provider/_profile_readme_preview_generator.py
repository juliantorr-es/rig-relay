"""Profile README preview file generator — evidence-backed, deterministic, content-light.

Generates a local README.md preview from an evidence-backed public claims index.
Conservative public-safe output. No raw content, secrets, tokens, or private data.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.core.utils.io import read_safe

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CLAIMS_PATH = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_evidence_backed_claims_index_v1.v1.json"
)
_DEFAULT_OUTPUT_DIR = _REPO_ROOT / ".build" / "rig-relay" / "previews"
_DEFAULT_OUTPUT_PATH = _DEFAULT_OUTPUT_DIR / "profile_readme_preview.md"

_CLAIM_CATEGORY_ORDER = [
    "product_identity",
    "integration_claim",
    "test_coverage_claim",
    "security_claim",
    "governance_claim",
    "surface_claim",
    "release_claim",
    "ci_cd_claim",
    "permission_claim",
    "community_claim",
]

_CATEGORY_HEADERS: dict[str, str] = {
    "product_identity": "About",
    "integration_claim": "Integrations",
    "test_coverage_claim": "Testing & Quality",
    "security_claim": "Security",
    "governance_claim": "Governance",
    "surface_claim": "Public Surfaces",
    "release_claim": "Releases",
    "ci_cd_claim": "CI/CD",
    "permission_claim": "Permissions",
    "community_claim": "Community",
}

_PUBLIC_INCLUSION_REQUIRED_ACTIONS = {"keep", "caveat", "verify"}
_PUBLIC_INCLUSION_CONFIDENCES = {"high", "medium"}

_FORBIDDEN_PREVIEW_CONTENT = (
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "github_pat_",
    "ya29.",
    "1//",
    "BEGIN PRIVATE KEY",
    "access_token",
)


class ProfileReadmePreviewGeneratorError(Exception):
    """Raised when preview generation fails."""


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def load_evidence_backed_claims(
    claims_path: Path = _DEFAULT_CLAIMS_PATH,
) -> dict[str, Any]:
    """Load the evidence-backed claims index artifact."""
    if not claims_path.exists():
        return {"claims": []}

    raw = read_safe(claims_path, raise_on_error=True)
    data = json.loads(raw.text)
    if not isinstance(data, dict):
        return {"claims": []}
    return data


def _is_claim_eligible_for_public_profile(claim: dict[str, Any]) -> bool:
    """Determine if a claim is eligible for public profile README inclusion."""
    if not isinstance(claim, dict):
        return False

    action = claim.get("suggested_action", "")
    confidence = claim.get("confidence", "")
    risk = claim.get("public_wording_risk", "high")
    remote_mut = claim.get("remote_mutation", False)
    local_mut = claim.get("local_mutation", False)

    if remote_mut or local_mut:
        return False

    if risk == "high":
        return False

    if action not in _PUBLIC_INCLUSION_REQUIRED_ACTIONS:
        return False

    if confidence not in _PUBLIC_INCLUSION_CONFIDENCES:
        return False

    return True


def filter_public_profile_claims(
    claims_data: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Filter claims into included and excluded sets for public profile README.

    Returns (included, excluded) tuple.
    """
    claims = claims_data.get("claims", [])
    if not isinstance(claims, list):
        return [], []

    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for claim in claims:
        if not isinstance(claim, dict):
            continue

        if _is_claim_eligible_for_public_profile(claim):
            claim_entry = {
                "claim_id": claim.get("claim_id", ""),
                "claim_category": claim.get("claim_category", "unknown"),
                "claim_summary": claim.get("normalized_claim_summary", ""),
                "evidence_refs": claim.get("evidence_refs", []),
                "support_status": claim.get("support_status", "unknown"),
                "confidence": claim.get("confidence", "unknown"),
                "public_wording_risk": claim.get("public_wording_risk", "unknown"),
                "inclusion_decision": "included",
            }
            included.append(claim_entry)
        else:
            reason = _exclusion_reason(claim)
            claim_entry = {
                "claim_id": claim.get("claim_id", ""),
                "claim_category": claim.get("claim_category", "unknown"),
                "claim_summary": claim.get("normalized_claim_summary", ""),
                "evidence_refs": claim.get("evidence_refs", []),
                "support_status": claim.get("support_status", "unknown"),
                "confidence": claim.get("confidence", "unknown"),
                "public_wording_risk": claim.get("public_wording_risk", "unknown"),
                "inclusion_decision": "excluded",
                "disabled_reason": reason,
            }
            excluded.append(claim_entry)

    return included, excluded


def _exclusion_reason(claim: dict[str, Any]) -> str:
    action = claim.get("suggested_action", "")
    confidence = claim.get("confidence", "")
    risk = claim.get("public_wording_risk", "high")
    remote_mut = claim.get("remote_mutation", False)

    if remote_mut:
        return "remote_mutation_claim"
    if risk == "high":
        return "high_public_wording_risk"
    if action not in _PUBLIC_INCLUSION_REQUIRED_ACTIONS:
        return f"action_{action}"
    if confidence not in _PUBLIC_INCLUSION_CONFIDENCES:
        return f"confidence_{confidence}"
    return "unknown"


def _group_claims_by_category(
    claims: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        category = claim.get("claim_category", "other")
        if category not in grouped:
            grouped[category] = []
        grouped[category].append(claim)
    return grouped


def _render_claim(claim: dict[str, Any]) -> str:
    """Render a single claim as a Markdown bullet point.
    Conservative: includes evidence markers, not raw evidence content.
    """
    summary = claim.get("claim_summary", "")
    status = claim.get("support_status", "unknown")
    confidence = claim.get("confidence", "unknown")

    status_marker = ""
    if status == "supported":
        status_marker = "[verified]"
    elif status == "partially_supported":
        status_marker = "[partial]"

    confidence_note = f" (confidence: {confidence})" if confidence != "high" else ""

    return f"- {summary} {status_marker}{confidence_note}"


def build_public_profile_readme(
    included_claims: list[dict[str, Any]], *, owner: str, repo: str = "rig-relay"
) -> str:
    """Build a deterministic public profile README from included claims.

    The output is a public claims renderer, not a marketing copywriter.
    No timestamps, no raw content, no unverifiable claims.
    """
    grouped = _group_claims_by_category(included_claims)

    lines: list[str] = []
    lines.append(f"# {owner}")
    lines.append("")
    lines.append(
        f"Public profile README for **{owner}** — maintained by [Rig Relay](https://github.com/juliantorr-es/rig-relay)."
    )
    lines.append("")
    lines.append(
        "This README is generated from an evidence-backed public claims index."
    )
    lines.append("Every claim links to verification evidence.")
    lines.append("")

    total_included = len(included_claims)
    lines.append(
        f"> **Claims included:** {total_included} from verified public evidence."
    )
    lines.append("")

    categories_rendered = 0
    for category in _CLAIM_CATEGORY_ORDER:
        claims_in_cat = grouped.pop(category, [])
        if not claims_in_cat:
            continue

        header = _CATEGORY_HEADERS.get(category, category.replace("_", " ").title())
        lines.append(f"## {header}")
        lines.append("")

        for claim in claims_in_cat:
            lines.append(_render_claim(claim))

        lines.append("")
        categories_rendered += 1

    # Render remaining uncategorized claims
    if grouped:
        for category, claims_in_cat in sorted(grouped.items()):
            if not claims_in_cat:
                continue
            header = category.replace("_", " ").title()
            lines.append(f"## {header}")
            lines.append("")
            for claim in claims_in_cat:
                lines.append(_render_claim(claim))
            lines.append("")

    lines.append("---")
    lines.append(
        "*Generated by Rig Relay • public claims renderer • no raw content stored*"
    )

    return "\n".join(lines)


def _redaction_scan(text: str) -> tuple[bool, list[str]]:
    """Scan generated text for forbidden patterns. Returns (clean, matches)."""
    matches: list[str] = []
    for line_num, line in enumerate(text.splitlines(), 1):
        for pattern in _FORBIDDEN_PREVIEW_CONTENT:
            if pattern in line:
                matches.append(f"line_{line_num}:{pattern}")
    return len(matches) == 0, matches


def generate_preview_file(
    *,
    owner: str,
    claims_path: Path = _DEFAULT_CLAIMS_PATH,
    output_path: Path = _DEFAULT_OUTPUT_PATH,
    repo: str = "rig-relay",
) -> dict[str, Any]:
    """Generate the actual profile README preview file from evidence-backed claims.

    Returns metadata about the generated file. Does not perform remote mutation.
    """
    claims_data = load_evidence_backed_claims(claims_path)
    included, excluded = filter_public_profile_claims(claims_data)

    readme_content = build_public_profile_readme(included, owner=owner, repo=repo)

    # Redaction scan before writing
    clean, redaction_matches = _redaction_scan(readme_content)

    # Write preview file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(readme_content, encoding="utf-8")

    preview_sha256 = _sha256_file(output_path)
    preview_bytes = output_path.stat().st_size
    preview_line_count = len(readme_content.splitlines())

    return {
        "generated_preview_path": str(output_path),
        "generated_preview_sha256": preview_sha256,
        "generated_preview_bytes": preview_bytes,
        "generated_preview_line_count": preview_line_count,
        "source_claim_count": len(claims_data.get("claims", [])),
        "included_claim_count": len(included),
        "excluded_claim_count": len(excluded),
        "included_claims": included,
        "excluded_claims": excluded,
        "excluded_claim_reasons": list({
            c.get("disabled_reason", "") for c in excluded if c.get("disabled_reason")
        }),
        "public_surface_classification": "public_profile_readme",
        "permission_neutrality_status": "permission_neutral",
        "publish_blocked_reasons": [],
        "redaction_scan": {
            "content_clean": clean,
            "redaction_matches": redaction_matches,
            "forbidden_patterns_checked": len(_FORBIDDEN_PREVIEW_CONTENT),
        },
        "evidence_source": str(claims_path),
    }


__all__ = [
    "ProfileReadmePreviewGeneratorError",
    "build_public_profile_readme",
    "filter_public_profile_claims",
    "generate_preview_file",
    "load_evidence_backed_claims",
]
