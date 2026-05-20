from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import jsonschema

from rig_relay.core.paths._vibe_home import SESSIONS_ROOT
from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.deepseek_routing._policy import (
    validate_deepseek_routing_decision,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
DEFAULT_POLICY_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "integrations"
    / "deepseek_router_promotion_policy.v1.json"
)
DEFAULT_USAGE_SUMMARY_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "integrations"
    / "deepseek_opencode_usage_summary.v1.json"
)
DEFAULT_USAGE_REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "integrations"
    / "deepseek_opencode_usage_report.v1.json"
)

POLICY_SCHEMA_ID = "rig.deepseek.router_promotion_policy.v1"
REPORT_SCHEMA_ID = "rig.deepseek.router_promotion_gate.v1"
ROUTING_SCHEMA_ID = "rig.deepseek.routing_decision.v1"
ENVELOPE_SCHEMA_ID = "rig.relay.artifact.envelope.v1"
TASK_LINK_SCHEMA_ID = "rig.relay.artifact.task_session_link.v1"
USAGE_SUMMARY_SCHEMA_ID = "rig.deepseek_opencode_usage_summary.v1"
USAGE_REPORT_SCHEMA_ID = "rig.deepseek_opencode_usage_report.v1"

LANE_IDS = (
    "cheap_inspect",
    "normal_repo_work",
    "hard_convergence",
    "json_artifact",
    "strict_tool_beta",
)

MIN_TIMESTAMP_PAIR = 2
TASK_RECEIPT_GLOB = "*_task_session_link_*.json"

_LANE_RANKS = {
    "cheap_inspect": 0,
    "normal_repo_work": 1,
    "hard_convergence": 2,
    "json_artifact": 3,
    "strict_tool_beta": 4,
}

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


@dataclass(frozen=True, slots=True)
class LoadedArtifact:
    path: Path
    sha256: str
    kind: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TaskOutcomeRecord:
    path: Path
    task_id: str
    session_id: str
    status: str
    lane_id: str
    lane_rank: int
    started_at: datetime | None
    completed_at: datetime | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PromotionCorpus:
    route_receipts: list[LoadedArtifact]
    task_receipts: list[LoadedArtifact]
    usage_artifact: LoadedArtifact | None
    all_artifacts: list[LoadedArtifact]


@dataclass(frozen=True, slots=True)
class RouteSummary:
    decisions_by_lane: dict[str, int]
    override_count: int
    dynamic_prefix_warning_count: int
    reason_codes: tuple[str, ...]
    timestamps: tuple[datetime, ...]


@dataclass(frozen=True, slots=True)
class TaskSummary:
    records: list[TaskOutcomeRecord]
    completed_tasks: int
    failed_task_count: int
    lane_attributed_failure_count: int
    manual_rerun_harder_lane_count: int
    distinct_sessions: int | None
    reason_codes: tuple[str, ...]
    timestamps: tuple[datetime, ...]


@dataclass(frozen=True, slots=True)
class UsageSummary:
    cache_hit_ratio: float | None
    discounted_cost_estimate: float | None
    full_cost_estimate: float | None
    pro_max_share: float | None
    reason_codes: tuple[str, ...]
    timestamps: tuple[datetime, ...]


@dataclass(frozen=True, slots=True)
class SafetySummary:
    raw_secret_violation_count: int
    raw_task_text_persisted_count: int
    opencode_mutation_count: int
    live_network_escalation_count: int


@dataclass(frozen=True, slots=True)
class ThresholdPolicyView:
    minimums: dict[str, Any]
    cache_thresholds: dict[str, Any]
    override_thresholds: dict[str, Any]
    failure_thresholds: dict[str, Any]
    cost_thresholds: dict[str, Any]
    safety_thresholds: dict[str, Any]
    rollback_thresholds: dict[str, Any]
    lane_thresholds: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ThresholdState:
    promotion_window_satisfied: bool
    sample_thresholds_met: bool
    cache_threshold_met: bool | None
    override_threshold_met: bool | None
    failure_threshold_met: bool | None
    safety_violated: bool
    rollback_required: bool
    cheap_inspect_ready: bool
    normal_repo_work_ready: bool
    all_allowed_ready: bool


def _schema(schema_id: str) -> dict[str, Any]:
    schema_path = SCHEMAS_DIR / f"{schema_id}.schema.json"
    return json.loads(read_safe(schema_path).text)


def _validate_artifact(artifact: dict[str, Any], schema_id: str) -> list[str]:
    schema = _schema(schema_id)
    validator = jsonschema.Draft7Validator(schema)
    return [
        f"{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in validator.iter_errors(artifact)
    ]


def validate_router_promotion_policy(policy: dict[str, Any]) -> list[str]:
    return _validate_artifact(policy, POLICY_SCHEMA_ID)


def validate_router_promotion_report(report: dict[str, Any]) -> list[str]:
    return _validate_artifact(report, REPORT_SCHEMA_ID)


def load_router_promotion_policy(path: Path | None = None) -> dict[str, Any]:
    policy_path = path or DEFAULT_POLICY_PATH
    policy = json.loads(read_safe(policy_path).text)
    errors = validate_router_promotion_policy(policy)
    if errors:
        raise ValueError(
            f"DeepSeek router promotion policy validation failed: {'; '.join(errors)}"
        )
    return policy


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_prefixed(value: Any) -> str:
    return f"sha256:{_sha256_hex(value)}"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(read_safe(path).text)


def _artifact_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            strings.extend(_artifact_strings(child))
        return strings
    if isinstance(value, list):
        for child in value:
            strings.extend(_artifact_strings(child))
        return strings
    if isinstance(value, str):
        strings.append(value)
    return strings


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = value.rstrip("Z")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_secret_like(text: str) -> bool:
    lowered = text.lower()
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        return True
    return any(token in lowered for token in ("api_key", "auth header", "private key"))


