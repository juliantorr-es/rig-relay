"""Codebase Evidence Graph v1 — deterministic, content-light, zero new dependencies.

Scans existing Rig Relay artifacts, schemas, source files, receipts, release gate data,
and provider registries to build a governed graph of nodes (file, module, schema, etc.)
and edges (depends_on, tests, validates_artifact, etc.).

Uses stdlib ast, json, csv, pathlib, subprocess. DuckDB for read-side projection only.
Content-light: never stores raw source, absolute paths, or token/secret data.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GOV = _REPO_ROOT / "docs" / "json" / "governance"
_SCHEMAS = _REPO_ROOT / "docs" / "schemas"
_RALPH = Path.home() / ".rig" / "ralph" / "receipts"
_BUILD = _REPO_ROOT / ".build" / "rig-relay"
_DERIVED = _BUILD / "derived"

_DEFAULT_GRAPH = _GOV / "codebase_evidence_graph_v1.v1.json"
_DEFAULT_NODES = _DERIVED / "codebase_evidence_graph_nodes_v1.csv"
_DEFAULT_EDGES = _DERIVED / "codebase_evidence_graph_edges_v1.csv"

_FORBIDDEN = frozenset({
    "access_token",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "code_snippet",
    "vulnerable_code",
    "secret_value",
    "source_content",
})


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


# ══════════════════════ v0.1: Artifact + Receipt Scanner ══════════════════════


def scan_artifacts(directory: Path = _GOV) -> list[dict[str, Any]]:
    artifacts = []
    for path in sorted(directory.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            artifacts.append({
                "node_id": _sha256_text(str(path.relative_to(_REPO_ROOT))),
                "node_type": "artifact",
                "label": path.name,
                "relative_path": str(path.relative_to(_REPO_ROOT)),
                "schema_version": data.get("schema_version", "unknown"),
                "content_light": data.get("content_light", True),
                "remote_mutation": data.get("remote_mutation", True),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            })
        except (json.JSONDecodeError, OSError):
            pass
    return artifacts


def scan_receipts(directory: Path = _RALPH) -> list[dict[str, Any]]:
    receipts = []
    if not directory.exists():
        return receipts
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            receipts.append({
                "node_id": _sha256_text(data.get("receipt_id", path.name)),
                "node_type": "receipt",
                "label": data.get("receipt_id", path.name)[:40],
                "receipt_id": data.get("receipt_id", ""),
                "event_sha256": data.get("event_sha256", ""),
                "decision_action": data.get("decision_action", ""),
                "status": data.get("status", ""),
                "created_at": data.get("created_at", ""),
            })
        except (json.JSONDecodeError, OSError):
            pass
    return receipts


# ══════════════════════ v0.2: Schema Scanner ══════════════════════


def scan_schemas(directory: Path = _SCHEMAS) -> list[dict[str, Any]]:
    schemas = []
    for path in sorted(directory.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            schemas.append({
                "node_id": _sha256_text(str(path.relative_to(_REPO_ROOT))),
                "node_type": "schema",
                "label": path.name,
                "relative_path": str(path.relative_to(_REPO_ROOT)),
                "schema_id": data.get("$id", ""),
                "title": data.get("title", ""),
            })
        except (json.JSONDecodeError, OSError):
            pass
    return schemas


def build_validates_edges(
    artifacts: list[dict[str, Any]], schemas: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    edges = []
    schema_versions = {s["node_id"]: s.get("schema_id", "") for s in schemas}
    for art in artifacts:
        sv = art.get("schema_version", "")
        for sid, schema_id in schema_versions.items():
            if (
                sv in schema_id
                or sv.replace(".v1.v1", ".v1").replace(".v1", "") in schema_id
            ):
                edges.append({
                    "source": sid,
                    "target": art["node_id"],
                    "edge_type": "validates_artifact",
                })
    return edges


# ══════════════════════ v0.3: File + Symbol Scanner ══════════════════════


def scan_files() -> list[dict[str, Any]]:
    files = []
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.split("\0"):
            line = line.strip()
            if not line or line.startswith(".") or "test" in line.lower():
                continue
            p = _REPO_ROOT / line
            if not p.exists():
                continue
            ext = p.suffix.lower()
            is_py = ext == ".py"
            is_schema = ".schema.json" in p.name
            is_json = ext == ".json" and not is_schema
            files.append({
                "node_id": _sha256_text(line),
                "node_type": "file",
                "label": Path(line).name,
                "relative_path": line,
                "extension": ext,
                "is_python": is_py,
                "is_schema": is_schema,
                "is_json": is_json,
                "line_count": len(p.read_text(encoding="utf-8").splitlines())
                if is_py
                else 0,
            })
    except (OSError, subprocess.CalledProcessError):
        pass
    return files


def scan_imports(py_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract module-to-module depends_on edges from Python import statements."""
    edges = []
    rig_prefix = "rig_relay"
    for f in py_files:
        if not f.get("is_python"):
            continue
        p = _REPO_ROOT / f["relative_path"]
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
            source_id = f["node_id"]
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(rig_prefix):
                            target_id = _sha256_text(
                                alias.name.replace(".", "/") + ".py"
                            )
                            edges.append({
                                "source": source_id,
                                "target": target_id,
                                "edge_type": "depends_on",
                            })
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith(rig_prefix):
                        target_id = _sha256_text(node.module.replace(".", "/") + ".py")
                        edges.append({
                            "source": source_id,
                            "target": target_id,
                            "edge_type": "depends_on",
                        })
        except (SyntaxError, OSError, UnicodeDecodeError):
            pass
    return edges


