"""Canonical JSON helper — stdlib-only, no ``vibe.*`` dependency.

Replaces ``vibe.core.telemetry.local.dump_canonical_json`` for Relay-native
modules that must not import from ``vibe.*``.
"""

from __future__ import annotations

import json
from typing import Any


def dump_canonical_json(value: Any) -> str:
    """Serialize *value* to a canonical JSON string.

    Uses deterministic key ordering, compact separators, and UTF-8 output.
    Equivalent to ``vibe.core.telemetry.local.dump_canonical_json``.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


__all__ = ["dump_canonical_json"]
