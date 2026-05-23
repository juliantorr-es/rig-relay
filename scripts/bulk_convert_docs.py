#!/usr/bin/env python3
"""Bulk Markdown-to-JSON documentation converter.

Reads Markdown files from docs/ subdirectories (governance, audits,
conversations, findings, legal, release, protocols, demo, ui, etc.)
and produces rig.documentation.page.v1 JSON output.

Skips: allowed exceptions, already-migrated files (when JSON exists).

Dry-run by default. Pass --execute to perform document mutation.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess

from rig_relay.cli.governance_guard import (
    emit_structured_result,
    require_governed_execution_with_evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"
DOCS_JSON = DOCS / "json"

_ALLOWED_MARKDOWN = {
    "AGENTS.md",
    "README.md",
    "CONTRIBUTING.md",
    "CONTRIBUTOR_LICENSE_AGREEMENT.md",
    "LICENSE",
    "ATTRIBUTION.md",
    "UPSTREAM.md",
    "THIRD_PARTY_NOTICES.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "analysis_results.md",
}

_ALREADY_MIGRATED = {
    "docs/governance/tracing-doctrine.md",
    "docs/governance/test-suite-doctrine.md",
    "docs/governance/storage-retention-policy.md",
    "docs/governance/agent-loop-boundary.md",
    "docs/governance/tool-runtime-boundary.md",
    "docs/governance/orchestrator-loop-boundary.md",
}


def _git_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT
        )
        return r.stdout.strip()[:12]
    except Exception:
        return "unknown"


def _doc_id(md_path: str) -> str:
    """Derive a stable document_id from the Markdown path."""
    stem = Path(md_path).stem
    # Replace underscores already present, then add kebab-case
    return stem.replace("_", "-").lower()


def _json_path(md_path: str) -> str:
    """Map Markdown path to JSON output path."""
    rel = Path(md_path)
    parent = str(rel.parent).replace("docs/", "docs/json/", 1)
    return f"{parent}/{rel.stem}.v1.json"


def _md_to_blocks(text: str) -> list[dict]:  # noqa: PLR0915
    """Convert Markdown text to structured blocks."""
    blocks: list[dict] = []
    lines = text.split("\n")
    i = 0
    bid_counter = 0

    def _bid(kind: str) -> str:
        nonlocal bid_counter
        bid_counter += 1
        return f"{kind}-{bid_counter}"

    while i < len(lines):
        line = lines[i]

        # Skip empty
        if not line.strip():
            i += 1
            continue

        # Heading
        if line.startswith("# "):
            blocks.append({
                "block_id": _bid("h1"),
                "type": "heading",
                "level": 1,
                "content": line[2:].strip(),
            })
            i += 1
            continue

        if line.startswith("## "):
            blocks.append({
                "block_id": _bid("h2"),
                "type": "heading",
                "level": 2,
                "content": line[2:].strip(),
            })
            i += 1
            continue

        if line.startswith("### "):
            blocks.append({
                "block_id": _bid("h3"),
                "type": "heading",
                "level": 3,
                "content": line[3:].strip(),
            })
            i += 1
            continue

        # Code block
        if line.startswith("```"):
            lang = line[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            blocks.append({
                "block_id": _bid("code"),
                "type": "code",
                "language": lang or "text",
                "content": "\n".join(code_lines),
            })
            continue

        # Table detection: next line has |---|---|
        if (
            "|" in line
            and i + 1 < len(lines)
            and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip())
        ):
            header = [c.strip() for c in line.split("|") if c.strip()]
            i += 2  # skip separator
            rows = []
            while i < len(lines) and "|" in lines[i]:
                rows.append([c.strip() for c in lines[i].split("|") if c.strip()])
                i += 1
            blocks.append({
                "block_id": _bid("table"),
                "type": "table",
                "columns": header,
                "rows": rows,
            })
            continue

        # Paragraph — accumulate until blank line
        para_lines = []
        while (
            i < len(lines)
            and lines[i].strip()
            and not lines[i].startswith("#")
            and not lines[i].startswith("```")
            and not (
                "|" in lines[i]
                and i + 1 < len(lines)
                and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip())
            )
        ):
            para_lines.append(lines[i].strip())
            i += 1
        if para_lines:
            blocks.append({
                "block_id": _bid("p"),
                "type": "paragraph",
                "content": " ".join(para_lines),
            })
        else:
            i += 1

    return blocks


def _first_heading(text: str) -> str:
    for line in text.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return "Untitled"


def _first_paragraph(text: str) -> str:
    for line in text.split("\n"):
        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith("#")
            and not stripped.startswith("```")
            and "|" not in stripped
        ):
            return stripped[:200]
    return ""


def convert_file(md_path: str, git_sha: str) -> tuple[str, dict] | None:
    """Convert a single Markdown file to JSON. Returns (json_path, data) or None."""
    full_path = REPO_ROOT / md_path
    if not full_path.is_file():
        return None

    text = full_path.read_text(encoding="utf-8")

    json_path = _json_path(md_path)
    doc_id = _doc_id(md_path)

    data = {
        "schema_version": "rig.documentation.page.v1",
        "document_id": doc_id,
        "document_type": _doc_type(md_path),
        "title": _first_heading(text),
        "summary": _first_paragraph(text),
        "status": "active",
        "created_at": datetime.now().strftime("%Y-%m-%d"),
        "updated_at": datetime.now().strftime("%Y-%m-%d"),
        "source_commit": git_sha,
        "owners": ["maintainer"],
        "tags": [],
        "audience": ["contributor", "maintainer"],
        "canonical_path": json_path,
        "render": {"toc": True, "search_index": True},
        "sections": _md_to_blocks(text),
        "references": [],
        "related_documents": [],
        "provenance": {"source_files": [md_path]},
    }

    return json_path, data


def _doc_type(md_path: str) -> str:  # noqa: PLR0911
    if "/governance/" in md_path:
        return "governance"
    if "/audits/" in md_path:
        return "audit"
    if "/conversations/" in md_path:
        return "report"
    if "/findings/" in md_path:
        return "findings"
    if "/legal/" in md_path:
        return "legal"
    if "/release/" in md_path:
        return "reference"
    if "/protocols/" in md_path:
        return "reference"
    if "/demo/" in md_path:
        return "guide"
    if "/ui/" in md_path:
        return "audit"
    return "reference"


def _count_dry_run() -> tuple[int, int, int, int]:
    converted = 0
    skipped_allowed = 0
    skipped_migrated = 0
    skipped_no_content = 0

    for md_path in sorted(Path("docs").rglob("*.md")):
        rel = str(md_path)
        if Path(rel).name in _ALLOWED_MARKDOWN and md_path.parent == Path("."):
            skipped_allowed += 1
            continue
        if rel in _ALREADY_MIGRATED:
            skipped_migrated += 1
            continue
        json_path = _json_path(rel)
        if (REPO_ROOT / json_path).exists():
            skipped_migrated += 1
            continue
        full_path = REPO_ROOT / rel
        if not full_path.is_file():
            skipped_no_content += 1
            continue
        converted += 1

    return converted, skipped_allowed, skipped_migrated, skipped_no_content


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bulk Markdown-to-JSON documentation converter."
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
        script_name="bulk_convert_docs",
        authority_tier="local_mutation",
        capability_id="doc_bulk_convert",
        execute_requested=args.execute,
    )

    if not args.execute:
        converted, skipped_allowed, skipped_migrated, skipped_no_content = (
            _count_dry_run()
        )
        print(
            f"DRY-RUN: Would convert {converted} Markdown files to JSON. Pass --execute to proceed."
        )
        print(f"  Skipped (allowed exceptions): {skipped_allowed}")
        print(f"  Skipped (already migrated): {skipped_migrated}")
        print(f"  Skipped (no content): {skipped_no_content}")
        if args.json:
            r = emit_structured_result(
                script_name="bulk_convert_docs",
                authority_tier="local_mutation",
                capability_id="doc_bulk_convert",
                dry_run=True,
                execute_requested=False,
                decision=governed.decision,
                status="dry_run",
            )
            print(json.dumps(r, indent=2))
        return 0

    if not governed.can_execute:
        r = emit_structured_result(
            script_name="bulk_convert_docs",
            authority_tier="local_mutation",
            capability_id="doc_bulk_convert",
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
                print("  EVIDENCE: persistence failed — convert blocked (fail-closed)")
        return 1

    git_sha = _git_sha()
    converted = 0
    skipped_allowed = 0
    skipped_migrated = 0
    skipped_no_content = 0

    for md_path in sorted(Path("docs").rglob("*.md")):
        rel = str(md_path)
        if Path(rel).name in _ALLOWED_MARKDOWN and md_path.parent == Path("."):
            skipped_allowed += 1
            continue
        if rel in _ALREADY_MIGRATED:
            skipped_migrated += 1
            continue
        json_path = _json_path(rel)
        if (REPO_ROOT / json_path).exists():
            skipped_migrated += 1
            continue

        result = convert_file(rel, git_sha)
        if result is None:
            skipped_no_content += 1
            continue

        out_path_str, data = result
        out_path = REPO_ROOT / out_path_str
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        converted += 1

    print(f"Converted: {converted}")
    print(f"Skipped (allowed): {skipped_allowed}")
    print(f"Skipped (already migrated): {skipped_migrated}")

    if args.json:
        r = emit_structured_result(
            script_name="bulk_convert_docs",
            authority_tier="local_mutation",
            capability_id="doc_bulk_convert",
            dry_run=False,
            execute_requested=True,
            decision=governed.decision,
            status="executed",
            can_execute=True,
            evidence_ref=governed.evidence_ref,
            evidence_status=governed.evidence_status,
            artifacts={
                "converted": converted,
                "skipped_allowed": skipped_allowed,
                "skipped_migrated": skipped_migrated,
            },
        )
        print(json.dumps(r, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
