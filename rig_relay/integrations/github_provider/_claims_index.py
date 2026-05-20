from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_OUTPUT_PATH = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_evidence_backed_claims_index_v1.v1.json"
)
_OPERATING_PICTURE_PATH = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_operating_picture_v1.v1.json"
)
_SURFACE_AUDIT_PATH = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_surface_audit_v1.v1.json"
)

_VALIDATION_COMMANDS = [
    "uv run python scripts/rig_relay_validate_schemas.py",
    "uv run pytest tests/integrations/test_github_claims_index.py -v",
    "uv run pytest tests/adversarial/test_github_claims_index_redaction.py -v",
    "uv run pytest tests/governance/test_github_claims_index_artifact.py -v",
]

_CI_CHECKS_THRESHOLD = 5


class GitHubClaimsIndexError(Exception):
    """Raised when claims index build fails."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else str(value) if value is not None else ""


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _as_bool(value: object) -> bool:
    return bool(value) if value is not None else False


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _read_json(path: Path) -> dict | None:
    try:
        result = read_safe(path)
        return json.loads(result.text)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def _read_readme(root: Path) -> str:
    readme_path = root / "README.md"
    if not readme_path.exists():
        readme_path = root / "readme.md"
    if readme_path.exists():
        result = read_safe(readme_path)
        return result.text
    return ""


_README_CLAIM_PATTERNS: list[tuple[str, str, str, str]] = [
    (
        "Python 3.12",
        "platform_support_claim",
        "README.md#badge-status-block",
        "Requires Python 3.12+ runtime",
    ),
    (
        "python-3.12",
        "platform_support_claim",
        "README.md#badge-status-block",
        "Requires Python 3.12+ runtime",
    ),
    (
        "Quick Start",
        "installation_claim",
        "README.md#quick-start",
        "Clone and uv sync provides a working installation",
    ),
    (
        "uv tool install",
        "installation_claim",
        "README.md#quick-start",
        "Installable via uv tool install from git",
    ),
    (
        "governed local server/control-plane",
        "functionality_claim",
        "README.md#header",
        "Provides a governed local server/control-plane with desktop cockpit",
    ),
    (
        "receipt-backed evidence",
        "governance_claim",
        "README.md#features",
        "Every tool call, checkpoint, and consultation produces a receipt",
    ),
    (
        "worktree isolation",
        "security_claim",
        "README.md#features",
        "Agents operate in git worktrees under .rig/relay/worktrees",
    ),
    (
        "multi-provider consultation",
        "functionality_claim",
        "README.md#features",
        "Multi-provider adversarial review (Council) with structured opinions",
    ),
    (
        "Council",
        "functionality_claim",
        "README.md#features",
        "Multi-provider adversarial review (Council) with structured opinions",
    ),
    (
        "Fleet orchestration",
        "functionality_claim",
        "README.md#features",
        "Fleet orchestration for roadmap planning, sprint scoping, mission tasking",
    ),
    (
        "MCP tools for Antigravity",
        "integration_claim",
        "README.md#protocol-surfaces",
        "Exposes MCP server with 16 governed tools across 5 tiers",
    ),
    (
        "MCP Server",
        "integration_claim",
        "README.md#protocol-surfaces",
        "Exposes MCP server with 16 governed tools across 5 tiers",
    ),
    (
        "Speaks ACP",
        "integration_claim",
        "README.md#protocol-surfaces",
        "Speaks Agent Client Protocol for editor-integrated agent sessions",
    ),
    (
        "dry-run mode",
        "functionality_claim",
        "README.md#quick-start",
        "Starts in dry-run mode without API key, full projection available",
    ),
    (
        "Provider onboarding",
        "integration_claim",
        "README.md#features",
        "Interactive provider onboarding for DeepSeek, OpenAI, Anthropic, Google, Mistral, OpenRouter",
    ),
    (
        "onboarding wizard",
        "integration_claim",
        "README.md#features",
        "Interactive provider onboarding for DeepSeek, OpenAI, Anthropic, Google, Mistral, OpenRouter",
    ),
    (
        "Release Readiness",
        "release_readiness_claim",
        "README.md#release-readiness",
        "Release readiness validation scripts available",
    ),
    (
        "Release Candidate Status",
        "release_readiness_claim",
        "README.md#release-candidate-status",
        "Release candidate in alpha (v0.1.0a1), gate is HOLD",
    ),
    (
        "bounded autonomy",
        "governance_claim",
        "README.md#safety-story",
        "Communicates bounded autonomy with four-tier safety scope",
    ),
    (
        "OWASP agent security",
        "security_claim",
        "README.md#safety-story",
        "Safety gates align with OWASP agent security best practices",
    ),
    (
        "Frontend is a dumb renderer",
        "security_claim",
        "README.md#safety-story",
        "Frontend is a dumb renderer; backend owns all policy transitions",
    ),
    (
        "uv run pyright",
        "test_coverage_claim",
        "README.md#development",
        "Strict type checking via pyright",
    ),
    (
        "uv run ruff",
        "test_coverage_claim",
        "README.md#development",
        "Linting and formatting via ruff",
    ),
    (
        "AGPL-3.0-or-later",
        "documentation_claim",
        "README.md#license",
        "Licensed under AGPL-3.0-or-later",
    ),
    (
        "No markdown-as-evidence",
        "documentation_claim",
        "README.md#structured-evidence",
        "All evidence is JSON/JSONL/CSV; no Markdown-as-evidence",
    ),
    (
        "Telemetry is local-first",
        "telemetry_privacy_claim",
        "README.md#telemetry-privacy",
        "Telemetry is local-first and opt-out only",
    ),
    (
        "No raw file contents",
        "telemetry_privacy_claim",
        "README.md#telemetry-privacy",
        "No raw file contents, secrets, or private code emitted in telemetry",
    ),
    (
        "Desktop Cockpit",
        "functionality_claim",
        "README.md#desktop-cockpit",
        "Desktop cockpit with Operator, Review, System, and Technical layout modes",
    ),
    (
        "headlessly for review",
        "functionality_claim",
        "README.md#desktop-cockpit",
        "Can launch headlessly for review, browser validation, and live exercise",
    ),
    (
        "Agent Profiles",
        "functionality_claim",
        "README.md#agent-profiles",
        "Ships with 7 built-in agent profiles",
    ),
    (
        "Configuration",
        "documentation_claim",
        "README.md#configuration",
        "Project-specific and user-global TOML configuration with onboarding wizard",
    ),
    (
        "protocol surfaces",
        "integration_claim",
        "README.md#protocol-surfaces",
        "Four protocol surfaces: ACP Agent, MCP Client, MCP Server, WebSocket",
    ),
    (
        "Legacy Path",
        "functionality_claim",
        "README.md#legacy-path",
        "Retains legacy vibe CLI and Textual TUI for compatibility during migration",
    ),
]

_PYTEST_PATTERNS: list[tuple[str, str, str, str]] = [
    (
        "uv run pytest",
        "test_coverage_claim",
        "README.md#development",
        "Full test suite via pytest with parallel execution",
    )
]


def _extract_readme_claims(readme_text: str) -> list[dict]:
    claims: list[dict] = []
    seen_summaries: set[str] = set()

    for pattern, category, surface_ref, summary in _README_CLAIM_PATTERNS:
        if pattern not in readme_text:
            continue
        if summary in seen_summaries:
            continue
        claims.append({
            "claim_summary": summary,
            "claim_category": category,
            "source_surface_ref": surface_ref,
        })
        seen_summaries.add(summary)

    for pattern, category, surface_ref, summary in _PYTEST_PATTERNS:
        if pattern in readme_text and "Development" in readme_text:
            claims.append({
                "claim_summary": summary,
                "claim_category": category,
                "source_surface_ref": surface_ref,
            })

    return claims


def _resolve_evidence_for_claim(claim: dict, operating_picture: dict) -> dict:
    category = _as_str(claim.get("claim_category"))
    claim_summary = _as_str(claim.get("claim_summary"))
    evidence_refs: list[str] = []

    source_artifacts = _as_list(operating_picture.get("source_artifacts"))
    artifact_by_id: dict[str, dict] = {}
    for art in source_artifacts:
        art_id = _as_str(art.get("artifact_id"))
        artifact_by_id[art_id] = {
            "status": _as_str(art.get("status")),
            "path": _as_str(art.get("path")),
            "summary": _as_dict(art.get("summary")),
        }

    ci_cd = artifact_by_id.get("github_ci_cd_reliability", {})
    surface_audit_art = artifact_by_id.get("github_surface_audit", {})
    live_auth = artifact_by_id.get("live_auth", {})
    intake = artifact_by_id.get("security_intake", {})

    support_status, confidence = _compute_support(
        category, ci_cd, surface_audit_art, live_auth, intake, operating_picture
    )
    evidence_refs = _compute_evidence(category)

    suggested_action = _determine_action(support_status)
    public_wording_risk = _assess_public_wording_risk(support_status)
    human_review_required = support_status in {"contradicted", "unsupported"}

    return {
        "claim_id": _sha256_text(f"claim:{category}:{claim_summary}"),
        "claim_category": category,
        "source_surface_ref": _as_str(claim.get("source_surface_ref")),
        "normalized_claim_summary": claim_summary,
        "evidence_refs": evidence_refs,
        "support_status": support_status,
        "confidence": confidence,
        "public_wording_risk": public_wording_risk,
        "suggested_action": suggested_action,
        "human_review_required": human_review_required,
        "local_mutation": False,
        "remote_mutation": False,
        "remaining_seams": [],
    }


def _compute_support(
    category: str,
    ci_cd: dict,
    surface_audit_art: dict,
    live_auth: dict,
    intake: dict,
    operating_picture: dict,
) -> tuple[str, str]:
    match category:
        case "platform_support_claim":
            if ci_cd.get("status") == "present":
                return "supported", "high"
        case "installation_claim":
            if ci_cd.get("status") == "present":
                return "supported", "medium"
        case "test_coverage_claim":
            ci_summary = _as_dict(ci_cd.get("summary"))
            checks_count = _as_int(ci_summary.get("required_checks_count"))
            if (
                ci_cd.get("status") == "present"
                and checks_count >= _CI_CHECKS_THRESHOLD
            ):
                return "supported", "high"
        case "security_claim":
            intake_summary = _as_dict(intake.get("summary"))
            code_scanning_open = _as_int(intake_summary.get("code_scanning_open"))
            if code_scanning_open > 0:
                return "partially_supported", "medium"
            return "supported", "medium"
        case "governance_claim":
            return "supported", "medium"
        case "release_readiness_claim":
            live_auth_summary = _as_dict(live_auth.get("summary"))
            if _as_bool(live_auth_summary.get("public_release_ready")):
                return "supported", "high"
            return "contradicted", "high"
        case "integration_claim":
            return "partially_supported", "medium"
        case "functionality_claim":
            return "partially_supported", "low"
        case "documentation_claim":
            if surface_audit_art.get("status") == "present":
                return "supported", "high"
            return "partially_supported", "medium"
        case "stability_claim":
            return "partially_supported", "low"
        case "telemetry_privacy_claim":
            redaction = _as_dict(operating_picture.get("redaction_status"))
            if _as_bool(redaction.get("content_light")):
                return "supported", "high"
            return "partially_supported", "medium"
    return "unknown", "low"


def _compute_evidence(category: str) -> list[str]:
    match category:
        case "platform_support_claim":
            return ["github_ci_cd_reliability_v1.v1.json"]
        case "installation_claim":
            return ["github_ci_cd_reliability_v1.v1.json"]
        case "test_coverage_claim":
            return ["github_ci_cd_reliability_v1.v1.json"]
        case "security_claim":
            return [
                "github_surface_audit_v1.v1.json",
                "github_security_intake_result.v1.json",
            ]
        case "governance_claim":
            return [
                "github_operating_picture_v1.v1.json",
                "github_surface_audit_v1.v1.json",
            ]
        case "release_readiness_claim":
            return ["github_operating_picture_v1.v1.json"]
        case "integration_claim":
            return [
                "github_surface_audit_v1.v1.json",
                "github_ci_cd_reliability_v1.v1.json",
            ]
        case "functionality_claim":
            return ["github_operating_picture_v1.v1.json"]
        case "documentation_claim":
            return ["github_surface_audit_v1.v1.json"]
        case "stability_claim":
            return ["github_operating_picture_v1.v1.json"]
        case "telemetry_privacy_claim":
            return ["github_operating_picture_v1.v1.json"]
    return ["github_operating_picture_v1.v1.json"]


def _determine_action(support_status: str) -> str:
    match support_status:
        case "supported":
            return "keep"
        case "partially_supported":
            return "caveat"
        case "contradicted":
            return "downgrade"
        case "unsupported":
            return "remove"
    return "request_human_review"


def _assess_public_wording_risk(support_status: str) -> str:
    match support_status:
        case "contradicted" | "unsupported":
            return "high"
        case "unknown" | "partially_supported":
            return "medium"
    return "low"


def _build_summary(claims: list[dict]) -> dict:
    supported = sum(1 for c in claims if c.get("support_status") == "supported")
    unsupported = sum(1 for c in claims if c.get("support_status") == "unsupported")
    partially = sum(
        1 for c in claims if c.get("support_status") == "partially_supported"
    )
    contradicted = sum(1 for c in claims if c.get("support_status") == "contradicted")
    unknown = sum(1 for c in claims if c.get("support_status") == "unknown")

    if contradicted > 0:
        next_action = "review_contradicted_claims"
    elif unsupported > 0:
        next_action = "remove_or_caveat_unsupported_claims"
    elif partially > 0:
        next_action = "add_caveats"
    else:
        next_action = "claims_healthy"

    return {
        "total_claims": len(claims),
        "supported_count": supported,
        "unsupported_count": unsupported,
        "partially_supported_count": partially,
        "contradicted_count": contradicted,
        "unknown_count": unknown,
        "next_recommended_action": next_action,
    }


def build_github_claims_index(
    owner: str = "juliantorr-es", repo: str = "rig-relay", *, root: Path | None = None
) -> dict:
    root = root or _REPO_ROOT
    operating_picture = _read_json(_OPERATING_PICTURE_PATH)
    surface_audit = _read_json(_SURFACE_AUDIT_PATH)

    readme_text = _read_readme(root)
    raw_claims = _extract_readme_claims(readme_text)

    resolved_claims = [
        _resolve_evidence_for_claim(c, operating_picture or {}) for c in raw_claims
    ]

    resolved_claims.sort(key=lambda c: _as_str(c.get("claim_id")))

    source_picture_hash = (
        _sha256_text(json.dumps(operating_picture, sort_keys=True))
        if operating_picture
        else ""
    )
    source_audit_hash = (
        _sha256_text(json.dumps(surface_audit, sort_keys=True)) if surface_audit else ""
    )

    report = {
        "schema_version": "rig.github.evidence_backed_claims_index.v1",
        "generated_at": _now_iso(),
        "owner": owner,
        "repo": repo,
        "content_light": True,
        "remote_mutation": False,
        "local_mutation": False,
        "source_operating_picture_path": str(_OPERATING_PICTURE_PATH),
        "source_operating_picture_hash": source_picture_hash,
        "source_surface_audit_path": str(_SURFACE_AUDIT_PATH),
        "source_surface_audit_hash": source_audit_hash,
        "claims": resolved_claims,
        "validation_commands": list(_VALIDATION_COMMANDS),
        "claim_summary": (
            "Evidence-backed claims index extracted from README.md "
            "and cross-referenced against operating picture and surface audit artifacts."
        ),
        "summary": _build_summary(resolved_claims),
    }
    assert_content_light_mapping(report)
    return safe_summary(report)


def write_github_claims_index(
    owner: str = "juliantorr-es",
    repo: str = "rig-relay",
    *,
    root: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    report = build_github_claims_index(owner=owner, repo=repo, root=root)
    path = output_path or _DEFAULT_OUTPUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


__all__ = [
    "GitHubClaimsIndexError",
    "build_github_claims_index",
    "write_github_claims_index",
]
