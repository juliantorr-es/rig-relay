"""Shared helpers for evidence tests."""

from __future__ import annotations

from typing import Any

FORBIDDEN_RAW_FIELD_NAMES: frozenset[str] = frozenset({
    "content",
    "stdout",
    "stderr",
    "output_text",
    "diff",
    "patch",
    "snippet",
    "file_contents",
    "old_text",
    "new_text",
})


def check_schema_for_forbidden_fields(schema_dict: dict[str, Any]) -> None:
    """Assert that a schema dict does not contain forbidden raw field names.

    Recursively walks dicts and lists. Forbidden field names are
    defined in FORBIDDEN_RAW_FIELD_NAMES.
    """

    def _check(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert k not in FORBIDDEN_RAW_FIELD_NAMES, (
                    f"Forbidden field '{k}' at {path}"
                )
                _check(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _check(item, f"{path}[{i}]")

    _check(schema_dict, "schema")
