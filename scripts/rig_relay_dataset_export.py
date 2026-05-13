#!/usr/bin/env python3
"""Rig Relay Dataset Exporter.

Reads event streams and findings registries, then writes clean derived JSONL/CSV
files for machine consumption. Validates exported rows against schemas where
schemas exist.

Usage:
    uv run python scripts/rig_relay_dataset_export.py
    uv run python scripts/rig_relay_dataset_export.py --output-dir .build/rig-relay/derived --format csv
    uv run python scripts/rig_relay_dataset_export.py --strict

Content-light: never includes raw prompts, model outputs, file contents,
stdout/stderr bodies, or raw private code paths.
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, cast

try:
    import jsonschema as _jsonschema_mod

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False
    _jsonschema_mod = cast(Any, None)

jsonschema = _jsonschema_mod


# ── Paths ────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"
COORD_EVENTS = BUILD_ROOT / "coordination" / "events.jsonl"
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
FINDINGS_PATH = REPO_ROOT / "docs" / "findings" / "out-of-scope-findings.jsonl"
SESSIONS_ROOT = Path.home() / ".rig" / "relay" / "sessions"

DEFAULT_OUTPUT_DIR = BUILD_ROOT / "derived"

# Schema IDs for validation
SCHEMA_CROSS_SESSION = "rig.relay.cross_session_coordination.v1"
SCHEMA_COORD_CONFLICT = "rig.relay.coordination_conflict.v1"
SCHEMA_ARTIFACT_REUSE = "rig.relay.artifact_reuse.v1"
SCHEMA_CHECKPOINT_EVAL = "rig.relay.checkpoint_eval.v1"


# ── Helpers ──────────────────────────────────────────────────────────────


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


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write rows as JSONL, one per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _load_schema(schema_id: str, schemas_dir: Path) -> dict[str, Any] | None:
    """Load a JSON Schema file by its schema ID (filename prefix match)."""
    expected_name = f"{schema_id}.schema.json"
    path = schemas_dir / expected_name
    if path.is_file():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    # Fallback: search by partial name match
    for path in sorted(schemas_dir.glob("*.schema.json")):
        if schema_id in path.name:
            try:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
    return None


def _validate_row(row: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Validate a single row against a JSON Schema. Returns list of error messages."""
    if not HAS_JSONSCHEMA:
        return ["jsonschema not available; skipping validation"]
    _jsonschema = jsonschema
    errors: list[str] = []
    try:
        _jsonschema.validate(instance=row, schema=schema)
    except _jsonschema.ValidationError as e:
        errors.append(str(e))
    return errors


def _jsonl_paths(root: Path, pattern: str = "observability.jsonl") -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.glob(f"*/{pattern}"))


def _safe_str(val: Any) -> str | None:
    if val is None:
        return None
    return str(val)


# ── Event loading ────────────────────────────────────────────────────────


def load_coordination_events(path: Path) -> list[dict[str, Any]]:
    """Load coordination events from the coordination store events.jsonl."""
    return _load_jsonl(path)


def load_observability_events(sessions_root: Path) -> list[dict[str, Any]]:
    """Load all observability events from session directories."""
    events: list[dict[str, Any]] = []
    for path in _jsonl_paths(sessions_root):
        events.extend(_load_jsonl(path))
    return events


def load_findings(path: Path) -> list[dict[str, Any]]:
    """Load out-of-scope findings."""
    return _load_jsonl(path)


# ── Coordination transformers ────────────────────────────────────────────


def transform_coord_to_cross_session(event: dict[str, Any]) -> dict[str, Any] | None:
    """Transform a coord.* event into a cross_session_coordination row."""
    event_name = event.get("event_name", "")
    if not event_name.startswith("coord."):
        return None

    payload = event.get("payload", {})
    fields: dict[str, Any] = {
        "schema_version": "rig.relay.cross_session_coordination.v1",
        "event_id": event.get("event_id", ""),
        "session_id": event.get("session_id", ""),
        "task_id": event.get("task_id"),
        "sequence": event.get("sequence", 0),
        "created_at": event.get("created_at", ""),
        "event_name": event_name,
        "event_hash": event.get("event_hash"),
        "status": payload.get("status"),
        "event_kind": payload.get("event_kind"),
        "outcome": payload.get("outcome"),
    }

    # Copy payload fields that map to the schema
    field_map = {
        "provider": "provider",
        "model": "model",
        "thinking_enabled": "thinking_enabled",
        "reservation_mode": "reservation_mode",
        "reservation_status": "reservation_status",
        "path_hashes": "path_hashes",
        "path_count": "path_count",
        "artifact_kind": "artifact_kind",
        "artifact_sha256": "artifact_sha256",
        "conflict_kind": "conflict_kind",
        "conflict_id": "conflict_id",
        "other_session_id": "other_session_id",
        "resolution_kind": "resolution_kind",
        "handoff_from_session_id": "handoff_from_session_id",
        "handoff_to_session_id": "handoff_to_session_id",
        "claim_kind": "claim_kind",
        "ttl_seconds": "ttl_seconds",
        "expires_at": "expires_at",
        "current_step": "current_step",
        "projection_sha256": "projection_sha256",
        "latency_ms": "latency_ms",
        "warnings": "warnings",
    }
    for payload_key, field_name in field_map.items():
        val = payload.get(payload_key)
        if val is not None:
            fields[field_name] = val

    return {k: v for k, v in fields.items() if v is not None}


