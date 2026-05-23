#!/usr/bin/env python3
"""Render canonical JSON documentation to static HTML.

Loads docs/json/**/*.json, validates basic structure, builds navigation
from docs/json/site_manifest.v1.json, and renders static HTML into docs/.

Output:
  docs/index.html
  docs/pages/<document_id>.html
  docs/assets/site.css
  docs/search-index.json
  docs/render-manifest.json
  docs/.nojekyll

Usage:
  uv run python scripts/render_static_docs.py              # dry-run
  uv run python scripts/render_static_docs.py --execute     # render + publish

Governance-gated: rendering writes public HTML to docs/ which is published
via GitHub Pages. --execute is required for the actual render pass.
"""

from __future__ import annotations

import argparse
import json

from rig_relay.cli.governance_guard import (
    emit_structured_result,
    require_governed_execution_with_evidence,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render canonical JSON documentation to static HTML."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Execute the full render pass. Default is dry-run.",
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
        script_name="render_static_docs",
        authority_tier="local_mutation",
        capability_id="static_docs_render",
        execute_requested=args.execute,
    )

    if not args.execute:
        print("DRY-RUN: Would render static docs. Pass --execute to proceed.")
        if args.json:
            r = emit_structured_result(
                script_name="render_static_docs",
                authority_tier="local_mutation",
                capability_id="static_docs_render",
                dry_run=True,
                execute_requested=False,
                decision=governed.decision,
                status="dry_run",
            )
            print(json.dumps(r, indent=2))
        return 0

    if not governed.can_execute:
        r = emit_structured_result(
            script_name="render_static_docs",
            authority_tier="local_mutation",
            capability_id="static_docs_render",
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
                print("  EVIDENCE: persistence failed — render blocked (fail-closed)")
        return 1

    from rig_relay.docs_renderer.cli import main as _render_main

    exit_code = _render_main()

    if args.json:
        r = emit_structured_result(
            script_name="render_static_docs",
            authority_tier="local_mutation",
            capability_id="static_docs_render",
            dry_run=False,
            execute_requested=True,
            decision=governed.decision,
            status="executed" if exit_code == 0 else "failed",
            can_execute=True,
            evidence_ref=governed.evidence_ref,
            evidence_status=governed.evidence_status,
        )
        print(json.dumps(r, indent=2))

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
