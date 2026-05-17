#!/usr/bin/env python3
"""Render canonical JSON documentation to static HTML.

Loads docs/json/**/*.json, validates basic structure, builds navigation
from docs/json/site_manifest.v1.json, and renders static HTML into docs/.

Output:
  docs/index.html
  docs/pages/<document_id>.html
  docs/assets/site.css
  docs/search-index.json
  docs/render-manifest.json
  docs/.nojekyll

Usage:
  uv run python scripts/render_static_docs.py

This is a thin CLI shim that delegates to rig_relay.docs_renderer.
"""

from __future__ import annotations

from rig_relay.docs_renderer.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
