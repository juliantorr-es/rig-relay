"""Site manifest loading and helpers."""

from __future__ import annotations

from pathlib import Path

from rig_relay.docs_renderer.loader import load_json
from rig_relay.docs_renderer.paths import SITE_MANIFEST


def load_site_manifest(manifest_path: Path | None = None) -> dict:
    path = manifest_path or SITE_MANIFEST
    if path.is_file():
        return load_json(path)
    return {
        "schema_version": "rig.documentation.site_manifest.v1",
        "site_title": "Rig Relay Docs",
        "collections": [],
    }
