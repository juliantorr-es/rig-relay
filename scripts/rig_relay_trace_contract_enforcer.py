#!/usr/bin/env python3
"""Rig Relay Trace Contract Enforcer.

Validates that every trace event emitted in the codebase is registered
in the canonical correlation vocabulary and correlated visibility matrix,
and that every registered non-future event is emitted somewhere.

Treats the vocabulary and matrix as authority. Produces deterministic
JSON output suitable for CI gating and docs rendering.

Usage:
    uv run python scripts/rig_relay_trace_contract_enforcer.py
    uv run python scripts/rig_relay_trace_contract_enforcer.py --format text
    uv run python scripts/rig_relay_trace_contract_enforcer.py --strict
    uv run python scripts/rig_relay_trace_contract_enforcer.py --output report.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rig_relay.tracing._contract import (
    EventEmissionScanner,
    TraceContractRegistry,
    TraceContractValidator,
    build_contract_report,
)


def _format_text_report(report: dict) -> str:
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("Rig Relay Trace Contract Enforcement Report")
    lines.append("=" * 60)
    summary = report.get("summary", {})
    lines.append(f"Emitted events:    {summary.get('total_emitted', 0)}")
    lines.append(f"Registered events: {summary.get('total_registered', 0)}")
    lines.append(f"Total violations:  {summary.get('total_violations', 0)}")
    lines.append(f"  High:   {summary.get('high_severity', 0)}")
    lines.append(f"  Medium: {summary.get('medium_severity', 0)}")
    lines.append(f"  Low:    {summary.get('low_severity', 0)}")
    lines.append(f"Clean: {summary.get('clean', False)}")
    lines.append("")

    violations = report.get("violations", [])
    if violations:
        lines.append("Violations:")
        for v in violations:
            icon = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(
                str(v.get("severity", "")), "⚪"
            )
            lines.append(f"  {icon} [{v.get('kind', '?')}] {v.get('event_name', '?')}")
            lines.append(f"     {v.get('description', '')}")
            if v.get("source_file"):
                lines.append(f"     File: {v['source_file']}")
            if v.get("recommendation"):
                lines.append(f"     Fix: {v['recommendation']}")
        lines.append("")

    paths = report.get("paths", {})
    if paths:
        lines.append("Path Coverage:")
        for pid, pd in sorted(paths.items()):
            status = pd.get("visibility_status", "?")
            icon = {"complete": "✅", "partial": "⚠️", "missing": "❌"}.get(
                str(status), "❓"
            )
            lines.append(
                f"  {icon} {pid}: {status} "
                f"({pd.get('events_found', 0)} found / {pd.get('events_missing', 0)} missing)"
            )
        lines.append("")

    emitted = report.get("emitted_events", [])
    if emitted:
        lines.append(f"Emitted events ({len(emitted)}):")
        for name in emitted:
            lines.append(f"  - {name}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enforce trace contract: validate emitted events against vocabulary and matrix."
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json).",
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="Write report to file."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Exit with code 1 if any violations found.",
    )
    parser.add_argument(
        "--vocab-path",
        type=Path,
        default=None,
        help="Path to correlation vocabulary JSON.",
    )
    parser.add_argument(
        "--matrix-path",
        type=Path,
        default=None,
        help="Path to correlated visibility matrix JSON.",
    )
    args = parser.parse_args()

    registry = TraceContractRegistry(
        vocab_path=args.vocab_path, matrix_path=args.matrix_path
    )
    scanner = EventEmissionScanner()
    validator = TraceContractValidator(registry)

    emitted = scanner.scan()
    violations = validator.validate_all(emitted)
    report = build_contract_report(emitted, violations, registry)

    if args.format == "text":
        output = _format_text_report(report)
    else:
        output = json.dumps(report, indent=2, sort_keys=True, default=str)

    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(output)

    if args.strict and not validator.is_clean():
        sys.exit(1)


if __name__ == "__main__":
    main()