def _contains_raw_task_text(text: str) -> bool:
    lowered = text.lower()
    return any(
        needle in lowered
        for needle in ("task_text", "raw task", "raw prompt", "prompt:", "completion:")
    )


def _contains_opencode_mutation(text: str) -> bool:
    lowered = text.lower()
    return "opencode" in lowered and any(
        token in lowered for token in ("mutat", "sqlite", "config write", "db write")
    )


def _contains_live_network_escalation(text: str) -> bool:
    lowered = text.lower()
    return any(
        needle in lowered
        for needle in (
            "live network",
            "network escalation",
            "provider auth escalation",
            "live auth",
        )
    )


def _load_route_receipt(path: Path) -> LoadedArtifact | None:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != ROUTING_SCHEMA_ID:
        return None
    errors = validate_deepseek_routing_decision(payload)
    if errors:
        raise ValueError(
            f"DeepSeek routing receipt validation failed for {path}: {'; '.join(errors)}"
        )
    return LoadedArtifact(
        path=path,
        sha256=_sha256_prefixed(payload),
        kind="routing_decision",
        payload=payload,
    )


def _load_task_receipt(path: Path) -> LoadedArtifact | None:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") == ENVELOPE_SCHEMA_ID:
        envelope_errors = _validate_artifact(payload, ENVELOPE_SCHEMA_ID)
        if envelope_errors:
            raise ValueError(
                f"Task receipt envelope validation failed for {path}: {'; '.join(envelope_errors)}"
            )
        artifact_kind = payload.get("artifact_kind")
        if artifact_kind != "task_session_link":
            return None
        artifact = payload.get("payload")
        if not isinstance(artifact, dict):
            raise ValueError(f"Task receipt payload is not an object: {path}")
        payload_errors = _validate_artifact(artifact, TASK_LINK_SCHEMA_ID)
        if payload_errors:
            raise ValueError(
                f"Task session link validation failed for {path}: {'; '.join(payload_errors)}"
            )
        return LoadedArtifact(
            path=path,
            sha256=_sha256_prefixed(payload),
            kind="task_session_link",
            payload=artifact,
        )

    if payload.get("artifact_kind") == "task_session_link":
        payload_errors = _validate_artifact(payload, TASK_LINK_SCHEMA_ID)
        if payload_errors:
            raise ValueError(
                f"Task session link validation failed for {path}: {'; '.join(payload_errors)}"
            )
        return LoadedArtifact(
            path=path,
            sha256=_sha256_prefixed(payload),
            kind="task_session_link",
            payload=payload,
        )
    return None


def _load_usage_artifact(path: Path) -> LoadedArtifact | None:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return None
    schema_version = payload.get("schema_version")
    if schema_version == USAGE_SUMMARY_SCHEMA_ID:
        errors = _validate_artifact(payload, USAGE_SUMMARY_SCHEMA_ID)
        if errors:
            raise ValueError(
                f"DeepSeek usage summary validation failed for {path}: {'; '.join(errors)}"
            )
        return LoadedArtifact(
            path=path,
            sha256=_sha256_prefixed(payload),
            kind="usage_summary",
            payload=payload,
        )
    if schema_version == USAGE_REPORT_SCHEMA_ID:
        errors = _validate_artifact(payload, USAGE_REPORT_SCHEMA_ID)
        if errors:
            raise ValueError(
                f"DeepSeek usage report validation failed for {path}: {'; '.join(errors)}"
            )
        return LoadedArtifact(
            path=path,
            sha256=_sha256_prefixed(payload),
            kind="usage_report",
            payload=payload,
        )
    return None


def _discover_usage_artifact(receipts_dir: Path) -> LoadedArtifact | None:
    for candidate in (
        receipts_dir / "deepseek_opencode_usage_summary.v1.json",
        receipts_dir / "deepseek_opencode_usage_report.v1.json",
        DEFAULT_USAGE_SUMMARY_PATH,
        DEFAULT_USAGE_REPORT_PATH,
    ):
        if not candidate.exists():
            continue
        usage = _load_usage_artifact(candidate)
        if usage is not None:
            return usage
    return None


def _load_route_receipts(
    receipts_dir: Path, excluded: set[Path]
) -> list[LoadedArtifact]:
    route_receipts: list[LoadedArtifact] = []
    for path in sorted(receipts_dir.rglob("*.json")):
        if path.resolve() in excluded:
            continue
        artifact = _load_route_receipt(path)
        if artifact is not None:
            route_receipts.append(artifact)
    return route_receipts


def _load_task_receipts(task_root: Path, excluded: set[Path]) -> list[LoadedArtifact]:
    task_receipts: list[LoadedArtifact] = []
    for path in sorted(task_root.rglob(TASK_RECEIPT_GLOB)):
        if path.resolve() in excluded:
            continue
        artifact = _load_task_receipt(path)
        if artifact is not None:
            task_receipts.append(artifact)
    return task_receipts


def load_router_promotion_corpus(
    receipts_dir: Path, *, exclude_paths: list[Path] | None = None
) -> PromotionCorpus:
    excluded = {path.resolve() for path in (exclude_paths or [])}
    route_receipts = _load_route_receipts(receipts_dir, excluded)
    task_receipts = _load_task_receipts(SESSIONS_ROOT.path, excluded)
    usage_artifact: LoadedArtifact | None = None

    for path in sorted(receipts_dir.rglob("*.json")):
        if path.resolve() in excluded:
            continue
        artifact = _load_usage_artifact(path)
        if artifact is None:
            continue
        if artifact.kind == "usage_summary" or usage_artifact is None:
            usage_artifact = artifact

    if usage_artifact is None:
        usage_artifact = _discover_usage_artifact(receipts_dir)

    all_artifacts = [*route_receipts, *task_receipts]
    if usage_artifact is not None:
        all_artifacts.append(usage_artifact)

    return PromotionCorpus(
        route_receipts=route_receipts,
        task_receipts=task_receipts,
        usage_artifact=usage_artifact,
        all_artifacts=all_artifacts,
    )


