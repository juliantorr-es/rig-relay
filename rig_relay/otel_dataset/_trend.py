from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
DEFAULT_INPUT_ROOT = REPO_ROOT / ".build" / "rig-relay" / "otel" / "aggregate"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / ".build" / "rig-relay" / "otel" / "trends"

TREND_REPORT_SCHEMA = "rig.otel.trend_report.v1"
HARDENING_DELTA_SCHEMA = "rig.otel.hardening_delta.v1"

CONSECUTIVE_IMPROVEMENT_RATIO = 0.8
MIN_COMPARISON_RUNS = 2
SINGLE_OCCURRENCE_COUNT = 1
HIGH_CONFIDENCE_RUN_COUNT = 4
HIGH_CONFIDENCE_OCCURRENCE_COUNT = 3
MEDIUM_CONFIDENCE_OCCURRENCE_COUNT = 2

TREND_CLASS_ORDER = {
    "persistent_pain": 0,
    "new_regression": 1,
    "improved": 2,
    "one_off_noise": 3,
    "insufficient_sample": 4,
}

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass(slots=True)
class LoadedAggregateRun:
    run_id: str
    run_dir: Path
    run_manifest_path: Path
    hardening_shortlist_path: Path
    aggregate_report_path: Path
    run_manifest: dict[str, Any] | None
    hardening_shortlist: dict[str, Any] | None
    aggregate_report: dict[str, Any] | None
    run_manifest_sha256: str | None
    hardening_shortlist_sha256: str | None
    aggregate_report_sha256: str | None
    warning_count: int
    error_count: int
    issues: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return bool(
            self.run_manifest_sha256
            and self.hardening_shortlist_sha256
            and self.aggregate_report_sha256
            and not self.issues
        )

    @property
    def evidence_hashes(self) -> list[str]:
        return [
            value
            for value in (
                self.run_manifest_sha256,
                self.hardening_shortlist_sha256,
                self.aggregate_report_sha256,
            )
            if value is not None
        ]

    @property
    def generated_at(self) -> str:
        if self.aggregate_report is not None:
            value = self.aggregate_report.get("generated_at")
            if isinstance(value, str):
                return value
        if self.run_manifest is not None:
            value = self.run_manifest.get("generated_at")
            if isinstance(value, str):
                return value
        return ""

    @property
    def candidate_map(self) -> dict[tuple[str, str], dict[str, Any]]:
        if self.hardening_shortlist is None:
            return {}
        candidates = self.hardening_shortlist.get("candidates", [])
        if not isinstance(candidates, list):
            return {}
        return {
            (
                str(candidate.get("affected_tool_category", "unknown")),
                str(candidate.get("signal_kind", "unknown")),
            ): candidate
            for candidate in candidates
            if isinstance(candidate, dict)
        }


