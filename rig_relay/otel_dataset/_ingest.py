from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema

from rig_relay.otel_dataset._normalize import normalize_otel_capture
from rig_relay.otel_dataset._summarize import build_tool_behavior_summary

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"


@dataclass(frozen=True, slots=True)
class IngestContext:
    input_path: Path
    run_id: str
    output_root: Path
    source_system: str
    fail_on_redaction_error: bool
    raw_capture: Any
    raw_input_sha256: str


@dataclass(frozen=True, slots=True)
class IngestArtifactPaths:
    normalized_root: Path
    raw_root: Path
    display_root: Path
    raw_manifest_path: Path
    normalized_output_path: Path
    summary_path: Path
    ingest_report_path: Path


@dataclass(frozen=True, slots=True)
class ReportCoreInput:
    run_id: str
    generated_at: str
    raw_manifest_path: Path
    normalized_output_path: Path
    summary_path: Path
    raw_input_sha256: str
    normalized_output_sha256: str
    schema_validation_results: dict[str, dict[str, Any]]
    redaction_results: dict[str, Any]
    warnings: list[str]
    errors: list[str]
    display_root: Path


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_raw_capture(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"Raw OTel capture not found: {path}")
    try:
        return _read_json(path)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed raw OTel JSON: {path}") from exc


def _schema_path(schema_name: str) -> Path:
    return SCHEMAS_DIR / f"{schema_name}.schema.json"


def _validate_against_schema(payload: Any, schema_name: str) -> list[str]:
    schema = _read_json(_schema_path(schema_name))
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        return [str(exc)]
    return []


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _relative_artifact_path(path: Path, display_root: Path) -> str:
    return str(path.relative_to(display_root))


def _capture_kind(signal_counts: dict[str, int]) -> str:
    active_signals = [count for count in signal_counts.values() if count > 0]
    if len(active_signals) > 1:
        return "mixed"
    for signal, count in signal_counts.items():
        if count > 0:
            return signal
    return "unknown"


def _build_raw_capture_manifest(
    *,
    run_id: str,
    generated_at: str,
    source_system: str,
    input_path: Path,
    raw_input_sha256: str,
    signal_counts: dict[str, int],
    redaction_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "rig.otel.raw_capture_manifest.v1",
        "run_id": run_id,
        "generated_at": generated_at,
        "source_system": source_system
        if source_system in {"opencode", "otel_collector", "unknown"}
        else "unknown",
        "raw_input_name": input_path.name,
        "raw_input_sha256": raw_input_sha256,
        "raw_input_path_hash": "sha256:"
        + hashlib.sha256(str(input_path).encode("utf-8")).hexdigest(),
        "capture_kind": _capture_kind(signal_counts),
        "signal_counts": signal_counts,
        "content_light": True,
        "redaction_summary": redaction_summary,
    }