def _classify_task_lane(payload: dict[str, Any]) -> str:
    model = str(payload.get("model") or "")
    reasoning_effort = str(payload.get("reasoning_effort") or "")
    if model == "deepseek-v4-flash":
        return "cheap_inspect"
    if model == "deepseek-v4-pro" and reasoning_effort == "max":
        return "hard_convergence"
    if model == "deepseek-v4-pro":
        return "normal_repo_work"
    return "strict_tool_beta" if payload.get("thinking_requested") else "cheap_inspect"


def _task_lane_rank(lane_id: str) -> int:
    return _LANE_RANKS.get(lane_id, -1)


def _count_all_strings(artifact: LoadedArtifact) -> tuple[int, int, int, int]:
    strings = _artifact_strings(artifact.payload)
    secret_like = 1 if any(_is_secret_like(text) for text in strings) else 0
    raw_task_text = 1 if any(_contains_raw_task_text(text) for text in strings) else 0
    opencode_mutation = (
        1 if any(_contains_opencode_mutation(text) for text in strings) else 0
    )
    live_network = (
        1 if any(_contains_live_network_escalation(text) for text in strings) else 0
    )
    return secret_like, raw_task_text, opencode_mutation, live_network


def _count_harder_reruns(records: list[TaskOutcomeRecord]) -> int:
    grouped: dict[str, list[TaskOutcomeRecord]] = {}
    for record in records:
        grouped.setdefault(record.task_id, []).append(record)

    reruns = 0
    for group in grouped.values():
        if len(group) < MIN_TIMESTAMP_PAIR:
            continue
        ordered = sorted(
            group,
            key=lambda record: (
                record.started_at
                or record.completed_at
                or datetime.min.replace(tzinfo=UTC),
                record.path.as_posix(),
            ),
        )
        best_failed_rank: int | None = None
        for record in ordered:
            if record.status != "completed":
                if record.lane_rank >= 0:
                    best_failed_rank = (
                        record.lane_rank
                        if best_failed_rank is None
                        else max(best_failed_rank, record.lane_rank)
                    )
                continue
            if best_failed_rank is not None and record.lane_rank > best_failed_rank:
                reruns += 1
                break
    return reruns


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _build_evidence_paths(corpus: PromotionCorpus) -> list[Path]:
    paths: list[Path] = []
    for artifact in corpus.all_artifacts:
        paths.append(artifact.path)
    return sorted(dict.fromkeys(paths), key=lambda path: path.as_posix())


def _load_default_usage_evidence() -> LoadedArtifact | None:
    for candidate in (DEFAULT_USAGE_SUMMARY_PATH, DEFAULT_USAGE_REPORT_PATH):
        if not candidate.exists():
            continue
        artifact = _load_usage_artifact(candidate)
        if artifact is not None:
            return artifact
    return None


def _route_summary(route_receipts: list[LoadedArtifact]) -> RouteSummary:
    decisions_by_lane = {lane_id: 0 for lane_id in LANE_IDS}
    override_count = 0
    dynamic_prefix_warning_count = 0
    reason_codes: list[str] = []
    timestamps: list[datetime] = []
    for receipt in route_receipts:
        payload = receipt.payload
        selected_lane = str(payload["selected_lane"])
        if selected_lane in decisions_by_lane:
            decisions_by_lane[selected_lane] += 1
        if payload.get("override_used") is True:
            override_count += 1
        if "stable_prefix_risk" in {
            str(code) for code in payload.get("reason_codes", [])
        }:
            dynamic_prefix_warning_count += 1
        if parsed := _parse_datetime(str(payload.get("generated_at"))):
            timestamps.append(parsed)
    if route_receipts:
        _append_unique(reason_codes, "routing_receipts_loaded")
    if dynamic_prefix_warning_count > 0:
        _append_unique(reason_codes, "stable_prefix_risk_detected")
    return RouteSummary(
        decisions_by_lane=decisions_by_lane,
        override_count=override_count,
        dynamic_prefix_warning_count=dynamic_prefix_warning_count,
        reason_codes=tuple(reason_codes),
        timestamps=tuple(timestamps),
    )


