"""JSON loading, validation, and classification for documentation sources."""

from __future__ import annotations

import json
from pathlib import Path


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_REQUIRED_PAGE_FIELDS = {"schema_version", "document_id", "title", "sections"}


def validate_page(data: dict, path: Path) -> list[str]:
    errors: list[str] = []
    for field in _REQUIRED_PAGE_FIELDS:
        if field not in data:
            errors.append(f"{path.name}: missing required field '{field}'")
    if "schema_version" in data:
        sv = data["schema_version"]
        if not sv.startswith("rig.documentation.page.v"):
            errors.append(f"{path.name}: unexpected schema_version '{sv}'")
    if "document_id" in data:
        did = data["document_id"]
        if not did or not isinstance(did, str):
            errors.append(f"{path.name}: invalid document_id")
    if "sections" in data:
        sections = data["sections"]
        if not isinstance(sections, list) or len(sections) == 0:
            errors.append(f"{path.name}: sections must be non-empty array")
    return errors