@dataclass(slots=True)
class MetricSnapshot:
    candidate_count: int = 0
    affected_event_count: int = 0
    p50_duration_ms: float | None = None
    p95_duration_ms: float | None = None
    p99_duration_ms: float | None = None
    error_count: int = 0
    retry_count: int = 0
    timeout_count: int = 0
    cancellation_count: int = 0
    missing_trace_id_count: int = 0
    missing_parent_span_id_count: int = 0
    redaction_drop_count: int = 0
    unknown_tool_category_count: int = 0

    @classmethod
    def zero(cls) -> MetricSnapshot:
        return cls()

    @classmethod
    def from_candidate(cls, candidate: dict[str, Any] | None) -> MetricSnapshot:
        if candidate is None:
            return cls.zero()
        unknown_count = 0
        if str(candidate.get("signal_kind")) == "unknown_tool_category":
            unknown_count = int(candidate.get("affected_event_count", 0))
        return cls(
            candidate_count=1,
            affected_event_count=int(candidate.get("affected_event_count", 0)),
            p50_duration_ms=_optional_float(candidate.get("p50_duration_ms")),
            p95_duration_ms=_optional_float(candidate.get("p95_duration_ms")),
            p99_duration_ms=_optional_float(candidate.get("p99_duration_ms")),
            error_count=int(candidate.get("error_count", 0)),
            retry_count=int(candidate.get("retry_count", 0)),
            timeout_count=int(candidate.get("timeout_count", 0)),
            cancellation_count=int(candidate.get("cancellation_count", 0)),
            missing_trace_id_count=int(candidate.get("missing_trace_id_count", 0)),
            missing_parent_span_id_count=int(
                candidate.get("missing_parent_span_id_count", 0)
            ),
            redaction_drop_count=int(candidate.get("redaction_drop_count", 0)),
            unknown_tool_category_count=unknown_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": self.candidate_count,
            "affected_event_count": self.affected_event_count,
            "p50_duration_ms": self.p50_duration_ms,
            "p95_duration_ms": self.p95_duration_ms,
            "p99_duration_ms": self.p99_duration_ms,
            "error_count": self.error_count,
            "retry_count": self.retry_count,
            "timeout_count": self.timeout_count,
            "cancellation_count": self.cancellation_count,
            "missing_trace_id_count": self.missing_trace_id_count,
            "missing_parent_span_id_count": self.missing_parent_span_id_count,
            "redaction_drop_count": self.redaction_drop_count,
            "unknown_tool_category_count": self.unknown_tool_category_count,
        }

    def delta(self, other: MetricSnapshot) -> dict[str, Any]:
        return {
            "candidate_count": self.candidate_count - other.candidate_count,
            "affected_event_count": (
                self.affected_event_count - other.affected_event_count
            ),
            "p50_duration_ms": _numeric_delta(
                self.p50_duration_ms, other.p50_duration_ms
            ),
            "p95_duration_ms": _numeric_delta(
                self.p95_duration_ms, other.p95_duration_ms
            ),
            "p99_duration_ms": _numeric_delta(
                self.p99_duration_ms, other.p99_duration_ms
            ),
            "error_count": self.error_count - other.error_count,
            "retry_count": self.retry_count - other.retry_count,
            "timeout_count": self.timeout_count - other.timeout_count,
            "cancellation_count": self.cancellation_count - other.cancellation_count,
            "missing_trace_id_count": (
                self.missing_trace_id_count - other.missing_trace_id_count
            ),
            "missing_parent_span_id_count": (
                self.missing_parent_span_id_count - other.missing_parent_span_id_count
            ),
            "redaction_drop_count": self.redaction_drop_count
            - other.redaction_drop_count,
            "unknown_tool_category_count": (
                self.unknown_tool_category_count - other.unknown_tool_category_count
            ),
        }


@dataclass(frozen=True, slots=True)
class TrendThresholds:
    latency_p95_regression_ms: float = 1000.0
    error_count_regression: int = 2
    retry_count_regression: int = 2
    redaction_drop_regression: int = 1


@dataclass(frozen=True, slots=True)
class TrendReportCoreInput:
    trend_run_id: str
    generated_at: str
    deltas_path: Path
    comparison_window: dict[str, Any]
    runs: list[LoadedAggregateRun]
    deltas: list[dict[str, Any]]
    warnings: list[str]
    errors: list[str]
    verdict: str
    path_anchor: Path


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


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


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _numeric_delta(latest: float | None, baseline: float | None) -> float | None:
    if latest is None and baseline is None:
        return None
    if latest is None:
        return -baseline if baseline is not None else None
    if baseline is None:
        return latest
    return latest - baseline


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
            (path / "otel_run_manifest.v1.json").exists()
            or (path / "otel_hardening_shortlist.v1.json").exists()
            or (path / "otel_aggregate_report.v1.json").exists()
        )
    )


def _load_json_artifact(
    path: Path, *, schema_name: str, missing_issue: str
) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    if not path.is_file():
        return None, None, [missing_issue]
    payload = _read_json(path)
    errors = _validate_against_schema(payload, schema_name)
    if errors:
        raise ValueError("; ".join(errors))
    return payload, _file_sha256(path), []