def _task_summary(task_receipts: list[LoadedArtifact]) -> TaskSummary:
    records: list[TaskOutcomeRecord] = []
    timestamps: list[datetime] = []
    for receipt in task_receipts:
        payload = receipt.payload
        lane_id = _classify_task_lane(payload)
        started_at = (
            _parse_datetime(str(payload.get("started_at")))
            if payload.get("started_at") is not None
            else None
        )
        completed_at = (
            _parse_datetime(str(payload.get("completed_at")))
            if payload.get("completed_at") is not None
            else None
        )
        records.append(
            TaskOutcomeRecord(
                path=receipt.path,
                task_id=str(
                    payload.get("task_id")
                    or payload.get("child_session_id")
                    or payload.get("parent_session_id")
                    or receipt.path.stem
                ),
                session_id=str(
                    payload.get("child_session_id")
                    or payload.get("parent_session_id")
                    or payload.get("task_id")
                    or receipt.path.parent.name
                ),
                status=str(payload.get("status") or "unknown"),
                lane_id=lane_id,
                lane_rank=_task_lane_rank(lane_id),
                started_at=started_at,
                completed_at=completed_at,
                warnings=tuple(str(item) for item in payload.get("warnings", [])),
            )
        )
        if started_at is not None:
            timestamps.append(started_at)
        if completed_at is not None:
            timestamps.append(completed_at)

    completed_tasks = sum(1 for record in records if record.status == "completed")
    failed_task_count = sum(1 for record in records if record.status != "completed")
    lane_attributed_failure_count = sum(
        1
        for record in records
        if record.status != "completed" and record.lane_rank >= 0
    )
    manual_rerun_harder_lane_count = _count_harder_reruns(records)
    distinct_sessions = (
        len({record.session_id for record in records}) if records else None
    )

    reason_codes: list[str] = []
    if records:
        _append_unique(reason_codes, "task_outcomes_loaded")
    if manual_rerun_harder_lane_count > 0:
        _append_unique(reason_codes, "manual_rerun_harder_lane_activity")

    return TaskSummary(
        records=records,
        completed_tasks=completed_tasks,
        failed_task_count=failed_task_count,
        lane_attributed_failure_count=lane_attributed_failure_count,
        manual_rerun_harder_lane_count=manual_rerun_harder_lane_count,
        distinct_sessions=distinct_sessions,
        reason_codes=tuple(reason_codes),
        timestamps=tuple(timestamps),
    )


def _usage_summary(usage_artifact: LoadedArtifact | None) -> UsageSummary:
    if usage_artifact is None:
        return UsageSummary(None, None, None, None, tuple(), tuple())

    timestamps: list[datetime] = []
    reason_codes = [f"usage_{usage_artifact.kind}_loaded"]
    if parsed := _parse_datetime(str(usage_artifact.payload.get("generated_at"))):
        timestamps.append(parsed)

    cache_hit_ratio: float | None = None
    discounted_cost_estimate: float | None = None
    full_cost_estimate: float | None = None
    pro_max_share: float | None = None
    if usage_artifact.kind == "usage_summary":
        cache_hit_ratio = _as_float(usage_artifact.payload.get("cache_hit_ratio"))
        discounted_cost_estimate = _as_float(
            usage_artifact.payload.get("estimated_discounted_cost_usd")
        )
        full_cost_estimate = _as_float(
            usage_artifact.payload.get("estimated_full_cost_usd")
        )
        lane_usage = usage_artifact.payload.get("lane_usage", [])
        if isinstance(lane_usage, list):
            shares = (
                share
                for share in (
                    _as_float(row.get("request_share"))
                    for row in lane_usage
                    if isinstance(row, dict)
                    and row.get("model_id") == "deepseek-v4-pro"
                    and row.get("variant") == "max"
                )
                if share is not None
            )
            pro_max_share = sum(shares, 0.0) or None
    else:
        cache_hit_ratio = _as_float(usage_artifact.payload.get("cache_hit_ratio"))
        discounted_cost = usage_artifact.payload.get(
            "estimated_discounted_cost_if_pricing_available"
        )
        full_cost = usage_artifact.payload.get(
            "estimated_full_cost_if_pricing_available"
        )
        if isinstance(discounted_cost, dict):
            discounted_cost_estimate = _as_float(discounted_cost.get("amount_usd"))
        if isinstance(full_cost, dict):
            full_cost_estimate = _as_float(full_cost.get("amount_usd"))
        max_usage = usage_artifact.payload.get("max_vs_default_effort_usage", {})
        if isinstance(max_usage, dict):
            max_row = max_usage.get("max")
            if isinstance(max_row, dict):
                pro_max_share = _as_float(max_row.get("request_share"))

    return UsageSummary(
        cache_hit_ratio=cache_hit_ratio,
        discounted_cost_estimate=discounted_cost_estimate,
        full_cost_estimate=full_cost_estimate,
        pro_max_share=pro_max_share,
        reason_codes=tuple(reason_codes),
        timestamps=tuple(timestamps),
    )


def _safety_summary(artifacts: list[LoadedArtifact]) -> SafetySummary:
    raw_secret_violation_count = 0
    raw_task_text_persisted_count = 0
    opencode_mutation_count = 0
    live_network_escalation_count = 0
    for artifact in artifacts:
        secret_like, raw_task_text, opencode_mutation, live_network = (
            _count_all_strings(artifact)
        )
        raw_secret_violation_count += secret_like
        raw_task_text_persisted_count += raw_task_text
        opencode_mutation_count += opencode_mutation
        live_network_escalation_count += live_network
    return SafetySummary(
        raw_secret_violation_count=raw_secret_violation_count,
        raw_task_text_persisted_count=raw_task_text_persisted_count,
        opencode_mutation_count=opencode_mutation_count,
        live_network_escalation_count=live_network_escalation_count,
    )


def _observation_window_days(timestamps: tuple[datetime, ...]) -> int | None:
    if len(timestamps) < MIN_TIMESTAMP_PAIR:
        return None
    return (max(timestamps) - min(timestamps)).days


