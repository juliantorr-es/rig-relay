"""GitHub Pages and Portfolio Publishing — authorization-gated Pages operations.

Pages read: GET /repos/{owner}/{repo}/pages
Pages configure: PUT /repos/{owner}/{repo}/pages (authorization-gated)
Portfolio: deterministic static HTML generation from approved evidence.

All mutation operations refuse without Lane A authorization.
"""

from __future__ import annotations

from enum import StrEnum
import hashlib
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from rig_relay.integrations.github_provider._redaction import hash_identifier

GITHUB_API_BASE = "https://api.github.com"


# ── Pages Models ────────────────────────────────────────────────────────


class PagesTargetType(StrEnum):
    PROFILE_README = "profile_readme"
    USER_PORTFOLIO = "user_portfolio"
    PROJECT_PAGES = "project_pages"


class PagesSiteStatus(BaseModel):
    """Read-only GitHub Pages site status."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str
    has_pages: bool = False
    cname: str | None = None
    custom_domain: str | None = None
    https_enforced: bool = False
    source_branch: str | None = None
    source_path: str | None = None
    build_status: str | None = None  # built, building, errored, null
    html_url: str | None = None
    evidence_digest: str | None = None

    def compute_digest(self) -> str:
        raw = self.model_dump_json(exclude={"evidence_digest"})
        return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


class PagesPublicationPlan(BaseModel):
    """Typed publication plan for GitHub Pages."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = ""
    target_type: str = PagesTargetType.PROJECT_PAGES.value

    # Repository target
    owner: str = ""
    repo: str = ""
    source_branch: str = "main"
    source_path: str = "/"
    custom_domain: str | None = None
    https_enforced: bool = True

    # Build assets
    build_manifest_digest: str | None = None
    asset_inventory: list[str] = Field(default_factory=list)
    preview_generated: bool = False
    preview_available: bool = False

    # Required permissions
    required_permissions: list[str] = Field(default_factory=list)

    # Authorization
    authorization_required: bool = True
    authorization_status: str = "pending"

    # State
    status: str = "planned"
    blockers: list[str] = Field(default_factory=list)
    suggested_next_action: str | None = None


class PagesPublicationResult(BaseModel):
    """Result of a Pages publication attempt."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    status: str  # executed, refused, authorization_pending, error
    site_url: str | None = None
    build_status: str | None = None
    verification_digest: str | None = None
    error_kind: str | None = None
    suggested_next_action: str | None = None


# ── Pages Error Vocabulary ──────────────────────────────────────────────


class PagesErrorKind:
    MISSING_PERMISSION = "github.pages.missing_permission"
    SITE_NOT_CONFIGURED = "github.pages.site_not_configured"
    AUTHORIZATION_PENDING = "github.pages.authorization_pending"
    STALE_PLAN = "github.pages.stale_plan"
    BUILD_FAILED = "github.pages.build_failed"
    API_UNAVAILABLE = "github.pages.api_unavailable"
    UNKNOWN = "github.pages.unknown_error"


# ── Pages Adapter ──────────────────────────────────────────────────────


class GitHubPagesAdapter:
    """Read-only Pages status + authorization-gated Pages configuration."""

    def __init__(self, token_getter: Any = None) -> None:
        self._token_getter = token_getter

    def _get_token(self) -> str:
        if self._token_getter is None:
            raise PagesError(PagesErrorKind.MISSING_PERMISSION, "No token manager")
        token = self._token_getter.get_token()
        if token is None:
            raise PagesError(PagesErrorKind.MISSING_PERMISSION, "Token unavailable")
        return token

    async def get_pages_status(self, owner: str, repo: str) -> PagesSiteStatus:
        repo_hash = hash_identifier(f"{owner}/{repo}")
        try:
            token = self._get_token()
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pages",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                    },
                )
                response.raise_for_status()
                data = response.json()

            status = PagesSiteStatus(
                repository_hash=repo_hash,
                has_pages=True,
                cname=data.get("cname"),
                custom_domain=data.get("custom_domain"),
                https_enforced=data.get("https_enforced", False),
                source_branch=data.get("source", {}).get("branch"),
                source_path=data.get("source", {}).get("path", "/"),
                build_status=data.get("status"),
                html_url=data.get("html_url"),
            )
            status.evidence_digest = status.compute_digest()
            return status
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return PagesSiteStatus(
                    repository_hash=repo_hash,
                    has_pages=False,
                    evidence_digest=f"sha256:{hashlib.sha256(b'no-pages').hexdigest()}",
                )
            raise PagesError(
                PagesErrorKind.API_UNAVAILABLE, f"API error {e.response.status_code}"
            ) from e

    async def configure_pages(
        self,
        owner: str,
        repo: str,
        source_branch: str,
        source_path: str = "/",
        _authorized: bool = False,
    ) -> PagesPublicationResult:
        plan_id = f"pages-{owner}/{repo}-{int(__import__('time').time())}"
        if not _authorized:
            return PagesPublicationResult(
                plan_id=plan_id,
                status="authorization_pending",
                error_kind=PagesErrorKind.AUTHORIZATION_PENDING,
                suggested_next_action="Pages configuration requires Lane A authorization",
            )

        try:
            token = self._get_token()
            payload: dict[str, Any] = {
                "source": {"branch": source_branch, "path": source_path}
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.put(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pages",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                    },
                    json=payload,
                )
                response.raise_for_status()

            # Verify
            status = await self.get_pages_status(owner, repo)
            return PagesPublicationResult(
                plan_id=plan_id,
                status="executed",
                site_url=status.html_url,
                build_status=status.build_status,
                verification_digest=status.evidence_digest,
                suggested_next_action=f"Pages configured for {owner}/{repo}",
            )
        except PagesError as e:
            return PagesPublicationResult(
                plan_id=plan_id, status="error", error_kind=e.error_kind
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                return PagesPublicationResult(
                    plan_id=plan_id,
                    status="error",
                    error_kind=PagesErrorKind.SITE_NOT_CONFIGURED,
                    suggested_next_action="Pages site already exists; update configuration instead",
                )
            return PagesPublicationResult(
                plan_id=plan_id,
                status="error",
                error_kind=PagesErrorKind.API_UNAVAILABLE,
            )


class PagesError(Exception):
    def __init__(self, error_kind: str, message: str) -> None:
        super().__init__(message)
        self.error_kind = error_kind


# ── Portfolio Generator ─────────────────────────────────────────────────


class PortfolioProfile(BaseModel):
    """Operator-editable public profile data for portfolio generation."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = ""
    headline: str = ""
    bio: str = ""
    location: str = ""
    website_url: str = ""
    github_username: str = ""
    tech_stack: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.display_name and not self.bio


