#!/usr/bin/env python3
"""Rig Relay code scanning patch preview CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.github_provider._code_scanning_patch_preview import (
    write_code_scanning_patch_preview,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_patch_preview_v1.v1.json"
)


def _print_summary(report: dict[str, object]) -> None:
    print("\nCode Scanning Patch Preview Summary")
    print("-" * 40)
    raw_blocked = report.get("blocked_reasons")
    blocked_str = ", ".join(raw_blocked) if isinstance(raw_blocked, list) else "none"
    rows = [
        ("preview_status", report.get("patch_preview_status")),
        ("alert_number", report.get("alert_number")),
        ("severity", report.get("severity")),
        ("diff_path", report.get("diff_preview_path")),
        (
            "diff_sha256",
            str(report.get("diff_preview_sha256", ""))[:16] + "..."
            if report.get("diff_preview_sha256")
            else "N/A",
        ),
        ("diff_bytes", report.get("diff_preview_bytes")),
        ("diff_lines", report.get("diff_preview_line_count")),
        ("diff_class", report.get("diff_content_classification")),
        ("remote_mutation", report.get("remote_mutation_status")),
        ("pr_creation", report.get("pr_creation_status")),
        (("blocked", blocked_str),),
    ]
    for label, value in rows:
        print(f"  {label:<16} {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-code-scanning-patch-preview",
        description="Generate dry-run patch preview.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at-utc", type=str, default=None)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    report = write_code_scanning_patch_preview(
        output_path=args.output_json, generated_at_utc=args.generated_at_utc
    )
    if args.summary:
        _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
