"""Metadata generation: OG, Twitter, canonical, favicon, theme-color."""

from __future__ import annotations

from rig_relay.docs_renderer.models import SiteMeta


def extract_site_meta(site_manifest: dict | None) -> SiteMeta:
    if site_manifest is None:
        return SiteMeta("", "/rig-relay", "Rig Relay Docs", "#1e3a5f", "", "")
    metadata = site_manifest.get("metadata", {})
    return SiteMeta(
        base_url=str(site_manifest.get("base_url", "")),
        base_path=str(site_manifest.get("base_path", "/rig-relay")),
        site_title=str(site_manifest.get("site_title", "Rig Relay Docs")),
        theme_color=metadata.get("theme_color", "#1e3a5f"),
        favicon=metadata.get("favicon", ""),
        og_image=metadata.get("og_image", ""),
    )


def make_og_tags(canonical_url: str, title: str, description: str, og_type: str) -> str:
    if not canonical_url:
        return ""
    return f"""<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="{og_type}">
<meta property="og:url" content="{canonical_url}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{description}">
"""


def make_head_tags(sm: SiteMeta, canonical_url: str, og_tags: str) -> str:
    canonical_link = (
        f'<link rel="canonical" href="{canonical_url}">' if canonical_url else ""
    )
    favicon_link = (
        f'<link rel="icon" href="{sm.favicon}" type="image/svg+xml">'
        if sm.favicon
        else ""
    )
    og_image_tags = ""
    if sm.og_image:
        og_image_tags = f'<meta property="og:image" content="{sm.og_image}">\n<meta name="twitter:image" content="{sm.og_image}">'
    return f"""{canonical_link}
{og_tags}{og_image_tags}
<meta name="theme-color" content="{sm.theme_color}">
{favicon_link}
<link rel="stylesheet" href="{sm.base_path}/assets/site.css">"""
