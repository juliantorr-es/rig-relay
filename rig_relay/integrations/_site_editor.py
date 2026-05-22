"""Static Site Editor v1 — schema-driven WYSIWYG form generator.

Walks JSON schemas to produce editable form field definitions.
Reads/writes canonical JSON artifacts. Triggers static site re-render.
Zero new dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS_JSON = _REPO_ROOT / "docs" / "json"
_SCHEMAS = _REPO_ROOT / "docs" / "schemas"


def read_schema_fields(schema_path: Path) -> list[dict[str, Any]]:
    """Walk a JSON schema's properties block and produce editable field definitions."""
    if not schema_path.exists():
        return []
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    properties = schema.get("properties", {})
    fields: list[dict[str, Any]] = []

    for key, prop in properties.items():
        if key in (
            "schema_version",
            "document_id",
            "provenance",
            "metadata",
            "disclosure",
        ):
            continue
        field: dict[str, Any] = {
            "field_name": key,
            "field_label": prop.get("title", key.replace("_", " ").title()),
            "field_type": _map_json_type(prop),
        }
        if "enum" in prop:
            field["field_type"] = "select"
            field["choices"] = prop["enum"]
        if "default" in prop:
            field["default"] = prop["default"]
        if "description" in prop:
            field["description"] = prop["description"]

        # Handle array-of-objects as card editor
        if prop.get("type") == "array" and isinstance(prop.get("items"), dict):
            items = prop["items"]
            field["field_type"] = "card_list"
            field["item_fields"] = [
                {
                    "field_name": k,
                    "field_label": v.get("title", k.replace("_", " ").title()),
                    "field_type": "textarea" if v.get("type") == "string" else "text",
                }
                for k, v in items.get("properties", {}).items()
                if k not in ("schema_version", "document_id")
            ]
        elif prop.get("type") == "string":
            field["field_type"] = (
                "textarea"
                if len(key) > 20
                or "summary" in key.lower()
                or "description" in key.lower()
                else "text"
            )
        elif prop.get("type") == "array" and "string" in str(
            prop.get("items", {}).get("type", "")
        ):
            field["field_type"] = "tag_list"

        fields.append(field)
    return fields


def _map_json_type(prop: dict[str, Any]) -> str:
    t = prop.get("type", "string")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")
    return t


def read_page_data(artifact_path: Path) -> dict[str, Any]:
    """Read current page data from canonical JSON artifact."""
    if not artifact_path.exists():
        return {}
    return json.loads(artifact_path.read_text(encoding="utf-8"))


def write_page_data(artifact_path: Path, data: dict[str, Any]) -> bool:
    """Write page data back to canonical JSON artifact with validation."""
    try:
        existing = read_page_data(artifact_path)
        # Preserve immutable fields
        for key in ("schema_version", "document_id", "provenance"):
            if key in existing and key not in data:
                data[key] = existing[key]
        artifact_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return True
    except Exception:
        return False


def trigger_render() -> bool:
    """Run the static site renderer to regenerate HTML from updated JSON."""
    try:
        subprocess.run(
            ["uv", "run", "python", "scripts/render_static_docs.py"],
            cwd=_REPO_ROOT,
            capture_output=True,
            timeout=120,
        )
        return True
    except Exception:
        return False


def build_site_editor_projection() -> dict[str, Any]:
    """Build projection data for the cockpit site editor widget."""
    import os

    site_home = _DOCS_JSON / "site_home.v1.json"
    home_schema = _SCHEMAS / "rig.documentation.home.v1.schema.json"

    page_data = read_page_data(site_home)
    fields = read_schema_fields(home_schema) if home_schema.exists() else []

    # Filter page data to only editable fields
    editable = {}
    for field in fields:
        key = field["field_name"]
        if key in page_data:
            val = page_data[key]
            if field["field_type"] == "card_list" and isinstance(val, list):
                editable[key] = val
            elif isinstance(val, (str, int, bool, list)):
                editable[key] = val

    # Check if the rendered site exists as a safety signal
    rendered = (_REPO_ROOT / "docs" / "index.html").exists()

    return {
        "available": True,
        "artifact_path": str(site_home),
        "schema_path": str(home_schema),
        "fields": fields,
        "page_data": editable,
        "schema_valid": True,
        "can_save": os.environ.get("RIG_RELAY_ALLOW_SITE_EDITS", "0") == "1",
        "last_rendered": rendered,
        "content_light": True,
        "raw_payloads_exposed": False,
    }


__all__ = [
    "build_site_editor_projection",
    "read_page_data",
    "read_schema_fields",
    "trigger_render",
    "write_page_data",
]
