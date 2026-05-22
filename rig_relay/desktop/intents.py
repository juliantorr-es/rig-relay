"""Desktop intents — split into sub-modules for maintainability."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

import jsonschema

from rig_relay.desktop._intents._refinement import _execute_site_editor_save
from rig_relay.desktop._intents._shared import execute_desktop_intent

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
DEFAULT_DERIVED_DIR = REPO_ROOT / ".build" / "rig-relay" / "derived"
DEFAULT_REPORTS_DIR = REPO_ROOT / ".build" / "rig-relay" / "reports"
DEFAULT_BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"

REQUEST_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.desktop_intent_request.v1.schema.json"
RESULT_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.desktop_intent_result.v1.schema.json"

PROTECTED_INTENTS: dict[str, str] = {
    "bash": "protected_intent_not_enabled",
    "shell": "protected_intent_not_enabled",
    "write_file": "protected_intent_not_enabled",
    "search_replace": "protected_intent_not_enabled",
    "remote_upload.confirm": "protected_intent_not_enabled",
    "lease_cleanup.remove": "protected_intent_not_enabled",
    "spawn.execute": "protected_intent_not_enabled",
    "fleet.execute": "protected_intent_not_enabled",
    "delegate.execute": "protected_intent_not_enabled",
}

ALLOWED_INTENTS: dict[str, dict[str, Any]] = {
    "refresh_projection": {
        "description": "Rebuild the content-light projection from available artifacts.",
        "affects_projection": True,
        "parameters": {},
    }
}


def _load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_intent_request(raw: dict[str, Any]) -> list[str]:
    """Validate intent request against the request schema."""
    schema = _load_schema(REQUEST_SCHEMA_PATH)
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(raw)]


def _build_result(
    intent_name: str,
    intent_id: str,
    status: str,
    *,
    dry_run: bool = True,
    summary: str = "",
    result_kind: str = "summary",
    **extra: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "rig.relay.desktop_intent_result.v1",
        "intent_id": intent_id,
        "created_at": datetime.now(UTC).isoformat(),
        "intent_name": intent_name,
        "status": status,
        "dry_run": dry_run,
        "result_kind": result_kind,
        "summary": summary,
        "output_refs": extra.get("output_refs", []),
        "projection_refresh_recommended": extra.get(
            "projection_refresh_recommended", False
        ),
        "authorization_required": extra.get("authorization_required", False),
        "warnings": extra.get("warnings", []),
    }
    error_code = extra.get("error_code")
    if error_code:
        result["error_code"] = error_code
    authorization_receipt = extra.get("authorization_receipt")
    if authorization_receipt:
        result["authorization_receipt"] = authorization_receipt
    inspection = extra.get("inspection")
    if inspection:
        result["inspection"] = inspection
    extra_fields = extra.get("extra_fields")
    if extra_fields:
        result["extra_fields"] = extra_fields
    return result


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
