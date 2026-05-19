from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

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
    return template.render(
        title=page_model.get("title", "Untitled"),
        description=page_model.get("description", ""),
        route=page_model.get("route", "/"),
        sections=page_model.get("sections", []),
        source_artifact_paths=page_model.get("source_artifact_paths", []),
        safety_status=page_model.get("public_safety_status", "public_safe"),
        generated_at=page_model.get("generated_at", datetime.now(UTC).isoformat()),
        nav_section=page_model.get("page_id", ""),
        relative_root=relative_root,
        nav_pages=nav_pages or [],
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
        title="Rig Relay — Evidence Site",
        tagline="Structured evidence generated from canonical JSON artifacts.",
        pages=pages,
        generated_at=site_meta.get("generated_at", datetime.now(UTC).isoformat()),
        branch=site_meta.get("branch", ""),
        head_sha=site_meta.get("head_sha", ""),
        safety_passed=site_meta.get("safety_passed", False),
        relative_root=relative_root,
        nav_pages=nav_pages or [],
    )


def write_page(output_path: Path, html: str) -> None:
    """Write rendered HTML to a file, creating parent directories if needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
