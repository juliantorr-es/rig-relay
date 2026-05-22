from __future__ import annotations

from dataclasses import dataclass, field
import json
import keyword
from pathlib import Path
import re
from typing import Any

import yaml

_VALID_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*\Z")


def _safe_python_identifier(name: str) -> bool:
    """Return True if name is a valid, non-keyword Python identifier."""
    return bool(_VALID_IDENTIFIER_RE.match(name)) and not keyword.iskeyword(name)


def _escape_py_str(value: str) -> str:
    """Escape a value for inclusion in a Python string literal."""
    return json.dumps(value)


@dataclass
class FieldSpec:
    name: str
    type: str
    optional: bool


@dataclass
class ModelSpec:
    contract_family_id: str
    schema_version: str
    models: list[dict[str, Any]] = field(default_factory=list)
    imports: list[str] = field(
        default_factory=lambda: ["from pydantic import BaseModel"]
    )


def load_target_schema(schema_path: Path) -> dict:
    raw = schema_path.read_text(encoding="utf-8")
    suffix = schema_path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(raw)
    elif suffix == ".json":
        data = json.loads(raw)
    else:
        raise ValueError(f"Unsupported schema format: {suffix}")
    _validate_json_schema(data, schema_path)
    return data


def derive_model_spec_from_schema(schema: dict, schema_path: Path) -> ModelSpec:
    schema_id = schema.get("$id", str(schema_path))
    schema_version = (
        schema.get("properties", {}).get("schema_version", {}).get("const", "")
    )
    required_fields = schema.get("required", [])
    props = schema.get("properties", {})

    fields: list[dict[str, Any]] = []
    for field_name, prop in props.items():
        if field_name == "schema_version":
            continue
        if not _safe_python_identifier(field_name):
            raise ValueError(
                f"Schema property {field_name!r} is not a valid Python identifier. "
                f"Only [a-zA-Z_][a-zA-Z0-9_]* non-keyword names are allowed."
            )
        field_type = _map_type(prop)
        is_required = field_name in required_fields
        fields.append({
            "name": field_name,
            "type": field_type,
            "optional": not is_required,
        })

    model = {
        "class_name": "GeneratedModel",
        "base": "BaseModel",
        "schema_version": _escape_py_str(schema_version),
        "fields": fields,
    }

    return ModelSpec(
        contract_family_id=_derive_family_id(schema_id),
        schema_version=schema_version,
        models=[model],
        imports=["from pydantic import BaseModel"],
    )


def _validate_json_schema(data: dict, schema_path: Path) -> None:
    from jsonschema import Draft7Validator

    Draft7Validator.check_schema(data)


def _derive_family_id(schema_id: str) -> str:
    parts = schema_id.replace("https://", "").replace("http://", "").split("/")
    for p in parts:
        if "rig.relay.coordination." in p or "rig.relay." in p:
            return p
    return parts[-1] if parts else "unknown"


_TYPE_MAP: dict[str, str] = {
    "array": "list",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "object": "dict",
    "string": "str",
}


def _map_type(prop: dict) -> str:
    t = prop.get("type", "str")
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        return _TYPE_MAP.get(non_null[0], "str") if non_null else "str"
    return _TYPE_MAP.get(t, "str")
