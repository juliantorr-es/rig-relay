#!/usr/bin/env python3
# ruff: noqa: PLR0912, PLR0914, PLR0915
"""Rig Relay Coordination Dataset Exporter.

Transforms normalized coordination/checkpoint event envelopes into
schema-validated derived dataset JSONL rows.

Usage:
    uv run python scripts/rig_relay_export_coordination_datasets.py \\
        --events .build/rig-relay/coordination/events.jsonl \\
        --output-dir .build/rig-relay/derived \\
        --schemas-dir docs/schemas

    uv run python scripts/rig_relay_export_coordination_datasets.py \\
        --events .build/rig-relay/coordination/events.jsonl \\
        --observability ~/.rig/relay/sessions/<session_id>/observability.jsonl \\
        --output-dir .build/rig-relay/derived --strict

Content-light guarantees:
    - No raw file paths (salted hashes only)
    - No prompt text, model output text, stdout/stderr bodies
    - No file contents, diff bodies, or validation logs
    - All rows validated against JSON Schema when jsonschema is available
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

# ── Optional jsonschema dependency ──────────────────────────────────────

_HAS_JSONSCHEMA: bool = False
_js: Any = None
try:
    import jsonschema as _js

    _HAS_JSONSCHEMA = True
except ImportError:
    _js = None


# ── Constants ────────────────────────────────────────────────────────────

DATASET_NAMES = [
    "cross_session_coordination_dataset",
    "coordination_conflict_dataset",
    "artifact_reuse_dataset",
    "checkpoint_eval_dataset",
]

SCHEMA_FILES: dict[str, str] = {
    "cross_session_coordination_dataset": "rig.relay.cross_session_coordination.v1.schema.json",
    "coordination_conflict_dataset": "rig.relay.coordination_conflict.v1.schema.json",
    "artifact_reuse_dataset": "rig.relay.artifact_reuse.v1.schema.json",
    "checkpoint_eval_dataset": "rig.relay.checkpoint_eval.v1.schema.json",
}

# Fields that must NOT appear in any exported row (content-light enforcement).
_FORBIDDEN_KEYS: set[str] = {
    "prompt",
    "model_output",
    "raw_output",
    "stdout",
    "stderr",
    "file_contents",
    "diff_body",
    "validation_log",
}


# ── Helpers ──────────────────────────────────────────────────────────────


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(
                json.dumps(
                    row, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                )
            )
            f.write("\n")


def _check_forbidden_payload(payload: dict[str, Any]) -> list[str]:
    """Check a raw event payload for forbidden content keys.

    Returns a list of violation descriptions (empty if clean).
    """
    found: list[str] = []
    for key in _FORBIDDEN_KEYS:
        if key in payload:
            found.append(key)
    for key, val in payload.items():
        if isinstance(val, str):
            for forbidden in _FORBIDDEN_KEYS:
                if forbidden in val:
                    found.append(f"{key}:<contains '{forbidden}'>")
    return found


def _check_forbidden(row: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for key in _FORBIDDEN_KEYS:
        if key in row:
            found.append(key)
    for key, val in row.items():
        if isinstance(val, str):
            for forbidden in _FORBIDDEN_KEYS:
                if forbidden in val:
                    found.append(f"{key}:<contains '{forbidden}'>")
    return found


def _validate_row(
    row: dict[str, Any], schema: dict[str, Any], strict: bool, warnings: list[str]
) -> bool:
    """Validate a single row against its JSON Schema.

    Returns True if valid. Appends to warnings on failure (non-strict) or
    raises SystemExit (strict).
    """
    if not _HAS_JSONSCHEMA:
        # Basic required-field check when jsonschema is unavailable.
        required = schema.get("required", [])
        for field in required:
            if field not in row or row[field] is None:
                msg = f"Missing required field '{field}' in row"
                if strict:
                    print(f"ERROR: {msg}", file=sys.stderr)
                    sys.exit(1)
                warnings.append(msg)
                return False
        return True

    try:
        _js.validate(instance=row, schema=schema)
        return True
    except _js.ValidationError as exc:
        msg = f"Schema validation failed: {exc.message}"
        if strict:
            print(f"ERROR: {msg}", file=sys.stderr)
            sys.exit(1)
        warnings.append(msg)
        return False


def _load_json_schema(schemas_dir: Path, schema_file: str) -> dict[str, Any]:
    path = schemas_dir / schema_file
    if not path.is_file():
        print(f"WARNING: Schema file not found: {path}", file=sys.stderr)
        return {"type": "object", "properties": {}, "required": []}
    return _load_json(path)


# ── Row builders ─────────────────────────────────────────────────────────


def _build_coordination_row(event: dict[str, Any]) -> dict[str, Any]:
    """Build a cross_session_coordination row from any coord.* event."""
    payload = event.get("payload", {})
    row: dict[str, Any] = {
        "schema_version": "rig.relay.cross_session_coordination.v1",
        "event_id": event.get("event_id", ""),
        "session_id": event.get("session_id") or payload.get("session_id"),
        "sequence": event.get("sequence", 0),
        "created_at": event.get("created_at"),
        "event_name": event.get("event_name", ""),
        "event_hash": event.get("event_hash"),
    }

    # Copy safe fields from payload.
    safe_fields = [
        "task_id",
        "event_kind",
        "status",
        "outcome",
        "provider",
        "model",
        "thinking_enabled",
        "reservation_mode",
        "reservation_status",
        "path_hashes",
        "path_count",
        "artifact_kind",
        "artifact_sha256",
        "conflict_kind",
        "conflict_id",
        "other_session_id",
        "resolution_kind",
        "handoff_from_session_id",
        "handoff_to_session_id",
        "claim_kind",
        "ttl_seconds",
        "expires_at",
        "current_step",
        "projection_sha256",
        "latency_ms",
        "warnings",
        "agent_profile_name",
    ]
    for field in safe_fields:
        if field in payload and payload[field] is not None:
            row[field] = payload[field]

    return row


def _build_conflict_row(event: dict[str, Any]) -> dict[str, Any] | None:
    """Build a coordination_conflict row from conflict/reservation_refused events."""
    payload = event.get("payload", {})
    conflict_kind = payload.get("conflict_kind")
    if not conflict_kind:
        return None

    row: dict[str, Any] = {
        "schema_version": "rig.relay.coordination_conflict.v1",
        "conflict_id": payload.get("conflict_id", ""),
        "session_id": event.get("session_id") or payload.get("session_id"),
        "conflict_kind": conflict_kind,
        "created_at": event.get("created_at"),
    }

    safe_fields = [
        "other_session_id",
        "task_id",
        "event_name",
        "event_hash",
        "path_hashes",
        "path_count",
        "resolution_kind",
        "outcome",
        "prevented_write",
        "latency_ms",
    ]
    row["event_name"] = event.get("event_name", "")
    row["event_hash"] = event.get("event_hash")
    for field in safe_fields:
        if (
            field in payload
            and payload[field] is not None
            and field not in {"event_name", "event_hash"}
        ):
            row[field] = payload[field]

    return row


def _build_artifact_reuse_row(event: dict[str, Any]) -> dict[str, Any] | None:
    """Build an artifact_reuse row from artifact published events."""
    payload = event.get("payload", {})
    artifact_kind = payload.get("artifact_kind")
    artifact_sha256 = payload.get("artifact_sha256")
    if not artifact_kind or not artifact_sha256:
        return None

    row: dict[str, Any] = {
        "schema_version": "rig.relay.artifact_reuse.v1",
        "session_id": event.get("session_id") or payload.get("session_id"),
        "artifact_kind": artifact_kind,
        "artifact_sha256": artifact_sha256,
        "created_at": event.get("created_at"),
    }

    safe_fields = [
        "task_id",
        "producer_session_id",
        "consumer_session_id",
        "reuse_kind",
        "avoided_tool_call",
        "outcome",
        "event_name",
        "event_hash",
        "latency_ms",
    ]
    row["event_name"] = event.get("event_name", "")
    row["event_hash"] = event.get("event_hash")
    for field in safe_fields:
        if (
            field in payload
            and payload[field] is not None
            and field not in {"event_name", "event_hash"}
        ):
            row[field] = payload[field]

    return row


def _build_checkpoint_row(event: dict[str, Any]) -> dict[str, Any]:
    """Build a checkpoint_eval row from checkpoint committed/refused events."""
    payload = event.get("payload", {})
    event_name = event.get("event_name", "")
    status = "committed" if "committed" in event_name else "refused"

    row: dict[str, Any] = {
        "schema_version": "rig.relay.checkpoint_eval.v1",
        "session_id": event.get("session_id") or payload.get("session_id"),
        "event_name": event_name,
        "status": status,
        "created_at": event.get("created_at"),
    }

    safe_fields = [
        "task_id",
        "event_hash",
        "branch",
        "pre_commit_head",
        "post_commit_head",
        "commit_sha",
        "files_committed_count",
        "validation_summary_hash",
        "checkpoint_artifact_sha256",
        "refusal_code",
        "warnings",
        "latency_ms",
    ]
    row["event_hash"] = event.get("event_hash")
    for field in safe_fields:
        if field in payload and payload[field] is not None and field != "event_hash":
            row[field] = payload[field]

    return row


# ── Main export logic ─────────────────────────────────────────────────---


def export_datasets(
    *,
    events_path: Path,
    output_dir: Path,
    schemas_dir: Path,
    strict: bool = False,
    observability_path: Path | None = None,
) -> dict[str, Any]:
    """Run the export and return a summary dict."""
    warnings: list[str] = []
    skipped_count = 0
    input_event_count = 0

    # Validate input
    if not events_path.is_file():
        if not strict:
            print(
                f"WARNING: Coordination events file not found: {events_path}",
                file=sys.stderr,
            )
            warnings.append(f"Input events file not found: {events_path}")
        else:
            print(
                f"ERROR: Coordination events file not found: {events_path}",
                file=sys.stderr,
            )
            sys.exit(1)

    events: list[dict[str, Any]] = []
    if events_path.is_file():
        events = _load_jsonl(events_path)

    obs_events: list[dict[str, Any]] = []
    if observability_path and observability_path.is_file():
        obs_events = _load_jsonl(observability_path)

    # Build dataset rows
    coord_rows: list[dict[str, Any]] = []
    conflict_rows: list[dict[str, Any]] = []
    artifact_rows: list[dict[str, Any]] = []
    checkpoint_rows: list[dict[str, Any]] = []

    def _check_event_forbidden(event: dict[str, Any]) -> list[str]:
        """Check an event's payload for forbidden content (side-effect: appends to warnings in strict mode)."""
        payload = event.get("payload", {})
        return _check_forbidden_payload(payload)

    for event in events:
        event_name = event.get("event_name", "")
        input_event_count += 1

        # Check for forbidden content in raw event payload
        forbidden = _check_event_forbidden(event)
        if forbidden:
            msg = f"Event '{event_name}' payload contains forbidden keys: {forbidden}"
            if strict:
                print(f"ERROR: {msg}", file=sys.stderr)
                sys.exit(1)
            warnings.append(msg)
            continue

        # Every coord.* event → cross_session_coordination
        if event_name.startswith("coord."):
            coord_rows.append(_build_coordination_row(event))

        # Conflict sources → coordination_conflict
        if event_name in {"coord.conflict.reported", "coord.path.reservation_refused"}:
            row = _build_conflict_row(event)
            if row:
                conflict_rows.append(row)

        # Artifact published → artifact_reuse
        if event_name == "coord.artifact.published":
            row = _build_artifact_reuse_row(event)
            if row:
                artifact_rows.append(row)

        # Skip checkpoint events from events.jsonl (they come via observability)
        if event_name.startswith("rig.relay.checkpoint."):
            skipped_count += 1

    # Observability events → checkpoint_eval
    for event in obs_events:
        event_name = event.get("event_name", "")
        input_event_count += 1

        forbidden = _check_event_forbidden(event)
        if forbidden:
            msg = f"Observability event '{event_name}' payload contains forbidden keys: {forbidden}"
            if strict:
                print(f"ERROR: {msg}", file=sys.stderr)
                sys.exit(1)
            warnings.append(msg)
            continue

        if event_name in {
            "rig.relay.checkpoint.committed",
            "rig.relay.checkpoint.refused",
        }:
            checkpoint_rows.append(_build_checkpoint_row(event))

    # Content-light enforcement on built rows (belt-and-suspenders)
    all_rows = coord_rows + conflict_rows + artifact_rows + checkpoint_rows
    for row in all_rows:
        forbidden = _check_forbidden(row)
        if forbidden:
            msg = f"Built row contains forbidden keys: {forbidden}"
            if strict:
                print(f"ERROR: {msg}", file=sys.stderr)
                sys.exit(1)
            warnings.append(msg)

    # Load schemas
    schemas: dict[str, dict[str, Any]] = {}
    for dataset_name in DATASET_NAMES:
        schema_file = SCHEMA_FILES.get(dataset_name, "")
        schemas[dataset_name] = _load_json_schema(schemas_dir, schema_file)

    # Validate rows against schemas
    dataset_rows = {
        "cross_session_coordination_dataset": coord_rows,
        "coordination_conflict_dataset": conflict_rows,
        "artifact_reuse_dataset": artifact_rows,
        "checkpoint_eval_dataset": checkpoint_rows,
    }

    for dataset_name, rows in dataset_rows.items():
        schema = schemas.get(dataset_name, {})
        for row in rows:
            _validate_row(row, schema, strict, warnings)

    # Write output files
    row_counts: dict[str, int] = {}
    output_dir.mkdir(parents=True, exist_ok=True)
    for dataset_name, rows in dataset_rows.items():
        path = output_dir / f"{dataset_name}.jsonl"
        _write_jsonl(path, rows)
        row_counts[dataset_name] = len(rows)

    # Write manifest
    manifest: dict[str, Any] = {
        "schema_version": "rig.relay.export.manifest.v1",
        "input_events_path": str(events_path),
        "observability_path": str(observability_path) if observability_path else None,
        "output_dir": str(output_dir),
        "exported_at": datetime.now(UTC).isoformat(),
        "row_counts": row_counts,
        "schema_files_used": {k: str(v) for k, v in SCHEMA_FILES.items()},
        "warnings": warnings,
        "input_event_count": input_event_count,
        "skipped_event_count": skipped_count,
    }
    manifest_path = output_dir / "export_manifest.json"
    _write_jsonl(manifest_path, [manifest])

    return manifest


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export coordination/checkpoint events into derived evaluation datasets."
    )
    parser.add_argument(
        "--events",
        type=Path,
        default=Path(".build/rig-relay/coordination/events.jsonl"),
        help="Path to coordination events.jsonl",
    )
    parser.add_argument(
        "--observability",
        type=Path,
        default=None,
        help="Path to observability.jsonl (for checkpoint events)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".build/rig-relay/derived"),
        help="Output directory for derived datasets",
    )
    parser.add_argument(
        "--schemas-dir",
        type=Path,
        default=Path("docs/schemas"),
        help="Directory containing JSON Schema files",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on first validation error or missing input",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    manifest = export_datasets(
        events_path=args.events,
        output_dir=args.output_dir,
        schemas_dir=args.schemas_dir,
        strict=args.strict,
        observability_path=args.observability,
    )
    rcounts = manifest.get("row_counts", {})
    total = sum(rcounts.values())
    print(f"Exported {total} rows across {len(rcounts)} datasets to {args.output_dir}")
    for name, count in sorted(rcounts.items()):
        print(f"  {name}: {count}")
    if manifest["warnings"]:
        print(f"Warnings ({len(manifest['warnings'])}):", file=sys.stderr)
        for w in manifest["warnings"]:
            print(f"  - {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