def _build_schema_validation_results(
    *,
    raw_capture_manifest: dict[str, Any],
    normalized_events: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    raw_capture_errors = _validate_against_schema(
        raw_capture_manifest, "rig.otel.raw_capture_manifest.v1"
    )
    normalized_errors = [
        error
        for row in normalized_events
        for error in _validate_against_schema(row, "rig.otel.normalized_event.v1")
    ]
    summary_errors = _validate_against_schema(
        summary, "rig.otel.tool_behavior_summary.v1"
    )
    return {
        "raw_capture_manifest": {
            "valid": not raw_capture_errors,
            "errors": raw_capture_errors,
        },
        "normalized_events": {
            "valid": not normalized_errors,
            "errors": normalized_errors,
        },
        "tool_behavior_summary": {
            "valid": not summary_errors,
            "errors": summary_errors,
        },
    }


def _build_report_core(inputs: ReportCoreInput) -> dict[str, Any]:
    return {
        "schema_version": "rig.otel.ingest_report.v1",
        "run_id": inputs.run_id,
        "generated_at": inputs.generated_at,
        "raw_capture_manifest_path": _relative_artifact_path(
            inputs.raw_manifest_path, inputs.display_root
        ),
        "normalized_events_path": _relative_artifact_path(
            inputs.normalized_output_path, inputs.display_root
        ),
        "tool_behavior_summary_path": _relative_artifact_path(
            inputs.summary_path, inputs.display_root
        ),
        "raw_input_sha256": inputs.raw_input_sha256,
        "normalized_output_sha256": inputs.normalized_output_sha256,
        "schema_validation_results": {
            **inputs.schema_validation_results,
            "ingest_report": {"valid": True, "errors": []},
        },
        "redaction_results": inputs.redaction_results,
        "warnings": inputs.warnings,
        "errors": inputs.errors,
        "ingest_verdict": "fail"
        if inputs.errors
        or any(
            not section["valid"]
            for section in inputs.schema_validation_results.values()
        )
        else "pass",
    }


def _build_artifact_paths(output_root: Path, run_id: str) -> IngestArtifactPaths:
    normalized_root = output_root / run_id
    raw_root = output_root.parent / "raw" / run_id
    display_root = output_root.parent
    return IngestArtifactPaths(
        normalized_root=normalized_root,
        raw_root=raw_root,
        display_root=display_root,
        raw_manifest_path=raw_root / "otel_raw_capture_manifest.v1.json",
        normalized_output_path=normalized_root / "otel_normalized_events.v1.jsonl",
        summary_path=normalized_root / "otel_tool_behavior_summary.v1.json",
        ingest_report_path=normalized_root / "otel_ingest_report.v1.json",
    )


def _run_ingest(context: IngestContext) -> dict[str, Any]:
    normalized_at = _now()
    normalization = normalize_otel_capture(
        context.raw_capture,
        source_system=context.source_system,
        normalized_at=normalized_at,
    )
    paths = _build_artifact_paths(context.output_root, context.run_id)
    summary = build_tool_behavior_summary(
        normalization.events,
        run_id=context.run_id,
        generated_at=normalized_at,
        source_event_count=normalization.source_event_count,
        normalized_event_count=normalization.normalized_event_count,
        dropped_event_count=normalization.dropped_event_count,
        redaction_summary=normalization.redaction_summary,
        hardening_candidates=normalization.hardening_candidates,
    )
    raw_capture_manifest = _build_raw_capture_manifest(
        run_id=context.run_id,
        generated_at=normalized_at,
        source_system=context.source_system,
        input_path=context.input_path,
        raw_input_sha256=context.raw_input_sha256,
        signal_counts=normalization.signal_counts,
        redaction_summary=normalization.redaction_summary,
    )
    normalized_jsonl = "\n".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"))
        for row in normalization.events
    )
    if normalized_jsonl:
        normalized_jsonl += "\n"
    normalized_output_sha256 = _sha256_text(normalized_jsonl)
    schema_validation_results = _build_schema_validation_results(
        raw_capture_manifest=raw_capture_manifest,
        normalized_events=normalization.events,
        summary=summary,
    )
    redaction_results = {
        "redacted_count": normalization.redaction_summary["redacted_count"],
        "hashed_count": normalization.redaction_summary["hashed_count"],
        "content_light": True,
    }
    warnings = list(normalization.redaction_summary.get("warnings", []))
    errors: list[str] = []
    if context.fail_on_redaction_error and any(
        event["redaction_status"] not in {"content_light", "hashed", "redacted"}
        for event in normalization.events
    ):
        errors.append("content-light policy failed")

    report_core = _build_report_core(
        ReportCoreInput(
            run_id=context.run_id,
            generated_at=normalized_at,
            raw_manifest_path=paths.raw_manifest_path,
            normalized_output_path=paths.normalized_output_path,
            summary_path=paths.summary_path,
            raw_input_sha256=context.raw_input_sha256,
            normalized_output_sha256=normalized_output_sha256,
            schema_validation_results=schema_validation_results,
            redaction_results=redaction_results,
            warnings=warnings,
            errors=errors,
            display_root=paths.display_root,
        )
    )
    report_errors = _validate_against_schema(report_core, "rig.otel.ingest_report.v1")
    if report_errors:
        report_core["schema_validation_results"]["ingest_report"] = {
            "valid": False,
            "errors": report_errors,
        }
        report_core["errors"] = [*report_core["errors"], *report_errors]
        report_core["ingest_verdict"] = "fail"
        raise ValueError("OTel ingest report failed schema validation")
    if any(not section["valid"] for section in schema_validation_results.values()):
        raise ValueError("OTel dataset failed schema validation")
    if context.fail_on_redaction_error and report_core["errors"]:
        raise ValueError("OTel dataset failed content-light policy")

    _write_json(paths.raw_manifest_path, raw_capture_manifest)
    _write_jsonl(paths.normalized_output_path, normalization.events)
    _write_json(paths.summary_path, summary)
    _write_json(paths.ingest_report_path, report_core)

    report = dict(report_core)
    report["raw_capture_manifest_path_absolute"] = str(paths.raw_manifest_path)
    report["normalized_events_path_absolute"] = str(paths.normalized_output_path)
    report["tool_behavior_summary_path_absolute"] = str(paths.summary_path)
    report["ingest_report_path_absolute"] = str(paths.ingest_report_path)
    report["raw_capture_manifest_path"] = _relative_artifact_path(
        paths.raw_manifest_path, paths.display_root
    )
    report["normalized_events_path"] = _relative_artifact_path(
        paths.normalized_output_path, paths.display_root
    )
    report["tool_behavior_summary_path"] = _relative_artifact_path(
        paths.summary_path, paths.display_root
    )
    report["ingest_report_path"] = _relative_artifact_path(
        paths.ingest_report_path, paths.display_root
    )
    return report


def ingest_otel_dataset(
    *,
    input_path: Path,
    run_id: str,
    output_root: Path,
    source_system: str,
    fail_on_redaction_error: bool = False,
) -> dict[str, Any]:
    raw_text = input_path.read_text(encoding="utf-8") if input_path.is_file() else None
    if raw_text is None:
        raise FileNotFoundError(f"Raw OTel capture not found: {input_path}")
    raw_capture = _load_raw_capture(input_path)
    context = IngestContext(
        input_path=input_path,
        run_id=run_id,
        output_root=output_root,
        source_system=source_system,
        fail_on_redaction_error=fail_on_redaction_error,
        raw_capture=raw_capture,
        raw_input_sha256=_sha256_text(raw_text),
    )
    return _run_ingest(context)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest local OTel JSON into Rig analytical datasets"
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / ".build" / "rig-relay" / "otel" / "normalized",
    )
    parser.add_argument("--source-system", default="opencode")
    parser.add_argument("--fail-on-redaction-error", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        ingest_otel_dataset(
            input_path=args.input,
            run_id=args.run_id,
            output_root=args.output_root,
            source_system=args.source_system,
            fail_on_redaction_error=args.fail_on_redaction_error,
        )
        return 0
    except FileNotFoundError as exc:
        print(str(exc))
        return 2
    except (ValueError, jsonschema.ValidationError) as exc:
        print(str(exc))
        return 1
