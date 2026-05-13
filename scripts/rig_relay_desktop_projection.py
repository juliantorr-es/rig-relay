#!/usr/bin/env python3
"""Rig Relay Desktop Projection Builder — CLI wrapper.

The core implementation now lives in ``rig_relay.desktop.projection``.
This script is a thin CLI wrapper for backward compatibility. All
imports of ``scripts.rig_relay_desktop_projection`` continue to work.

Pattern source: Rig's projection_builder.py (WidgetProjection + UIProjection
model) adapted for Rig Relay's artifact stack. Not a copy of Rig's product
domain — uses Rig Relay's own artifact schemas and field names.

Usage:
    uv run python scripts/rig_relay_desktop_projection.py
    uv run python scripts/rig_relay_desktop_projection.py --build-root .build/rig-relay --output /tmp/projection.json
"""

from __future__ import annotations

from rig_relay.desktop.projection import (  # noqa: F401
    DEFAULT_BUILD_ROOT,
    PROJECTION_SCHEMA_PATH,
    READ_ONLY_ACTIONS,
    REPO_ROOT,
    _build_current_state,
    _build_dataset,
    _build_queue,
    _build_semantic_snippets,
    _build_telemetry_bundle,
    _build_update,
    _get_app_version,
    _load_json,
    _load_markdown_summary,
    _validate_against_schema,
    build_projection,
    main,
)

if __name__ == "__main__":
    raise SystemExit(main())