def _build_metrics(
    corpus: PromotionCorpus, policy: dict[str, Any]
) -> tuple[dict[str, Any], list[str], list[str]]:
    route_summary = _route_summary(corpus.route_receipts)
    task_summary = _task_summary(corpus.task_receipts)
    usage_summary = _usage_summary(corpus.usage_artifact)
    safety_summary = _safety_summary([*corpus.route_receipts, *corpus.task_receipts])

    timestamps = (
        *route_summary.timestamps,
        *task_summary.timestamps,
        *usage_summary.timestamps,
    )
    observation_window_days = _observation_window_days(timestamps)
    stable_prefix_warning_rate = (
        route_summary.dynamic_prefix_warning_count / len(corpus.route_receipts)
        if corpus.route_receipts
        else None
    )
    override_rate = (
        route_summary.override_count / len(corpus.route_receipts)
        if corpus.route_receipts
        else None
    )
    lane_attributed_failure_rate = (
        task_summary.lane_attributed_failure_count / len(task_summary.records)
        if task_summary.records
        else None
    )

    metrics = {
        "total_decisions": len(corpus.route_receipts),
        "decisions_by_lane": route_summary.decisions_by_lane,
        "completed_tasks": task_summary.completed_tasks
        if task_summary.records
        else None,
        "distinct_sessions": task_summary.distinct_sessions,
        "observation_window_days": observation_window_days,
        "override_count": route_summary.override_count,
        "override_rate": override_rate,
        "manual_rerun_harder_lane_count": (
            task_summary.manual_rerun_harder_lane_count
            if task_summary.records
            else None
        ),
        "failed_task_count": task_summary.failed_task_count
        if task_summary.records
        else None,
        "lane_attributed_failure_count": (
            task_summary.lane_attributed_failure_count if task_summary.records else None
        ),
        "lane_attributed_failure_rate": lane_attributed_failure_rate,
        "cache_hit_ratio": usage_summary.cache_hit_ratio,
        "discounted_cost_estimate": usage_summary.discounted_cost_estimate,
        "full_cost_estimate": usage_summary.full_cost_estimate,
        "pro_max_share": usage_summary.pro_max_share,
        "raw_secret_violation_count": safety_summary.raw_secret_violation_count,
        "raw_task_text_persisted_count": safety_summary.raw_task_text_persisted_count,
        "opencode_mutation_count": safety_summary.opencode_mutation_count,
        "live_network_escalation_count": safety_summary.live_network_escalation_count,
        "dynamic_prefix_warning_count": route_summary.dynamic_prefix_warning_count,
        "stable_prefix_warning_rate": stable_prefix_warning_rate,
    }

    reason_codes = [
        *route_summary.reason_codes,
        *task_summary.reason_codes,
        *usage_summary.reason_codes,
    ]
    if task_summary.manual_rerun_harder_lane_count > 0:
        _append_unique(reason_codes, "manual_rerun_harder_lane_activity")
    if route_summary.dynamic_prefix_warning_count > 0:
        _append_unique(reason_codes, "stable_prefix_risk_detected")
    evidence_paths = [str(path) for path in _build_evidence_paths(corpus)]
    return metrics, reason_codes, evidence_paths


def _promotion_window_satisfied(
    minimums: dict[str, Any],
    distinct_sessions: int | None,
    observation_window_days: int | None,
) -> bool:
    return bool(
        (
            distinct_sessions is not None
            and distinct_sessions >= minimums["minimum_distinct_sessions"]
        )
        or (
            observation_window_days is not None
            and observation_window_days >= minimums["minimum_observation_days"]
        )
    )


def _sample_thresholds_met(
    minimums: dict[str, Any],
    total_decisions: int,
    completed_tasks: int | None,
    promotion_window_satisfied: bool,
) -> bool:
    return bool(
        total_decisions >= minimums["minimum_total_decisions"]
        and completed_tasks is not None
        and completed_tasks >= minimums["minimum_completed_tasks"]
        and promotion_window_satisfied
    )


def _cache_threshold_met(
    cache_hit_ratio: float | None, cache_thresholds: dict[str, Any]
) -> bool | None:
    if cache_hit_ratio is None:
        return None
    return cache_hit_ratio >= cache_thresholds["minimum_cache_hit_ratio_low_risk"]


def _override_threshold_met(
    override_rate: float | None, override_thresholds: dict[str, Any]
) -> bool | None:
    if override_rate is None:
        return None
    return override_rate < override_thresholds["maximum_override_rate_low_risk"]


def _failure_threshold_met(
    lane_failure_rate: float | None, failure_thresholds: dict[str, Any]
) -> bool | None:
    if lane_failure_rate is None:
        return None
    return (
        lane_failure_rate
        < failure_thresholds["maximum_lane_attributed_failure_rate_low_risk"]
    )


def _safety_violated(
    metrics: dict[str, Any], safety_thresholds: dict[str, Any]
) -> bool:
    return any((
        metrics["raw_secret_violation_count"]
        > safety_thresholds["maximum_raw_secret_violation_count"],
        metrics["raw_task_text_persisted_count"]
        > safety_thresholds["maximum_raw_task_text_persisted_count"],
        metrics["opencode_mutation_count"]
        > safety_thresholds["maximum_opencode_mutation_count"],
        metrics["live_network_escalation_count"]
        > safety_thresholds["maximum_live_network_escalation_count"],
        metrics["dynamic_prefix_warning_count"]
        > safety_thresholds["maximum_dynamic_prefix_warning_count"],
    ))


def _rollback_required(
    metrics: dict[str, Any], rollback_thresholds: dict[str, Any]
) -> bool:
    cache_hit_ratio = metrics["cache_hit_ratio"]
    lane_failure_rate = metrics["lane_attributed_failure_rate"]
    override_rate = metrics["override_rate"]
    return bool(
        metrics["raw_secret_violation_count"]
        >= rollback_thresholds["raw_secret_violation_count"]
        or metrics["raw_task_text_persisted_count"]
        >= rollback_thresholds["raw_task_text_persisted_count"]
        or metrics["opencode_mutation_count"]
        >= rollback_thresholds["opencode_mutation_count"]
        or metrics["live_network_escalation_count"]
        >= rollback_thresholds["live_network_escalation_count"]
        or (
            cache_hit_ratio is not None
            and cache_hit_ratio < rollback_thresholds["cache_hit_ratio_floor"]
        )
        or (
            lane_failure_rate is not None
            and lane_failure_rate
            >= rollback_thresholds["lane_attributed_failure_rate_spike"]
        )
        or (
            override_rate is not None
            and override_rate >= rollback_thresholds["override_rate_floor"]
        )
    )