def load_aggregate_run(run_dir: Path) -> LoadedAggregateRun:
    run_id = run_dir.name
    paths = {
        "manifest": run_dir / "otel_run_manifest.v1.json",
        "shortlist": run_dir / "otel_hardening_shortlist.v1.json",
        "report": run_dir / "otel_aggregate_report.v1.json",
    }
    manifest_artifact = _load_json_artifact(
        paths["manifest"],
        schema_name="rig.otel.run_manifest.v1",
        missing_issue="missing_run_manifest",
    )
    shortlist_artifact = _load_json_artifact(
        paths["shortlist"],
        schema_name="rig.otel.hardening_shortlist.v1",
        missing_issue="missing_hardening_shortlist",
    )
    report_artifact = _load_json_artifact(
        paths["report"],
        schema_name="rig.otel.aggregate_report.v1",
        missing_issue="missing_aggregate_report",
    )
    manifest, manifest_sha256, manifest_issues = manifest_artifact
    shortlist, shortlist_sha256, shortlist_issues = shortlist_artifact
    report, report_sha256, report_issues = report_artifact
    issues = [*manifest_issues, *shortlist_issues, *report_issues]

    return LoadedAggregateRun(
        run_id=run_id,
        run_dir=run_dir,
        run_manifest_path=paths["manifest"],
        hardening_shortlist_path=paths["shortlist"],
        aggregate_report_path=paths["report"],
        run_manifest=manifest,
        hardening_shortlist=shortlist,
        aggregate_report=report,
        run_manifest_sha256=manifest_sha256,
        hardening_shortlist_sha256=shortlist_sha256,
        aggregate_report_sha256=report_sha256,
        warning_count=len(report.get("warnings", []))
        if isinstance(report, dict)
        else 0,
        error_count=len(report.get("errors", [])) if isinstance(report, dict) else 0,
        issues=issues,
    )


def _candidate_presence_series(
    runs: list[LoadedAggregateRun],
) -> dict[tuple[str, str], list[dict[str, Any] | None]]:
    series: dict[tuple[str, str], list[dict[str, Any] | None]] = defaultdict(list)
    ordered_keys = sorted(
        {key for run in runs for key in run.candidate_map},
        key=lambda key: (key[0], key[1]),
    )
    for key in ordered_keys:
        series[key] = [run.candidate_map.get(key) for run in runs]
    return series


def _series_key(candidate: dict[str, Any]) -> tuple[str, str]:
    return (
        str(candidate.get("affected_tool_category", "unknown")),
        str(candidate.get("signal_kind", "unknown")),
    )


def _first_present_index(series: list[dict[str, Any] | None]) -> int | None:
    for index, candidate in enumerate(series):
        if candidate is not None:
            return index
    return None


def _last_present_index(series: list[dict[str, Any] | None]) -> int | None:
    for index in range(len(series) - 1, -1, -1):
        if series[index] is not None:
            return index
    return None


def _candidate_id(
    *,
    trend_run_id: str,
    affected_tool_category: str,
    signal_kind: str,
    trend_class: str,
    first_seen_run_id: str,
    latest_seen_run_id: str,
) -> str:
    return _sha256_json({
        "trend_run_id": trend_run_id,
        "affected_tool_category": affected_tool_category,
        "signal_kind": signal_kind,
        "trend_class": trend_class,
        "first_seen_run_id": first_seen_run_id,
        "latest_seen_run_id": latest_seen_run_id,
    })


def _baseline_or_latest_hashes(runs: list[LoadedAggregateRun]) -> list[str]:
    hashes: set[str] = set()
    for run in runs:
        hashes.update(run.evidence_hashes)
    return sorted(hashes)


def _severity_for_candidate(candidate: dict[str, Any] | None) -> str:
    if candidate is None:
        return "low"
    severity = str(candidate.get("severity", "low"))
    if severity in SEVERITY_ORDER:
        return severity
    return "low"


