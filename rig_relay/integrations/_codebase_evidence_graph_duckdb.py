"""Codebase Evidence Graph — DuckDB Read-Side Projection v0.5.

Read-only queries over the canonical graph JSON. Content-light.
Uses existing in-memory DuckDB connection factory pattern.
Zero new dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GRAPH_PATH = (
    _REPO_ROOT / "docs" / "json" / "governance" / "codebase_evidence_graph_v1.v1.json"
)
_DERIVED = _REPO_ROOT / ".build" / "rig-relay" / "derived"


def _duckdb_connection() -> Any:
    import duckdb

    return duckdb.connect(":memory:")


def build_duckdb_projection(graph_path: Path = _GRAPH_PATH) -> dict[str, Any]:  # noqa: PLR0914
    if not graph_path.exists():
        return {"available": False, "error": "graph_artifact_missing"}

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    con = _duckdb_connection()

    # Load nodes as table
    con.execute(
        "CREATE TABLE nodes AS SELECT * FROM read_json_auto(?)", [json.dumps(nodes)]
    )

    # Load edges as table
    con.execute(
        "CREATE TABLE edges AS SELECT * FROM read_json_auto(?)", [json.dumps(edges)]
    )

    # Top nodes by type
    node_counts = con.execute("""
        SELECT node_type, count(*) as cnt FROM nodes
        GROUP BY node_type ORDER BY cnt DESC
    """).fetchall()
    node_breakdown = [{"node_type": r[0], "count": r[1]} for r in node_counts]

    # Top edge types
    edge_counts = con.execute("""
        SELECT edge_type, count(*) as cnt FROM edges
        GROUP BY edge_type ORDER BY cnt DESC
    """).fetchall()
    edge_breakdown = [{"edge_type": r[0], "count": r[1]} for r in edge_counts]

    # Most-connected nodes (by edge degree)
    degree = con.execute("""
        WITH node_deg AS (
            SELECT source as node_id FROM edges
            UNION ALL
            SELECT target as node_id FROM edges
        )
        SELECT n.node_id, n.node_type, n.label, count(*) as degree
        FROM node_deg d
        LEFT JOIN nodes n ON d.node_id = n.node_id
        GROUP BY n.node_id, n.node_type, n.label
        ORDER BY degree DESC LIMIT 15
    """).fetchall()
    top_nodes = [
        {"node_id": r[0][:16], "node_type": r[1], "label": r[2], "degree": r[3]}
        for r in degree
    ]

    # Dependencies: which modules have the most dependencies?
    dep_counts = con.execute("""
        SELECT n.label, n.node_type, count(*) as dep_count
        FROM edges e
        JOIN nodes n ON e.source = n.node_id
        WHERE e.edge_type = 'depends_on' AND n.node_type = 'module'
        GROUP BY n.label, n.node_type
        ORDER BY dep_count DESC LIMIT 10
    """).fetchall()
    top_dependencies = [{"label": r[0], "dep_count": r[2]} for r in dep_counts]

    # Schema coverage: how many artifacts does each schema validate?
    schema_cov = con.execute("""
        SELECT n.label, count(*) as coverage
        FROM edges e
        JOIN nodes n ON e.source = n.node_id
        WHERE e.edge_type = 'validates_artifact'
        GROUP BY n.label
        ORDER BY coverage DESC LIMIT 10
    """).fetchall()
    schema_coverage = [
        {"schema": r[0], "artifacts_validated": r[1]} for r in schema_cov
    ]

    con.close()

    projection = {
        "schema_version": "rig.relay.codebase_evidence_graph_duckdb_projection.v1",
        "content_light": True,
        "graph_loaded": True,
        "summary": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "node_type_breakdown": node_breakdown,
            "edge_type_breakdown": edge_breakdown,
            "top_connected_nodes": top_nodes,
            "top_dependency_modules": top_dependencies,
            "schema_coverage": schema_coverage,
        },
    }

    out_path = _DERIVED / "codebase_evidence_graph_duckdb_projection_v1.json"
    out_path.write_text(
        json.dumps(projection, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return projection


__all__ = ["build_duckdb_projection"]