def transform_coord_to_conflict(event: dict[str, Any]) -> dict[str, Any] | None:
    """Transform a conflict-related coord.* event into a coordination_conflict row."""
    event_name = event.get("event_name", "")
    if event_name not in {"coord.conflict.reported", "coord.path.reservation_refused"}:
        return None

    payload = event.get("payload", {})

    mapping: dict[str, Any] = {
        "schema_version": "rig.relay.coordination_conflict.v1",
        "conflict_id": payload.get("conflict_id") or event.get("event_id", ""),
        "session_id": event.get("session_id", ""),
        "other_session_id": payload.get("other_session_id"),
        "task_id": event.get("task_id"),
        "conflict_kind": payload.get("conflict_kind") or "path_write_overlap",
        "event_name": event_name,
        "event_hash": event.get("event_hash"),
        "path_hashes": payload.get("path_hashes"),
        "path_count": payload.get("path_count"),
        "resolution_kind": payload.get("resolution_kind")
        or payload.get("recommended_resolution"),
        "outcome": payload.get("outcome"),
        "prevented_write": payload.get("prevented_write"),
        "created_at": event.get("created_at", ""),
        "latency_ms": payload.get("latency_ms"),
    }
    # Remove None values so schema validation passes (nulls are allowed for optional fields)
    return {k: v for k, v in mapping.items() if v is not None}


def transform_coord_to_artifact_reuse(event: dict[str, Any]) -> dict[str, Any] | None:
    """Transform an artifact-related coord.* event into an artifact_reuse row."""
    event_name = event.get("event_name", "")
    if event_name not in {"coord.artifact.published"}:
        return None

    payload = event.get("payload", {})

    mapping: dict[str, Any] = {
        "schema_version": "rig.relay.artifact_reuse.v1",
        "session_id": event.get("session_id", ""),
        "task_id": event.get("task_id"),
        "artifact_kind": payload.get("artifact_kind", "unknown"),
        "artifact_sha256": payload.get("artifact_sha256", ""),
        "producer_session_id": payload.get("producer_session_id")
        or event.get("session_id"),
        "consumer_session_id": None,
        "reuse_kind": "read",
        "avoided_tool_call": None,
        "outcome": None,
        "event_name": event_name,
        "event_hash": event.get("event_hash"),
        "created_at": event.get("created_at", ""),
        "latency_ms": payload.get("latency_ms"),
    }
    return {k: v for k, v in mapping.items() if v is not None}


def transform_coord_to_checkpoint(event: dict[str, Any]) -> dict[str, Any] | None:
    """Transform a checkpoint event (could be in coordination or observability stream)."""
    event_name = event.get("event_name", "")
    if event_name not in {
        "rig.relay.checkpoint.committed",
        "rig.relay.checkpoint.refused",
    }:
        return None

    payload = event.get("payload", {})
    status = (
        "committed" if event_name == "rig.relay.checkpoint.committed" else "refused"
    )

    mapping: dict[str, Any] = {
        "schema_version": "rig.relay.checkpoint_eval.v1",
        "session_id": event.get("session_id", ""),
        "task_id": event.get("task_id"),
        "event_name": event_name,
        "event_hash": event.get("event_hash"),
        "status": status,
        "branch": payload.get("branch"),
        "pre_commit_head": payload.get("pre_commit_head"),
        "post_commit_head": payload.get("post_commit_head"),
        "commit_sha": payload.get("commit_sha"),
        "files_committed_count": payload.get("files_committed_count"),
        "validation_summary_hash": payload.get("validation_summary_hash"),
        "checkpoint_artifact_sha256": payload.get("checkpoint_artifact_sha256"),
        "refusal_code": payload.get("refusal_code"),
        "warnings": payload.get("warnings"),
        "created_at": event.get("created_at", ""),
        "latency_ms": payload.get("latency_ms"),
    }
    return {k: v for k, v in mapping.items() if v is not None}