def _severity_for_trend(
    trend_class: str,
    *,
    baseline: MetricSnapshot,
    latest: MetricSnapshot,
    latest_candidate: dict[str, Any] | None,
) -> str:
    candidate_severity = _severity_for_candidate(latest_candidate)
    severity = "low"
    if trend_class == "persistent_pain":
        severity = candidate_severity if candidate_severity != "low" else "medium"
    elif trend_class == "new_regression":
        severity = (
            candidate_severity if candidate_severity in {"high", "critical"} else "high"
        )
    elif trend_class == "improved":
        severity = "low" if latest.affected_event_count == 0 else "medium"
    elif trend_class == "one_off_noise":
        severity = candidate_severity
    return severity


def _confidence_for_trend(
    *, trend_class: str, candidate_presence_count: int, run_count: int
) -> str:
    confidence = "low"
    if trend_class != "insufficient_sample":
        if (
            run_count >= HIGH_CONFIDENCE_RUN_COUNT
            and candidate_presence_count >= HIGH_CONFIDENCE_OCCURRENCE_COUNT
        ):
            confidence = "high"
        elif candidate_presence_count >= MEDIUM_CONFIDENCE_OCCURRENCE_COUNT:
            confidence = "medium"
    return confidence


def _materially_improved(
    signal_kind: str,
    baseline: MetricSnapshot,
    latest: MetricSnapshot,
    thresholds: TrendThresholds,
) -> bool:
    improved = False
    match signal_kind:
        case "latency":
            if baseline.candidate_count and not latest.candidate_count:
                improved = True
            elif (
                baseline.p95_duration_ms is not None
                and latest.p95_duration_ms is not None
            ):
                improved = (
                    baseline.p95_duration_ms - latest.p95_duration_ms
                    >= thresholds.latency_p95_regression_ms
                    or latest.p95_duration_ms
                    <= baseline.p95_duration_ms * CONSECUTIVE_IMPROVEMENT_RATIO
                )
        case "error_rate":
            improved = (
                baseline.error_count - latest.error_count
                >= thresholds.error_count_regression
                or latest.error_count < baseline.error_count
            )
        case "retry_loop":
            improved = (
                baseline.retry_count - latest.retry_count
                >= thresholds.retry_count_regression
                or latest.retry_count < baseline.retry_count
            )
        case "timeout":
            improved = latest.timeout_count < baseline.timeout_count
        case "cancellation":
            improved = latest.cancellation_count < baseline.cancellation_count
        case "redaction_pressure":
            improved = (
                baseline.redaction_drop_count - latest.redaction_drop_count
                >= thresholds.redaction_drop_regression
                or latest.redaction_drop_count < baseline.redaction_drop_count
            )
        case "excessive_attributes":
            improved = latest.affected_event_count < baseline.affected_event_count
        case "missing_trace_context":
            baseline_missing = (
                baseline.missing_trace_id_count + baseline.missing_parent_span_id_count
            )
            latest_missing = (
                latest.missing_trace_id_count + latest.missing_parent_span_id_count
            )
            improved = latest_missing < baseline_missing
        case "unknown_tool_category":
            improved = (
                latest.unknown_tool_category_count
                < baseline.unknown_tool_category_count
            )
        case _:
            improved = latest.affected_event_count < baseline.affected_event_count
    return improved


def classify_trend(
    *,
    signal_kind: str,
    baseline_metrics: MetricSnapshot,
    latest_metrics: MetricSnapshot,
    candidate_presence_count: int,
    run_count: int,
    latest_candidate: dict[str, Any] | None,
    thresholds: TrendThresholds,
) -> str:
    trend_class = "one_off_noise"
    if run_count < MIN_COMPARISON_RUNS:
        trend_class = "insufficient_sample"
    elif (
        latest_candidate is not None
        and baseline_metrics.candidate_count == 0
        and _severity_for_candidate(latest_candidate) in {"high", "critical"}
    ):
        trend_class = "new_regression"
    elif candidate_presence_count == SINGLE_OCCURRENCE_COUNT:
        trend_class = "one_off_noise"
    elif _materially_improved(
        signal_kind, baseline_metrics, latest_metrics, thresholds
    ):
        trend_class = "improved"
    elif (
        latest_candidate is None
        and candidate_presence_count >= MEDIUM_CONFIDENCE_OCCURRENCE_COUNT
    ):
        trend_class = "improved"
    elif (
        latest_candidate is not None
        and candidate_presence_count >= MEDIUM_CONFIDENCE_OCCURRENCE_COUNT
    ):
        trend_class = "persistent_pain"
    return trend_class


