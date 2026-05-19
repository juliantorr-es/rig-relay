from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
DEFAULT_INPUT_ROOT = REPO_ROOT / ".build" / "rig-relay" / "otel" / "trends"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / ".build" / "rig-relay" / "tool-hardening"

PROPOSAL_SCHEMA = "rig.tool_hardening.proposal.v1"
PROPOSAL_ITEM_SCHEMA = "rig.tool_hardening.proposal_item.v1"
TREND_REPORT_SCHEMA = "rig.otel.trend_report.v1"
HARDENING_DELTA_SCHEMA = "rig.otel.hardening_delta.v1"

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
TREND_ORDER = {
    "persistent_pain": 0,
    "new_regression": 1,
    "improved": 2,
    "one_off_noise": 3,
    "insufficient_sample": 4,
}
LANE_TITLES = {
    "tool_runtime_hardening": "Tool runtime hardening",
    "trace_context_hardening": "Trace context hardening",
    "redaction_policy_hardening": "Redaction policy hardening",
    "retry_policy_hardening": "Retry policy hardening",
    "timeout_policy_hardening": "Timeout policy hardening",
    "cancellation_policy_hardening": "Cancellation policy hardening",
    "schema_contract_hardening": "Schema contract hardening",
    "observability_quality_hardening": "Observability quality hardening",
    "unknown_tool_classification": "Unknown tool classification",
    "tool_invocation_boundary": "Tool invocation boundary hardening",
    "defer_insufficient_sample": "Defer until sample grows",
}
NON_GOALS = [
    "No runtime auto-mutation",
    "No coordination ledger mutation",
    "No release gate mutation",
]