def _sample_reason_codes(
    metrics: dict[str, Any], minimums: dict[str, Any], promotion_window_satisfied: bool
) -> list[str]:
    reason_codes: list[str] = []
    total_decisions = int(metrics["total_decisions"])
    completed_tasks = metrics["completed_tasks"]
    distinct_sessions = metrics["distinct_sessions"]
    observation_window_days = metrics["observation_window_days"]

    if total_decisions < minimums["minimum_total_decisions"]:
        _append_unique(reason_codes, "total_decisions_below_threshold")
    if completed_tasks is None or completed_tasks < minimums["minimum_completed_tasks"]:
        _append_unique(reason_codes, "completed_tasks_below_threshold")
    if (
        distinct_sessions is None
        or distinct_sessions < minimums["minimum_distinct_sessions"]
    ):
        _append_unique(reason_codes, "distinct_sessions_below_threshold")
    if (
        observation_window_days is None
        or observation_window_days < minimums["minimum_observation_days"]
    ):
        _append_unique(reason_codes, "observation_window_below_threshold")
    if not promotion_window_satisfied:
        _append_unique(reason_codes, "promotion_window_below_threshold")
    if total_decisions < minimums["minimum_total_decisions"] or completed_tasks is None:
        _append_unique(reason_codes, "insufficient_sample")
    return reason_codes


def _cache_reason_codes(
    cache_hit_ratio: float | None,
    cache_thresholds: dict[str, Any],
    rollback_thresholds: dict[str, Any],
) -> list[str]:
    reason_codes: list[str] = []
    if cache_hit_ratio is None:
        _append_unique(reason_codes, "cache_hit_ratio_unavailable")
    elif cache_hit_ratio < rollback_thresholds["cache_hit_ratio_floor"]:
        _append_unique(reason_codes, "cache_hit_ratio_below_rollback_floor")
    elif cache_hit_ratio < cache_thresholds["minimum_cache_hit_ratio_low_risk"]:
        _append_unique(reason_codes, "cache_hit_ratio_below_threshold")
    return reason_codes


def _override_reason_codes(
    override_rate: float | None,
    override_thresholds: dict[str, Any],
    rollback_thresholds: dict[str, Any],
) -> list[str]:
    reason_codes: list[str] = []
    if override_rate is None:
        _append_unique(reason_codes, "override_rate_unavailable")
    elif override_rate >= rollback_thresholds["override_rate_floor"]:
        _append_unique(reason_codes, "override_rate_rollback")
    elif override_rate >= override_thresholds["maximum_override_rate_low_risk"]:
        _append_unique(reason_codes, "override_rate_too_high")
    return reason_codes


def _failure_reason_codes(
    lane_failure_rate: float | None,
    failure_thresholds: dict[str, Any],
    rollback_thresholds: dict[str, Any],
) -> list[str]:
    reason_codes: list[str] = []
    if lane_failure_rate is None:
        _append_unique(reason_codes, "lane_failure_rate_unavailable")
    elif lane_failure_rate >= rollback_thresholds["lane_attributed_failure_rate_spike"]:
        _append_unique(reason_codes, "lane_failure_rate_rollback")
    elif (
        lane_failure_rate
        >= failure_thresholds["maximum_lane_attributed_failure_rate_low_risk"]
    ):
        _append_unique(reason_codes, "lane_failure_rate_too_high")
    return reason_codes


def _safety_reason_codes(metrics: dict[str, Any], safety_violated: bool) -> list[str]:
    reason_codes: list[str] = []
    if safety_violated:
        _append_unique(reason_codes, "safety_thresholds_violated")
    if metrics["raw_secret_violation_count"] > 0:
        _append_unique(reason_codes, "raw_secret_violation_detected")
    if metrics["raw_task_text_persisted_count"] > 0:
        _append_unique(reason_codes, "raw_task_text_persisted_detected")
    if metrics["opencode_mutation_count"] > 0:
        _append_unique(reason_codes, "opencode_mutation_detected")
    if metrics["live_network_escalation_count"] > 0:
        _append_unique(reason_codes, "live_network_escalation_detected")
    if metrics["dynamic_prefix_warning_count"] > 0:
        _append_unique(reason_codes, "stable_prefix_risk_detected")
    return reason_codes


def _cost_reason_codes(
    pro_max_share: float | None,
    discounted_cost_estimate: float | None,
    full_cost_estimate: float | None,
    cost_thresholds: dict[str, Any],
) -> list[str]:
    reason_codes: list[str] = []
    if (
        pro_max_share is not None
        and pro_max_share > cost_thresholds["maximum_pro_max_share"]
    ):
        _append_unique(reason_codes, "pro_max_share_above_ceiling")
    if discounted_cost_estimate is not None and full_cost_estimate is not None:
        _append_unique(reason_codes, "usage_costs_recorded")
    return reason_codes


def _recommended_lanes(recommendation: str) -> list[str]:
    if recommendation == "auto_apply_low_risk":
        return ["cheap_inspect"]
    if recommendation == "auto_apply_normal_repo_work":
        return ["cheap_inspect", "normal_repo_work"]
    if recommendation == "auto_apply_all_allowed":
        return [
            "cheap_inspect",
            "normal_repo_work",
            "hard_convergence",
            "json_artifact",
        ]
    return []


