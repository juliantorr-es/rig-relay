from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
DEFAULT_INPUT_ROOT = REPO_ROOT / ".build" / "rig-relay" / "otel" / "normalized"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / ".build" / "rig-relay" / "otel" / "aggregate"

NORMALIZED_EVENT_SCHEMA = "rig.otel.normalized_event.v1"
INGEST_REPORT_SCHEMA = "rig.otel.ingest_report.v1"
SUMMARY_SCHEMA = "rig.otel.tool_behavior_summary.v1"
RUN_MANIFEST_SCHEMA = "rig.otel.run_manifest.v1"
SHORTLIST_SCHEMA = "rig.otel.hardening_shortlist.v1"
AGGREGATE_REPORT_SCHEMA = "rig.otel.aggregate_report.v1"

LATENCY_P95_THRESHOLD_MS = 1000.0
ERROR_COUNT_THRESHOLD = 2
TIMEOUT_COUNT_THRESHOLD = 1
CANCELLATION_COUNT_THRESHOLD = 1
RETRY_COUNT_THRESHOLD = 2
MALFORMED_INPUT_THRESHOLD = 1
REDACTION_DROP_THRESHOLD = 1
EXCESSIVE_ATTRIBUTE_THRESHOLD = 20
UNKNOWN_TOOL_CATEGORY_THRESHOLD = 1
MISSING_TRACE_CONTEXT_THRESHOLD = 1
SEVERITY_HIGH_COUNT_THRESHOLD = 5
SEVERITY_REDACTION_THRESHOLD = 10
SEVERITY_UNKNOWN_THRESHOLD = 5
MISSING_ARTIFACT_COUNT = 3

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
SIGNAL_CATEGORY = {
    "latency": "performance",
    "error_rate": "reliability",
    "retry_loop": "reliability",
    "cancellation": "reliability",
    "timeout": "reliability",
    "missing_trace_context": "telemetry_quality",
    "redaction_pressure": "content_light",
    "malformed_input": "ingest_quality",
    "excessive_attributes": "telemetry_quality",
    "unknown_tool_category": "tool_catalog",
}


@dataclass(slots=True)
class LoadedRun:
    run_id: str
    run_dir: Path
    normalized_events_path: Path
    ingest_report_path: Path
    tool_behavior_summary_path: Path
    normalized_events_sha256: str | None
    ingest_report_sha256: str | None
    tool_behavior_summary_sha256: str | None
    event_count: int
    warning_count: int
    error_count: int
    source_event_count: int
    normalized_event_count: int
    dropped_event_count: int
    redaction_summary: dict[str, int]
    events: list[dict[str, Any]]
    report: dict[str, Any] | None
    summary: dict[str, Any] | None
    issues: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return bool(
            self.normalized_events_sha256
            and self.ingest_report_sha256
            and self.tool_behavior_summary_sha256
        )

    @property
    def evidence_hashes(self) -> list[str]:
        return [
            value
            for value in (
                self.normalized_events_sha256,
                self.ingest_report_sha256,
                self.tool_behavior_summary_sha256,
            )
            if value is not None
        ]


@dataclass(slots=True)
class CategoryStats:
    tool_category: str
    event_count: int = 0
    durations: list[float] = field(default_factory=list)
    error_count: int = 0
    timeout_count: int = 0
    cancellation_count: int = 0
    retry_signature_count: Counter[tuple[str, str]] = field(default_factory=Counter)
    missing_trace_id_count: int = 0
    missing_parent_span_id_count: int = 0
    redaction_drop_count: int = 0
    excessive_attributes_count: int = 0
    unknown_tool_category_count: int = 0
    evidence_run_ids: set[str] = field(default_factory=set)
    evidence_hashes: set[str] = field(default_factory=set)


@dataclass(slots=True)
class EventsArtifact:
    events: list[dict[str, Any]]
    sha256: str | None
    count: int
    issues: list[str]


@dataclass(slots=True)
class ReportArtifact:
    report: dict[str, Any] | None
    sha256: str | None
    warning_count: int
    error_count: int
    issues: list[str]


@dataclass(slots=True)
class SummaryArtifact:
    summary: dict[str, Any] | None
    sha256: str | None
    source_event_count: int
    normalized_event_count: int
    dropped_event_count: int
    redaction_summary: dict[str, int]
    issues: list[str]


@dataclass(frozen=True, slots=True)
class AggregateThresholds:
    latency_p95_threshold_ms: float
    error_count_threshold: int = ERROR_COUNT_THRESHOLD
    timeout_count_threshold: int = TIMEOUT_COUNT_THRESHOLD
    cancellation_count_threshold: int = CANCELLATION_COUNT_THRESHOLD
    retry_count_threshold: int = RETRY_COUNT_THRESHOLD
    redaction_drop_threshold: int = REDACTION_DROP_THRESHOLD
    excessive_attribute_threshold: int = EXCESSIVE_ATTRIBUTE_THRESHOLD
    unknown_tool_category_threshold: int = UNKNOWN_TOOL_CATEGORY_THRESHOLD
    missing_trace_context_threshold: int = MISSING_TRACE_CONTEXT_THRESHOLD
    malformed_input_threshold: int = MALFORMED_INPUT_THRESHOLD


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON: {path}") from exc


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _schema_path(schema_name: str) -> Path:
    return SCHEMAS_DIR / f"{schema_name}.schema.json"


