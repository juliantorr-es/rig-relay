"""Metadata generation: OG, Twitter, canonical, favicon, theme-color."""

from __future__ import annotations

from rig_relay.docs_renderer.models import SiteMeta


def extract_site_meta(site_manifest: dict | None) -> SiteMeta:
    if site_manifest is None:
        return SiteMeta(
            base_url="",
            base_path="/rig-relay",
            site_title="Rig Relay Docs",
            theme_color="#1e3a5f",
            favicon="",
            og_image="",
        )
    metadata = site_manifest.get("metadata", {})
    return SiteMeta(
        base_url=str(site_manifest.get("base_url", "")),
        base_path=str(site_manifest.get("base_path", "/rig-relay")),
        site_title=str(site_manifest.get("site_title", "Rig Relay Docs")),
        theme_color=str(metadata.get("theme_color", "#1e3a5f")),
        favicon=str(metadata.get("favicon", "")),
        og_image=str(metadata.get("og_image", "")),
        og_image_alt=str(metadata.get("og_image_alt", "")),
        og_image_width=int(metadata.get("og_image_width", 0)),
        og_image_height=int(metadata.get("og_image_height", 0)),
        twitter_card=str(metadata.get("twitter_card", "")),
        canonical_url=str(site_manifest.get("canonical_url", "")),
        site_language=str(site_manifest.get("site_language", "en")),
    )


def make_og_tags(
    canonical_url: str,
    title: str,
    description: str,
    og_type: str,
    *,
    og_image: str = "",
    og_image_alt: str = "",
    og_image_width: int = 0,
    og_image_height: int = 0,
    twitter_card: str = "",
    og_locale: str = "",
) -> str:
    if not canonical_url:
        return ""
    resolved_card = twitter_card or ("summary_large_image" if og_image else "summary")
    parts: list[str] = [
        f'<meta property="og:title" content="{title}">',
        f'<meta property="og:description" content="{description}">',
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:url" content="{canonical_url}">',
        f'<meta name="twitter:card" content="{resolved_card}">',
        f'<meta name="twitter:title" content="{title}">',
        f'<meta name="twitter:description" content="{description}">',
    ]
    if og_image:
        parts.append(f'<meta property="og:image" content="{og_image}">')
        parts.append(f'<meta name="twitter:image" content="{og_image}">')
        if og_image_alt:
            parts.append(f'<meta property="og:image:alt" content="{og_image_alt}">')
            parts.append(f'<meta name="twitter:image:alt" content="{og_image_alt}">')
        if og_image_width:
            parts.append(f'<meta property="og:image:width" content="{og_image_width}">')
        if og_image_height:
            parts.append(
                f'<meta property="og:image:height" content="{og_image_height}">'
            )
    if og_locale:
        parts.append(f'<meta property="og:locale" content="{og_locale}">')
    return "\n".join(parts) + "\n"


def make_head_tags(
    sm: SiteMeta, canonical_url: str, og_tags: str, relative_root: str = "."
) -> str:
    from rig_relay.docs_renderer.paths import make_relative_link

    effective_canonical = canonical_url or sm.canonical_url
    canonical_link = (
        f'<link rel="canonical" href="{effective_canonical}">'
        if effective_canonical
        else ""
    )
    fav = (
        make_relative_link(sm.favicon, relative_root, sm.base_path)
        if sm.favicon
        else ""
    )
    favicon_link = f'<link rel="icon" href="{fav}" type="image/svg+xml">' if fav else ""

    og_locale_tag = ""
    if sm.site_language:
        og_locale_tag = f'<meta property="og:locale" content="{sm.site_language}">'

    css_href = make_relative_link(
        f"{sm.base_path}/assets/site.css", relative_root, sm.base_path
    )
    js_href = make_relative_link(
        f"{sm.base_path}/assets/site.js", relative_root, sm.base_path
    )

    twitter_card_tag = ""
    if sm.twitter_card:
        twitter_card_tag = f'<meta name="twitter:card" content="{sm.twitter_card}">'

    meta_parts: list[str] = [
        canonical_link,
        og_tags,
        og_locale_tag,
        twitter_card_tag,
        f'<meta name="theme-color" content="{sm.theme_color}">',
        '<meta name="robots" content="index,follow">',
        f'<meta name="base-path" content="{sm.base_path}">',
        f'<meta name="relative-root" content="{relative_root}">',
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'\">",
        favicon_link,
        f'<link rel="stylesheet" href="{css_href}">',
        f'<script src="{js_href}" defer></script>',
    ]
    return "\n".join(p for p in meta_parts if p)