@dataclass(slots=True)
class LoadedTrendArtifacts:
    trend_dir: Path
    trend_report_path: Path
    hardening_deltas_path: Path
    trend_report: dict[str, Any] | None
    hardening_deltas: dict[str, Any] | None
    trend_report_sha256: str | None
    hardening_deltas_sha256: str | None
    issues: list[str]

    @property
    def complete(self) -> bool:
        return bool(
            self.trend_report_sha256
            and self.hardening_deltas_sha256
            and not self.issues
        )


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


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


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_for_hash(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key in {
                "generated_at",
                "proposal_item_id",
                "source_trend_report_sha256",
                "source_hardening_deltas_sha256",
            }:
                normalized[key] = "<normalized>"
            elif key in {
                "content_light_evidence_hashes",
                "source_delta_id",
                "input_manifest_hashes",
                "input_shortlist_hashes",
            }:
                normalized[key] = _normalize_for_hash(item)
            else:
                normalized[key] = _normalize_for_hash(item)
        return normalized
    if isinstance(value, list):
        return [_normalize_for_hash(item) for item in value]
    return value


def _stable_json_sha256(value: Any) -> str:
    return _sha256_json(_normalize_for_hash(value))


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _relativize(path: Path, anchor: Path) -> str:
    try:
        return str(path.resolve().relative_to(anchor.resolve()))
    except ValueError:
        return path.name


def _load_json_artifact(
    path: Path, *, schema_name: str, missing_issue: str
) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    if not path.is_file():
        return None, None, [missing_issue]
    payload = _read_json(path)
    errors = _validate_against_schema(payload, schema_name)
    if errors:
        raise ValueError("; ".join(errors))
    return payload, _stable_json_sha256(payload), []


def load_trend_artifacts(trend_dir: Path) -> LoadedTrendArtifacts:
    report_path = trend_dir / "otel_trend_report.v1.json"
    deltas_path = trend_dir / "otel_hardening_deltas.v1.json"
    report, report_sha256, report_issues = _load_json_artifact(
        report_path,
        schema_name=TREND_REPORT_SCHEMA,
        missing_issue="missing_trend_report",
    )
    deltas, deltas_sha256, delta_issues = _load_json_artifact(
        deltas_path,
        schema_name=HARDENING_DELTA_SCHEMA,
        missing_issue="missing_hardening_deltas",
    )
    issues = [*report_issues, *delta_issues]
    if issues:
        raise FileNotFoundError("; ".join(issues))
    return LoadedTrendArtifacts(
        trend_dir=trend_dir,
        trend_report_path=report_path,
        hardening_deltas_path=deltas_path,
        trend_report=report,
        hardening_deltas=deltas,
        trend_report_sha256=report_sha256,
        hardening_deltas_sha256=deltas_sha256,
        issues=[],
    )


def _actionable_delta(delta: dict[str, Any]) -> bool:
    return str(delta.get("trend_class")) in {"persistent_pain", "new_regression"}


def _recommended_lane_for_delta(delta: dict[str, Any]) -> str:
    signal_kind = str(delta.get("signal_kind", "unknown"))
    category = str(delta.get("affected_tool_category", "unknown"))
    evidence_run_ids = delta.get("evidence_run_ids", [])
    lane_map = {
        "latency": "tool_runtime_hardening",
        "error_rate": "tool_runtime_hardening",
        "missing_trace_context": "trace_context_hardening",
        "redaction_pressure": "redaction_policy_hardening",
        "retry_loop": "retry_policy_hardening",
        "timeout": "timeout_policy_hardening",
        "cancellation": "cancellation_policy_hardening",
        "unknown_tool_category": "unknown_tool_classification",
        "excessive_attributes": "observability_quality_hardening",
        "malformed_input": "schema_contract_hardening",
    }
    lane = lane_map.get(signal_kind, "observability_quality_hardening")
    if signal_kind == "malformed_input":
        if category != "unknown" and len(evidence_run_ids) > 1:
            lane = "tool_invocation_boundary"
    return lane


def _affected_event_count(delta: dict[str, Any]) -> int:
    latest_metrics = delta.get("latest_metrics", {})
    if isinstance(latest_metrics, dict):
        return int(latest_metrics.get("affected_event_count", 0))
    return 0


def classify_recommended_lane(delta: dict[str, Any]) -> tuple[str, str, str]:
    lane = _recommended_lane_for_delta(delta)
    if lane == "tool_runtime_hardening":
        scope = "runtime_policy"
        payoff = (
            "reduced_latency"
            if delta.get("signal_kind") == "latency"
            else "fewer_failed_tool_calls"
        )
    elif lane == "trace_context_hardening":
        scope = "adapter_boundary"
        payoff = "improved_traceability"
    elif lane == "redaction_policy_hardening":
        scope = "adapter_boundary"
        payoff = "reduced_redaction_pressure"
    elif lane == "retry_policy_hardening":
        scope = "runtime_policy"
        payoff = "reduced_retries"
    elif lane == "timeout_policy_hardening":
        scope = "runtime_policy"
        payoff = "fewer_failed_tool_calls"
    elif lane == "cancellation_policy_hardening":
        scope = "runtime_policy"
        payoff = "fewer_failed_tool_calls"
    elif lane == "schema_contract_hardening":
        scope = "schema_contract"
        payoff = "reduced_human_review_load"
    elif lane == "observability_quality_hardening":
        scope = "adapter_boundary"
        payoff = "improved_traceability"
    elif lane == "unknown_tool_classification":
        scope = "schema_contract"
        payoff = "improved_tool_classification"
    elif lane == "tool_invocation_boundary":
        scope = "tool_invocation_boundary"
        payoff = "fewer_failed_tool_calls"
    else:
        scope = "unknown"
        payoff = "unknown"
    return lane, scope, payoff


def compute_priority_score(delta: dict[str, Any]) -> int:
    severity_weight = {"low": 100, "medium": 200, "high": 300, "critical": 400}
    trend_weight = {
        "persistent_pain": 200,
        "new_regression": 180,
        "improved": 0,
        "one_off_noise": 10,
        "insufficient_sample": 0,
    }
    confidence_weight = {"low": 0, "medium": 25, "high": 50}
    signal_weight = {
        "latency": 40,
        "error_rate": 35,
        "retry_loop": 35,
        "cancellation": 30,
        "timeout": 30,
        "missing_trace_context": 50,
        "redaction_pressure": 55,
        "malformed_input": 60,
        "excessive_attributes": 20,
        "unknown_tool_category": 45,
    }
    return (
        severity_weight.get(str(delta.get("severity", "low")), 0)
        + trend_weight.get(str(delta.get("trend_class", "one_off_noise")), 0)
        + confidence_weight.get(str(delta.get("confidence", "low")), 0)
        + signal_weight.get(str(delta.get("signal_kind", "unknown")), 0)
        + min(_affected_event_count(delta), 50)
    )


def _proposal_item_id(proposal_run_id: str, delta: dict[str, Any]) -> str:
    return _sha256_json({
        "proposal_run_id": proposal_run_id,
        "source_delta_id": delta["delta_id"],
        "recommended_lane": delta["recommended_lane"],
        "priority_score": delta["priority_score"],
    })


def _risk_if_ignored(delta: dict[str, Any]) -> str:
    signal_kind = str(delta.get("signal_kind", "unknown"))
    category = str(delta.get("affected_tool_category", "unknown"))
    risk_map = {
        "latency": f"Latency in {category} will continue to slow tool throughput",
        "error_rate": f"Errors in {category} will keep surfacing failed tool calls",
        "retry_loop": f"Retry loops in {category} may amplify load and latency",
        "timeout": f"Timeouts in {category} will keep truncating tool execution",
        "cancellation": f"Cancellation handling in {category} may remain ambiguous",
        "missing_trace_context": (
            "Trace correlation will remain incomplete for follow-up analysis"
        ),
        "redaction_pressure": (
            "Sensitive telemetry pressure may remain too high for content-light use"
        ),
        "malformed_input": (
            "Malformed inputs may keep causing proposal churn and ingest failure"
        ),
        "excessive_attributes": "Noisy attributes will keep raising observability cost",
        "unknown_tool_category": (
            "Unknown tool categories will keep weakening tool classification"
        ),
    }
    return risk_map.get(signal_kind, "The hardening pattern may continue unchecked")


def _build_non_goals() -> list[str]:
    return list(NON_GOALS)


def _build_proposal_item(proposal_run_id: str, delta: dict[str, Any]) -> dict[str, Any]:
    lane, scope, payoff = classify_recommended_lane(delta)
    priority_score = compute_priority_score(delta)
    return {
        "schema_version": PROPOSAL_ITEM_SCHEMA,
        "proposal_item_id": _proposal_item_id(
            proposal_run_id,
            {**delta, "recommended_lane": lane, "priority_score": priority_score},
        ),
        "proposal_run_id": proposal_run_id,
        "source_delta_id": delta["delta_id"],
        "affected_tool_category": delta["affected_tool_category"],
        "signal_kind": delta["signal_kind"],
        "trend_class": delta["trend_class"],
        "severity": delta["severity"],
        "confidence": delta["confidence"],
        "priority_score": priority_score,
        "affected_event_count": _affected_event_count(delta),
        "evidence_run_ids": delta["evidence_run_ids"],
        "content_light_evidence_hashes": delta["content_light_evidence_hashes"],
        "recommended_hardening_action": delta["recommended_hardening_action"],
        "recommended_lane": lane,
        "implementation_scope": scope,
        "expected_payoff": payoff,
        "risk_if_ignored": _risk_if_ignored(delta),
        "non_goals": _build_non_goals(),
        "generated_at": _now(),
        "local_only": True,
        "content_light": True,
        "redaction_status": "content_light",
    }


def rank_hardening_deltas(
    *, proposal_run_id: str, deltas: list[dict[str, Any]], min_priority_score: int
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for delta in deltas:
        if not _actionable_delta(delta):
            continue
        item = _build_proposal_item(proposal_run_id, delta)
        if item["priority_score"] < min_priority_score:
            continue
        items.append(item)
    return sorted(
        items,
        key=lambda item: (
            -int(item["priority_score"]),
            -SEVERITY_ORDER[item["severity"]],
            TREND_ORDER[item["trend_class"]],
            -int(item["affected_event_count"]),
            item["affected_tool_category"],
            item["signal_kind"],
            item["proposal_item_id"],
        ),
    )


def _severity_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(item["severity"] for item in items)
    return {key: counts.get(key, 0) for key in ("critical", "high", "medium", "low")}


def _confidence_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(item["confidence"] for item in items)
    return {key: counts.get(key, 0) for key in ("high", "medium", "low")}


def _recommended_next_lanes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lane_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        lane_items[item["recommended_lane"]].append(item)
    lanes = []
    for lane_id, lane_group in lane_items.items():
        sorted_group = sorted(
            lane_group,
            key=lambda item: (-int(item["priority_score"]), item["proposal_item_id"]),
        )
        lanes.append({
            "lane_id": lane_id,
            "lane_title": LANE_TITLES.get(lane_id, lane_id),
            "priority": int(sorted_group[0]["priority_score"]),
            "reason": sorted_group[0]["recommended_hardening_action"],
            "related_item_ids": [item["proposal_item_id"] for item in sorted_group],
        })
    return sorted(lanes, key=lambda lane: (-lane["priority"], lane["lane_id"]))


def validate_tool_hardening_outputs(
    *, proposal: dict[str, Any], items: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    proposal_errors = _validate_against_schema(proposal, PROPOSAL_SCHEMA)
    item_errors: list[str] = []
    for item in items:
        item_errors.extend(_validate_against_schema(item, PROPOSAL_ITEM_SCHEMA))
    return {
        "proposal": {"valid": not proposal_errors, "errors": proposal_errors},
        "items": {"valid": not item_errors, "errors": item_errors},
    }


def _proposal_core(
    *,
    proposal_run_id: str,
    trend: LoadedTrendArtifacts,
    items: list[dict[str, Any]],
    warnings: list[str],
    errors: list[str],
    path_anchor: Path,
    verdict: str,
) -> dict[str, Any]:
    trend_report = trend.trend_report or {}
    source_trend_report_path = _relativize(trend.trend_report_path, path_anchor)
    source_hardening_deltas_path = _relativize(trend.hardening_deltas_path, path_anchor)
    return {
        "schema_version": PROPOSAL_SCHEMA,
        "proposal_run_id": proposal_run_id,
        "generated_at": _now(),
        "source_trend_run_id": trend_report["trend_run_id"],
        "source_trend_report_path": source_trend_report_path,
        "source_hardening_deltas_path": source_hardening_deltas_path,
        "source_trend_report_sha256": trend.trend_report_sha256,
        "source_hardening_deltas_sha256": trend.hardening_deltas_sha256,
        "proposal_verdict": verdict,
        "item_count": len(items),
        "ranked_item_ids": [item["proposal_item_id"] for item in items],
        "severity_summary": _severity_summary(items),
        "confidence_summary": _confidence_summary(items),
        "recommended_next_lanes": _recommended_next_lanes(items),
        "warnings": warnings,
        "errors": errors,
        "local_only": True,
        "content_light": True,
        "coordination_ledger_mutated": False,
        "release_gate_mutated": False,
        "runtime_mutated": False,
        "redaction_status": "content_light",
    }


def _proposal_paths(output_root: Path, proposal_run_id: str) -> dict[str, Path]:
    proposal_dir = output_root / proposal_run_id
    return {
        "proposal_dir": proposal_dir,
        "proposal_path": proposal_dir / "tool_hardening_proposal.v1.json",
        "items_path": proposal_dir / "tool_hardening_items.v1.jsonl",
    }


def write_tool_hardening_proposal(
    *,
    output_root: Path,
    proposal_run_id: str,
    proposal: dict[str, Any],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    paths = _proposal_paths(output_root, proposal_run_id)
    _write_json(paths["proposal_path"], proposal)
    _write_jsonl(paths["items_path"], items)
    return {
        "proposal_path": str(paths["proposal_path"]),
        "items_path": str(paths["items_path"]),
        "proposal_path_absolute": str(paths["proposal_path"].resolve()),
        "items_path_absolute": str(paths["items_path"].resolve()),
        "proposal_sha256": _file_sha256(paths["proposal_path"]),
        "items_sha256": _file_sha256(paths["items_path"]),
    }


def build_tool_hardening_proposal(
    *,
    trend_dir: Path = DEFAULT_INPUT_ROOT,
    proposal_run_id: str,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    min_priority_score: int = 0,
    fail_on_schema_error: bool = False,
) -> dict[str, Any]:
    trend = load_trend_artifacts(trend_dir)
    if trend.trend_report is None or trend.hardening_deltas is None:
        raise FileNotFoundError("Trend artifacts are incomplete")

    validation_results = validate_tool_hardening_outputs(
        proposal=_proposal_core(
            proposal_run_id=proposal_run_id,
            trend=trend,
            items=[],
            warnings=[],
            errors=[],
            path_anchor=output_root.parent,
            verdict="hold",
        ),
        items=[],
    )
    if fail_on_schema_error and any(
        not result["valid"] for result in validation_results.values()
    ):
        raise ValueError("Trend inputs failed schema validation")

    deltas = trend.hardening_deltas.get("deltas", [])
    if not isinstance(deltas, list):
        raise ValueError("Trend hardening deltas are malformed")
    ranked_items = rank_hardening_deltas(
        proposal_run_id=proposal_run_id,
        deltas=[delta for delta in deltas if isinstance(delta, dict)],
        min_priority_score=min_priority_score,
    )
    warnings = list(trend.trend_report.get("warnings", []))
    errors = list(trend.trend_report.get("errors", []))
    verdict = "pass" if ranked_items else "hold"
    proposal = _proposal_core(
        proposal_run_id=proposal_run_id,
        trend=trend,
        items=ranked_items,
        warnings=warnings,
        errors=errors,
        path_anchor=output_root.parent,
        verdict=verdict,
    )
    validation_results = validate_tool_hardening_outputs(
        proposal=proposal, items=ranked_items
    )
    if any(not result["valid"] for result in validation_results.values()):
        raise ValueError("Tool hardening proposal failed schema validation")
    write_result = write_tool_hardening_proposal(
        output_root=output_root,
        proposal_run_id=proposal_run_id,
        proposal=proposal,
        items=ranked_items,
    )
    result = dict(proposal)
    result["proposal_path_absolute"] = write_result["proposal_path_absolute"]
    result["items_path_absolute"] = write_result["items_path_absolute"]
    result["proposal_sha256"] = write_result["proposal_sha256"]
    result["items_sha256"] = write_result["items_sha256"]
    return result


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Rig tool hardening proposals from OTel trend deltas"
    )
    parser.add_argument("--trend-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--min-priority-score", type=int, default=0)
    parser.add_argument("--fail-on-schema-error", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        result = build_tool_hardening_proposal(
            trend_dir=args.trend_dir,
            proposal_run_id=args.run_id,
            output_root=args.output_root,
            min_priority_score=args.min_priority_score,
            fail_on_schema_error=args.fail_on_schema_error,
        )
        match result["proposal_verdict"]:
            case "pass":
                return 0
            case "hold":
                return 2
            case "fail":
                return 1
        return 1
    except FileNotFoundError as exc:
        print(str(exc))
        return 1
    except (NotADirectoryError, ValueError, jsonschema.ValidationError) as exc:
        print(str(exc))
        return 1