def _validate_against_schema(payload: Any, schema_name: str) -> list[str]:
    schema = _read_json(_schema_path(schema_name))
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        return [str(exc)]
    return []


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _relativize(path: Path, anchor: Path) -> str:
    try:
        return str(path.resolve().relative_to(anchor.resolve()))
    except ValueError:
        return path.name


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (percentile / 100)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _discover_run_dirs(input_root: Path) -> list[Path]:
    if not input_root.exists():
        raise FileNotFoundError(f"Input root not found: {input_root}")
    if not input_root.is_dir():
        raise NotADirectoryError(f"Input root is not a directory: {input_root}")
    return sorted(
        path
        for path in input_root.iterdir()
        if path.is_dir()
        and (
            (path / "otel_normalized_events.v1.jsonl").exists()
            or (path / "otel_ingest_report.v1.json").exists()
            or (path / "otel_tool_behavior_summary.v1.json").exists()
        )
    )


def _load_events_artifact(events_path: Path) -> EventsArtifact:
    if not events_path.exists():
        return EventsArtifact(
            events=[], sha256=None, count=0, issues=["missing_normalized_events"]
        )
    events: list[dict[str, Any]] = []
    schema_errors: list[str] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSONL: {events_path}") from exc
        errors = _validate_against_schema(event, NORMALIZED_EVENT_SCHEMA)
        if errors:
            schema_errors.extend(errors)
        events.append(event)
    if schema_errors:
        raise ValueError("; ".join(schema_errors))
    return EventsArtifact(
        events=events, sha256=_file_sha256(events_path), count=len(events), issues=[]
    )


def _load_report_artifact(report_path: Path) -> ReportArtifact:
    if not report_path.exists():
        return ReportArtifact(
            report=None,
            sha256=None,
            warning_count=0,
            error_count=0,
            issues=["missing_ingest_report"],
        )
    report = _read_json(report_path)
    report_errors = _validate_against_schema(report, INGEST_REPORT_SCHEMA)
    if report_errors:
        raise ValueError("; ".join(report_errors))
    return ReportArtifact(
        report=report,
        sha256=_file_sha256(report_path),
        warning_count=len(report.get("warnings", [])),
        error_count=len(report.get("errors", [])),
        issues=[],
    )


def _load_summary_artifact(summary_path: Path) -> SummaryArtifact:
    if not summary_path.exists():
        return SummaryArtifact(
            summary=None,
            sha256=None,
            source_event_count=0,
            normalized_event_count=0,
            dropped_event_count=0,
            redaction_summary={
                "redacted_count": 0,
                "hashed_count": 0,
                "dropped_count": 0,
            },
            issues=["missing_tool_behavior_summary"],
        )
    summary = _read_json(summary_path)
    summary_errors = _validate_against_schema(summary, SUMMARY_SCHEMA)
    if summary_errors:
        raise ValueError("; ".join(summary_errors))
    redaction_summary = summary.get("redaction_summary", {})
    return SummaryArtifact(
        summary=summary,
        sha256=_file_sha256(summary_path),
        source_event_count=int(summary.get("source_event_count", 0)),
        normalized_event_count=int(summary.get("normalized_event_count", 0)),
        dropped_event_count=int(summary.get("dropped_event_count", 0)),
        redaction_summary={
            "redacted_count": int(redaction_summary.get("redacted_count", 0)),
            "hashed_count": int(redaction_summary.get("hashed_count", 0)),
            "dropped_count": int(redaction_summary.get("dropped_count", 0)),
        },
        issues=[],
    )


def load_normalized_run(run_dir: Path) -> LoadedRun:
    run_id = run_dir.name
    events_path = run_dir / "otel_normalized_events.v1.jsonl"
    report_path = run_dir / "otel_ingest_report.v1.json"
    summary_path = run_dir / "otel_tool_behavior_summary.v1.json"

    events_artifact = _load_events_artifact(events_path)
    report_artifact = _load_report_artifact(report_path)
    summary_artifact = _load_summary_artifact(summary_path)
    issues = [
        *events_artifact.issues,
        *report_artifact.issues,
        *summary_artifact.issues,
    ]
    if len(issues) == MISSING_ARTIFACT_COUNT:
        issues.append("incomplete_run")

    return LoadedRun(
        run_id=run_id,
        run_dir=run_dir,
        normalized_events_path=events_path,
        ingest_report_path=report_path,
        tool_behavior_summary_path=summary_path,
        normalized_events_sha256=events_artifact.sha256,
        ingest_report_sha256=report_artifact.sha256,
        tool_behavior_summary_sha256=summary_artifact.sha256,
        event_count=events_artifact.count,
        warning_count=report_artifact.warning_count,
        error_count=report_artifact.error_count,
        source_event_count=summary_artifact.source_event_count,
        normalized_event_count=summary_artifact.normalized_event_count
        or events_artifact.count,
        dropped_event_count=summary_artifact.dropped_event_count,
        redaction_summary=summary_artifact.redaction_summary,
        events=events_artifact.events,
        report=report_artifact.report,
        summary=summary_artifact.summary,
        issues=issues,
    )


