from __future__ import annotations

from dataclasses import dataclass, field
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
    _REPO_ROOT / "docs" / "json" / "governance" / "github_surface_packets_v1.v1.json"
)
_OPERATING_PICTURE_PATH = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_operating_picture_v1.v1.json"
)
_SURFACE_AUDIT_PATH = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_surface_audit_v1.v1.json"
)

_VALIDATION_COMMANDS = [
    "uv run python scripts/rig_relay_validate_schemas.py",
    "uv run pytest tests/integrations/test_github_surface_packets.py -v",
    "uv run pytest tests/adversarial/test_github_surface_packets_redaction.py -v",
    "uv run pytest tests/governance/test_github_surface_packets_artifact.py -v",
]

_SURFACE_TO_PACKET_TYPE: dict[str, str] = {
    "project_readme": "project_readme_packet",
    "profile_readme": "profile_readme_packet",
    "static_site_pages": "github_pages_packet",
    "badge_status_block": "badge_status_packet",
    "public_claims": "claim_cleanup_packet",
    "changelog": "release_notes_packet",
    "license": "no_action_packet",
    "contributing": "contribution_surface_packet",
    "security_policy": "security_posture_packet",
    "code_of_conduct": "no_action_packet",
}

_SURFACE_CHANGE_SUMMARIES: dict[str, str] = {
    "project_readme": "Review project README for freshness, completeness, and accurate claims.",
    "profile_readme": "Needs live network check to verify github.com/{owner}/{owner} profile README presence.",
    "static_site_pages": "Verify GitHub Pages publishing pipeline and static site artifact freshness.",
    "badge_status_block": "Validate status badge block freshness against current CI/CD state.",
    "public_claims": "Reconcile public claims with current operating picture; align RC readiness language.",
    "changelog": "Review CHANGELOG.md for version accuracy and release history completeness.",
    "license": "No action needed — LICENSE file present and verified.",
    "contributing": "Review CONTRIBUTING.md for developer onboarding accuracy.",
    "security_policy": "Review SECURITY.md for vulnerability-reporting instructions and supported versions.",
    "code_of_conduct": "No action needed — CODE_OF_CONDUCT.md present and verified.",
}

_SURFACE_REMAINING_SEAMS: dict[str, list[str]] = {
    "project_readme": [],
    "profile_readme": ["requires live network check; local-only read not sufficient"],
    "static_site_pages": ["pages publishing source not verified via live API"],
    "badge_status_block": ["badge freshness not verified via live CI/CD API"],
    "public_claims": [
        "claim verification requires operating picture freshness guarantee"
    ],
    "changelog": [],
    "license": [],
    "contributing": [],
    "security_policy": [],
    "code_of_conduct": [],
}