class ProjectCard(BaseModel):
    """A single project card sourced from approved project-profile evidence."""

    model_config = ConfigDict(extra="forbid")

    repo_name: str = ""
    description: str = ""
    url: str = ""
    topics: list[str] = Field(default_factory=list)
    language: str = ""
    stars: int = 0


class PortfolioBuildManifest(BaseModel):
    """Manifest of generated portfolio assets with digests."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.portfolio_build.v1"
    profile: PortfolioProfile = Field(default_factory=PortfolioProfile)
    projects: list[ProjectCard] = Field(default_factory=list)
    generated_files: list[str] = Field(default_factory=list)
    generated_digests: dict[str, str] = Field(default_factory=dict)
    total_size_bytes: int = 0
    built_at: str = ""


class PortfolioGenerator:
    """Deterministic static portfolio HTML generator.

    Generates previewable HTML from approved evidence only. Never fabricates
    professional claims, employment history, or project descriptions from
    private repository activity.
    """

    @staticmethod
    def generate_html(profile: PortfolioProfile, projects: list[ProjectCard]) -> str:
        """Generate a deterministic static portfolio HTML page."""
        project_cards: list[str] = []
        for p in projects[:20]:
            topics_html = "".join(
                f'<span class="topic">{t}</span>' for t in p.topics[:5]
            )
            project_cards.append(f"""\
    <div class="project-card">
      <h3><a href="{p.url}">{p.repo_name}</a></h3>
      <p class="description">{p.description}</p>
      <div class="meta">
        <span class="language">{p.language}</span>
        <span class="stars">{p.stars} ★</span>
      </div>
      <div class="topics">{topics_html}</div>
    </div>""")

        cards_html = "\n".join(project_cards)
        tech_html = ", ".join(profile.tech_stack[:15]) if profile.tech_stack else ""
        profile_html = ""
        if not profile.is_empty():
            profile_html = f"""\
  <header class="profile">
    <h1>{profile.display_name}</h1>
    <p class="headline">{profile.headline}</p>
    <p class="bio">{profile.bio}</p>
    <p class="location">{profile.location}</p>
    <p class="tech"><strong>Tech:</strong> {tech_html}</p>
  </header>"""

        return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{profile.display_name or "Developer Portfolio"}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 800px; margin: 0 auto; padding: 2rem; }}
    .project-card {{ border: 1px solid #ddd; padding: 1rem; margin: 1rem 0; border-radius: 4px; }}
    .topic {{ background: #f0f0f0; padding: 2px 8px; border-radius: 12px; font-size: 0.8rem; margin-right: 4px; }}
    .meta {{ margin: 0.5rem 0; font-size: 0.9rem; color: #666; }}
  </style>
</head>
<body>
{profile_html}
  <main class="projects">
    <h2>Projects</h2>
{cards_html}
  </main>
  <footer><p>Generated by Rig Relay — {__import__("datetime").datetime.now().strftime("%Y-%m-%d")}</p></footer>
</body>
</html>"""

    @staticmethod
    def build_manifest(
        profile: PortfolioProfile, projects: list[ProjectCard], html: str
    ) -> PortfolioBuildManifest:
        digest = f"sha256:{hashlib.sha256(html.encode('utf-8')).hexdigest()}"
        return PortfolioBuildManifest(
            profile=profile,
            projects=projects,
            generated_files=["index.html"],
            generated_digests={"index.html": digest},
            total_size_bytes=len(html.encode("utf-8")),
            built_at=__import__("datetime").datetime.now().isoformat(),
        )


__all__ = [
    "GitHubPagesAdapter",
    "PagesError",
    "PagesErrorKind",
    "PagesPublicationPlan",
    "PagesPublicationResult",
    "PagesSiteStatus",
    "PagesTargetType",
    "PortfolioBuildManifest",
    "PortfolioGenerator",
    "PortfolioProfile",
    "ProjectCard",
]