def _tool_category(event: dict[str, Any]) -> str:
    return str(event.get("tool_category") or "unknown")


def _tool_name_hash(event: dict[str, Any]) -> str:
    value = event.get("tool_name_hash")
    return str(value or "")


def _status_code(event: dict[str, Any]) -> str:
    value = event.get("status_code")
    return str(value or "UNKNOWN").upper()


def _is_timeout(event: dict[str, Any]) -> bool:
    return (
        _status_code(event) == "TIMEOUT"
        or "timeout" in str(event.get("span_name", "")).lower()
    )


def _is_cancellation(event: dict[str, Any]) -> bool:
    return (
        _status_code(event) == "CANCELLED"
        or "cancel" in str(event.get("span_name", "")).lower()
    )


def _is_error(event: dict[str, Any]) -> bool:
    return _status_code(event) == "ERROR"


def _is_missing_trace_context(event: dict[str, Any]) -> bool:
    return not event.get("trace_id") or not event.get("span_id")


def _is_excessive_attributes(event: dict[str, Any], threshold: int) -> bool:
    return len(event.get("retained_attribute_keys", [])) > threshold


def _collect_category_stats(
    runs: list[LoadedRun], thresholds: AggregateThresholds
) -> tuple[dict[str, CategoryStats], dict[str, Any]]:
    category_stats: dict[str, CategoryStats] = {}
    global_stats = {
        "missing_trace_context_count": 0,
        "missing_parent_span_id_count": 0,
        "malformed_input_run_ids": [],
        "redaction_drop_count": 0,
        "warning_count": 0,
        "error_count": 0,
        "unknown_tool_category_count": 0,
    }

    for run in runs:
        global_stats["warning_count"] += run.warning_count
        global_stats["error_count"] += run.error_count
        if run.issues:
            global_stats["malformed_input_run_ids"].append(run.run_id)
        if run.summary is not None:
            missing_trace = int(run.summary.get("missing_trace_id_count", 0))
            missing_parent = int(run.summary.get("missing_parent_span_id_count", 0))
            global_stats["missing_trace_context_count"] += (
                missing_trace + missing_parent
            )
            global_stats["redaction_drop_count"] += int(
                run.summary.get("redaction_summary", {}).get("dropped_count", 0)
            )
        for event in run.events:
            category = _tool_category(event)
            stats = category_stats.setdefault(
                category, CategoryStats(tool_category=category)
            )
            stats.event_count += 1
            stats.evidence_run_ids.add(run.run_id)
            stats.evidence_hashes.update(run.evidence_hashes)
            if (duration := event.get("duration_ms")) is not None:
                try:
                    stats.durations.append(float(duration))
                except (TypeError, ValueError):
                    pass
            if _is_error(event):
                stats.error_count += 1
            if _is_timeout(event):
                stats.timeout_count += 1
            if _is_cancellation(event):
                stats.cancellation_count += 1
            if _is_missing_trace_context(event):
                stats.missing_trace_id_count += int(not event.get("trace_id"))
                stats.missing_parent_span_id_count += int(
                    not event.get("parent_span_id")
                )
                global_stats["missing_trace_context_count"] += int(
                    not event.get("trace_id")
                ) + int(not event.get("span_id"))
            stats.redaction_drop_count += len(event.get("dropped_attribute_keys", []))
            stats.excessive_attributes_count += int(
                _is_excessive_attributes(
                    event, thresholds.excessive_attribute_threshold
                )
            )
            stats.unknown_tool_category_count += int(category == "unknown")
            global_stats["unknown_tool_category_count"] += int(category == "unknown")
            signature = (
                str(event.get("span_name") or "unknown"),
                _tool_name_hash(event),
            )
            stats.retry_signature_count[signature] += 1
    return category_stats, global_stats


def _aggregate_retry_count(stats: CategoryStats) -> int:
    return sum(count - 1 for count in stats.retry_signature_count.values() if count > 1)


def _candidate_id(
    aggregate_run_id: str, category: str, signal_kind: str, evidence_run_ids: list[str]
) -> str:
    return _sha256_json({
        "aggregate_run_id": aggregate_run_id,
        "category": category,
        "signal_kind": signal_kind,
        "evidence_run_ids": evidence_run_ids,
    })


