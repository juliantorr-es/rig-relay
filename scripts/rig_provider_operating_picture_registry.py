#!/usr/bin/env python3
"""Rig Relay cross-provider operating picture registry CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.provider_registry._operating_picture_registry import (
    write_provider_operating_picture_registry,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "provider_operating_picture_registry_v1.v1.json"
)


def _print_summary(report: dict[str, object], output_json: Path) -> None:
    providers = report.get("providers")
    aggregate = report.get("aggregate_summary")
    if not isinstance(providers, list):
        providers = []
    if not isinstance(aggregate, dict):
        aggregate = {}

    headers = [
        "provider",
        "auth",
        "intake",
        "packets",
        "surface",
        "public_release_ready",
        "next_action",
    ]
    header_fmt = "  ".join(
        f"{h:<24}" if i == 0 else f"{h:<18}" for i, h in enumerate(headers)
    )
    print(header_fmt)
    print("-" * len(header_fmt))

    for entry in providers:
        if not isinstance(entry, dict):
            continue
        row = [
            str(entry.get("display_name", ""))[:24],
            str(entry.get("auth_status", ""))[:18],
            str(entry.get("intake_status", ""))[:18],
            str(entry.get("packet_status", ""))[:18],
            str(entry.get("surface_status", ""))[:18],
            str(entry.get("public_release_ready", ""))[:18],
            str(entry.get("next_recommended_action", ""))[:18],
        ]
        row_fmt = "  ".join(
            f"{v:<24}" if i == 0 else f"{v:<18}" for i, v in enumerate(row)
        )
        print(row_fmt)

    print()
    summary_rows = [
        ("providers_configured", aggregate.get("providers_configured_count")),
        ("readonly_ready", aggregate.get("providers_readonly_ready_count")),
        ("public_release_ready", aggregate.get("providers_public_release_ready_count")),
        ("remote_mutation_enabled", aggregate.get("remote_mutation_enabled_count")),
        ("refused_surfaces", aggregate.get("refused_surface_count")),
        ("stale_providers", aggregate.get("stale_provider_count")),
        ("next_global_action", aggregate.get("next_global_action")),
        ("output_json", str(output_json)),
        ("remote_mutation", report.get("remote_mutation")),
        ("content_light", report.get("content_light")),
    ]
    width = max(len(str(label)) for label, _ in summary_rows)
    for label, value in summary_rows:
        print(f"{label:<{width}}  {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-provider-operating-picture-registry",
        description="Build a cross-provider operating picture registry from provider artifacts.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output registry artifact path.",
    )
    parser.add_argument(
        "--generated-at-utc",
        type=str,
        default=None,
        help="Override generation timestamp for deterministic tests.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact content-light summary table.",
    )
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="Exit non-zero if any provider is stale.",
    )
    parser.add_argument(
        "--fail-on-remote-mutation",
        action="store_true",
        help="Exit non-zero if any provider has remote_mutation enabled.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        action="append",
        dest="providers",
        help="Only include specified providers (can repeat).",
    )
    args = parser.parse_args(argv)

    report = write_provider_operating_picture_registry(
        args.output_json,
        generated_at_utc=args.generated_at_utc,
        provider_filter=args.providers,
    )
    if args.summary:
        _print_summary(report, args.output_json)

    if args.fail_on_remote_mutation:
        providers = report.get("providers")
        if isinstance(providers, list):
            for p in providers:
                if isinstance(p, dict) and p.get("remote_mutation"):
                    return 2

    if args.fail_on_stale:
        aggregate = report.get("aggregate_summary")
        if isinstance(aggregate, dict) and aggregate.get("stale_provider_count", 0) > 0:
            return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
