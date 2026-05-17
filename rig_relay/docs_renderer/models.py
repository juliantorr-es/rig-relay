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