def _severity_for_signal(
    signal_kind: str,
    affected_event_count: int,
    *,
    p95_duration_ms: float | None = None,
    p99_duration_ms: float | None = None,
) -> str:
    severity = "low"
    match signal_kind:
        case "malformed_input":
            severity = "high"
        case "latency":
            if (
                p99_duration_ms is not None
                and p99_duration_ms >= LATENCY_P95_THRESHOLD_MS * 2
            ):
                severity = "high"
            else:
                severity = "medium"
        case "error_rate":
            severity = (
                "high"
                if affected_event_count >= SEVERITY_HIGH_COUNT_THRESHOLD
                else "medium"
            )
        case "retry_loop" | "timeout" | "cancellation":
            severity = (
                "medium"
                if affected_event_count < SEVERITY_HIGH_COUNT_THRESHOLD
                else "high"
            )
        case "missing_trace_context":
            severity = (
                "high"
                if affected_event_count >= SEVERITY_HIGH_COUNT_THRESHOLD
                else "medium"
            )
        case "redaction_pressure" | "excessive_attributes":
            severity = (
                "medium"
                if affected_event_count < SEVERITY_REDACTION_THRESHOLD
                else "high"
            )
        case "unknown_tool_category":
            severity = (
                "low" if affected_event_count < SEVERITY_UNKNOWN_THRESHOLD else "medium"
            )
    return severity


def _category_summary_candidate(
    *,
    aggregate_run_id: str,
    signal_kind: str,
    category: str,
    stats: CategoryStats,
    thresholds: AggregateThresholds,
) -> dict[str, Any] | None:
    p50 = _percentile(stats.durations, 50) if stats.durations else None
    p95 = _percentile(stats.durations, 95) if stats.durations else None
    p99 = _percentile(stats.durations, 99) if stats.durations else None
    retry_count = _aggregate_retry_count(stats)
    affected_event_count = stats.event_count
    candidate = False
    match signal_kind:
        case "latency":
            candidate = bool(
                stats.durations
                and (
                    (p95 is not None and p95 >= thresholds.latency_p95_threshold_ms)
                    or (p99 is not None and p99 >= thresholds.latency_p95_threshold_ms)
                )
            )
        case "error_rate":
            candidate = stats.error_count >= thresholds.error_count_threshold
            if candidate:
                affected_event_count = stats.error_count
        case "retry_loop":
            candidate = retry_count >= thresholds.retry_count_threshold
            if candidate:
                affected_event_count = retry_count
        case "timeout" | "cancellation":
            candidate = (
                stats.timeout_count >= thresholds.timeout_count_threshold
                if signal_kind == "timeout"
                else stats.cancellation_count >= thresholds.cancellation_count_threshold
            )
            if candidate:
                affected_event_count = (
                    stats.timeout_count
                    if signal_kind == "timeout"
                    else stats.cancellation_count
                )
        case "redaction_pressure" | "excessive_attributes":
            candidate = (
                stats.redaction_drop_count >= thresholds.redaction_drop_threshold
                if signal_kind == "redaction_pressure"
                else stats.excessive_attributes_count
                >= thresholds.excessive_attribute_threshold
            )
            if candidate:
                affected_event_count = (
                    stats.redaction_drop_count
                    if signal_kind == "redaction_pressure"
                    else stats.excessive_attributes_count
                )
        case "unknown_tool_category":
            candidate = (
                stats.unknown_tool_category_count
                >= thresholds.unknown_tool_category_threshold
            )
            if candidate:
                affected_event_count = stats.unknown_tool_category_count
    if not candidate:
        return None
    evidence_run_ids = sorted(stats.evidence_run_ids)
    return {
        "candidate_id": _candidate_id(
            aggregate_run_id, category, signal_kind, evidence_run_ids
        ),
        "category": category,
        "severity": _severity_for_signal(
            signal_kind, affected_event_count, p95_duration_ms=p95, p99_duration_ms=p99
        ),
        "signal_kind": signal_kind,
        "affected_tool_category": stats.tool_category,
        "affected_event_count": affected_event_count,
        "evidence_run_ids": evidence_run_ids,
        "p50_duration_ms": round(p50, 3) if p50 is not None else None,
        "p95_duration_ms": round(p95, 3) if p95 is not None else None,
        "p99_duration_ms": round(p99, 3) if p99 is not None else None,
        "error_count": stats.error_count,
        "retry_count": retry_count,
        "timeout_count": stats.timeout_count,
        "cancellation_count": stats.cancellation_count,
        "missing_trace_id_count": stats.missing_trace_id_count,
        "missing_parent_span_id_count": stats.missing_parent_span_id_count,
        "redaction_drop_count": stats.redaction_drop_count,
        "recommended_hardening_action": _recommended_action(signal_kind, category),
        "content_light_evidence_hashes": sorted(stats.evidence_hashes),
    }


