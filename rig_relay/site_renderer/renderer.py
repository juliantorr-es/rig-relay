from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

TEMPLATES_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml", "j2"]),
)


def render_page(
    page_model: dict, nav_pages: list[dict] = None, relative_root: str = "."
) -> str:
    """Render a page model dict to HTML string using the page.html.j2 template."""
    template = _env.get_template("page.html.j2")
    page_title = page_model.get("title", "Untitled")
    page_desc = page_model.get("description", "")
    return template.render(
        title=page_title,
        description=page_desc,
        route=page_model.get("route", "/"),
        sections=page_model.get("sections", []),
        source_artifact_paths=page_model.get("source_artifact_paths", []),
        safety_status=page_model.get("public_safety_status", "public_safe"),
        generated_at=page_model.get("generated_at", datetime.now(UTC).isoformat()),
        nav_section=page_model.get("page_id", ""),
        page_id=page_model.get("page_id", ""),
        relative_root=relative_root,
        nav_pages=nav_pages or [],
        og_title=page_model.get("og_title", page_title),
        og_description=page_model.get("og_description", page_desc),
        og_image=page_model.get("og_image", ""),
        og_type=page_model.get("og_type", "article"),
        og_url=page_model.get("og_url", ""),
        og_site_name="Rig Relay",
        twitter_card=page_model.get("twitter_card", "summary"),
        canonical_url=page_model.get("canonical_url", ""),
        theme_color=page_model.get("theme_color", "#1e3a5f"),
        robots=page_model.get("robots", "index,follow"),
        structured_data_json=Markup(page_model.get("structured_data_json", "")),
    )


def render_index(
    pages: list[dict],
    site_meta: dict,
    nav_pages: list[dict] = None,
    relative_root: str = ".",
) -> str:
    """Render the homepage index."""
    template = _env.get_template("index.html.j2")
    return template.render(
        title=site_meta.get(
            "public_title", "Rig Relay — Governed Local Agent Platform"
        ),
        tagline=site_meta.get(
            "tagline",
            "Making AI-assisted software work inspectable, auditable, and refusal-first.",
        ),
        description=site_meta.get(
            "public_description",
            "Rig Relay is a governed local agent platform that turns agent execution into schema-governed, trace-correlated, content-light, refusal-first local evidence.",
        ),
        pages=pages,
        generated_at=site_meta.get("generated_at", datetime.now(UTC).isoformat()),
        branch=site_meta.get("branch", ""),
        head_sha=site_meta.get("head_sha", ""),
        safety_passed=site_meta.get("safety_passed", False),
        release_summary=site_meta.get("release_summary", {}),
        proof_summary=site_meta.get("proof_summary", {}),
        public_claims=site_meta.get("public_claims", []),
        rejected_claims=site_meta.get("rejected_claims", []),
        remaining_seams=site_meta.get("remaining_seams", []),
        schema_count=site_meta.get("schema_count", 0),
        github_url=site_meta.get("github_url", ""),
        relative_root=relative_root,
        nav_pages=nav_pages or [],
        page_id="",
        og_title=site_meta.get("og_title", "Rig Relay"),
        og_description=site_meta.get(
            "og_description",
            "Governed local agent platform — inspectable, auditable, refusal-first.",
        ),
        og_image=site_meta.get("og_image", ""),
        og_type=site_meta.get("og_type", "website"),
        og_url=site_meta.get("og_url", ""),
        og_site_name="Rig Relay",
        twitter_card=site_meta.get("twitter_card", "summary"),
        canonical_url=site_meta.get("canonical_url", ""),
        theme_color=site_meta.get("theme_color", "#1e3a5f"),
        robots=site_meta.get("robots", "index,follow"),
        structured_data_json=Markup(site_meta.get("structured_data_json", "")),
    )


def write_page(output_path: Path, html: str) -> None:
    """Write rendered HTML to a file, creating parent directories if needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