def _metrics_from_candidate(candidate: dict[str, Any] | None) -> MetricSnapshot:
    return MetricSnapshot.from_candidate(candidate)


def _delta_record(
    *,
    trend_run_id: str,
    runs: list[LoadedAggregateRun],
    candidate_series: list[dict[str, Any] | None],
    signal_kind: str,
    affected_tool_category: str,
    candidate_presence_count: int,
    thresholds: TrendThresholds,
) -> dict[str, Any] | None:
    if candidate_presence_count == 0:
        return None
    baseline_candidate = candidate_series[0] if candidate_series else None
    latest_candidate = candidate_series[-1] if candidate_series else None
    first_present_index = _first_present_index(candidate_series)
    last_present_index = _last_present_index(candidate_series)
    if first_present_index is None or last_present_index is None:
        return None
    if baseline_candidate is None and latest_candidate is None:
        baseline_candidate = candidate_series[first_present_index]
        latest_candidate = None
    baseline_metrics = _metrics_from_candidate(baseline_candidate)
    latest_metrics = _metrics_from_candidate(latest_candidate)
    trend_class = classify_trend(
        signal_kind=signal_kind,
        baseline_metrics=baseline_metrics,
        latest_metrics=latest_metrics,
        candidate_presence_count=candidate_presence_count,
        run_count=len(runs),
        latest_candidate=latest_candidate,
        thresholds=thresholds,
    )
    if trend_class == "insufficient_sample" and len(runs) >= MIN_COMPARISON_RUNS:
        return None
    first_seen_run_id = runs[first_present_index].run_id
    latest_seen_run_id = runs[last_present_index].run_id
    evidence_run_ids = sorted({
        run.run_id
        for run in runs
        if run.candidate_map.get((affected_tool_category, signal_kind)) is not None
    })
    return {
        "delta_id": _candidate_id(
            trend_run_id=trend_run_id,
            affected_tool_category=affected_tool_category,
            signal_kind=signal_kind,
            trend_class=trend_class,
            first_seen_run_id=first_seen_run_id,
            latest_seen_run_id=latest_seen_run_id,
        ),
        "affected_tool_category": affected_tool_category,
        "signal_kind": signal_kind,
        "trend_class": trend_class,
        "severity": _severity_for_trend(
            trend_class,
            baseline=baseline_metrics,
            latest=latest_metrics,
            latest_candidate=latest_candidate,
        ),
        "first_seen_run_id": first_seen_run_id,
        "latest_seen_run_id": latest_seen_run_id,
        "evidence_run_ids": evidence_run_ids,
        "baseline_metrics": baseline_metrics.to_dict(),
        "latest_metrics": latest_metrics.to_dict(),
        "delta_metrics": latest_metrics.delta(baseline_metrics),
        "confidence": _confidence_for_trend(
            trend_class=trend_class,
            candidate_presence_count=candidate_presence_count,
            run_count=len(runs),
        ),
        "recommended_hardening_action": _recommended_action(
            signal_kind=signal_kind,
            trend_class=trend_class,
            category=affected_tool_category,
        ),
        "content_light_evidence_hashes": _baseline_or_latest_hashes(runs),
    }


def _recommended_action(*, signal_kind: str, trend_class: str, category: str) -> str:
    if trend_class == "persistent_pain":
        return f"Prioritize hardening for persistent {signal_kind} pain in {category}"
    if trend_class == "new_regression":
        return f"Triage the new {signal_kind} regression in {category}"
    if trend_class == "improved":
        return f"Keep the {signal_kind} fix in {category} and monitor for regression"
    if trend_class == "one_off_noise":
        return f"Monitor the isolated {signal_kind} noise in {category}"
    return (
        f"Collect a larger sample before acting on {signal_kind} behavior in {category}"
    )


