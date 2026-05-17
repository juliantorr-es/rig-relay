"""Curated homepage renderer for the Rig Relay documentation site."""

from __future__ import annotations

import html as _html
import json

from rig_relay.docs_renderer.metadata import (
    extract_site_meta,
    make_head_tags,
    make_og_tags,
)
from rig_relay.docs_renderer.paths import REPO_ROOT


def _load_home_json() -> dict:
    path = REPO_ROOT / "docs" / "json" / "site_home.v1.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _home_actions(data: dict, sm: SiteMeta) -> str:
    from rig_relay.docs_renderer.paths import make_relative_link

    parts = []
    for a in data.get("primary_actions", []):
        href = make_relative_link(str(a.get("href", "")), ".", sm.base_path)
        parts.append(
            f'<a class="action-card" href="{_html.escape(href)}">'
            f"<strong>{_html.escape(a.get('label', ''))}</strong>"
            f"<span>{_html.escape(a.get('description', ''))}</span></a>"
        )
    return "\n".join(parts)


def _home_works(data: dict) -> str:
    return "\n".join(
        f"<li>{_html.escape(i)}</li>" for i in data.get("what_works_today", [])[:8]
    )


def _home_features(data: dict) -> str:
    parts = []
    for card in data.get("feature_cards", []):
        parts.append(
            f'<div class="feature-card"><h3>{_html.escape(card.get("title", ""))}</h3>'
            f"<p>{_html.escape(card.get('description', ''))}</p></div>"
        )
    return "\n".join(parts)


def _home_metrics(data: dict) -> str:
    parts = []
    for m in data.get("proof_metrics", []):
        parts.append(
            f'<div class="metric-card">'
            f'<span class="metric-value">{_html.escape(m.get("value", ""))}</span>'
            f'<span class="metric-label">{_html.escape(m.get("label", ""))}</span></div>'
        )
    return "\n".join(parts)


def _home_audience(data: dict, sm: SiteMeta) -> str:
    from rig_relay.docs_renderer.paths import make_relative_link

    parts = []
    for p in data.get("audience_paths", []):
        href = make_relative_link(str(p.get("href", "")), ".", sm.base_path)
        parts.append(
            f'<a class="audience-card" href="{_html.escape(href)}">'
            f"<strong>{_html.escape(p.get('label', ''))}</strong>"
            f"<span>{_html.escape(p.get('description', ''))}</span></a>"
        )
    return "\n".join(parts)


def _home_featured(data: dict, sm: SiteMeta) -> str:
    from rig_relay.docs_renderer.paths import make_relative_link

    parts = []
    for f in data.get("featured_links", [])[:5]:
        href = make_relative_link(str(f.get("href", "")), ".", sm.base_path)
        parts.append(
            f'<li><a href="{_html.escape(href)}">'
            f"{_html.escape(f.get('title', ''))}</a>"
            f'<span class="search-snippet">{_html.escape(f.get("summary", ""))}</span></li>'
        )
    return "\n".join(parts)


def _home_diagram(data: dict) -> str:
    hero = data.get("hero_diagram", {})
    if not hero.get("path"):
        return ""
    from rig_relay.docs_renderer.diagrams import render_diagram_ref

    return render_diagram_ref({
        "block_id": "hero-diagram",
        "type": "diagram_ref",
        "diagram_id": hero.get("diagram_id", ""),
        "path": hero.get("path", ""),
        "caption": "",
        "fallback_text": data.get("title", ""),
    })


def render_homepage(manifest: dict) -> str:
    from rig_relay.docs_renderer.paths import make_relative_link

    data = _load_home_json()
    sm = extract_site_meta(manifest)
    title = _html.escape(data.get("title", sm.site_title))
    tagline = _html.escape(data.get("tagline", ""))
    desc = _html.escape(data.get("plain_language_summary", ""))
    partner = _html.escape(data.get("partner_friendly_explanation", ""))
    canonical_url = f"{sm.base_url}/" if sm.base_url else ""
    og_tags = make_og_tags(canonical_url, title, desc, "website")
    head_tags = make_head_tags(sm, canonical_url, og_tags, relative_root=".")

    archive = data.get("archive_link", {})
    archive_html = ""
    if archive:
        arch_href = make_relative_link(str(archive.get("href", "")), ".", sm.base_path)
        archive_html = (
            f'<a class="archive-callout" href="{_html.escape(arch_href)}">'
            f"{_html.escape(archive.get('label', ''))}</a>"
        )

    diagram_html = _home_diagram(data)
    footer_href = make_relative_link(
        f"{sm.base_path}/collections/index.html", ".", sm.base_path
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{desc}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header hero">
  <h1>{title}</h1>
  <p class="tagline">{tagline}</p>
  <p class="hero-summary">{desc}</p>
  <p class="hero-partner">{partner}</p>
  <div class="hero-actions">{_home_actions(data, sm)}</div>
</header>
<main id="main" class="homepage">
  <div id="site-search"></div>
  <section id="overview"><h2>What Works Today</h2><ul class="works-list">{_home_works(data)}</ul></section>
  <section id="metrics"><h2>Proof Metrics</h2><div class="metrics-grid">{_home_metrics(data)}</div></section>
  <section><h2>Features</h2><div class="features-grid">{_home_features(data)}</div></section>
  {f"<section><h2>How It Works</h2>{diagram_html}</section>" if diagram_html else ""}
  <section id="audience"><h2>Who Are You?</h2><div class="audience-grid">{_home_audience(data, sm)}</div></section>
  <section><h2>Featured Docs</h2><ul class="featured-list">{_home_featured(data, sm)}</ul></section>
  <section>{archive_html}</section>
</main>
<footer>
  <p><a href="{footer_href}">Evidence Archive</a> &middot; Rig Relay &mdash; AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""