def _policy_threshold_views(policy: dict[str, Any]) -> ThresholdPolicyView:
    return ThresholdPolicyView(
        minimums=policy["minimum_sample_thresholds"],
        cache_thresholds=policy["cache_thresholds"],
        override_thresholds=policy["override_thresholds"],
        failure_thresholds=policy["failure_thresholds"],
        cost_thresholds=policy["cost_thresholds"],
        safety_thresholds=policy["safety_thresholds"],
        rollback_thresholds=policy["rollback_thresholds"],
        lane_thresholds=policy["lane_thresholds"],
    )


def _build_threshold_state(
    metrics: dict[str, Any], policy_view: ThresholdPolicyView
) -> ThresholdState:
    promotion_window_satisfied = _promotion_window_satisfied(
        policy_view.minimums,
        metrics["distinct_sessions"],
        metrics["observation_window_days"],
    )
    sample_thresholds_met = _sample_thresholds_met(
        policy_view.minimums,
        int(metrics["total_decisions"]),
        metrics["completed_tasks"],
        promotion_window_satisfied,
    )
    cache_threshold_met = _cache_threshold_met(
        metrics["cache_hit_ratio"], policy_view.cache_thresholds
    )
    override_threshold_met = _override_threshold_met(
        metrics["override_rate"], policy_view.override_thresholds
    )
    failure_threshold_met = _failure_threshold_met(
        metrics["lane_attributed_failure_rate"], policy_view.failure_thresholds
    )
    safety_violated = _safety_violated(metrics, policy_view.safety_thresholds)
    rollback_required = _rollback_required(metrics, policy_view.rollback_thresholds)
    cheap_inspect_ready = bool(
        sample_thresholds_met
        and metrics["decisions_by_lane"]["cheap_inspect"]
        >= policy_view.lane_thresholds["cheap_inspect"]["minimum_successful_decisions"]
        and cache_threshold_met is True
        and override_threshold_met is True
        and failure_threshold_met is True
        and not safety_violated
    )
    normal_repo_work_ready = bool(
        cheap_inspect_ready
        and metrics["decisions_by_lane"]["normal_repo_work"]
        >= policy_view.lane_thresholds["normal_repo_work"][
            "minimum_successful_decisions"
        ]
        and not rollback_required
    )
    all_allowed_ready = bool(
        normal_repo_work_ready
        and metrics["decisions_by_lane"]["hard_convergence"]
        >= policy_view.lane_thresholds["hard_convergence"][
            "minimum_successful_decisions"
        ]
        and metrics["decisions_by_lane"]["json_artifact"]
        >= policy_view.lane_thresholds["json_artifact"]["minimum_successful_decisions"]
        and (
            metrics["pro_max_share"] is None
            or metrics["pro_max_share"]
            <= policy_view.cost_thresholds["maximum_pro_max_share"]
        )
        and not rollback_required
    )
    return ThresholdState(
        promotion_window_satisfied=promotion_window_satisfied,
        sample_thresholds_met=sample_thresholds_met,
        cache_threshold_met=cache_threshold_met,
        override_threshold_met=override_threshold_met,
        failure_threshold_met=failure_threshold_met,
        safety_violated=safety_violated,
        rollback_required=rollback_required,
        cheap_inspect_ready=cheap_inspect_ready,
        normal_repo_work_ready=normal_repo_work_ready,
        all_allowed_ready=all_allowed_ready,
    )


def _recommendation_from_state(state: ThresholdState) -> str:
    recommendation = "recommendation_only"
    if state.rollback_required:
        recommendation = "rollback"
    elif not state.sample_thresholds_met:
        recommendation = "hold"
    elif state.cache_threshold_met is not True:
        recommendation = "hold"
    elif state.override_threshold_met is not True:
        recommendation = "hold"
    elif state.failure_threshold_met is not True:
        recommendation = "hold"
    elif state.cheap_inspect_ready and not state.normal_repo_work_ready:
        recommendation = "auto_apply_low_risk"
    elif state.normal_repo_work_ready and not state.all_allowed_ready:
        recommendation = "auto_apply_normal_repo_work"
    elif state.all_allowed_ready:
        recommendation = "auto_apply_all_allowed"
    return recommendation


def _evaluate_thresholds(
    metrics: dict[str, Any], policy: dict[str, Any]
) -> tuple[dict[str, Any], str, list[str], list[str], bool, list[str]]:
    policy_view = _policy_threshold_views(policy)
    state = _build_threshold_state(metrics, policy_view)
    threshold_results = {
        "sample_thresholds_met": state.sample_thresholds_met,
        "promotion_window_satisfied": state.promotion_window_satisfied,
        "cache_threshold_met": state.cache_threshold_met,
        "override_threshold_met": state.override_threshold_met,
        "failure_threshold_met": state.failure_threshold_met,
        "safety_thresholds_violated": state.safety_violated,
        "low_risk_ready": state.cheap_inspect_ready,
        "normal_repo_work_ready": state.normal_repo_work_ready,
        "all_allowed_ready": state.all_allowed_ready,
        "strict_tool_beta_auto_promote_blocked": True,
    }
    reason_codes = [
        *_sample_reason_codes(
            metrics, policy_view.minimums, state.promotion_window_satisfied
        ),
        *_cache_reason_codes(
            metrics["cache_hit_ratio"],
            policy_view.cache_thresholds,
            policy_view.rollback_thresholds,
        ),
        *_override_reason_codes(
            metrics["override_rate"],
            policy_view.override_thresholds,
            policy_view.rollback_thresholds,
        ),
        *_failure_reason_codes(
            metrics["lane_attributed_failure_rate"],
            policy_view.failure_thresholds,
            policy_view.rollback_thresholds,
        ),
        *_safety_reason_codes(metrics, state.safety_violated),
        *_cost_reason_codes(
            metrics["pro_max_share"],
            metrics["discounted_cost_estimate"],
            metrics["full_cost_estimate"],
            policy_view.cost_thresholds,
        ),
    ]
    recommendation = _recommendation_from_state(state)
    allowed_auto_apply_lanes: list[str] = _recommended_lanes(recommendation)
    refused_auto_apply_lanes: list[str] = (
        [lane_id for lane_id in LANE_IDS if lane_id not in allowed_auto_apply_lanes]
        if allowed_auto_apply_lanes
        else list(LANE_IDS)
    )
    return (
        threshold_results,
        recommendation,
        allowed_auto_apply_lanes,
        refused_auto_apply_lanes,
        state.rollback_required,
        reason_codes,
    )


