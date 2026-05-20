#!/usr/bin/env python3
"""Rig Relay Phase 2 security lifecycle replay and causal report CLI.

Reconstructs pipeline state from existing Phase 2 artifacts (Workstream B).
Generates causal/event fabric/spiderweb consolidation report (Workstream D).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.github_provider._security_lifecycle_replay import (
    build_causal_report,
    build_replay,
    write_causal_report,
    write_replay,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPLAY_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_lifecycle_replay_v1.v1.json"
)
DEFAULT_CAUSAL_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_lifecycle_causal_report_v1.v1.json"
)

_STAGE_KIND_LABELS: dict[str, str] = {
    "intake": "IN",
    "queue": "QU",
    "planning": "PL",
    "gate": "GT",
    "simulation": "SM",
    "lifecycle": "LC",
    "governance": "GV",
}

_STATUS_ICON: dict[str, str] = {
    "complete": "\u2713",
    "blocked": "\u2717",
    "degraded": "!",
    "deferred": "~",
    "missing": "-",
    "invalid": "?",
    "simulated": "S",
    "disabled": "D",
}


def _print_replay_section(replay: dict) -> None:
    print("\n-- Replay: Pipeline Stages --")
    print(f"  {'Stage':<24} {'Slice':>5} {'Kind':>4} {'Status':>10}")
    print(f"  {'-' * 24} {'-' * 5} {'-' * 4} {'-' * 10}")
    stages = replay.get("lifecycle_stages")
    if isinstance(stages, list):
        for s in stages:
            if isinstance(s, dict):
                sid = s.get("stage_id", "?")
                slc = s.get("slice", "?")
                knd = _STAGE_KIND_LABELS.get(str(s.get("kind")), "??")
                sts = s.get("status", "?")
                icon = _STATUS_ICON.get(str(sts), "?")
                print(f"  {sid:<24} {slc:>5} {knd:>4} {icon} {sts:<8}")

    print(f"\n  stages_present:  {replay.get('stages_present')}")
    print(f"  stages_missing:  {replay.get('stages_missing')}")
    print(f"  stages_complete: {replay.get('stages_complete')}")
    print(f"  stages_simulated:{replay.get('stages_simulated')}")
    print(f"  stages_blocked:  {replay.get('stages_blocked')}")

    print("\n-- Replay: Lifecycle State --")
    print(f"  PR lifecycle:     {replay.get('pr_lifecycle_state')}")
    print(f"  Alert lifecycle:  {replay.get('alert_lifecycle_state')}")
    pca = replay.get("pr_to_alert_causal_chain")
    if isinstance(pca, dict):
        print(f"  PR→Alert relation: {pca.get('relationship')}")

    print("\n-- Replay: Chains --")
    print(
        f"  Permission:        planning_stages_no_mutation={replay.get('permission_chain', {}).get('planning_stages_no_mutation')}"
    )
    print(
        f"  Mutation:          remote_mutation_detected={replay.get('mutation_chain', {}).get('remote_mutation_detected')}"
    )
    print(f"  Approval:          model={replay.get('approval_chain', {}).get('model')}")
    print(
        f"  Idempotency:       strategy={replay.get('idempotency_chain', {}).get('strategy')}"
    )
    print(f"  Next safe action:  {replay.get('next_safe_action')}")


def _print_causal_section(causal: dict) -> None:
    print("\n-- Causal Report: Links --")
    print(f"  observed:        {causal.get('observed_links')}")
    print(f"  derived:         {causal.get('derived_links')}")
    print(f"  inferred:        {causal.get('inferred_links')}")
    print(f"  correlated_only: {causal.get('correlated_only_links')}")
    print(f"  rejected:        {causal.get('rejected_links')}")
    print(f"  total_links:     {causal.get('total_links')}")
    print(f"  nodes:           {len(causal.get('causal_nodes', []))}")

    print("\n-- Causal Report: Event Fabric --")
    ef = causal.get("event_fabric_event_count", 0)
    print(f"  events referenced: {ef}")

    print("\n-- Causal Report: Spiderweb --")
    sw = causal.get("spiderweb_projection_contribution_summary")
    if isinstance(sw, dict):
        print(f"  DAG constructed:    {sw.get('pipeline_dag_constructed')}")
        print(f"  all 10 stages:      {sw.get('all_10_stages_mapped')}")
        print(f"  chain integrity:    {sw.get('causal_chain_integrity')}")
        print(f"  simulation clear:   {sw.get('simulation_boundary_clear')}")
        print(f"  alert-PR governed:  {sw.get('alert_pr_separation_governed')}")
        print(f"  evidence preserved: {sw.get('evidence_preserved')}")


def _print_summary(replay: dict, causal: dict) -> None:
    print("\nPhase 2 Security Lifecycle Replay & Causal Report")
    print("=" * 60)
    _print_replay_section(replay)
    _print_causal_section(causal)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-security-lifecycle-replay",
        description="Phase 2 security lifecycle replay (Workstream B) and causal report (Workstream D).",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_REPLAY_OUTPUT,
        help="Replay artifact output path.",
    )
    parser.add_argument(
        "--causal-output",
        type=Path,
        default=DEFAULT_CAUSAL_OUTPUT,
        help="Causal report output path.",
    )
    parser.add_argument("--generated-at-utc", type=str, default=None)
    parser.add_argument(
        "--summary", action="store_true", help="Print summary to stdout."
    )
    parser.add_argument(
        "--replay-only",
        action="store_true",
        help="Generate replay artifact only (skip causal report).",
    )
    parser.add_argument(
        "--causal-only",
        action="store_true",
        help="Generate causal report only (skip replay artifact).",
    )
    args = parser.parse_args(argv)

    replay_data: dict = {}
    causal_data: dict = {}

    if not args.causal_only:
        replay_data = write_replay(
            output_path=args.output_json, generated_at_utc=args.generated_at_utc
        )
        print(f"Replay artifact written: {args.output_json}")

    if not args.replay_only:
        causal_data = write_causal_report(
            output_path=args.causal_output, generated_at_utc=args.generated_at_utc
        )
        print(f"Causal report written: {args.causal_output}")

    if args.summary:
        replay_data = replay_data or build_replay(
            generated_at_utc=args.generated_at_utc
        )
        causal_data = causal_data or build_causal_report(
            generated_at_utc=args.generated_at_utc
        )
        _print_summary(replay_data, causal_data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
