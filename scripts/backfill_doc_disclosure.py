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

Dry-run by default. Pass --execute to perform document mutation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.cli.governance_guard import (
    emit_structured_result,
    require_governed_execution_with_evidence,
)

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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill disclosure metadata into JSON documentation pages."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Execute document mutation. Default is dry-run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit structured JSON output.",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args()

    governed = require_governed_execution_with_evidence(
        script_name="backfill_doc_disclosure",
        authority_tier="local_mutation",
        capability_id="doc_disclosure_backfill",
        execute_requested=args.execute,
    )

    if not args.execute:
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
            if "disclosure" not in data:
                changed = True
            else:
                for section in data.get("sections", []):
                    if "disclosure" not in section:
                        changed = True
                        break
            if changed:
                count += 1
        print(
            f"DRY-RUN: Would backfill disclosure for {count} pages. Pass --execute to proceed."
        )
        if args.json:
            r = emit_structured_result(
                script_name="backfill_doc_disclosure",
                authority_tier="local_mutation",
                capability_id="doc_disclosure_backfill",
                dry_run=True,
                execute_requested=False,
                decision=governed.decision,
                status="dry_run",
            )
            print(json.dumps(r, indent=2))
        return 0

    if not governed.can_execute:
        r = emit_structured_result(
            script_name="backfill_doc_disclosure",
            authority_tier="local_mutation",
            capability_id="doc_disclosure_backfill",
            dry_run=False,
            execute_requested=True,
            decision=governed.decision,
            status="blocked_by_governance",
            can_execute=False,
            evidence_ref=governed.evidence_ref,
            evidence_status=governed.evidence_status,
        )
        if args.json:
            print(json.dumps(r, indent=2))
        else:
            print(f"BLOCKED: {governed.decision.decision.value}")
            if governed.evidence_status == "persistence_failed":
                print("  EVIDENCE: persistence failed — backfill blocked (fail-closed)")
        return 1

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

    if args.json:
        r = emit_structured_result(
            script_name="backfill_doc_disclosure",
            authority_tier="local_mutation",
            capability_id="doc_disclosure_backfill",
            dry_run=False,
            execute_requested=True,
            decision=governed.decision,
            status="executed",
            can_execute=True,
            evidence_ref=governed.evidence_ref,
            evidence_status=governed.evidence_status,
            artifacts={"pages_updated": count},
        )
        print(json.dumps(r, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
