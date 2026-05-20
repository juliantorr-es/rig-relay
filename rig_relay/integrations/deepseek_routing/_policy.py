"""Deterministic DeepSeek lane routing policy and decision receipts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema

from rig_relay.core.utils.io import read_safe

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
DEFAULT_POLICY_PATH = (
    REPO_ROOT / "docs" / "json" / "integrations" / ("deepseek_lane_policy.v1.json")
)
POLICY_SCHEMA_ID = "rig.deepseek.lane_policy.v1"
DECISION_SCHEMA_ID = "rig.deepseek.routing_decision.v1"

LANE_IDS = (
    "cheap_inspect",
    "normal_repo_work",
    "hard_convergence",
    "json_artifact",
    "strict_tool_beta",
)

VALID_MUTATION_RISKS = ("none", "low", "medium", "high")
VALID_CONCURRENCY_RISKS = ("none", "low", "medium", "high")


@dataclass(frozen=True, slots=True)
class DeepSeekRoutingTask:
    task_text: str
    estimated_context_tokens: int
    requested_output_kind: str
    touches_code: bool
    touches_tests: bool
    touches_schemas: bool
    touches_provider_auth: bool
    touches_release_claims: bool
    touches_public_site: bool
    live_network: bool
    mutation_risk: str
    concurrency_risk: str
    requires_json_output: bool
    requires_tool_calls: bool
    requires_multi_file_reasoning: bool
    requires_strict_tool_beta: bool
    strict_tool_schema_compatible: bool
    user_override_lane: str | None = None


@dataclass(frozen=True, slots=True)
class _TaskFacts:
    normalized: dict[str, Any]
    task_text_lower: str
    task_text_hash: str
    requested_json: bool
    dry_run_low_context: bool


@dataclass(frozen=True, slots=True)
class _LaneSelection:
    selected_lane: str
    override_used: bool
    reason_codes: list[str]
    warnings: list[str]


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


def validate_deepseek_lane_policy(policy: dict[str, Any]) -> list[str]:
    return _validate_artifact(policy, POLICY_SCHEMA_ID)


def validate_deepseek_routing_decision(decision: dict[str, Any]) -> list[str]:
    return _validate_artifact(decision, DECISION_SCHEMA_ID)


def load_deepseek_lane_policy(path: Path | None = None) -> dict[str, Any]:
    policy_path = path or DEFAULT_POLICY_PATH
    policy = json.loads(read_safe(policy_path).text)
    errors = validate_deepseek_lane_policy(policy)
    if errors:
        raise ValueError(f"DeepSeek lane policy validation failed: {'; '.join(errors)}")
    return policy


def _normalize_task(task: DeepSeekRoutingTask) -> dict[str, Any]:
    requested_output_kind = task.requested_output_kind.strip().lower()
    user_override_lane = (
        task.user_override_lane.strip() if task.user_override_lane else None
    )
    return {
        "task_text": task.task_text.rstrip("\r\n"),
        "estimated_context_tokens": int(task.estimated_context_tokens),
        "requested_output_kind": requested_output_kind,
        "touches_code": bool(task.touches_code),
        "touches_tests": bool(task.touches_tests),
        "touches_schemas": bool(task.touches_schemas),
        "touches_provider_auth": bool(task.touches_provider_auth),
        "touches_release_claims": bool(task.touches_release_claims),
        "touches_public_site": bool(task.touches_public_site),
        "live_network": bool(task.live_network),
        "mutation_risk": task.mutation_risk,
        "concurrency_risk": task.concurrency_risk,
        "requires_json_output": bool(task.requires_json_output),
        "requires_tool_calls": bool(task.requires_tool_calls),
        "requires_multi_file_reasoning": bool(task.requires_multi_file_reasoning),
        "requires_strict_tool_beta": bool(task.requires_strict_tool_beta),
        "strict_tool_schema_compatible": bool(task.strict_tool_schema_compatible),
        "user_override_lane": user_override_lane,
    }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _contains_any(text: str, phrases: list[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _lane_map(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lanes = policy.get("lanes", [])
    return {str(lane["lane_id"]): lane for lane in lanes}


def _selected_model_for_lane(
    lane_id: str, policy: dict[str, Any], context_tokens: int
) -> str:
    lane = _lane_map(policy)[lane_id]
    if lane_id == "json_artifact":
        threshold = int(policy["json_artifact_small_context_token_threshold"])
        if context_tokens <= threshold and lane.get("small_artifact_model_id"):
            return str(lane["small_artifact_model_id"])
    return str(lane["preferred_model_id"])


def _stable_prefix_warning(policy: dict[str, Any]) -> str:
    return str(policy["stable_prefix_warning"])


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _collect_hard_reasons(
    normalized: dict[str, Any],
    policy: dict[str, Any],
    *,
    task_text_lower: str,
    dry_run_low_context: bool,
) -> list[str]:
    hard_reasons: list[str] = []
    if normalized["mutation_risk"] == "high":
        _append_unique(hard_reasons, "mutation_risk_high")
    if normalized["concurrency_risk"] == "high":
        _append_unique(hard_reasons, "concurrency_risk_high")
    if normalized["requires_multi_file_reasoning"] or (
        normalized["estimated_context_tokens"]
        > int(policy["hard_convergence_context_threshold_tokens"])
    ):
        _append_unique(hard_reasons, "multi_file_or_large_context")
    if normalized["touches_release_claims"] or _contains_any(
        task_text_lower, list(policy["hard_convergence_text_phrases"])
    ):
        _append_unique(hard_reasons, "release_claim_or_audit")
    if (
        normalized["touches_provider_auth"] or normalized["live_network"]
    ) and not dry_run_low_context:
        _append_unique(hard_reasons, "provider_auth_or_live_network")
    return hard_reasons


def _task_facts(task: DeepSeekRoutingTask, policy: dict[str, Any]) -> _TaskFacts:
    normalized = _normalize_task(task)
    task_text = normalized["task_text"]
    task_text_lower = task_text.lower()
    requested_json = bool(normalized["requires_json_output"]) or (
        normalized["requested_output_kind"] in policy["json_output_kinds"]
    )
    dry_run_low_context = _contains_any(
        task_text_lower, list(policy["read_only_dry_run_phrases"])
    ) and normalized["estimated_context_tokens"] <= int(
        policy["read_only_dry_run_context_threshold_tokens"]
    )
    return _TaskFacts(
        normalized=normalized,
        task_text_lower=task_text_lower,
        task_text_hash=_sha256_text(task_text),
        requested_json=requested_json,
        dry_run_low_context=dry_run_low_context,
    )


def _select_lane(
    facts: _TaskFacts, policy: dict[str, Any], *, hard_reasons: list[str]
) -> _LaneSelection:
    lane_map = _lane_map(policy)
    normalized = facts.normalized
    override_lane = normalized["user_override_lane"]
    warnings = [_stable_prefix_warning(policy)]
    reason_codes: list[str] = []
    selected_lane = str(policy["default_lane"])
    override_used = False
    override_valid = False
    if override_lane:
        if override_lane in lane_map:
            reason_codes.append("override_used")
            warnings.append(f"User override lane {override_lane} honored with warning.")
            selected_lane = override_lane
            override_used = True
            override_valid = True
        else:
            reason_codes.append("override_invalid")
            warnings.append(f"Invalid override lane {override_lane} ignored.")
    if not override_valid:
        if hard_reasons:
            reason_codes.extend(hard_reasons)
            if facts.requested_json:
                warnings.append(
                    "JSON output requested, but hard_convergence was selected because of risk."
                )
            selected_lane = "hard_convergence"
        elif facts.requested_json:
            reason_codes.append("json_output_requested")
            selected_lane = "json_artifact"
        elif (
            normalized["requires_strict_tool_beta"]
            and normalized["strict_tool_schema_compatible"]
            and normalized["requires_tool_calls"]
        ):
            reason_codes.extend([
                "strict_tool_beta_requested",
                "strict_tool_schema_compatible",
                "tool_calls_requested",
            ])
            selected_lane = "strict_tool_beta"
        elif normalized["touches_schemas"] or normalized["touches_tests"]:
            if normalized["estimated_context_tokens"] <= int(
                policy["hard_convergence_context_threshold_tokens"]
            ):
                reason_codes.append("tests_or_schemas_moderate_context")
                selected_lane = "normal_repo_work"
        elif normalized["estimated_context_tokens"] <= int(
            policy["cheap_inspect_max_context_tokens"]
        ) and normalized["mutation_risk"] in {"none", "low"}:
            reason_codes.append("short_low_risk")
            selected_lane = "cheap_inspect"
        else:
            reason_codes.append("default_normal_repo_work")

    if _contains_any(
        facts.task_text_lower, list(policy["dynamic_prefix_risk_phrases"])
    ):
        warnings.append(
            "Task asks to randomize or reorder providers, tools, or context blocks; "
            "keep stable prefixes to preserve DeepSeek cache hits."
        )
        _append_unique(reason_codes, "stable_prefix_risk")

    return _LaneSelection(
        selected_lane=selected_lane,
        override_used=override_used,
        reason_codes=reason_codes,
        warnings=warnings,
    )


def _build_decision_payload(
    task: DeepSeekRoutingTask, policy: dict[str, Any]
) -> dict[str, Any]:
    facts = _task_facts(task, policy)
    hard_reasons = _collect_hard_reasons(
        facts.normalized,
        policy,
        task_text_lower=facts.task_text_lower,
        dry_run_low_context=facts.dry_run_low_context,
    )
    selection = _select_lane(facts, policy, hard_reasons=hard_reasons)
    selected_lane = selection.selected_lane
    selected_model = _selected_model_for_lane(
        selected_lane, policy, facts.normalized["estimated_context_tokens"]
    )
    lane = _lane_map(policy)[selected_lane]
    selected_json = bool(lane["json_mode_enabled"]) or (
        selected_lane == "hard_convergence"
        and facts.requested_json
        and not selection.override_used
    )
    rejected_lanes = [
        str(lane_item["lane_id"])
        for lane_item in policy["lanes"]
        if str(lane_item["lane_id"]) != selected_lane
    ]

    canonical = {
        "task_text_hash": facts.task_text_hash,
        "selected_lane": selected_lane,
        "selected_model": selected_model,
        "thinking_mode": str(lane["thinking_mode"]),
        "reasoning_effort": str(lane["reasoning_effort"]),
        "json_mode_enabled": selected_json,
        "strict_tool_beta_enabled": bool(lane["strict_tool_beta_enabled"]),
        "beta_endpoint_required": bool(lane["beta_endpoint_required"]),
        "cache_stability_requirement": bool(policy["cache_stability_requirement"]),
        "stable_prefix_warning": _stable_prefix_warning(policy),
        "reason_codes": selection.reason_codes,
        "rejected_lanes": rejected_lanes,
        "override_used": selection.override_used,
        "warnings": selection.warnings,
    }
    decision_id = _sha256_text(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    )

    return {
        "schema_version": DECISION_SCHEMA_ID,
        "policy_id": str(policy["policy_id"]),
        "decision_id": decision_id,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "task_text_hash": facts.task_text_hash,
        "selected_lane": selected_lane,
        "selected_model": selected_model,
        "thinking_mode": str(lane["thinking_mode"]),
        "reasoning_effort": str(lane["reasoning_effort"]),
        "json_mode_enabled": selected_json,
        "strict_tool_beta_enabled": bool(lane["strict_tool_beta_enabled"]),
        "beta_endpoint_required": bool(lane["beta_endpoint_required"]),
        "cache_stability_requirement": bool(policy["cache_stability_requirement"]),
        "stable_prefix_warning": _stable_prefix_warning(policy),
        "reason_codes": selection.reason_codes,
        "rejected_lanes": rejected_lanes,
        "override_used": selection.override_used,
        "warnings": selection.warnings,
        "redaction_status": "content_light",
        "content_light": True,
    }


def build_deepseek_routing_decision(
    task: DeepSeekRoutingTask,
    *,
    policy: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    loaded_policy = policy or load_deepseek_lane_policy()
    decision = _build_decision_payload(task, loaded_policy)
    if generated_at is not None:
        decision["generated_at"] = generated_at
        canonical = {
            key: value
            for key, value in decision.items()
            if key not in {"generated_at", "decision_id"}
        }
        decision["decision_id"] = _sha256_text(
            json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        )
    errors = validate_deepseek_routing_decision(decision)
    if errors:
        raise ValueError(
            f"DeepSeek routing decision validation failed: {'; '.join(errors)}"
        )
    return decision


def write_deepseek_routing_decision(decision: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(decision, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def format_deepseek_routing_decision_table(decision: dict[str, Any]) -> str:
    rows = [
        ("decision_id", decision["decision_id"]),
        ("task_text_hash", decision["task_text_hash"]),
        ("selected_lane", decision["selected_lane"]),
        ("selected_model", decision["selected_model"]),
        ("thinking_mode", decision["thinking_mode"]),
        ("reasoning_effort", decision["reasoning_effort"]),
        ("json_mode_enabled", str(decision["json_mode_enabled"]).lower()),
        ("strict_tool_beta_enabled", str(decision["strict_tool_beta_enabled"]).lower()),
        ("beta_endpoint_required", str(decision["beta_endpoint_required"]).lower()),
        (
            "cache_stability_requirement",
            str(decision["cache_stability_requirement"]).lower(),
        ),
        ("override_used", str(decision["override_used"]).lower()),
        ("reason_codes", ", ".join(decision["reason_codes"])),
        ("rejected_lanes", ", ".join(decision["rejected_lanes"])),
        ("warnings", " | ".join(decision["warnings"])),
    ]
    width = max(len(label) for label, _ in rows)
    lines = [f"{label.ljust(width)}  {value}" for label, value in rows]
    return "\n".join(lines)


def format_deepseek_routing_preflight_banner(
    decision: dict[str, Any], *, default_lane: str, receipt_path: Path | None = None
) -> str:
    receipt_display = (
        f".build/rig-relay/deepseek-routing/{decision['decision_id']}.json"
    )
    if receipt_path is not None:
        try:
            receipt_display = (
                receipt_path.resolve().relative_to(Path.cwd().resolve()).as_posix()
            )
        except ValueError:
            receipt_display = receipt_path.name
    lines = [
        "DeepSeek routing recommendation",
        f"Lane: {decision['selected_lane']}",
        f"Model: {decision['selected_model']}",
        f"Effort: {decision['reasoning_effort']}",
        f"Reason: {', '.join(decision['reason_codes'])}",
        "Cache warning: preserve stable prefixes",
        f"Override: --deepseek-lane {default_lane}",
        f"Receipt: {receipt_display}",
    ]
    return "\n".join(lines)
