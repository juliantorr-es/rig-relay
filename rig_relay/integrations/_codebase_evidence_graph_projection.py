"""Codebase Evidence Graph — Shared Projection Substrate v1.

Canonical projection layer over the codebase evidence graph. Multiple modes:
- public_static: content-light, no local paths, no session data
- cockpit_local: includes local-safe metadata, branch context
- context_digest: compact, deterministic context packet for assembler
- duckdb_read_side: DuckDB queries, counts, faceted analytics
- impact_analysis: changed-paths-to-adjacent-evidence mapping

One canonical graph → multiple projections. Zero duplication.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GRAPH_PATH = (
    _REPO_ROOT / "docs" / "json" / "governance" / "codebase_evidence_graph_v1.v1.json"
)
_GOV = _REPO_ROOT / "docs" / "json" / "governance"
_DERIVED = _REPO_ROOT / ".build" / "rig-relay" / "derived"

_FORBIDDEN_PUBLIC = frozenset({
    "absolute_path",
    "home_path",
    "session_id",
    "trace_id",
    "dirty_sha",
    "coordination_lease",
    "branch_name",
    "local_artifact_path",
})
_FORBIDDEN_COCKPIT_LOCAL = frozenset({
    "absolute_path",
    "home_path",
    "raw_source",
    "token",
    "secret",
    "credential",
})


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_graph(graph_path: Path = _GRAPH_PATH) -> dict[str, Any]:
    if not graph_path.exists():
        return {"nodes": [], "edges": [], "summary": {}, "schema_version": ""}
    return json.loads(graph_path.read_text(encoding="utf-8"))


# ══════════════════════ Projection Modes ══════════════════════


def build_projection(mode: str, graph_path: Path = _GRAPH_PATH) -> dict[str, Any]:
    graph = load_graph(graph_path)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    if mode == "public_static":
        nodes_out = [
            {k: v for k, v in n.items() if k not in _FORBIDDEN_PUBLIC} for n in nodes
        ]
        edges_out = [
            {k: v for k, v in e.items() if k not in _FORBIDDEN_PUBLIC} for e in edges
        ]
    elif mode == "cockpit_local":
        nodes_out = [
            {k: v for k, v in n.items() if k not in _FORBIDDEN_COCKPIT_LOCAL}
            for n in nodes
        ]
        edges_out = [
            {k: v for k, v in e.items() if k not in _FORBIDDEN_COCKPIT_LOCAL}
            for e in edges
        ]
    elif mode == "context_digest":
        nodes_out = [
            {
                "node_id": n.get("node_id", ""),
                "node_type": n.get("node_type", ""),
                "label": n.get("label", ""),
                "relative_path": n.get("relative_path", ""),
            }
            for n in nodes
        ]
        edges_out = [
            {
                "source": e.get("source", ""),
                "target": e.get("target", ""),
                "edge_type": e.get("edge_type", ""),
            }
            for e in edges
        ]
    elif mode == "duckdb_read_side":
        nodes_out = nodes
        edges_out = edges
    else:
        nodes_out = nodes
        edges_out = edges

    return {
        "schema_version": "rig.relay.codebase_evidence_graph_projection_manifest.v1",
        "content_light": True,
        "mode": mode,
        "total_nodes": len(nodes_out),
        "total_edges": len(edges_out),
        "nodes": nodes_out,
        "edges": edges_out,
    }


def build_context_digest(
    changed_paths: list[str] | None = None, graph_path: Path = _GRAPH_PATH
) -> dict[str, Any]:
    graph = load_graph(graph_path)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    affected_nodes: list[dict[str, Any]] = []
    adjacent: list[dict[str, Any]] = []

    if changed_paths:
        for path in changed_paths:
            node_id = _sha256_text(path)
            for n in nodes:
                if n.get("node_id") == node_id or n.get("relative_path") == path:
                    affected_nodes.append(n)
            # Find adjacent via edges
            source_id = node_id
            for e in edges:
                if e.get("source") == source_id or e.get("target") == source_id:
                    adj_id = e["target"] if e["source"] == source_id else e["source"]
                    for n in nodes:
                        if n.get("node_id") == adj_id:
                            adjacent.append(n)

    # Extract release phases, schemas, tests relevant to affected nodes
    release_phases = [n for n in nodes if n.get("node_type") == "release_phase"]
    schemas = [n for n in nodes if n.get("node_type") == "schema"]
    risks = [n for n in nodes if n.get("node_type") == "risk"]

    digest = {
        "schema_version": "rig.relay.codebase_evidence_graph_context_digest.v1",
        "content_light": True,
        "changed_paths": changed_paths or [],
        "affected_nodes": affected_nodes,
        "affected_count": len(affected_nodes),
        "adjacent_nodes": adjacent[:30],  # bounded
        "adjacent_count": len(adjacent),
        "related_release_phases": [
            {"phase_id": p.get("label", ""), "status": p.get("status", "")}
            for p in release_phases
        ],
        "schema_count": len(schemas),
        "risk_count": len(risks),
        "evidence_paths": [str(_GRAPH_PATH)],
        "deterministic": True,
    }

    _write_json(_GOV / "codebase_evidence_graph_context_digest_v1.v1.json", digest)
    return digest


def build_impact_analysis(
    changed_paths: list[str] | None = None, graph_path: Path = _GRAPH_PATH
) -> dict[str, Any]:
    if changed_paths is None:
        return {"available": False, "error": "no_changed_paths_provided"}

    graph = load_graph(graph_path)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    impacted_nodes: list[dict[str, Any]] = []
    impacted_schemas: list[str] = []
    impacted_artifacts: list[str] = []
    impacted_tests: list[str] = []

    for path in changed_paths:
        node_id = _sha256_text(path)
        for e in edges:
            if e.get("source") == node_id or e.get("target") == node_id:
                other = e["target"] if e["source"] == node_id else e["source"]
                for n in nodes:
                    if n.get("node_id") == other:
                        impacted_nodes.append(n)
                        if n.get("node_type") == "schema":
                            impacted_schemas.append(n.get("label", ""))
                        elif n.get("node_type") == "artifact":
                            impacted_artifacts.append(n.get("label", ""))
                        elif "test" in n.get("label", "").lower():
                            impacted_tests.append(n.get("label", ""))

    impact = {
        "schema_version": "rig.relay.codebase_evidence_graph_impact.v1",
        "content_light": True,
        "changed_paths": changed_paths,
        "matched_graph_nodes": len([
            n for n in nodes if n.get("relative_path") in changed_paths
        ]),
        "impacted_schemas": impacted_schemas[:20],
        "impacted_artifacts": impacted_artifacts[:20],
        "impacted_tests": impacted_tests[:20],
        "total_impacted_nodes": len(impacted_nodes),
        "confidence": "deterministic",
    }

    _write_json(_DERIVED / "codebase_evidence_graph_impact_v1.json", impact)
    return impact


def _get_changed_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return [l.strip() for l in result.stdout.split("\n") if l.strip()]
    except (OSError, subprocess.CalledProcessError):
        return []


def _get_uncommitted_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        uncommitted = [l.strip() for l in result.stdout.split("\n") if l.strip()]
        staged = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        staged_files = [l.strip() for l in staged.stdout.split("\n") if l.strip()]
        return list(set(uncommitted + staged_files))
    except (OSError, subprocess.CalledProcessError):
        return []


def build_projection_manifest(graph_path: Path = _GRAPH_PATH) -> dict[str, Any]:
    graph = load_graph(graph_path)
    summary = graph.get("summary", {})
    manifest = {
        "schema_version": "rig.relay.codebase_evidence_graph_projection_manifest.v1",
        "content_light": True,
        "graph_schema_version": graph.get("schema_version", ""),
        "graph_generated_at": graph.get("generated_at", ""),
        "total_nodes": summary.get("total_nodes", 0),
        "total_edges": summary.get("total_edges", 0),
        "node_type_counts": summary.get("node_type_counts", {}),
        "edge_type_counts": summary.get("edge_type_counts", {}),
        "available_modes": [
            "public_static",
            "cockpit_local",
            "context_digest",
            "duckdb_read_side",
            "impact_analysis",
        ],
        "public_safe": True,
        "source_artifact": str(graph_path),
    }
    _write_json(
        _GOV / "codebase_evidence_graph_projection_manifest_v1.v1.json", manifest
    )
    return manifest


__all__ = [
    "_get_changed_files",
    "_get_uncommitted_files",
    "build_context_digest",
    "build_impact_analysis",
    "build_projection",
    "build_projection_manifest",
    "load_graph",
]
