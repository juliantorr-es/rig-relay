"""Rig Relay Dataset Inspector Library.

Reusable data-loading and summary helpers for Rig Relay derived datasets.
Designed to be used by both the marimo notebook and unit tests.

Content-light: never reads raw prompts, model outputs, file contents,
stdout/stderr bodies, or raw private code paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

DERIVED_DIR = Path.home() / ".build" / "rig-relay" / "derived"

# If the standard derived dir doesn't work in dev, try repo-relative
_REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_DERIVED_DIR = _REPO_ROOT / ".build" / "rig-relay" / "derived"

import duckdb

# ── Dataclasses ──────────────────────────────────────────────────────────


@dataclass
class InspectorSummary:
    """Aggregate summary of all derived datasets."""

    total_sessions: int = 0
    total_coordination_rows: int = 0
    total_conflict_rows: int = 0
    total_artifact_reuse_rows: int = 0
    total_checkpoint_rows: int = 0
    total_tool_failure_rows: int = 0
    total_provider_perf_rows: int = 0
    total_finding_rows: int = 0
    export_timestamp: str = ""
    export_warnings: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    empty_datasets: list[str] = field(default_factory=list)
    schema_validation_results: dict[str, dict[str, Any]] = field(default_factory=dict)


# ── Data loading ─────────────────────────────────────────────────────────


def _find_derived_dir() -> Path:
    """Return the first available derived datasets directory."""
    if REPO_DERIVED_DIR.is_dir():
        return REPO_DERIVED_DIR
    if DERIVED_DIR.is_dir():
        return DERIVED_DIR
    return REPO_DERIVED_DIR


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file, skipping malformed lines."""
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    return rows


def _load_manifest(path: Path) -> dict[str, Any] | None:
    """Load the export manifest (single JSONL row)."""
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as f:
        line = f.readline()
        if line:
            try:
                return json.loads(line.strip())
            except json.JSONDecodeError:
                return None
    return None


@dataclass
class DerivedDatasets:
    """Container for all loaded derived datasets."""

    coordination: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    artifact_reuse: list[dict[str, Any]] = field(default_factory=list)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    tool_failures: list[dict[str, Any]] = field(default_factory=list)
    provider_perf: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    manifest: dict[str, Any] | None = None
    missing_files: list[str] = field(default_factory=list)
    load_warnings: list[str] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return (
            len(self.coordination)
            + len(self.conflicts)
            + len(self.artifact_reuse)
            + len(self.checkpoints)
            + len(self.tool_failures)
            + len(self.provider_perf)
            + len(self.findings)
        )


def load_all(derived_dir: Path | None = None) -> DerivedDatasets:
    """Load all derived datasets from a directory.

    Missing files produce warnings and empty lists rather than failures.
    """
    if derived_dir is None:
        derived_dir = _find_derived_dir()

    datasets = DerivedDatasets()

    if not derived_dir.is_dir():
        datasets.load_warnings.append(
            f"Derived datasets directory not found: {derived_dir}"
        )
        return datasets

    file_map = {
        "coordination": "cross_session_coordination_dataset.jsonl",
        "conflicts": "coordination_conflict_dataset.jsonl",
        "artifact_reuse": "artifact_reuse_dataset.jsonl",
        "checkpoints": "checkpoint_eval_dataset.jsonl",
        "tool_failures": "tool_failure_patterns_dataset.jsonl",
        "provider_perf": "provider_task_performance_dataset.jsonl",
        "findings": "findings_dataset.jsonl",
        "manifest": "export_manifest.json",
    }

    for attr, filename in file_map.items():
        path = derived_dir / filename
        if not path.is_file():
            datasets.missing_files.append(filename)
            datasets.load_warnings.append(f"Missing dataset: {filename}")
            continue
        if attr == "manifest":
            datasets.manifest = _load_manifest(path)
        else:
            rows = _load_jsonl(path)
            setattr(datasets, attr, rows)

    return datasets


# ── Summary computation ──────────────────────────────────────────────────


