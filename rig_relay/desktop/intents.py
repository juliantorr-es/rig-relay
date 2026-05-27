from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from rig_relay.desktop._intents._refresh import _execute_site_editor_save
from rig_relay.desktop._intents._shared import (
    ALLOWED_INTENTS,
    DEFAULT_BUILD_ROOT,
    DEFAULT_DERIVED_DIR,
    DEFAULT_REPORTS_DIR,
    PROTECTED_INTENTS,
    REPO_ROOT,
    SCHEMAS_DIR,
    _build_result,
    execute_desktop_intent,
)

REQUEST_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.desktop_intent_request.v1.schema.json"
RESULT_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.desktop_intent_result.v1.schema.json"


def _load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_intent_request(raw: dict[str, Any]) -> list[str]:
    schema = _load_schema(REQUEST_SCHEMA_PATH)
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(raw)]


__all__ = [
    "ALLOWED_INTENTS",
    "DEFAULT_BUILD_ROOT",
    "DEFAULT_DERIVED_DIR",
    "DEFAULT_REPORTS_DIR",
    "PROTECTED_INTENTS",
    "REPO_ROOT",
    "REQUEST_SCHEMA_PATH",
    "RESULT_SCHEMA_PATH",
    "SCHEMAS_DIR",
    "_build_result",
    "_execute_site_editor_save",
    "execute_desktop_intent",
    "validate_intent_request",
]