def _recommended_action(signal_kind: str, category: str) -> str:
    actions = {
        "latency": f"Reduce tail latency for {category} tool calls",
        "error_rate": f"Harden failure handling for {category} tool calls",
        "retry_loop": f"Reduce retry loops for {category} tool calls",
        "timeout": f"Add timeout handling for {category} tool calls",
        "cancellation": f"Clarify cancellation handling for {category} tool calls",
        "missing_trace_context": "Preserve trace and parent span identifiers",
        "redaction_pressure": "Reduce sensitive attribute leakage into telemetry",
        "malformed_input": "Harden ingest parsing and quarantine malformed runs",
        "excessive_attributes": "Trim or hash noisy telemetry attributes",
        "unknown_tool_category": "Normalize tool category classification",
    }
    return actions.get(signal_kind, "Review telemetry pattern and harden the tool path")


def _build_malformed_input_candidate(
    *, aggregate_run_id: str, runs: list[LoadedRun], thresholds: AggregateThresholds
) -> dict[str, Any] | None:
    affected_runs = sorted({
        run.run_id for run in runs if run.issues or run.warning_count or run.error_count
    })
    if not affected_runs:
        return None
    evidence_hashes = sorted({
        hash_value for run in runs for hash_value in run.evidence_hashes
    })
    affected_event_count = sum(
        1 + run.warning_count + run.error_count
        for run in runs
        if run.issues or run.warning_count or run.error_count
    )
    return {
        "candidate_id": _candidate_id(
            aggregate_run_id, "ingest_quality", "malformed_input", affected_runs
        ),
        "category": "ingest_quality",
        "severity": "high"
        if affected_event_count >= thresholds.malformed_input_threshold
        else "medium",
        "signal_kind": "malformed_input",
        "affected_tool_category": "unknown",
        "affected_event_count": affected_event_count,
        "evidence_run_ids": affected_runs,
        "p50_duration_ms": None,
        "p95_duration_ms": None,
        "p99_duration_ms": None,
        "error_count": sum(
            run.error_count
            for run in runs
            if run.issues or run.warning_count or run.error_count
        ),
        "retry_count": 0,
        "timeout_count": 0,
        "cancellation_count": 0,
        "missing_trace_id_count": 0,
        "missing_parent_span_id_count": 0,
        "redaction_drop_count": 0,
        "recommended_hardening_action": "Quarantine malformed inputs and repair the collector/export path",
        "content_light_evidence_hashes": evidence_hashes,
    }


def _build_missing_trace_context_candidate(
    *,
    aggregate_run_id: str,
    runs: list[LoadedRun],
    category_stats: dict[str, CategoryStats],
) -> dict[str, Any] | None:
    missing_trace_ids = 0
    missing_parent_span_ids = 0
    evidence_run_ids: set[str] = set()
    evidence_hashes: set[str] = set()
    for stats in category_stats.values():
        missing_trace_ids += stats.missing_trace_id_count
        missing_parent_span_ids += stats.missing_parent_span_id_count
        if stats.missing_trace_id_count or stats.missing_parent_span_id_count:
            evidence_run_ids.update(stats.evidence_run_ids)
            evidence_hashes.update(stats.evidence_hashes)
    for run in runs:
        if run.summary is not None and (
            int(run.summary.get("missing_trace_id_count", 0))
            or int(run.summary.get("missing_parent_span_id_count", 0))
        ):
            evidence_run_ids.add(run.run_id)
            evidence_hashes.update(run.evidence_hashes)
    affected_event_count = missing_trace_ids + missing_parent_span_ids
    if affected_event_count < MISSING_TRACE_CONTEXT_THRESHOLD:
        return None
    evidence_run_ids_list = sorted(evidence_run_ids)
    return {
        "candidate_id": _candidate_id(
            aggregate_run_id,
            "telemetry_quality",
            "missing_trace_context",
            evidence_run_ids_list,
        ),
        "category": "telemetry_quality",
        "severity": _severity_for_signal("missing_trace_context", affected_event_count),
        "signal_kind": "missing_trace_context",
        "affected_tool_category": "unknown",
        "affected_event_count": affected_event_count,
        "evidence_run_ids": evidence_run_ids_list,
        "p50_duration_ms": None,
        "p95_duration_ms": None,
        "p99_duration_ms": None,
        "error_count": 0,
        "retry_count": 0,
        "timeout_count": 0,
        "cancellation_count": 0,
        "missing_trace_id_count": missing_trace_ids,
        "missing_parent_span_id_count": missing_parent_span_ids,
        "redaction_drop_count": 0,
        "recommended_hardening_action": "Preserve trace and parent span context across the tool boundary",
        "content_light_evidence_hashes": sorted(evidence_hashes),
    }