def scan_module_symbols(py_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract module, class, and function nodes from Python files."""
    symbols = []
    for f in py_files:
        if not f.get("is_python"):
            continue
        p = _REPO_ROOT / f["relative_path"]
        path_str = f["relative_path"]
        # Module node
        module_id = _sha256_text(f"{path_str}:module")
        class_count = 0
        func_count = 0
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    symbols.append({
                        "node_id": _sha256_text(f"{path_str}:class:{node.name}"),
                        "node_type": "class",
                        "label": node.name,
                        "source_file_id": f["node_id"],
                        "module_path": path_str,
                    })
                    class_count += 1
                elif isinstance(node, ast.FunctionDef):
                    symbols.append({
                        "node_id": _sha256_text(f"{path_str}:func:{node.name}"),
                        "node_type": "function",
                        "label": node.name,
                        "source_file_id": f["node_id"],
                        "module_path": path_str,
                    })
                    func_count += 1
        except (SyntaxError, OSError, UnicodeDecodeError):
            pass
        symbols.append({
            "node_id": module_id,
            "node_type": "module",
            "label": Path(path_str).stem,
            "relative_path": path_str,
            "source_file_id": f["node_id"],
            "class_count": class_count,
            "function_count": func_count,
        })
    return symbols


def scan_test_edges(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges = []
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        test_files = [
            l.strip()
            for l in result.stdout.split("\0")
            if l.strip() and "test" in l.strip().lower() and l.strip().endswith(".py")
        ]
        for tf in test_files:
            test_id = _sha256_text(tf)
            # Heuristic: test_X.py tests X.py (same relative path, strip test_ prefix)
            tf_dir = str(Path(tf).parent)
            tf_name = Path(tf).name
            for f in files:
                if not f.get("is_python"):
                    continue
                fp = Path(f["relative_path"])
                if str(fp.parent) == tf_dir:
                    source_name = (
                        tf_name
                        .replace("test_", "")
                        .replace("_test", "")
                        .replace("test", "")
                    )
                    if source_name in fp.name:
                        edges.append({
                            "source": test_id,
                            "target": f["node_id"],
                            "edge_type": "tests",
                        })
    except (OSError, subprocess.CalledProcessError):
        pass
    return edges


# ══════════════════════ v0.4: Release Gate + Provider Scanner ══════════════════════


def scan_release_gate() -> list[dict[str, Any]]:
    nodes = []
    gate_path = _GOV / ".." / "release_gate" / "rc_readiness_gate.v1.json"
    if not gate_path.exists():
        gate_path = (
            _REPO_ROOT / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json"
        )
    if not gate_path.exists():
        return nodes
    try:
        data = json.loads(gate_path.read_text(encoding="utf-8"))
        for phase in data.get("phases", []):
            nodes.append({
                "node_id": _sha256_text(f"release_phase:{phase.get('phase_id', '')}"),
                "node_type": "release_phase",
                "label": phase.get("phase_id", ""),
                "status": phase.get("status", ""),
                "blocker_count": len(phase.get("blocker_ids", [])),
            })
    except (json.JSONDecodeError, OSError):
        pass
    return nodes


def scan_providers() -> list[dict[str, Any]]:
    nodes = []
    reg_path = _GOV / "provider_operating_picture_registry_v1.v1.json"
    if not reg_path.exists():
        return nodes
    try:
        data = json.loads(reg_path.read_text(encoding="utf-8"))
        for p in data.get("providers", []):
            nodes.append({
                "node_id": _sha256_text(f"provider:{p.get('provider_id', '')}"),
                "node_type": "provider",
                "label": p.get("display_name", p.get("provider_id", "")),
                "provider_id": p.get("provider_id", ""),
                "risk_level": p.get("risk_level", ""),
            })
    except (json.JSONDecodeError, OSError):
        pass
    return nodes


def scan_dependency_csv() -> list[dict[str, Any]]:
    nodes = []
    csv_path = _DERIVED / "dependency_surface_audit_v1.csv"
    if not csv_path.exists():
        return nodes
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                nodes.append({
                    "node_id": _sha256_text(f"dep:{row.get('package', '')}"),
                    "node_type": "dependency",
                    "label": row.get("package", ""),
                    "risk_surface": row.get("risk_surface", ""),
                    "import_count": int(row.get("import_count", 0)),
                })
    except (OSError, KeyError):
        pass
    return nodes


# ══════════════════════ Graph Builder ══════════════════════


def build_codebase_evidence_graph(
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    gen_at = generated_at_utc or _now_iso()

    # v0.1: artifacts + receipts
    artifacts = scan_artifacts()
    receipts = scan_receipts()

    # v0.2: schemas + validates edges
    schemas = scan_schemas()
    validates_edges = build_validates_edges(artifacts, schemas)

    # v0.3: files + symbols + imports + tests
    files = scan_files()
    py_files = [f for f in files if f.get("is_python")]
    import_edges = scan_imports(py_files)
    symbols = scan_module_symbols(py_files)
    test_edges = scan_test_edges(files)

    # v0.4: release gate + providers + dependencies
    release_phases = scan_release_gate()
    providers = scan_providers()
    dependencies = scan_dependency_csv()

    # Assemble all nodes
    all_nodes = (
        artifacts
        + receipts
        + schemas
        + files
        + symbols
        + release_phases
        + providers
        + dependencies
    )
    all_edges = validates_edges + import_edges + test_edges

    graph = {
        "schema_version": "rig.relay.codebase_evidence_graph.v1",
        "generated_at": gen_at,
        "content_light": True,
        "remote_mutation": False,
        "summary": {
            "total_nodes": len(all_nodes),
            "total_edges": len(all_edges),
            "node_type_counts": {},
            "edge_type_counts": {},
            "scanners_run": 9,
        },
        "nodes": all_nodes,
        "edges": all_edges,
    }

    # Count node/edge types
    for n in all_nodes:
        t = n["node_type"]
        graph["summary"]["node_type_counts"][t] = (
            graph["summary"]["node_type_counts"].get(t, 0) + 1
        )
    for e in all_edges:
        t = e["edge_type"]
        graph["summary"]["edge_type_counts"][t] = (
            graph["summary"]["edge_type_counts"].get(t, 0) + 1
        )

    # Write graph
    _DEFAULT_GRAPH.write_text(
        json.dumps(graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Write derived CSVs
    _DERIVED.mkdir(parents=True, exist_ok=True)
    with open(_DEFAULT_NODES, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["node_id", "node_type", "label"])
        w.writeheader()
        for n in all_nodes:
            w.writerow({k: n.get(k, "") for k in w.fieldnames})
    with open(_DEFAULT_EDGES, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["source", "target", "edge_type"])
        w.writeheader()
        for e in all_edges:
            w.writerow(e)

    # Redaction check — scan graph-level fields only, not artifact data values
    for node in all_nodes:
        for k in node:
            if k in _FORBIDDEN:
                raise ValueError(f"forbidden_key_in_graph_node: {k}")
    for edge in all_edges:
        for k in edge:
            if k in _FORBIDDEN:
                raise ValueError(f"forbidden_key_in_graph_edge: {k}")

    return graph


__all__ = [
    "build_codebase_evidence_graph",
    "scan_artifacts",
    "scan_dependency_csv",
    "scan_files",
    "scan_imports",
    "scan_module_symbols",
    "scan_providers",
    "scan_receipts",
    "scan_release_gate",
    "scan_schemas",
    "scan_test_edges",
]
