#!/usr/bin/env python3
"""Rig Relay built-in tool refinement report generator.

Reads derived datasets with DuckDB and turns observed tool pressure into a
ranked, content-light refinement backlog.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
import uuid

import duckdb
import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.builtin_tool_refinement_item.v1.schema.json"
DEFAULT_DERIVED_DIR = REPO_ROOT / ".build" / "rig-relay" / "derived"
DEFAULT_REPORTS_DIR = REPO_ROOT / ".build" / "rig-relay" / "reports"
DEFAULT_OUTPUT = DEFAULT_REPORTS_DIR / "built-in-tool-refinement.md"
DEFAULT_JSONL_OUTPUT = DEFAULT_DERIVED_DIR / "builtin_tool_refinement_backlog.jsonl"

DATASET_FILES = {
    "tool_failure_patterns_dataset": "tool_failure_patterns_dataset.jsonl",
    "provider_task_performance_dataset": "provider_task_performance_dataset.jsonl",
    "cross_session_coordination_dataset": "cross_session_coordination_dataset.jsonl",
    "coordination_conflict_dataset": "coordination_conflict_dataset.jsonl",
    "artifact_reuse_dataset": "artifact_reuse_dataset.jsonl",
    "checkpoint_eval_dataset": "checkpoint_eval_dataset.jsonl",
    "findings_dataset": "findings_dataset.jsonl",
    "semantic_change_snippets": "semantic_change_snippets.jsonl",
    "command_tool_opportunity_dataset": "command_tool_opportunity_dataset.jsonl",
    "shell_command_events_dataset": "shell_command_events_dataset.jsonl",
    "export_manifest": "export_manifest.json",
    "storage_audit": "storage_audit.json",
}

SCORING_NOTES = [
    "+5 failure_count > 0",
    "+5 refusal_count > 0 and event_count >= 10",
    "+4 fallback_to_bash_count over threshold",
    "+4 storage_pressure_score high",
    "+3 semantic change pattern repeats",
    "+3 coordination pressure exists",
    "+2 truncation_count > 0",
    "+2 checkpoint/fleet readiness impacted",
]

FREQUENT_USAGE_THRESHOLD = 10
FALLBACK_THRESHOLD = 3
STORAGE_THRESHOLD = 4
COORDINATION_THRESHOLD = 3
PRESSURE_SCORE_THRESHOLD = 2
LARGE_USAGE_THRESHOLD = 20
P0_SCORE = 10
P1_SCORE = 7
P2_SCORE = 4
P3_SCORE = 0


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _duckdb_rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    try:
        result = con.execute(sql)
    except Exception:
        return []
    if result is None:
        return []
    columns = [desc[0] for desc in result.description]
    return [dict(zip(columns, row, strict=False)) for row in result.fetchall()]


def _present_datasets(derived_dir: Path) -> dict[str, Path]:
    present: dict[str, Path] = {}
    for name, filename in DATASET_FILES.items():
        path = derived_dir / filename
        if path.is_file():
            present[name] = path
    return present


def _missing_dataset_warnings(present: dict[str, Path]) -> list[str]:
    return [f"Missing dataset: {name}" for name in DATASET_FILES if name not in present]


def _normalize_tool_name(dataset_name: str, row: dict[str, Any]) -> str | None:
    explicit_tool = row.get("tool_name")
    if explicit_tool is not None:
        return str(explicit_tool)
    match dataset_name:
        case "shell_command_events_dataset":
            return "bash"
        case "semantic_change_snippets":
            return "semantic_change"
        case "storage_audit":
            return "storage"
        case "coordination_conflict_dataset" | "cross_session_coordination_dataset":
            return "coordination"
        case _:
            return None


def _accumulate_row(
    bucket: dict[str, dict[str, Any]], dataset_name: str, row: dict[str, Any]
) -> None:
    tool_name = _normalize_tool_name(dataset_name, row)
    if tool_name is None:
        return
    aggregate = bucket.setdefault(
        tool_name,
        {
            "tool_name": tool_name,
            "event_count": 0,
            "failure_count": 0,
            "refusal_count": 0,
            "timeout_count": 0,
            "fallback_to_bash_count": 0,
            "truncation_count": 0,
            "artifact_size_bytes": 0,
            "storage_pressure_score": 0,
            "coordination_pressure_score": 0,
            "semantic_change_kind": None,
        },
    )
    aggregate["event_count"] += 1
    status = str(row.get("status") or "").lower()
    failure_type = str(row.get("failure_type") or "").lower()
    event_name = str(row.get("event_name") or "").lower()
    change_kind = str(row.get("change_kind") or "").lower()
    if status in {"error", "failed", "failure", "refused", "blocked"}:
        aggregate["failure_count"] += 1
    if status == "refused":
        aggregate["refusal_count"] += 1
    if "timeout" in status:
        aggregate["timeout_count"] += 1
    if "bash" in event_name or "shell" in dataset_name or tool_name == "bash":
        aggregate["fallback_to_bash_count"] += 1
    if "truncat" in status or "truncat" in failure_type:
        aggregate["truncation_count"] += 1
    aggregate["artifact_size_bytes"] += int(
        row.get("estimated_tokens") or row.get("artifact_size_bytes") or 0
    )
    if dataset_name == "storage_audit" or "storage" in event_name:
        aggregate["storage_pressure_score"] += int(
            row.get("storage_pressure_score") or 2
        )
    if "coord" in dataset_name or "coord" in event_name:
        aggregate["coordination_pressure_score"] += 2
    if change_kind:
        aggregate["semantic_change_kind"] = change_kind


def _build_summary_rows(derived_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    present = _present_datasets(derived_dir)
    warnings = _missing_dataset_warnings(present)
    if not present:
        return [], warnings
    con = duckdb.connect()
    bucket: dict[str, dict[str, Any]] = {}

    for dataset_name, path in present.items():
        rows = _duckdb_rows(con, f"SELECT * FROM read_json_auto('{path}')")
        for row in rows:
            _accumulate_row(bucket, dataset_name, row)

    rows = sorted(
        bucket.values(),
        key=lambda row: (
            -int(row["failure_count"]),
            -int(row["refusal_count"]),
            -int(row["fallback_to_bash_count"]),
            -int(row["artifact_size_bytes"]),
            str(row["tool_name"]),
        ),
    )
    return rows, warnings


def _priority_from_score(score: int) -> str:
    if score >= P0_SCORE:
        return "P0"
    if score >= P1_SCORE:
        return "P1"
    if score >= P2_SCORE:
        return "P2"
    return "P3"


def _refinement_kind(
    failure_count: int,
    refusal_count: int,
    fallback_to_bash_count: int,
    storage_pressure_score: float,
    coordination_pressure_score: float,
    truncation_count: int,
) -> tuple[str, str | None]:
    if fallback_to_bash_count >= FALLBACK_THRESHOLD:
        return "replace_shell_pattern", "typed built-in"
    if storage_pressure_score >= STORAGE_THRESHOLD:
        return "reduce_artifact_weight", None
    if coordination_pressure_score >= COORDINATION_THRESHOLD:
        return "add_coordination_hook", None
    if failure_count or refusal_count:
        return "harden_existing_tool", None
    if truncation_count:
        return "add_structured_artifact", None
    return "promote_to_builtin", None


def _action_and_rationale(refinement_kind: str) -> tuple[str, str]:
    match refinement_kind:
        case "replace_shell_pattern":
            return (
                "Create typed built-in for repeated shell pattern.",
                "Repeated fallback to bash indicates a typed surface would remove brittle shell parsing.",
            )
        case "reduce_artifact_weight":
            return (
                "Reduce artifact weight and add compaction-friendly structured output.",
                "Storage pressure suggests the tool emits too much bulky output for long-lived retention.",
            )
        case "add_coordination_hook":
            return (
                "Add coordination hooks, task IDs, or lease-aware metadata.",
                "Coordination pressure suggests the tool participates in fleet/delegate flows without enough linkage.",
            )
        case "harden_existing_tool":
            return (
                "Harden the existing tool around observed failure and refusal modes.",
                "Failure or refusal signal makes this a direct hardening target.",
            )
        case "add_structured_artifact":
            return (
                "Add structured artifact output to avoid truncation loss.",
                "Truncation signal means the current inline surface is too lossy.",
            )
        case _:
            return (
                "Promote the repeated pattern into a narrower built-in surface.",
                "Observed repetition suggests the pattern should be a first-class tool.",
            )


def _score_row(
    row: dict[str, Any],
) -> tuple[int, str, str, str, float, str | None, str]:
    event_count = int(row.get("event_count") or 0)
    failure_count = int(row.get("failure_count") or 0)
    refusal_count = int(row.get("refusal_count") or 0)
    timeout_count = int(row.get("timeout_count") or 0)
    fallback_to_bash_count = int(row.get("fallback_to_bash_count") or 0)
    truncation_count = int(row.get("truncation_count") or 0)
    storage_pressure_score = float(row.get("storage_pressure_score") or 0)
    coordination_pressure_score = float(row.get("coordination_pressure_score") or 0)

    score = 0
    score += 5 if failure_count else 0
    score += 5 if refusal_count and event_count >= FREQUENT_USAGE_THRESHOLD else 0
    score += 4 if fallback_to_bash_count >= FALLBACK_THRESHOLD else 0
    score += 4 if storage_pressure_score >= PRESSURE_SCORE_THRESHOLD else 0
    score += 3 if coordination_pressure_score >= PRESSURE_SCORE_THRESHOLD else 0
    score += 2 if truncation_count else 0
    score += 2 if timeout_count else 0
    score += (
        2
        if event_count >= LARGE_USAGE_THRESHOLD
        and (failure_count or fallback_to_bash_count)
        else 0
    )

    priority = _priority_from_score(score)
    refinement_kind, suggested = _refinement_kind(
        failure_count,
        refusal_count,
        fallback_to_bash_count,
        storage_pressure_score,
        coordination_pressure_score,
        truncation_count,
    )
    action, rationale = _action_and_rationale(refinement_kind)
    confidence = min(1.0, 0.35 + score / 20.0)
    return score, priority, refinement_kind, action, confidence, suggested, rationale


def _build_item(
    row: dict[str, Any], created_at: str, derived_dir: Path
) -> dict[str, Any]:
    score, priority, refinement_kind, action, confidence, suggested, rationale = (
        _score_row(row)
    )
    tool_name = str(row.get("tool_name") or "unknown")
    return {
        "schema_version": "rig.relay.builtin_tool_refinement_item.v1",
        "item_id": f"refine_{uuid.uuid4().hex[:12]}",
        "created_at": created_at,
        "tool_name": tool_name,
        "tool_family": tool_name.split("_", 1)[0],
        "refinement_kind": refinement_kind,
        "priority": priority,
        "confidence": round(confidence, 3),
        "evidence_window": "latest derived datasets present in .build/rig-relay/derived",
        "evidence_sources": sorted([
            name
            for name in DATASET_FILES
            if (derived_dir / DATASET_FILES[name]).is_file()
        ]),
        "event_count": int(row.get("event_count") or 0),
        "failure_count": int(row.get("failure_count") or 0),
        "refusal_count": int(row.get("refusal_count") or 0),
        "timeout_count": int(row.get("timeout_count") or 0),
        "fallback_to_bash_count": int(row.get("fallback_to_bash_count") or 0),
        "truncation_count": int(row.get("truncation_count") or 0),
        "artifact_size_bytes": int(row.get("artifact_size_bytes") or 0),
        "storage_pressure_score": float(row.get("storage_pressure_score") or 0),
        "coordination_pressure_score": float(
            row.get("coordination_pressure_score") or 0
        ),
        "suggested_replacement_tool": suggested,
        "recommended_action": action,
        "rationale": rationale,
        "safety_notes": "Content-light row built from derived counts, labels, and schema-safe aggregates only.",
        "warnings": [],
        "_score": score,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _validate_rows(rows: list[dict[str, Any]]) -> list[str]:
    schema = _load_schema()
    errors: list[str] = []
    for row in rows:
        try:
            jsonschema.validate(instance=row, schema=schema)
        except jsonschema.ValidationError as exc:
            errors.append(str(exc))
    return errors


def _render_report(rows: list[dict[str, Any]], warnings: list[str]) -> str:
    lines: list[str] = []
    created_at = datetime.now(UTC).isoformat()
    lines.append("# Built-in Tool Refinement Report")
    lines.append(f"*Generated: {created_at}*")
    lines.append("")
    if warnings:
        lines.append("## Warnings")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")
    lines.append("## Executive Summary")
    top_rows = sorted(
        rows, key=lambda r: (r["_score"], r["priority"], r["tool_name"]), reverse=True
    )[:5]
    if top_rows:
        for row in top_rows:
            lines.append(
                f"- {row['tool_name']}: {row['priority']} via {row['refinement_kind']} ({row['recommended_action']})"
            )
    else:
        lines.append("- No ranked rows available from current derived datasets.")
    lines.append("")
    lines.append("## Scoring")
    for note in SCORING_NOTES:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("## Tool Pressure Table")
    lines.append(
        "| tool_name | event_count | failure_count | refusal_count | timeout_count | artifact_size_bytes | priority |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for row in sorted(rows, key=lambda r: (-r["_score"], r["tool_name"])):
        lines.append(
            f"| {row['tool_name']} | {row['event_count']} | {row['failure_count']} | {row['refusal_count']} | {row['timeout_count']} | {row['artifact_size_bytes']} | {row['priority']} |"
        )
    lines.append("")
    lines.append("## Recommended Implementation Backlog")
    for row in sorted(rows, key=lambda r: (-r["_score"], r["tool_name"])):
        lines.append(
            f"- {row['priority']} {row['tool_name']}: {row['recommended_action']} Evidence sources: {', '.join(row['evidence_sources'])}."
        )
    lines.append("")
    return "\n".join(lines)


def run(
    derived_dir: Path, reports_dir: Path, output: Path, jsonl_output: Path, strict: bool
) -> int:
    rows, warnings = _build_summary_rows(derived_dir)
    if strict and not rows:
        raise SystemExit("No derived datasets available in derived directory.")
    created_at = datetime.now(UTC).isoformat()
    items = [_build_item(row, created_at, derived_dir) for row in rows]
    stored_items = [
        {k: v for k, v in item.items() if not k.startswith("_")} for item in items
    ]
    validation_errors = _validate_rows(stored_items)
    if validation_errors:
        warnings.extend(validation_errors)
        if strict:
            raise SystemExit("\n".join(validation_errors))
    _write_jsonl(jsonl_output, stored_items)
    reports_dir.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_report(items, warnings), encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--derived-dir", type=Path, default=DEFAULT_DERIVED_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--jsonl-output", type=Path, default=DEFAULT_JSONL_OUTPUT)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    return run(
        args.derived_dir, args.reports_dir, args.output, args.jsonl_output, args.strict
    )


if __name__ == "__main__":
    raise SystemExit(main())