class GitHubSurfacePacketsError(Exception):
    """Raised when surface packets generation fails."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else str(value) if value is not None else ""


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


def _build_packet_id(packet_type: str, surface_name: str) -> str:
    return _sha256_text(f"surface_packet:{packet_type}:{surface_name}:v1")


def _build_finding_ref(surface_name: str, issue: str) -> str:
    return _sha256_text(f"finding:{surface_name}:{issue}")


def _build_claim_ref(surface_name: str, claim_id: str) -> str:
    return _sha256_text(f"claim:{surface_name}:{claim_id}")


def _build_single_packet(surface: dict, owner: str, repo: str) -> dict:
    surface_name = _as_str(surface.get("surface_name"))
    packet_type = _SURFACE_TO_PACKET_TYPE.get(surface_name, "human_review_packet")
    packet_id = _build_packet_id(packet_type, surface_name)
    issues_found = _as_list(surface.get("issues_found"))
    evidence_paths = _as_list(surface.get("evidence_paths"))

    source_findings = [
        _build_finding_ref(surface_name, issue) for issue in issues_found
    ]

    source_claims: list[str] = []
    if surface_name == "public_claims":
        source_claims = [
            _build_claim_ref(surface_name, f"claim_{i}")
            for i in range(len(issues_found))
        ]

    human_review_required = bool(issues_found) or surface_name == "profile_readme"

    change_summary_template = _SURFACE_CHANGE_SUMMARIES.get(
        surface_name, f"Review {surface_name} surface for public readiness."
    )
    proposed_change_summary = change_summary_template.format(owner=owner, repo=repo)

    remaining_seams = list(_SURFACE_REMAINING_SEAMS.get(surface_name, []))

    return {
        "packet_id": packet_id,
        "packet_type": packet_type,
        "source_findings": source_findings,
        "source_claims": source_claims,
        "target_surface_role": surface_name,
        "proposed_change_summary": proposed_change_summary,
        "generated_public_text_allowed": False,
        "evidence_refs": evidence_paths,
        "validation_commands": list(_VALIDATION_COMMANDS),
        "apply_ready": False,
        "preview_ready": not human_review_required,
        "human_review_required": human_review_required,
        "local_mutation": False,
        "remote_mutation": False,
        "remaining_seams": remaining_seams,
    }


def _build_packets(audited_surfaces: list[dict], owner: str, repo: str) -> list[dict]:
    return sorted(
        (_build_single_packet(surface, owner, repo) for surface in audited_surfaces),
        key=lambda p: _as_str(p.get("packet_id")),
    )


def _build_summary(surface_issues: dict[str, bool], packets: list[dict]) -> dict:
    packet_type_counts: dict[str, int] = {}
    for packet in packets:
        pt = _as_str(packet.get("packet_type"))
        packet_type_counts[pt] = packet_type_counts.get(pt, 0) + 1

    has_issues = any(surface_issues.values())
    has_human_review = any(packet.get("human_review_required") for packet in packets)

    if has_human_review:
        next_recommended_action = "human_review_required_for_some_packets"
    elif has_issues:
        next_recommended_action = "review_packets_with_issues"
    else:
        next_recommended_action = "surfaces_healthy"

    return {
        "total_packets": len(packets),
        "packet_type_counts": packet_type_counts,
        "next_recommended_action": next_recommended_action,
    }


@dataclass(slots=True)
class GitHubSurfacePackets:
    owner: str = "juliantorr-es"
    repo: str = "rig-relay"
    root: Path = field(default_factory=lambda: _REPO_ROOT)
    operating_picture_path: Path = field(
        default_factory=lambda: _OPERATING_PICTURE_PATH
    )
    surface_audit_path: Path = field(default_factory=lambda: _SURFACE_AUDIT_PATH)

    def build(self) -> dict:
        operating_picture = _read_json(self.operating_picture_path)
        surface_audit = _read_json(self.surface_audit_path)

        if surface_audit is None:
            raise GitHubSurfacePacketsError(
                f"Surface audit not found or unreadable at {self.surface_audit_path}"
            )

        audited_surfaces = _as_list(surface_audit.get("audited_surfaces"))

        owner = self.owner or _as_str(surface_audit.get("owner"))
        repo = self.repo or _as_str(surface_audit.get("repo"))

        surface_issues: dict[str, bool] = {}
        for surface in audited_surfaces:
            name = _as_str(surface.get("surface_name"))
            issues = _as_list(surface.get("issues_found"))
            if issues:
                surface_issues[name] = True

        operating_picture_source = (
            str(self.operating_picture_path) if operating_picture is not None else ""
        )
        surface_audit_source = str(self.surface_audit_path)

        packets = _build_packets(audited_surfaces, owner, repo)

        report = {
            "schema_version": "rig.github.surface_packets.v1",
            "generated_at": _now_iso(),
            "owner": owner,
            "repo": repo,
            "content_light": True,
            "remote_mutation": False,
            "local_mutation": False,
            "source_operating_picture_path": operating_picture_source,
            "source_surface_audit_path": surface_audit_source,
            "surface_issues_detected": surface_issues,
            "packets": packets,
            "summary": _build_summary(surface_issues, packets),
        }

        assert_content_light_mapping(report)
        report = safe_summary(report)

        packet_type_counts = _as_dict(report.get("summary", {})).get(
            "packet_type_counts", {}
        )
        if isinstance(packet_type_counts, dict):
            report["summary"]["packet_type_counts"] = dict(
                sorted(packet_type_counts.items())
            )

        return report


def build_github_surface_packets(
    owner: str = "juliantorr-es", repo: str = "rig-relay", *, root: Path | None = None
) -> dict:
    return GitHubSurfacePackets(owner=owner, repo=repo, root=root or _REPO_ROOT).build()


__all__ = [
    "GitHubSurfacePackets",
    "GitHubSurfacePacketsError",
    "build_github_surface_packets",
]
