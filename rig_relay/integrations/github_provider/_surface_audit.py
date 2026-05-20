from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_SURFACE_AUDIT_CATALOG = [
    "project_readme",
    "profile_readme",
    "static_site_pages",
    "badge_status_block",
    "public_claims",
    "changelog",
    "license",
    "contributing",
    "security_policy",
    "code_of_conduct",
]

_VALIDATION_COMMANDS = [
    "uv run python scripts/rig_relay_validate_schemas.py",
    "uv run pytest tests/integrations/test_github_surface_audit.py -v",
    "uv run pytest tests/adversarial/test_github_surface_audit_redaction.py -v",
    "uv run pytest tests/governance/test_github_surface_audit_artifact.py -v",
]


class GitHubSurfaceAuditError(Exception):
    """Raised when surface audit fails."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _check_file_exists(root: Path, *path_parts: str) -> bool:
    return (root.joinpath(*path_parts)).exists()


def _new_surface(name: str) -> dict:
    return {
        "surface_name": name,
        "status": "not_checked",
        "present": False,
        "details": "",
        "evidence_paths": [],
        "issues_found": [],
    }


def _simple_file_audit(
    surface: dict, root: Path, filename: str, label: str, issue: str
) -> dict:
    found = _check_file_exists(root, filename)
    surface["present"] = found
    surface["status"] = "present" if found else "missing"
    if found:
        surface["evidence_paths"] = [filename]
        surface["details"] = f"{filename} found at repository root."
    else:
        surface["details"] = f"No {filename} found."
        surface["issues_found"].append(issue)
    return surface


def _audit_project_readme(root: Path) -> dict:
    surface = _new_surface("project_readme")
    readme_found = _check_file_exists(root, "README.md") or _check_file_exists(
        root, "readme.md"
    )
    surface["present"] = readme_found
    surface["status"] = "present" if readme_found else "missing"
    if readme_found:
        surface["evidence_paths"] = ["README.md"]
        surface["details"] = "Project README found at repository root."
        readme_path = (
            root / "README.md" if (root / "README.md").exists() else root / "readme.md"
        )
        if readme_path.exists():
            readme_content = readme_path.read_text(encoding="utf-8")
            if "Quick Start" not in readme_content:
                surface["issues_found"].append("missing_quick_start_section")
            if "License" not in readme_content and "license" not in readme_content:
                surface["issues_found"].append("missing_license_reference")
    else:
        surface["details"] = "No README.md found at repository root."
        surface["issues_found"].append("missing_readme")
    return surface


def _audit_profile_readme(owner: str) -> dict:
    surface = _new_surface("profile_readme")
    surface["status"] = "needs_live_check"
    surface["details"] = (
        f"Profile README typically lives at github.com/{owner}/{owner}. "
        "Needs live network check to verify presence and content."
    )
    surface["issues_found"].append("needs_live_profile_repo_check")
    return surface


def _audit_static_site(root: Path) -> dict:
    surface = _new_surface("static_site_pages")
    render_manifest = _check_file_exists(root, "docs", "render-manifest.json")
    pages_dir = (root / "docs" / "pages").is_dir()
    index_html = _check_file_exists(root, "docs", "index.html")
    surface["present"] = render_manifest and pages_dir and index_html
    surface["status"] = "present" if surface["present"] else "incomplete"
    if render_manifest:
        surface["evidence_paths"].append("docs/render-manifest.json")
    if pages_dir:
        surface["evidence_paths"].append("docs/pages/")
    if index_html:
        surface["evidence_paths"].append("docs/index.html")
    surface["details"] = (
        "Static site artifacts found."
        if surface["present"]
        else "Some static site artifacts are missing."
    )
    if not surface["present"]:
        surface["issues_found"].append("incomplete_static_site_artifacts")
    return surface


def _audit_badges(root: Path) -> dict:
    surface = _new_surface("badge_status_block")
    readme_path = root / "README.md"
    badges_present = False
    if readme_path.exists():
        content = readme_path.read_text(encoding="utf-8")
        badges_present = "![" in content
    surface["present"] = badges_present
    surface["status"] = "present" if badges_present else "missing"
    if badges_present:
        surface["evidence_paths"] = ["README.md"]
        surface["details"] = "Badges detected in README.md."
    else:
        surface["details"] = "No status badges detected in README.md."
        surface["issues_found"].append("missing_status_badges")
    return surface


def _audit_public_claims(root: Path) -> dict:
    surface = _new_surface("public_claims")
    surface["status"] = "present"
    surface["present"] = True
    surface["evidence_paths"] = ["README.md"]
    surface["details"] = "Public claims extracted from README.md."
    readme_path = root / "README.md"
    unsupported: list[str] = []
    if (
        readme_path.exists()
        and (
            op_path := root
            / "docs"
            / "json"
            / "governance"
            / "github_operating_picture_v1.v1.json"
        ).exists()
    ):
        import json

        readme_content = readme_path.read_text(encoding="utf-8")
        op_picture = json.loads(op_path.read_text(encoding="utf-8"))
        if "Release Candidate" in readme_content and not op_picture.get(
            "public_release_ready", False
        ):
            unsupported.append(
                "README claims release-candidate readiness but "
                "operating_picture shows public_release_ready=false"
            )
    if unsupported:
        surface["issues_found"].extend(unsupported)
    return surface


def _audit_license(root: Path) -> dict:
    surface = _new_surface("license")
    found = _check_file_exists(root, "LICENSE") or _check_file_exists(
        root, "LICENSE.md"
    )
    surface["present"] = found
    surface["status"] = "present" if found else "missing"
    if found:
        actual = "LICENSE" if _check_file_exists(root, "LICENSE") else "LICENSE.md"
        surface["evidence_paths"] = [actual]
        surface["details"] = f"{actual} found at repository root."
    else:
        surface["details"] = "No LICENSE file found."
        surface["issues_found"].append("missing_license_file")
    return surface


_SURFACE_AUDITORS: dict[str, Callable[..., dict[str, Any]]] = {
    "project_readme": _audit_project_readme,
    "profile_readme": _audit_profile_readme,
    "static_site_pages": _audit_static_site,
    "badge_status_block": _audit_badges,
    "public_claims": _audit_public_claims,
    "changelog": lambda root: _simple_file_audit(
        _new_surface("changelog"),
        root,
        "CHANGELOG.md",
        "CHANGELOG.md",
        "missing_changelog",
    ),
    "license": _audit_license,
    "contributing": lambda root: _simple_file_audit(
        _new_surface("contributing"),
        root,
        "CONTRIBUTING.md",
        "CONTRIBUTING.md",
        "missing_contributing_guide",
    ),
    "security_policy": lambda root: _simple_file_audit(
        _new_surface("security_policy"),
        root,
        "SECURITY.md",
        "SECURITY.md",
        "missing_security_policy",
    ),
    "code_of_conduct": lambda root: _simple_file_audit(
        _new_surface("code_of_conduct"),
        root,
        "CODE_OF_CONDUCT.md",
        "CODE_OF_CONDUCT.md",
        "missing_code_of_conduct",
    ),
}


def _audit_surface(surface_name: str, *, root: Path, owner: str, repo: str) -> dict:
    auditor = _SURFACE_AUDITORS.get(surface_name)
    if auditor is not None and callable(auditor):
        if surface_name == "profile_readme":
            return auditor(owner)
        return auditor(root)
    return _new_surface(surface_name)


def _build_proposal_packets(audited_surfaces: list[dict]) -> list[dict]:
    proposals: list[dict] = []
    surface_proposals = {
        "project_readme": {
            "action": "project_readme_update",
            "title": "Update project README for completeness and freshness",
        },
        "profile_readme": {
            "action": "profile_readme_update",
            "title": "Create or update GitHub profile README",
        },
        "static_site_pages": {
            "action": "static_site_publish_check",
            "title": "Verify GitHub Pages / static site publishing pipeline",
        },
        "badge_status_block": {
            "action": "badge_status_block",
            "title": "Add or refresh status badges in README",
        },
        "public_claims": {
            "action": "unsupported_claim_cleanup",
            "title": "Review and reconcile public claims with current operating picture",
        },
        "changelog": {
            "action": "changelog_update",
            "title": "Create or update CHANGELOG.md",
        },
        "license": {
            "action": "license_review",
            "title": "Review LICENSE file presence and correctness",
        },
        "contributing": {
            "action": "contributing_review",
            "title": "Create or update CONTRIBUTING.md",
        },
        "security_policy": {
            "action": "security_policy_review",
            "title": "Create or update SECURITY.md",
        },
        "code_of_conduct": {
            "action": "contributing_review",
            "title": "Create or update CODE_OF_CONDUCT.md",
        },
    }

    for surface in audited_surfaces:
        name = surface.get("surface_name", "")
        status = surface.get("status", "")
        if status in {"missing", "incomplete", "stale", "needs_live_check"}:
            proposal = surface_proposals.get(name)
            if proposal:
                proposal_status = (
                    "blocked" if status == "needs_live_check" else "proposed"
                )
                proposals.append({
                    "proposal_id": f"proposal:{name}:{status}",
                    "title": proposal["title"],
                    "target_surface": name,
                    "action": proposal["action"],
                    "status": proposal_status,
                    "details": surface.get("details", f"Surface {name} is {status}."),
                })

    proposals.sort(key=lambda p: p["proposal_id"])
    return proposals


def _build_missing_surfaces(audited: list[dict]) -> list[dict]:
    return [
        {
            "surface_name": s["surface_name"],
            "reason": s.get("details", "Surface is missing."),
        }
        for s in audited
        if s.get("status") == "missing"
    ]


def _build_stale_surfaces(audited: list[dict]) -> list[dict]:
    return [
        {
            "surface_name": s["surface_name"],
            "reason": s.get("details", "Surface may be stale."),
        }
        for s in audited
        if s.get("status") == "stale"
    ]


def _build_summary(audited: list[dict], proposals: list[dict]) -> dict:
    present_count = sum(1 for s in audited if s.get("status") == "present")
    missing_count = sum(1 for s in audited if s.get("status") == "missing")
    stale_count = sum(1 for s in audited if s.get("status") == "stale")
    return {
        "total_surfaces_audited": len(audited),
        "present_surface_count": present_count,
        "missing_surface_count": missing_count,
        "stale_surface_count": stale_count,
        "proposal_count": len(proposals),
        "next_recommended_action": (
            "review_proposals" if proposals else "surfaces_healthy"
        ),
    }


@dataclass(slots=True)
class GitHubSurfaceStewardAudit:
    owner: str = "juliantorr-es"
    repo: str = "rig-relay"
    root: Path = field(default_factory=lambda: _REPO_ROOT)

    def run(self) -> dict:
        audited = [
            _audit_surface(name, root=self.root, owner=self.owner, repo=self.repo)
            for name in _SURFACE_AUDIT_CATALOG
        ]

        missing_surfaces = _build_missing_surfaces(audited)
        stale_surfaces = _build_stale_surfaces(audited)
        proposals = _build_proposal_packets(audited)

        report = {
            "schema_version": "rig.github.surface_audit.v1",
            "generated_at": _now_iso(),
            "owner": self.owner,
            "repo": self.repo,
            "content_light": True,
            "remote_mutation": False,
            "audited_surfaces": audited,
            "missing_surfaces": missing_surfaces,
            "stale_surfaces": stale_surfaces,
            "proposal_packets": proposals,
            "required_permissions_for_future_publish": [
                {
                    "permission": "repository_file_updates:write",
                    "scope": "repository",
                    "reason": "Needed to commit README, CHANGELOG, Pages updates.",
                },
                {
                    "permission": "pages:write",
                    "scope": "repository",
                    "reason": "Needed to configure GitHub Pages publishing source.",
                },
            ],
            "next_recommended_action": "review_proposals",
            "summary": _build_summary(audited, proposals),
        }
        assert_content_light_mapping(report)
        return safe_summary(report)


def build_github_surface_audit(
    owner: str = "juliantorr-es", repo: str = "rig-relay", *, root: Path | None = None
) -> dict:
    return GitHubSurfaceStewardAudit(
        owner=owner, repo=repo, root=root or _REPO_ROOT
    ).run()


__all__ = [
    "GitHubSurfaceAuditError",
    "GitHubSurfaceStewardAudit",
    "build_github_surface_audit",
]