# ── Observability transformers ───────────────────────────────────────────


def transform_observability_to_tool_failure(
    event: dict[str, Any],
) -> dict[str, Any] | None:
    """Transform a tool.call_completed event into a tool_failure_patterns row."""
    if event.get("event_name") != "rig.relay.tool.call_completed":
        return None

    payload = event.get("payload", {})
    status = payload.get("status", "unknown")
    # Only export non-success statuses for failure patterns
    if status == "success":
        return None

    return {
        "tool_name": payload.get("tool_name", "unknown"),
        "status": status,
        "session_id": event.get("session_id", ""),
        "task_id": event.get("task_id"),
        "event_hash": event.get("event_hash"),
        "created_at": event.get("created_at", ""),
        "warnings": payload.get("warnings"),
        "determinism_class": payload.get("determinism_class"),
        "mutation_class": payload.get("mutation_class"),
        "model": payload.get("model"),
    }


def transform_observability_to_provider_perf(
    event: dict[str, Any],
) -> dict[str, Any] | None:
    """Transform a request_accounted event into a provider_task_performance row."""
    if event.get("event_name") != "rig.relay.context.request_accounted":
        return None

    payload = event.get("payload", {})
    ca = payload.get("context_accounting", {}) or {}

    return {
        "session_id": event.get("session_id", ""),
        "task_id": event.get("task_id"),
        "event_hash": event.get("event_hash"),
        "created_at": event.get("created_at", ""),
        "model": ca.get("model") or payload.get("model", "unknown"),
        "estimated_tokens": ca.get("estimated_tokens"),
        "total_chars": ca.get("total_chars"),
        "total_messages": ca.get("total_messages"),
    }


# ── Findings transformer ─────────────────────────────────────────────────


def transform_finding(finding: dict[str, Any]) -> dict[str, Any]:
    """Transform an out-of-scope finding into a findings_dataset row."""
    return {
        "finding_id": finding.get("finding_id", ""),
        "finding_kind": finding.get("finding_kind", ""),
        "severity": finding.get("severity", ""),
        "status": finding.get("status", ""),
        "repo_area": finding.get("repo_area", ""),
        "language": finding.get("language", ""),
        "title": finding.get("title", ""),
        "suggested_slice": finding.get("suggested_slice"),
        "created_at": finding.get("created_at", ""),
    }


# ── Schema validation ────────────────────────────────────────────────────


def validate_dataset(
    rows: list[dict[str, Any]], schema_id: str, schemas_dir: Path
) -> tuple[int, list[str]]:
    """Validate all rows against a schema. Returns (valid_count, error_messages)."""
    if not rows:
        return 0, []
    schema = _load_schema(schema_id, schemas_dir)
    if schema is None:
        return len(rows), [f"Schema not found: {schema_id}"]
    if not HAS_JSONSCHEMA:
        return len(rows), ["jsonschema not available; skipping validation"]
    valid = 0
    errors: list[str] = []
    for i, row in enumerate(rows):
        row_errors = _validate_row(row, schema)
        if row_errors:
            for err in row_errors:
                errors.append(f"Row {i} in {schema_id}: {err}")
        else:
            valid += 1
    return valid, errors


# ── Export ───────────────────────────────────────────────────────────────


class ExportManifest:
    """Tracks export state and warnings."""

    def __init__(self) -> None:
        self.row_counts: dict[str, int] = {}
        self.warnings: list[str] = []
        self.skipped_event_count: int = 0
        self.validation_results: dict[str, dict[str, Any]] = {}
        self.input_paths: dict[str, str] = {}
        self.strict: bool = False
        self.output_dir: str = ""
        self.exported_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "exported_at": self.exported_at,
            "content_light_guarantee": True,
            "strict": self.strict,
            "output_dir": self.output_dir,
            "input_paths": self.input_paths,
            "row_counts": self.row_counts,
            "validation_results": self.validation_results,
            "warnings": self.warnings,
            "skipped_event_count": self.skipped_event_count,
        }