def build_hardening_shortlist(
    *,
    aggregate_run_id: str,
    generated_at: str,
    runs: list[LoadedRun],
    run_manifest: dict[str, Any],
    thresholds: AggregateThresholds,
) -> dict[str, Any]:
    category_stats, global_stats = _collect_category_stats(runs, thresholds)
    candidates: list[dict[str, Any]] = []

    for _category, stats in sorted(category_stats.items()):
        for signal_kind in (
            "latency",
            "error_rate",
            "retry_loop",
            "timeout",
            "cancellation",
            "redaction_pressure",
            "excessive_attributes",
            "unknown_tool_category",
        ):
            candidate = _category_summary_candidate(
                aggregate_run_id=aggregate_run_id,
                signal_kind=signal_kind,
                category=SIGNAL_CATEGORY[signal_kind],
                stats=stats,
                thresholds=thresholds,
            )
            if candidate is not None:
                candidates.append(candidate)

    malformed_candidate = _build_malformed_input_candidate(
        aggregate_run_id=aggregate_run_id, runs=runs, thresholds=thresholds
    )
    if malformed_candidate is not None:
        candidates.append(malformed_candidate)

    missing_trace_candidate = _build_missing_trace_context_candidate(
        aggregate_run_id=aggregate_run_id, runs=runs, category_stats=category_stats
    )
    if missing_trace_candidate is not None:
        candidates.append(missing_trace_candidate)

    candidates = sorted(
        candidates,
        key=lambda candidate: (
            -SEVERITY_ORDER[candidate["severity"]],
            candidate["signal_kind"],
            candidate["affected_tool_category"],
            candidate["candidate_id"],
        ),
    )

    summary = {
        "input_run_count": len(runs),
        "loaded_run_count": len([run for run in runs if run.complete]),
        "skipped_run_count": len(runs) - len([run for run in runs if run.complete]),
        "candidate_count": len(candidates),
        "signal_kind_counts": dict(
            Counter(candidate["signal_kind"] for candidate in candidates)
        ),
        "thresholds": {
            "latency_p95_threshold_ms": thresholds.latency_p95_threshold_ms,
            "error_count_threshold": thresholds.error_count_threshold,
            "timeout_count_threshold": thresholds.timeout_count_threshold,
            "cancellation_count_threshold": thresholds.cancellation_count_threshold,
            "retry_count_threshold": thresholds.retry_count_threshold,
            "redaction_drop_threshold": thresholds.redaction_drop_threshold,
            "excessive_attribute_threshold": thresholds.excessive_attribute_threshold,
            "unknown_tool_category_threshold": thresholds.unknown_tool_category_threshold,
            "missing_trace_context_threshold": thresholds.missing_trace_context_threshold,
            "malformed_input_threshold": thresholds.malformed_input_threshold,
        },
        "warning_count": sum(run.warning_count for run in runs)
        + len(global_stats["malformed_input_run_ids"]),
        "error_count": sum(run.error_count for run in runs),
        "content_light": True,
        "local_only": True,
        "source_event_count": int(run_manifest["source_event_count"]),
        "normalized_event_count": int(run_manifest["normalized_event_count"]),
        "dropped_event_count": int(run_manifest["dropped_event_count"]),
        "redaction_summary": dict(run_manifest["redaction_summary"]),
        "malformed_input_run_ids": sorted(global_stats["malformed_input_run_ids"]),
        "unknown_tool_category_count": global_stats["unknown_tool_category_count"],
        "missing_trace_context_count": global_stats["missing_trace_context_count"],
        "redaction_drop_count": global_stats["redaction_drop_count"],
        "run_manifest_sha256": run_manifest["manifest_sha256"],
        "aggregate_input_sha256": run_manifest["aggregate_input_sha256"],
    }
    return {
        "schema_version": SHORTLIST_SCHEMA,
        "aggregate_run_id": aggregate_run_id,
        "generated_at": generated_at,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "summary": summary,
    }


def build_run_manifest(
    *, aggregate_run_id: str, generated_at: str, input_root: Path, runs: list[LoadedRun]
) -> dict[str, Any]:
    complete_runs = [run for run in runs if run.complete]
    input_runs = [
        {
            "run_id": run.run_id,
            "normalized_events_path": _relativize(
                run.normalized_events_path, input_root.parent
            ),
            "ingest_report_path": _relativize(
                run.ingest_report_path, input_root.parent
            ),
            "tool_behavior_summary_path": _relativize(
                run.tool_behavior_summary_path, input_root.parent
            ),
            "normalized_events_sha256": run.normalized_events_sha256,
            "ingest_report_sha256": run.ingest_report_sha256,
            "tool_behavior_summary_sha256": run.tool_behavior_summary_sha256,
            "event_count": run.event_count,
            "warning_count": run.warning_count,
            "error_count": run.error_count,
        }
        for run in complete_runs
    ]
    source_event_count = sum(run.source_event_count for run in complete_runs)
    normalized_event_count = sum(run.normalized_event_count for run in complete_runs)
    dropped_event_count = sum(run.dropped_event_count for run in complete_runs)
    redaction_summary = {
        "run_count": len(complete_runs),
        "skipped_run_count": len(runs) - len(complete_runs),
        "redacted_count": sum(
            run.redaction_summary["redacted_count"] for run in complete_runs
        ),
        "hashed_count": sum(
            run.redaction_summary["hashed_count"] for run in complete_runs
        ),
        "dropped_count": sum(
            run.redaction_summary["dropped_count"] for run in complete_runs
        ),
        "warning_count": sum(run.warning_count for run in complete_runs),
        "error_count": sum(run.error_count for run in complete_runs),
    }
    manifest_core = {
        "schema_version": RUN_MANIFEST_SCHEMA,
        "aggregate_run_id": aggregate_run_id,
        "generated_at": generated_at,
        "input_runs": input_runs,
        "input_run_count": len(input_runs),
        "source_event_count": source_event_count,
        "normalized_event_count": normalized_event_count,
        "dropped_event_count": dropped_event_count,
        "aggregate_input_sha256": _sha256_json({
            "aggregate_run_id": aggregate_run_id,
            "generated_at": generated_at,
            "input_runs": input_runs,
            "source_event_count": source_event_count,
            "normalized_event_count": normalized_event_count,
            "dropped_event_count": dropped_event_count,
            "redaction_summary": redaction_summary,
        }),
        "redaction_summary": redaction_summary,
        "content_light": True,
        "local_only": True,
    }
    manifest_core["manifest_sha256"] = _sha256_json(manifest_core)
    return manifest_core


