#!/usr/bin/env python3
"""Rig Relay codebase evidence graph CLI."""

from __future__ import annotations

import argparse
import json

from rig_relay.integrations._codebase_evidence_graph import (
    build_codebase_evidence_graph,
)
from rig_relay.integrations._codebase_evidence_graph_projection import (
    _get_changed_files,
    _get_uncommitted_files,
    build_context_digest,
    build_impact_analysis,
    build_projection,
    build_projection_manifest,
)


def _print_summary(graph: dict[str, object]) -> None:
    summary = graph.get("summary")
    if not isinstance(summary, dict):
        return
    print("\nCodebase Evidence Graph")
    print("-" * 24)
    print(f"  total_nodes: {summary.get('total_nodes', 0)}")
    print(f"  total_edges: {summary.get('total_edges', 0)}")
    print("\n  Node types:")
    counts = summary.get("node_type_counts", {})
    if isinstance(counts, dict):
        for t, c in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"    {t:<20} {c}")
    print("\n  Edge types:")
    edge_counts = summary.get("edge_type_counts", {})
    if isinstance(edge_counts, dict):
        for t, c in sorted(edge_counts.items(), key=lambda x: -x[1]):
            print(f"    {t:<20} {c}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-codebase-evidence-graph",
        description="Build codebase evidence graph from existing artifacts.",
    )
    parser.add_argument("--generated-at-utc", type=str, default=None)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument(
        "--impact",
        action="store_true",
        help="Show impact of uncommitted changes on the graph.",
    )
    parser.add_argument(
        "--digest",
        action="store_true",
        help="Produce context digest for changed files.",
    )
    parser.add_argument(
        "--projection",
        type=str,
        choices=["public_static", "cockpit_local", "context_digest"],
        help="Build a specific projection mode.",
    )
    args = parser.parse_args(argv)
    if args.impact:
        changed = _get_uncommitted_files()
        if not changed:
            changed = _get_changed_files()
        result = build_impact_analysis(changed)
        if args.summary:
            print(f"Changed paths: {len(changed)}")
            print(f"Impacted schemas: {len(result.get('impacted_schemas', []))}")
            print(f"Impacted artifacts: {len(result.get('impacted_artifacts', []))}")
            print(f"Impacted tests: {len(result.get('impacted_tests', []))}")
        else:
            print(json.dumps(result, indent=2))
    elif args.digest:
        changed = _get_uncommitted_files()
        if not changed:
            changed = _get_changed_files()
        result = build_context_digest(changed)
        if args.summary:
            print(f"Changed: {len(changed)} paths")
            print(f"Affected nodes: {result['affected_count']}")
            print(f"Adjacent nodes: {result['adjacent_count']}")
        else:
            print(json.dumps(result, indent=2))
    elif args.projection:
        result = build_projection(args.projection)
        if args.summary:
            print(
                f"Mode: {args.projection}, nodes: {result['total_nodes']}, edges: {result['total_edges']}"
            )
        else:
            print(json.dumps(result, indent=2))
    else:
        graph = build_codebase_evidence_graph(generated_at_utc=args.generated_at_utc)
        build_projection_manifest()
        if args.summary:
            _print_summary(graph)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