def _export_coordination_datasets(
    manifest: ExportManifest,
    coord_events_path: Path,
    schemas_dir: Path,
    output_dir: Path,
    strict: bool,
) -> list[dict[str, Any]]:
    """Export coordination-derived datasets. Returns coord_events for later use."""
    coord_events = load_coordination_events(coord_events_path)
    if not coord_events:
        if strict:
            msg = f"Strict mode: coordination events required at {coord_events_path}"
            manifest.warnings.append(msg)
            raise FileNotFoundError(msg)
        manifest.warnings.append(f"No coordination events found at {coord_events_path}")
        return []

    cross_session_rows = _apply_and_write(
        coord_events,
        transform_coord_to_cross_session,
        output_dir,
        "cross_session_coordination_dataset",
        manifest,
        count_consumed=True,
    )
    _validate_and_record(
        cross_session_rows,
        SCHEMA_CROSS_SESSION,
        schemas_dir,
        manifest,
        "cross_session_coordination_dataset",
    )

    conflict_rows = _apply_and_write(
        coord_events,
        transform_coord_to_conflict,
        output_dir,
        "coordination_conflict_dataset",
        manifest,
    )
    _validate_and_record(
        conflict_rows,
        SCHEMA_COORD_CONFLICT,
        schemas_dir,
        manifest,
        "coordination_conflict_dataset",
    )

    artifact_rows = _apply_and_write(
        coord_events,
        transform_coord_to_artifact_reuse,
        output_dir,
        "artifact_reuse_dataset",
        manifest,
    )
    _validate_and_record(
        artifact_rows,
        SCHEMA_ARTIFACT_REUSE,
        schemas_dir,
        manifest,
        "artifact_reuse_dataset",
    )

    return coord_events


def _export_observability_datasets(
    manifest: ExportManifest,
    sessions_root: Path,
    coord_events: list[dict[str, Any]],
    schemas_dir: Path,
    output_dir: Path,
    strict: bool,
) -> None:
    """Export observability-derived datasets."""
    obs_events = load_observability_events(sessions_root)
    if not obs_events:
        if strict:
            msg = f"Strict mode: observability events required under {sessions_root}"
            manifest.warnings.append(msg)
            raise FileNotFoundError(msg)
        manifest.warnings.append(f"No observability events found under {sessions_root}")
        return

    # Checkpoint eval from both streams
    checkpoint_rows: list[dict[str, Any]] = []
    for event in obs_events:
        row = transform_coord_to_checkpoint(event)
        if row:
            checkpoint_rows.append(row)
    for event in coord_events:
        row = transform_coord_to_checkpoint(event)
        if row:
            checkpoint_rows.append(row)
    _write_jsonl(output_dir / "checkpoint_eval_dataset.jsonl", checkpoint_rows)
    manifest.row_counts["checkpoint_eval_dataset"] = len(checkpoint_rows)
    _validate_and_record(
        checkpoint_rows,
        SCHEMA_CHECKPOINT_EVAL,
        schemas_dir,
        manifest,
        "checkpoint_eval_dataset",
    )

    _ = _apply_and_write(
        obs_events,
        transform_observability_to_tool_failure,
        output_dir,
        "tool_failure_patterns_dataset",
        manifest,
    )
    _ = _apply_and_write(
        obs_events,
        transform_observability_to_provider_perf,
        output_dir,
        "provider_task_performance_dataset",
        manifest,
    )


def _export_findings_dataset(
    manifest: ExportManifest, findings_path: Path, output_dir: Path, strict: bool
) -> None:
    """Export findings-derived dataset."""
    findings = load_findings(findings_path)
    if not findings:
        if strict:
            msg = f"Strict mode: findings required at {findings_path}"
            manifest.warnings.append(msg)
            raise FileNotFoundError(msg)
        manifest.warnings.append(f"No findings found at {findings_path}")
        return

    findings_rows = [transform_finding(f) for f in findings]
    _write_jsonl(output_dir / "findings_dataset.jsonl", findings_rows)
    manifest.row_counts["findings_dataset"] = len(findings_rows)


def _apply_and_write(
    events: list[dict[str, Any]],
    transform_fn: Any,
    output_dir: Path,
    dataset_name: str,
    manifest: ExportManifest,
    count_consumed: bool = False,
) -> list[dict[str, Any]]:
    """Apply a transform function to events and write to JSONL."""
    rows: list[dict[str, Any]] = []
    for event in events:
        row = transform_fn(event)
        if row:
            rows.append(row)
        elif count_consumed:
            manifest.skipped_event_count += 1
    _write_jsonl(output_dir / f"{dataset_name}.jsonl", rows)
    manifest.row_counts[dataset_name] = len(rows)
    if count_consumed:
        manifest.row_counts[f"{dataset_name}_events_consumed"] = len(rows)
    return rows


def _validate_and_record(
    rows: list[dict[str, Any]],
    schema_id: str,
    schemas_dir: Path,
    manifest: ExportManifest,
    dataset_name: str,
) -> None:
    """Validate rows and record results in the manifest."""
    valid, errors = validate_dataset(rows, schema_id, schemas_dir)
    manifest.validation_results[dataset_name] = {
        "total": len(rows),
        "valid": valid,
        "errors": errors,
    }