def validate_aggregate_outputs(
    *,
    run_manifest: dict[str, Any],
    hardening_shortlist: dict[str, Any],
    aggregate_report: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    run_manifest_errors = _validate_against_schema(run_manifest, RUN_MANIFEST_SCHEMA)
    shortlist_errors = _validate_against_schema(hardening_shortlist, SHORTLIST_SCHEMA)
    aggregate_report_errors = _validate_against_schema(
        aggregate_report, AGGREGATE_REPORT_SCHEMA
    )
    return {
        "run_manifest": {
            "valid": not run_manifest_errors,
            "errors": run_manifest_errors,
        },
        "hardening_shortlist": {
            "valid": not shortlist_errors,
            "errors": shortlist_errors,
        },
        "aggregate_report": {
            "valid": not aggregate_report_errors,
            "errors": aggregate_report_errors,
        },
    }


def _aggregate_verdict(
    *,
    runs: list[LoadedRun],
    min_runs: int,
    validation_results: dict[str, dict[str, Any]],
) -> str:
    complete_run_count = len([run for run in runs if run.complete])
    if any(not result["valid"] for result in validation_results.values()):
        return "fail"
    if complete_run_count < min_runs:
        return "hold"
    if any(run.issues for run in runs):
        return "hold"
    if any(run.warning_count or run.error_count for run in runs):
        return "hold"
    return "pass"


def _aggregate_report_core(
    *,
    aggregate_run_id: str,
    generated_at: str,
    run_manifest_path: Path,
    hardening_shortlist_path: Path,
    path_anchor: Path,
    validation_results: dict[str, dict[str, Any]],
    warnings: list[str],
    errors: list[str],
    verdict: str,
) -> dict[str, Any]:
    return {
        "schema_version": AGGREGATE_REPORT_SCHEMA,
        "aggregate_run_id": aggregate_run_id,
        "generated_at": generated_at,
        "run_manifest_path": _relativize(run_manifest_path, path_anchor),
        "hardening_shortlist_path": _relativize(hardening_shortlist_path, path_anchor),
        "aggregate_verdict": verdict,
        "schema_validation_results": validation_results,
        "warnings": warnings,
        "errors": errors,
        "local_only": True,
        "coordination_ledger_mutated": False,
        "release_gate_mutated": False,
    }


def _aggregate_artifact_paths(
    output_root: Path, aggregate_run_id: str
) -> dict[str, Path]:
    aggregate_dir = output_root / aggregate_run_id
    return {
        "aggregate_dir": aggregate_dir,
        "run_manifest_path": aggregate_dir / "otel_run_manifest.v1.json",
        "hardening_shortlist_path": aggregate_dir / "otel_hardening_shortlist.v1.json",
        "aggregate_report_path": aggregate_dir / "otel_aggregate_report.v1.json",
    }


def write_aggregate_report(
    *,
    output_root: Path,
    aggregate_run_id: str,
    run_manifest: dict[str, Any],
    hardening_shortlist: dict[str, Any],
    aggregate_report: dict[str, Any],
) -> dict[str, Any]:
    paths = _aggregate_artifact_paths(output_root, aggregate_run_id)
    _write_json(paths["run_manifest_path"], run_manifest)
    _write_json(paths["hardening_shortlist_path"], hardening_shortlist)
    _write_json(paths["aggregate_report_path"], aggregate_report)
    return {
        "run_manifest_path": str(paths["run_manifest_path"]),
        "hardening_shortlist_path": str(paths["hardening_shortlist_path"]),
        "aggregate_report_path": str(paths["aggregate_report_path"]),
        "run_manifest_sha256": _file_sha256(paths["run_manifest_path"]),
        "hardening_shortlist_sha256": _file_sha256(paths["hardening_shortlist_path"]),
        "aggregate_report_sha256": _file_sha256(paths["aggregate_report_path"]),
    }


def aggregate_otel_runs(
    *,
    input_root: Path = DEFAULT_INPUT_ROOT,
    aggregate_run_id: str,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    min_runs: int = 1,
    latency_p95_threshold_ms: float = LATENCY_P95_THRESHOLD_MS,
    fail_on_schema_error: bool = False,
) -> dict[str, Any]:
    run_dirs = _discover_run_dirs(input_root)
    loaded_runs = [load_normalized_run(run_dir) for run_dir in run_dirs]
    generated_at = _now()
    thresholds = AggregateThresholds(latency_p95_threshold_ms=latency_p95_threshold_ms)

    run_manifest = build_run_manifest(
        aggregate_run_id=aggregate_run_id,
        generated_at=generated_at,
        input_root=input_root,
        runs=loaded_runs,
    )
    shortlist = build_hardening_shortlist(
        aggregate_run_id=aggregate_run_id,
        generated_at=generated_at,
        runs=loaded_runs,
        run_manifest=run_manifest,
        thresholds=thresholds,
    )

    preliminary_report = _aggregate_report_core(
        aggregate_run_id=aggregate_run_id,
        generated_at=generated_at,
        run_manifest_path=_aggregate_artifact_paths(output_root, aggregate_run_id)[
            "run_manifest_path"
        ],
        hardening_shortlist_path=_aggregate_artifact_paths(
            output_root, aggregate_run_id
        )["hardening_shortlist_path"],
        path_anchor=output_root.parent,
        validation_results={
            "run_manifest": {"valid": True, "errors": []},
            "hardening_shortlist": {"valid": True, "errors": []},
            "aggregate_report": {"valid": True, "errors": []},
        },
        warnings=[],
        errors=[],
        verdict="pass",
    )

    validation_results = validate_aggregate_outputs(
        run_manifest=run_manifest,
        hardening_shortlist=shortlist,
        aggregate_report=preliminary_report,
    )

    warnings = []
    errors = []
    for run in loaded_runs:
        if run.issues:
            warnings.append(f"{run.run_id}: {'; '.join(run.issues)}")
    if len([run for run in loaded_runs if run.complete]) < min_runs:
        warnings.append(
            f"insufficient complete runs for aggregation: {len([run for run in loaded_runs if run.complete])} < {min_runs}"
        )
    if any(run.warning_count or run.error_count for run in loaded_runs):
        warnings.append("source ingest reports contained warnings or errors")
    verdict = _aggregate_verdict(
        runs=loaded_runs, min_runs=min_runs, validation_results=validation_results
    )
    if any(not result["valid"] for result in validation_results.values()):
        errors.extend(
            error
            for result in validation_results.values()
            for error in result["errors"]
        )
    aggregate_report = _aggregate_report_core(
        aggregate_run_id=aggregate_run_id,
        generated_at=generated_at,
        run_manifest_path=_aggregate_artifact_paths(output_root, aggregate_run_id)[
            "run_manifest_path"
        ],
        hardening_shortlist_path=_aggregate_artifact_paths(
            output_root, aggregate_run_id
        )["hardening_shortlist_path"],
        path_anchor=output_root.parent,
        validation_results=validation_results,
        warnings=warnings,
        errors=errors,
        verdict=verdict,
    )
    if fail_on_schema_error and any(
        not result["valid"] for result in validation_results.values()
    ):
        raise ValueError("Aggregate outputs failed schema validation")

    write_result = write_aggregate_report(
        output_root=output_root,
        aggregate_run_id=aggregate_run_id,
        run_manifest=run_manifest,
        hardening_shortlist=shortlist,
        aggregate_report=aggregate_report,
    )

    report = dict(aggregate_report)
    report["run_manifest_path_absolute"] = write_result["run_manifest_path"]
    report["hardening_shortlist_path_absolute"] = write_result[
        "hardening_shortlist_path"
    ]
    report["aggregate_report_path_absolute"] = write_result["aggregate_report_path"]
    report["run_manifest_sha256"] = write_result["run_manifest_sha256"]
    report["hardening_shortlist_sha256"] = write_result["hardening_shortlist_sha256"]
    report["aggregate_report_sha256"] = write_result["aggregate_report_sha256"]
    report["aggregate_verdict"] = verdict
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate Rig OTel run manifests into a local hardening shortlist"
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--min-runs", type=int, default=1)
    parser.add_argument(
        "--latency-p95-threshold-ms", type=float, default=LATENCY_P95_THRESHOLD_MS
    )
    parser.add_argument("--fail-on-schema-error", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        report = aggregate_otel_runs(
            input_root=args.input_root,
            aggregate_run_id=args.run_id,
            output_root=args.output_root,
            min_runs=args.min_runs,
            latency_p95_threshold_ms=args.latency_p95_threshold_ms,
            fail_on_schema_error=args.fail_on_schema_error,
        )
        match report["aggregate_verdict"]:
            case "pass":
                return 0
            case "hold":
                return 2
            case "fail":
                return 1
        return 1
    except FileNotFoundError as exc:
        print(str(exc))
        return 2
    except (NotADirectoryError, ValueError, jsonschema.ValidationError) as exc:
        print(str(exc))
        return 1
