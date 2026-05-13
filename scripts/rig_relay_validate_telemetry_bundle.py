#!/usr/bin/env python3
"""Rig Relay Telemetry Bundle Validator — CLI wrapper.

The core implementation now lives in ``rig_relay.evidence.telemetry_bundle``.
This script is a thin CLI wrapper for backward compatibility. All imports
of ``scripts.rig_relay_validate_telemetry_bundle`` continue to work.

Usage:
    uv run python scripts/rig_relay_validate_telemetry_bundle.py \\
        --bundle .build/rig-relay/telemetry-bundles/bundle_20260513_test.zip
"""

from __future__ import annotations

from rig_relay.evidence.telemetry_bundle import (  # noqa: F401
    FORBIDDEN_FIELD_KEYS,
    REPO_ROOT,
    SCHEMAS_DIR,
    _forbidden_in_text,
    _try_validate_schema,
    main,
    validate_bundle,
)

if __name__ == "__main__":
    raise SystemExit(main())