def compute_hardening_deltas(
    *, trend_run_id: str, runs: list[LoadedAggregateRun], thresholds: TrendThresholds
) -> dict[str, Any]:
    ordered_runs = _ordered_runs(runs)
    series = _candidate_presence_series(ordered_runs)
    deltas: list[dict[str, Any]] = []

    for key, candidate_series in series.items():
        affected_tool_category, signal_kind = key
        candidate_presence_count = sum(
            1 for candidate in candidate_series if candidate is not None
        )
        if candidate_presence_count == 0:
            continue
        delta = _delta_record(
            trend_run_id=trend_run_id,
            runs=ordered_runs,
            candidate_series=candidate_series,
            signal_kind=signal_kind,
            affected_tool_category=affected_tool_category,
            candidate_presence_count=candidate_presence_count,
            thresholds=thresholds,
        )
        if delta is not None:
            deltas.append(delta)

    deltas = sorted(
        deltas,
        key=lambda delta: (
            TREND_CLASS_ORDER[delta["trend_class"]],
            -SEVERITY_ORDER[delta["severity"]],
            delta["affected_tool_category"],
            delta["signal_kind"],
            delta["delta_id"],
        ),
    )
    return {
        "schema_version": HARDENING_DELTA_SCHEMA,
        "trend_run_id": trend_run_id,
        "generated_at": _now(),
        "deltas": deltas,
    }


def _ordered_runs(runs: list[LoadedAggregateRun]) -> list[LoadedAggregateRun]:
    return sorted(runs, key=lambda run: (run.generated_at, run.run_id))


def _comparison_window(runs: list[LoadedAggregateRun]) -> dict[str, Any]:
    ordered_runs = _ordered_runs(runs)
    run_ids = [run.run_id for run in ordered_runs]
    return {
        "run_ids": run_ids,
        "first_run_id": run_ids[0] if run_ids else "",
        "latest_run_id": run_ids[-1] if run_ids else "",
        "run_count": len(run_ids),
    }


def _trend_label(deltas: list[dict[str, Any]], signal_kind: str) -> str:
    signal_deltas = [delta for delta in deltas if delta["signal_kind"] == signal_kind]
    if not signal_deltas:
        return "insufficient_sample"
    if any(
        delta["trend_class"] in {"persistent_pain", "new_regression"}
        for delta in signal_deltas
    ):
        return "worsening"
    if all(delta["trend_class"] == "improved" for delta in signal_deltas):
        return "improving"
    if any(delta["trend_class"] == "insufficient_sample" for delta in signal_deltas):
        return "insufficient_sample"
    return "stable"


def _priority_categories(deltas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        deltas,
        key=lambda delta: (
            -SEVERITY_ORDER[delta["severity"]],
            -delta["latest_metrics"]["affected_event_count"],
            TREND_CLASS_ORDER[delta["trend_class"]],
            delta["affected_tool_category"],
            delta["signal_kind"],
        ),
    )
    return [
        {
            "affected_tool_category": delta["affected_tool_category"],
            "signal_kind": delta["signal_kind"],
            "trend_class": delta["trend_class"],
            "severity": delta["severity"],
            "affected_event_count": delta["latest_metrics"]["affected_event_count"],
            "confidence": delta["confidence"],
            "evidence_run_ids": delta["evidence_run_ids"],
            "recommended_hardening_action": delta["recommended_hardening_action"],
        }
        for delta in ranked[:5]
    ]


def _build_trend_summary(deltas: list[dict[str, Any]]) -> dict[str, Any]:
    trend_counts = Counter(delta["trend_class"] for delta in deltas)
    return {
        "persistent_pain_count": trend_counts.get("persistent_pain", 0),
        "new_regression_count": trend_counts.get("new_regression", 0),
        "improved_category_count": trend_counts.get("improved", 0),
        "one_off_noise_count": trend_counts.get("one_off_noise", 0),
        "insufficient_sample_count": trend_counts.get("insufficient_sample", 0),
        "highest_priority_categories": _priority_categories(deltas),
        "redaction_pressure_trend": _trend_label(deltas, "redaction_pressure"),
        "trace_context_quality_trend": _trend_label(deltas, "missing_trace_context"),
        "candidate_count": len(deltas),
    }