def compute_summary(datasets: DerivedDatasets) -> InspectorSummary:
    """Compute aggregate summary from loaded datasets."""
    summary = InspectorSummary()

    summary.total_sessions = _count_distinct_sessions(datasets)
    summary.total_coordination_rows = len(datasets.coordination)
    summary.total_conflict_rows = len(datasets.conflicts)
    summary.total_artifact_reuse_rows = len(datasets.artifact_reuse)
    summary.total_checkpoint_rows = len(datasets.checkpoints)
    summary.total_tool_failure_rows = len(datasets.tool_failures)
    summary.total_provider_perf_rows = len(datasets.provider_perf)
    summary.total_finding_rows = len(datasets.findings)

    summary.missing_files = datasets.missing_files

    if datasets.manifest:
        summary.export_timestamp = datasets.manifest.get("exported_at", "")
        summary.export_warnings = datasets.manifest.get("warnings", [])
        summary.schema_validation_results = datasets.manifest.get(
            "validation_results", {}
        )

    # Identify empty datasets
    if not datasets.coordination:
        summary.empty_datasets.append("cross_session_coordination_dataset")
    if not datasets.conflicts:
        summary.empty_datasets.append("coordination_conflict_dataset")
    if not datasets.artifact_reuse:
        summary.empty_datasets.append("artifact_reuse_dataset")
    if not datasets.checkpoints:
        summary.empty_datasets.append("checkpoint_eval_dataset")
    if not datasets.tool_failures:
        summary.empty_datasets.append("tool_failure_patterns_dataset")
    if not datasets.provider_perf:
        summary.empty_datasets.append("provider_task_performance_dataset")
    if not datasets.findings:
        summary.empty_datasets.append("findings_dataset")

    return summary


def _count_distinct_sessions(datasets: DerivedDatasets) -> int:
    sessions: set[str] = set()
    for ds in [
        datasets.coordination,
        datasets.conflicts,
        datasets.artifact_reuse,
        datasets.checkpoints,
        datasets.tool_failures,
        datasets.provider_perf,
    ]:
        for row in ds:
            sid = row.get("session_id")
            if sid:
                sessions.add(str(sid))
    return len(sessions)


# ── Filter helpers ───────────────────────────────────────────────────────


def filter_by_session_id(
    rows: list[dict[str, Any]], session_id: str | None
) -> list[dict[str, Any]]:
    if not session_id:
        return rows
    return [r for r in rows if str(r.get("session_id", "")).startswith(session_id)]


def filter_by_task_id(
    rows: list[dict[str, Any]], task_id: str | None
) -> list[dict[str, Any]]:
    if not task_id:
        return rows
    return [r for r in rows if str(r.get("task_id", "")).startswith(task_id)]


def filter_by_event_name(
    rows: list[dict[str, Any]], event_name: str | None
) -> list[dict[str, Any]]:
    if not event_name:
        return rows
    return [r for r in rows if event_name in str(r.get("event_name", ""))]


def filter_by_tool_name(
    rows: list[dict[str, Any]], tool_name: str | None
) -> list[dict[str, Any]]:
    if not tool_name:
        return rows
    return [r for r in rows if tool_name in str(r.get("tool_name", ""))]


def filter_by_model(
    rows: list[dict[str, Any]], model: str | None
) -> list[dict[str, Any]]:
    if not model:
        return rows
    return [r for r in rows if model in str(r.get("model", ""))]


# ── Aggregation helpers ──────────────────────────────────────────────────


def count_by_field(rows: list[dict[str, Any]], field: str) -> list[tuple[str, int]]:
    """Count rows grouped by a field value. Returns sorted (value, count) list."""
    counts: dict[str, int] = {}
    for row in rows:
        val = row.get(field)
        if val is not None:
            key = str(val)
            counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])


def count_by_field_pair(
    rows: list[dict[str, Any]], field_a: str, field_b: str
) -> list[tuple[str, str, int]]:
    """Count rows grouped by two fields. Returns sorted (a, b, count) list."""
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        va = row.get(field_a)
        vb = row.get(field_b)
        if va is not None and vb is not None:
            key = (str(va), str(vb))
            counts[key] = counts.get(key, 0) + 1
    return sorted([(k[0], k[1], v) for k, v in counts.items()], key=lambda x: -x[2])


def unique_values(rows: list[dict[str, Any]], field: str) -> list[str]:
    """Get sorted unique values for a field."""
    vals: set[str] = set()
    for row in rows:
        val = row.get(field)
        if val is not None:
            vals.add(str(val))
    return sorted(vals)


# ── Chart-ready summary helpers ──────────────────────────────────────────


def event_counts_for_chart(datasets: DerivedDatasets) -> list[dict[str, Any]]:
    counts = count_by_field(datasets.coordination, "event_name")
    return [{"event_name": k, "count": v} for k, v in counts]