def _assemble_router_promotion_report(
    corpus: PromotionCorpus, loaded_policy: dict[str, Any], generated_at: str | None
) -> dict[str, Any]:
    metrics, reason_codes, evidence_paths = _build_metrics(corpus, loaded_policy)
    threshold_state = _evaluate_thresholds(metrics, loaded_policy)
    for reason in threshold_state[5]:
        _append_unique(reason_codes, reason)

    generated_at_value = generated_at or datetime.now(UTC).isoformat().replace(
        "+00:00", "Z"
    )
    ordered_artifacts = sorted(
        corpus.all_artifacts, key=lambda artifact: artifact.path.as_posix()
    )
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_ID,
        "report_id": "",
        "generated_at": generated_at_value,
        "policy_id": str(loaded_policy["policy_id"]),
        "source_receipt_count": len(ordered_artifacts),
        "source_receipt_hashes": list(
            dict.fromkeys(artifact.sha256 for artifact in ordered_artifacts)
        ),
        "metrics": metrics,
        "threshold_results": threshold_state[0],
        "recommendation": threshold_state[1],
        "allowed_auto_apply_lanes": threshold_state[2],
        "refused_auto_apply_lanes": threshold_state[3],
        "rollback_required": threshold_state[4],
        "reason_codes": reason_codes,
        "redaction_status": "content_light",
        "content_light": True,
        "evidence_paths": [str(path) for path in evidence_paths],
    }
    canonical = {
        key: value
        for key, value in report.items()
        if key not in {"generated_at", "report_id", "evidence_paths"}
    }
    report["report_id"] = _sha256_hex(canonical)
    errors = validate_router_promotion_report(report)
    if errors:
        raise ValueError(
            f"DeepSeek router promotion report validation failed: {'; '.join(errors)}"
        )
    return report


def build_router_promotion_report(
    receipts_dir: Path,
    *,
    policy: dict[str, Any] | None = None,
    output_json: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    loaded_policy = policy or load_router_promotion_policy()
    default_usage_artifact = _load_default_usage_evidence()
    corpus = load_router_promotion_corpus(
        receipts_dir, exclude_paths=[output_json] if output_json is not None else None
    )
    if corpus.usage_artifact is None:
        corpus = PromotionCorpus(
            route_receipts=corpus.route_receipts,
            task_receipts=corpus.task_receipts,
            usage_artifact=default_usage_artifact,
            all_artifacts=[
                *corpus.route_receipts,
                *corpus.task_receipts,
                *(
                    [default_usage_artifact]
                    if default_usage_artifact is not None
                    else []
                ),
            ],
        )
    return _assemble_router_promotion_report(corpus, loaded_policy, generated_at)


def write_router_promotion_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def validate_router_promotion_outputs(report: dict[str, Any]) -> list[str]:
    return validate_router_promotion_report(report)


def format_router_promotion_report_table(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    rows = [
        ("report_id", report["report_id"]),
        ("recommendation", report["recommendation"]),
        ("source_receipts", str(report["source_receipt_count"])),
        ("decisions", str(metrics["total_decisions"])),
        ("completed_tasks", _format_count(metrics["completed_tasks"])),
        ("distinct_sessions", _format_count(metrics["distinct_sessions"])),
        ("observation_days", _format_count(metrics["observation_window_days"])),
        ("override_rate", _format_percent(metrics["override_rate"])),
        ("lane_failure_rate", _format_percent(metrics["lane_attributed_failure_rate"])),
        ("cache_hit_ratio", _format_percent(metrics["cache_hit_ratio"])),
        ("discounted_cost_usd", _format_money(metrics["discounted_cost_estimate"])),
        ("full_cost_usd", _format_money(metrics["full_cost_estimate"])),
        ("pro_max_share", _format_percent(metrics["pro_max_share"])),
        (
            "allowed_auto_apply_lanes",
            ", ".join(report["allowed_auto_apply_lanes"]) or "-",
        ),
        (
            "refused_auto_apply_lanes",
            ", ".join(report["refused_auto_apply_lanes"]) or "-",
        ),
        ("reason_codes", ", ".join(report["reason_codes"])),
        ("rollback_required", str(report["rollback_required"]).lower()),
    ]
    width = max(len(label) for label, _ in rows)
    return "\n".join(f"{label.ljust(width)}  {value}" for label, value in rows)


def _format_percent(value: Any) -> str:
    number = _as_float(value)
    if number is None:
        return "-"
    return f"{number:.2%}"


def _format_count(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)


def _format_money(value: Any) -> str:
    number = _as_float(value)
    if number is None:
        return "-"
    return f"${number:,.4f}"


__all__ = [
    "DEFAULT_POLICY_PATH",
    "REPORT_SCHEMA_ID",
    "build_router_promotion_report",
    "format_router_promotion_report_table",
    "load_router_promotion_corpus",
    "load_router_promotion_policy",
    "validate_router_promotion_outputs",
    "validate_router_promotion_policy",
    "validate_router_promotion_report",
    "write_router_promotion_report",
]