def validate_trend_outputs(
    *, trend_report: dict[str, Any], hardening_deltas: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    trend_report_errors = _validate_against_schema(trend_report, TREND_REPORT_SCHEMA)
    hardening_delta_errors = _validate_against_schema(
        hardening_deltas, HARDENING_DELTA_SCHEMA
    )
    return {
        "trend_report": {
            "valid": not trend_report_errors,
            "errors": trend_report_errors,
        },
        "hardening_deltas": {
            "valid": not hardening_delta_errors,
            "errors": hardening_delta_errors,
        },
    }


def _trend_verdict(
    *,
    runs: list[LoadedAggregateRun],
    min_runs: int,
    validation_results: dict[str, dict[str, Any]],
) -> str:
    complete_run_count = len([run for run in runs if run.complete])
    if any(not result["valid"] for result in validation_results.values()):
        return "fail"
    if complete_run_count < min_runs or complete_run_count < MIN_COMPARISON_RUNS:
        return "hold"
    if any(run.issues for run in runs):
        return "hold"
    if any(run.warning_count or run.error_count for run in runs):
        return "hold"
    return "pass"


def _trend_report_core(inputs: TrendReportCoreInput) -> dict[str, Any]:
    summary = _build_trend_summary(inputs.deltas)
    return {
        "schema_version": TREND_REPORT_SCHEMA,
        "trend_run_id": inputs.trend_run_id,
        "generated_at": inputs.generated_at,
        "input_aggregate_run_ids": inputs.comparison_window["run_ids"],
        "input_aggregate_count": len(inputs.runs),
        "input_manifest_hashes": [
            {"aggregate_run_id": run.run_id, "sha256": run.run_manifest_sha256}
            for run in inputs.runs
            if run.run_manifest_sha256 is not None
        ],
        "input_shortlist_hashes": [
            {"aggregate_run_id": run.run_id, "sha256": run.hardening_shortlist_sha256}
            for run in inputs.runs
            if run.hardening_shortlist_sha256 is not None
        ],
        "comparison_window": inputs.comparison_window,
        "trend_verdict": inputs.verdict,
        "trend_summary": summary,
        "deltas_path": _relativize(inputs.deltas_path, inputs.path_anchor),
        "warnings": inputs.warnings,
        "errors": inputs.errors,
        "local_only": True,
        "coordination_ledger_mutated": False,
        "release_gate_mutated": False,
    }


def _trend_artifact_paths(output_root: Path, trend_run_id: str) -> dict[str, Path]:
    trend_dir = output_root / trend_run_id
    return {
        "trend_dir": trend_dir,
        "trend_report_path": trend_dir / "otel_trend_report.v1.json",
        "hardening_deltas_path": trend_dir / "otel_hardening_deltas.v1.json",
    }


def write_trend_report(
    *,
    output_root: Path,
    trend_run_id: str,
    trend_report: dict[str, Any],
    hardening_deltas: dict[str, Any],
) -> dict[str, Any]:
    paths = _trend_artifact_paths(output_root, trend_run_id)
    _write_json(paths["trend_report_path"], trend_report)
    _write_json(paths["hardening_deltas_path"], hardening_deltas)
    return {
        "trend_report_path": str(paths["trend_report_path"]),
        "hardening_deltas_path": str(paths["hardening_deltas_path"]),
        "trend_report_sha256": _file_sha256(paths["trend_report_path"]),
        "hardening_deltas_sha256": _file_sha256(paths["hardening_deltas_path"]),
    }


def compare_otel_aggregate_runs(
    *,
    input_root: Path = DEFAULT_INPUT_ROOT,
    trend_run_id: str,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    min_runs: int = 2,
    latency_p95_regression_ms: float = 1000.0,
    error_count_regression: int = 2,
    retry_count_regression: int = 2,
    redaction_drop_regression: int = 1,
    fail_on_schema_error: bool = False,
) -> dict[str, Any]:
    run_dirs = _discover_run_dirs(input_root)
    loaded_runs = [load_aggregate_run(run_dir) for run_dir in run_dirs]
    comparison_window = _comparison_window(loaded_runs)
    thresholds = TrendThresholds(
        latency_p95_regression_ms=latency_p95_regression_ms,
        error_count_regression=error_count_regression,
        retry_count_regression=retry_count_regression,
        redaction_drop_regression=redaction_drop_regression,
    )
    generated_at = _now()
    hardening_deltas = compute_hardening_deltas(
        trend_run_id=trend_run_id, runs=loaded_runs, thresholds=thresholds
    )
    trend_paths = _trend_artifact_paths(output_root, trend_run_id)
    validation_results = validate_trend_outputs(
        trend_report=_trend_report_core(
            TrendReportCoreInput(
                trend_run_id=trend_run_id,
                generated_at=generated_at,
                deltas_path=trend_paths["hardening_deltas_path"],
                comparison_window=comparison_window,
                runs=loaded_runs,
                deltas=hardening_deltas["deltas"],
                warnings=[],
                errors=[],
                verdict="pass",
                path_anchor=output_root.parent,
            )
        ),
        hardening_deltas=hardening_deltas,
    )
    warnings = []
    errors = []
    for run in loaded_runs:
        if run.issues:
            warnings.append(f"{run.run_id}: {'; '.join(run.issues)}")
    if len([run for run in loaded_runs if run.complete]) < min_runs:
        warnings.append(
            f"insufficient complete aggregate runs for trend comparison: {len([run for run in loaded_runs if run.complete])} < {min_runs}"
        )
    if any(run.warning_count or run.error_count for run in loaded_runs):
        warnings.append("source aggregate reports contained warnings or errors")
    if any(not result["valid"] for result in validation_results.values()):
        errors.extend(
            error
            for result in validation_results.values()
            for error in result["errors"]
        )
    verdict = _trend_verdict(
        runs=loaded_runs, min_runs=min_runs, validation_results=validation_results
    )
    trend_report = _trend_report_core(
        TrendReportCoreInput(
            trend_run_id=trend_run_id,
            generated_at=generated_at,
            deltas_path=trend_paths["hardening_deltas_path"],
            comparison_window=comparison_window,
            runs=loaded_runs,
            deltas=hardening_deltas["deltas"],
            warnings=warnings,
            errors=errors,
            verdict=verdict,
            path_anchor=output_root.parent,
        )
    )
    if fail_on_schema_error and any(
        not result["valid"] for result in validation_results.values()
    ):
        raise ValueError("Trend outputs failed schema validation")
    write_result = write_trend_report(
        output_root=output_root,
        trend_run_id=trend_run_id,
        trend_report=trend_report,
        hardening_deltas=hardening_deltas,
    )
    report = dict(trend_report)
    report["trend_report_path_absolute"] = write_result["trend_report_path"]
    report["hardening_deltas_path_absolute"] = write_result["hardening_deltas_path"]
    report["trend_report_sha256"] = write_result["trend_report_sha256"]
    report["hardening_deltas_sha256"] = write_result["hardening_deltas_sha256"]
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Rig OTel aggregate runs into a local trend report"
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--min-runs", type=int, default=2)
    parser.add_argument("--latency-p95-regression-ms", type=float, default=1000.0)
    parser.add_argument("--error-count-regression", type=int, default=2)
    parser.add_argument("--retry-count-regression", type=int, default=2)
    parser.add_argument("--redaction-drop-regression", type=int, default=1)
    parser.add_argument("--fail-on-schema-error", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        report = compare_otel_aggregate_runs(
            input_root=args.input_root,
            trend_run_id=args.run_id,
            output_root=args.output_root,
            min_runs=args.min_runs,
            latency_p95_regression_ms=args.latency_p95_regression_ms,
            error_count_regression=args.error_count_regression,
            retry_count_regression=args.retry_count_regression,
            redaction_drop_regression=args.redaction_drop_regression,
            fail_on_schema_error=args.fail_on_schema_error,
        )
        match report["trend_verdict"]:
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
