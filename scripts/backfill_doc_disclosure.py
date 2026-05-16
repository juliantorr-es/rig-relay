#!/usr/bin/env python3
"""Backfill disclosure metadata into existing JSON documentation pages.

Applies default disclosure behavior when missing:
- document default: standard
- block default: standard
- headings/paragraphs: standard
- code/json/schema_ref: detailed
- test_evidence: detailed
- risk (high severity): standard, initially_visible
- risk (low/medium): detailed, collapsible
- decision: standard
- file_reference: detailed
- large tables: detailed, collapsible

Does NOT overwrite existing disclosure metadata.
"""

from __future__ import annotations

import json
from pathlib import Path

DOCS_JSON = Path(__file__).resolve().parents[1] / "docs" / "json"

_DOC_DISCLOSURE = {
    "default_level": "standard",
    "available_levels": ["summary", "standard", "detailed", "exhaustive"],
    "render_strategy": "linear",
    "show_table_of_contents": True,
}


def _block_disclosure(block: dict) -> dict:
    btype = block.get("type", "paragraph")
    severity = block.get("severity", "")

    if btype == "heading":
        return {"level": "standard", "initially_visible": True}
    if btype == "paragraph":
        return {"level": "standard"}
    if btype in ("code", "json", "schema_ref"):
        return {"level": "detailed", "collapsible": True, "collapsed_by_default": True}
    if btype == "test_evidence":
        return {"level": "detailed"}
    if btype == "risk":
        if severity in ("error", "critical"):
            return {"level": "standard", "initially_visible": True}
        return {"level": "detailed", "collapsible": True}
    if btype == "decision":
        return {"level": "standard"}
    if btype == "file_reference":
        return {"level": "detailed"}
    if btype == "table":
        rows = block.get("rows", [])
        if len(rows) > 10:
            return {"level": "detailed", "collapsible": True}
        return {"level": "standard"}
    if btype == "callout":
        return {"level": "standard", "initially_visible": True}
    if btype == "list":
        items = block.get("items", [])
        if len(items) > 15:
            return {"level": "detailed", "collapsible": True}
        return {"level": "standard"}
    return {"level": "standard"}


def main() -> int:
    count = 0
    for jf in sorted(DOCS_JSON.rglob("*.json")):
        if jf.name in (
            "site_manifest.v1.json",
            "documentation_migration_manifest.v1.json",
        ):
            continue
        try:
            data = json.loads(jf.read_text())
        except Exception:
            continue

        sv = data.get("schema_version", "")
        if not sv.startswith("rig.documentation.page.v"):
            continue

        changed = False

        # Document-level
        if "disclosure" not in data:
            data["disclosure"] = dict(_DOC_DISCLOSURE)
            changed = True

        # Block-level
        for section in data.get("sections", []):
            if "disclosure" not in section:
                section["disclosure"] = _block_disclosure(section)
                changed = True

        if changed:
            jf.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            count += 1

    print(f"Backfilled disclosure for {count} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
