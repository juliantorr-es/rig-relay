"""Data models for the static documentation renderer."""

from __future__ import annotations

from typing import NamedTuple


class SiteMeta(NamedTuple):
    base_url: str
    base_path: str
    site_title: str
    theme_color: str
    favicon: str
    og_image: str
    og_image_alt: str = ""
    og_image_width: int = 0
    og_image_height: int = 0
    twitter_card: str = ""
    canonical_url: str = ""
    site_language: str = "en"