def _export_csv_datasets(
    output_dir: Path, names_and_rows: list[tuple[str, list[dict[str, Any]]]]
) -> None:
    """Export multiple datasets as CSV."""
    for name, rows in names_and_rows:
        _export_csv(output_dir, name, rows)


def export_all(
    coord_events_path: Path,
    sessions_root: Path,
    findings_path: Path,
    schemas_dir: Path,
    output_dir: Path,
    fmt: str = "jsonl",
    strict: bool = False,
) -> ExportManifest:
    """Run the full export pipeline. Returns an ExportManifest."""
    manifest = ExportManifest()
    manifest.strict = strict
    manifest.output_dir = str(output_dir)
    manifest.exported_at = datetime.now(UTC).isoformat()
    manifest.input_paths = {
        "coordination_events": str(coord_events_path),
        "observability_glob": str(sessions_root / "*/observability.jsonl"),
        "findings": str(findings_path),
    }

    output_dir.mkdir(parents=True, exist_ok=True)

    coord_events = _export_coordination_datasets(
        manifest, coord_events_path, schemas_dir, output_dir, strict
    )
    _export_observability_datasets(
        manifest, sessions_root, coord_events, schemas_dir, output_dir, strict
    )
    _export_findings_dataset(manifest, findings_path, output_dir, strict)

    if fmt in {"csv", "both"}:
        names = [
            "cross_session_coordination_dataset",
            "coordination_conflict_dataset",
            "artifact_reuse_dataset",
            "checkpoint_eval_dataset",
            "tool_failure_patterns_dataset",
            "provider_task_performance_dataset",
            "findings_dataset",
        ]
        loaded: dict[str, list[dict[str, Any]]] = {}
        for name in names:
            path = output_dir / f"{name}.jsonl"
            loaded[name] = _load_jsonl(path) if path.is_file() else []
        _export_csv_datasets(output_dir, [(n, loaded[n]) for n in names])

    total_rows = sum(manifest.row_counts.values())
    manifest.warnings.append(f"Total rows written: {total_rows}")
    _write_jsonl(output_dir / "export_manifest.json", [manifest.to_dict()])

    return manifest


def _export_csv(output_dir: Path, name: str, rows: list[dict[str, Any]]) -> None:
    """Write a dataset as CSV."""
    if not rows:
        # Write empty file with header
        path = output_dir / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return

    fieldnames = list(rows[0].keys())
    path = output_dir / f"{name}.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ── CLI ──────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rig Relay Dataset Exporter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python scripts/rig_relay_dataset_export.py\n"
            "  uv run python scripts/rig_relay_dataset_export.py --output-dir .build/rig-relay/derived --format csv\n"
            "  uv run python scripts/rig_relay_dataset_export.py --strict\n"
        ),
    )
    parser.add_argument(
        "--coordination-events",
        type=Path,
        default=COORD_EVENTS,
        help="Coordination events JSONL path",
    )
    parser.add_argument(
        "--observability-glob",
        type=Path,
        default=SESSIONS_ROOT,
        help="Sessions root directory containing */observability.jsonl",
    )
    parser.add_argument(
        "--findings",
        type=Path,
        default=FINDINGS_PATH,
        help="Out-of-scope findings JSONL path",
    )
    parser.add_argument(
        "--schemas-dir",
        type=Path,
        default=SCHEMAS_DIR,
        help="Directory containing JSON Schema files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for derived datasets",
    )
    parser.add_argument(
        "--format",
        choices=["jsonl", "csv", "both"],
        default="jsonl",
        help="Output format(s)",
    )
    parser.add_argument(
        "--strict", action="store_true", help="Fail on missing required inputs"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        manifest = export_all(
            coord_events_path=args.coordination_events,
            sessions_root=args.observability_glob,
            findings_path=args.findings,
            schemas_dir=args.schemas_dir,
            output_dir=args.output_dir,
            fmt=args.format,
            strict=args.strict,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1

    print(f"Export complete. Manifest at {args.output_dir / 'export_manifest.json'}")
    print(f"Datasets written: {list(manifest.row_counts.keys())}")
    print(f"Row counts: {manifest.row_counts}")
    if manifest.validation_results:
        for name, res in manifest.validation_results.items():
            if res["errors"]:
                print(
                    f"  {name}: {res['valid']}/{res['total']} valid, {len(res['errors'])} error(s)"
                )
    if manifest.warnings:
        for w in manifest.warnings:
            print(f"WARNING: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