def tool_status_counts_for_chart(datasets: DerivedDatasets) -> list[dict[str, Any]]:
    pairs = count_by_field_pair(datasets.tool_failures, "tool_name", "status")
    return [{"tool_name": a, "status": b, "count": c} for a, b, c in pairs]


def model_counts_for_chart(datasets: DerivedDatasets) -> list[dict[str, Any]]:
    counts = count_by_field(datasets.provider_perf, "model")
    return [{"model": k, "requests": v} for k, v in counts]


def findings_severity_counts_for_chart(
    datasets: DerivedDatasets,
) -> list[dict[str, Any]]:
    counts = count_by_field(datasets.findings, "severity")
    return [{"severity": k, "count": v} for k, v in counts]


def artifact_kind_counts_for_chart(datasets: DerivedDatasets) -> list[dict[str, Any]]:
    counts = count_by_field(datasets.artifact_reuse, "artifact_kind")
    return [{"artifact_kind": k, "count": v} for k, v in counts]


def checkpoint_status_counts_for_chart(
    datasets: DerivedDatasets,
) -> list[dict[str, Any]]:
    counts = count_by_field(datasets.checkpoints, "checkpoint_outcome")
    return [{"status": k, "count": v} for k, v in counts]


# ── DuckDB helper ────────────────────────────────────────────────────────


def _find_derived_jsonl_files(derived_dir: Path | None = None) -> dict[str, Path]:
    if derived_dir is None:
        derived_dir = _find_derived_dir()
    view_files: dict[str, Path] = {}
    if not derived_dir.is_dir():
        return view_files
    view_map = {
        "cross_session_coordination": "cross_session_coordination_dataset.jsonl",
        "coordination_conflict": "coordination_conflict_dataset.jsonl",
        "artifact_reuse": "artifact_reuse_dataset.jsonl",
        "checkpoint_eval": "checkpoint_eval_dataset.jsonl",
        "tool_failure_patterns": "tool_failure_patterns_dataset.jsonl",
        "provider_task_performance": "provider_task_performance_dataset.jsonl",
        "findings": "findings_dataset.jsonl",
    }
    for view_name, filename in view_map.items():
        p = derived_dir / filename
        if p.is_file():
            view_files[view_name] = p
    return view_files


def create_derived_connection(derived_dir: Path | None = None) -> tuple[Any, list[str]]:

    con = duckdb.connect(":memory:")
    created_views: list[str] = []
    view_files = _find_derived_jsonl_files(derived_dir)
    if not view_files:
        con.close()
        return None, []
    for view_name, p in view_files.items():
        try:
            con.execute(
                f"CREATE VIEW {view_name} AS SELECT * FROM read_json_auto('{p!s}')"
            )
            created_views.append(view_name)
        except Exception:
            continue
    return con, created_views


# ── Canned queries ───────────────────────────────────────────────────────


CANNED_QUERIES: dict[str, str] = {
    "top_event_names": (
        "SELECT event_name, COUNT(*) AS count "
        "FROM cross_session_coordination "
        "GROUP BY event_name ORDER BY count DESC"
    ),
    "tool_failures_by_status": (
        "SELECT tool_name, status, COUNT(*) AS count "
        "FROM tool_failure_patterns "
        "GROUP BY tool_name, status ORDER BY count DESC"
    ),
    "provider_model_counts": (
        "SELECT model, COUNT(*) AS requests "
        "FROM provider_task_performance "
        "GROUP BY model ORDER BY requests DESC"
    ),
    "artifact_kinds": (
        "SELECT artifact_kind, COUNT(*) AS count "
        "FROM artifact_reuse "
        "GROUP BY artifact_kind ORDER BY count DESC"
    ),
    "findings_by_severity_and_kind": (
        "SELECT severity, kind, COUNT(*) AS count "
        "FROM findings "
        "GROUP BY severity, kind ORDER BY severity, count DESC"
    ),
    "checkpoint_outcomes": (
        "SELECT checkpoint_outcome AS status, COUNT(*) AS count "
        "FROM checkpoint_eval "
        "GROUP BY checkpoint_outcome ORDER BY count DESC"
    ),
}


def run_canned_query(con: Any, query_name: str) -> list[dict[str, Any]] | None:
    if con is None:
        return None
    sql = CANNED_QUERIES.get(query_name)
    if sql is None:
        return None
    try:
        result = con.execute(sql)
        rows = result.fetchall()
        desc = [d[0] for d in result.description]
        return [dict(zip(desc, row, strict=True)) for row in rows]
    except Exception:
        return None
