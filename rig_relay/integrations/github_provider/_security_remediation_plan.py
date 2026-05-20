"""Security Remediation Plan v1 — governed, planning-only, content-light.

Selects top 3 actionable items from the unified security queue and generates
source-aware remediation plans. No patches, no PRs, no alert dismissal, no mutation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.core.utils.io import read_safe

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_QUEUE = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_security_queue_v1.v1.json"
)
_DEFAULT_OUTPUT = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_remediation_plan_v1.v1.json"
)

_MAX_SELECTED = 3

_SOURCE_STRATEGIES: dict[str, dict[str, Any]] = {
    "code_scanning": {
        "remediation_strategy": "Investigate alert context, review rule/query, plan local patch if evidence exists. No raw code snippets in artifacts.",
        "allowed_next_actions": [
            "inspect_alert_context",
            "review_codeql_rule",
            "plan_local_patch",
            "classify_false_positive",
        ],
        "forbidden_actions": [
            "dismiss_alert_without_evidence",
            "auto_close_alert",
            "publish_patch_without_review",
        ],
        "mutation_required": False,
        "human_review_required": True,
        "proposed_followup_slice": "Phase 2 Slice 3 — generate code scanning fix patch proposal with evidence",
    },
    "dependabot": {
        "remediation_strategy": "Dependabot surface is currently refused. Cannot plan dependency updates without live access. Request permission grant first.",
        "allowed_next_actions": [
            "request_permission",
            "audit_dependency_manifest_local",
        ],
        "forbidden_actions": [
            "fake_dependency_update",
            "auto_dismiss_dependabot_alert",
        ],
        "mutation_required": False,
        "human_review_required": True,
        "proposed_followup_slice": "Phase 2 Slice 4 — enable dependabot permission and generate dependency update plan",
    },
    "secret_scanning": {
        "remediation_strategy": "Secret scanning surface is refused. If enabled later: verify revocation/rotation of exposed credential, create cleanup commit. Never persist secret values in any artifact.",
        "allowed_next_actions": [
            "verify_revocation",
            "plan_cleanup_commit",
            "request_permission",
        ],
        "forbidden_actions": [
            "persist_secret_value",
            "auto_revoke",
            "expose_secret_location",
        ],
        "mutation_required": False,
        "human_review_required": True,
        "proposed_followup_slice": "Phase 2 Slice 5 — enable secret scanning and generate revocation verification plan",
    },
    "repository_security_advisory": {
        "remediation_strategy": "Security advisory surface is not available. Cannot plan advisory management without API access.",
        "allowed_next_actions": [
            "request_permission",
            "audit_existing_advisories_local",
        ],
        "forbidden_actions": ["fabricate_advisory_content"],
        "mutation_required": False,
        "human_review_required": True,
        "proposed_followup_slice": "Phase 2 Slice 6 — enable advisory access and generate advisory audit plan",
    },
    "security_policy_gap": {
        "remediation_strategy": "Security policy gap detected. Review existing SECURITY.md, compare with best practices, propose updates if missing or stale. No mutation in this slice.",
        "allowed_next_actions": [
            "audit_security_policy_file",
            "compare_with_best_practice",
            "propose_policy_update_plan",
        ],
        "forbidden_actions": ["auto_write_policy_file"],
        "mutation_required": False,
        "human_review_required": True,
        "proposed_followup_slice": "Phase 2 Slice 7 — generate security policy update proposal with evidence",
    },
}

_FORBIDDEN_PLAN = frozenset({
    "access_token",
    "token_prefix",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "patch",
    "diff",
    "code_snippet",
    "vulnerable_code",
    "file_body",
    "auth_header",
    "bearer",
    "secret_value",
    "raw_secret",
    "raw_alert_body",
})


class SecurityRemediationPlanError(Exception):
    """Raised when remediation planning fails."""


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    raw = read_safe(path, raise_on_error=True)
    try:
        data = json.loads(raw.text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return None


def _is_actionable(item: dict[str, Any]) -> bool:
    """Determine if a queue item is actionable for remediation planning."""
    source_kind = item.get("source_kind", "")
    state = item.get("state", "")

    if source_kind == "not_available":
        return False
    if state in {"fixed", "dismissed"}:
        return False
    if source_kind == "refusal" and state == "refused":
        return False

    return True


def _select_top_items(
    queue_items: list[dict[str, Any]], max_selected: int = _MAX_SELECTED
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select top actionable items by priority. Returns (selected, rejected)."""
    actionable = [qi for qi in queue_items if _is_actionable(qi)]
    rejected = [qi for qi in queue_items if not _is_actionable(qi)]

    # Sort by priority_score (lower = higher priority), stable by queue_item_id
    actionable.sort(
        key=lambda qi: (qi.get("priority_score", 99), qi.get("queue_item_id", ""))
    )

    selected = actionable[:max_selected]
    rejected.extend(actionable[max_selected:])

    return selected, rejected


def _build_item_plan(queue_item: dict[str, Any], rank: int) -> dict[str, Any]:
    source = queue_item.get("source_surface", "unknown")
    strategy = _SOURCE_STRATEGIES.get(
        source, _SOURCE_STRATEGIES.get("code_scanning", {})
    )

    # Build a safe issue summary from available metadata only
    parts: list[str] = []
    sev = queue_item.get("severity", "unknown")
    domain = queue_item.get("security_domain", "unknown")
    lane = queue_item.get("remediation_lane", "unknown")
    parts.append(f"[{sev}] {domain}")
    if lane and lane != "unknown_triage_needed":
        parts.append(f"lane={lane}")
    if queue_item.get("alert_number") is not None:
        parts.append(f"alert#{queue_item['alert_number']}")
    issue_summary = "; ".join(parts)

    # Evidence analysis
    has_evidence = bool(
        queue_item.get("rule_id_hash")
        or queue_item.get("package_name_hash")
        or queue_item.get("ghsa_id_hash")
        or queue_item.get("suggested_group_kind")
    )
    evidence_missing = []
    if source == "secret_scanning":
        evidence_missing.append("secret_value_not_available_by_policy")
        evidence_missing.append("revocation_status_unknown")
    if source == "dependabot" and queue_item.get("source_kind") == "refusal":
        evidence_missing.append("dependabot_surface_refused")
    if source == "security_policy_gap":
        evidence_missing.append("policy_file_state_unknown")

    plan_id = _sha256_text(f"remediation:{queue_item.get('queue_item_id', '')}:{rank}")

    return {
        "plan_id": plan_id,
        "queue_item_id": queue_item.get("queue_item_id", ""),
        "source_surface": source,
        "security_domain": domain,
        "severity": sev,
        "priority_rank": rank,
        "priority_score": queue_item.get("priority_score"),
        "source_identifier_hash": queue_item.get("rule_id_hash")
        or queue_item.get("package_name_hash")
        or queue_item.get("ghsa_id_hash"),
        "issue_summary_safe": issue_summary,
        "evidence_available": has_evidence,
        "evidence_missing": evidence_missing,
        "remediation_strategy": strategy.get("remediation_strategy", ""),
        "allowed_next_actions": strategy.get("allowed_next_actions", []),
        "forbidden_actions": strategy.get("forbidden_actions", []),
        "required_permissions": {
            "read": queue_item.get("required_permissions", []),
            "mutation": queue_item.get("remediation_permissions", []),
        },
        "mutation_required": False,
        "remote_mutation_status": "disabled",
        "local_mutation_status": "disabled",
        "confidence": "medium",
        "blocked_reasons": queue_item.get("blocked_reasons", []),
        "human_review_required": strategy.get("human_review_required", True),
        "proposed_followup_slice": strategy.get("proposed_followup_slice", ""),
        "redaction_status": {"content_light": True, "forbidden_fields_present": False},
    }


def build_security_remediation_plan(
    *,
    queue_path: Path = _DEFAULT_QUEUE,
    max_selected: int = _MAX_SELECTED,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    queue = _load_json(queue_path)
    if queue is None:
        raise SecurityRemediationPlanError(f"Queue artifact not found: {queue_path}")

    queue_items = queue.get("queue_items", [])
    if not isinstance(queue_items, list):
        queue_items = []

    selected, rejected = _select_top_items(queue_items, max_selected)

    plans = [_build_item_plan(qi, i + 1) for i, qi in enumerate(selected)]

    # Rejected summary
    rejected_by_source: dict[str, int] = {}
    rejected_reasons: list[str] = []
    for rj in rejected:
        source = rj.get("source_surface", "unknown")
        rejected_by_source[source] = rejected_by_source.get(source, 0) + 1
        for reason in rj.get("blocked_reasons", []):
            if isinstance(reason, str) and reason not in rejected_reasons:
                rejected_reasons.append(reason)

    selected_ids = [p["queue_item_id"] for p in plans]

    report: dict[str, Any] = {
        "schema_version": "rig.github.security_remediation_plan.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "remote_mutation": False,
        "source_queue_artifact": str(queue_path),
        "source_queue_hash": hashlib.sha256(queue_path.read_bytes()).hexdigest()
        if queue_path.exists()
        else None,
        "selection_policy": {
            "max_items": max_selected,
            "selection_criteria": [
                "item must be open/actionable (not fixed, dismissed, refused, or not_available)",
                "selected by lowest priority_score first",
                "stable tiebreaker by queue_item_id",
                "up to max_items selected",
            ],
            "total_queue_items": len(queue_items),
            "actionable_items": len(selected)
            + len([r for r in rejected if _is_actionable(r)]),
            "items_selected": len(selected),
            "items_rejected": len(rejected),
        },
        "selected_queue_item_ids": selected_ids,
        "rejected_queue_items_summary": {
            "total_rejected": len(rejected),
            "rejected_by_source_surface": rejected_by_source,
            "common_rejected_reasons": rejected_reasons,
        },
        "remediation_plans": plans,
        "permission_requirements": {
            "read_permissions_needed": sorted({
                p
                for plan_item in plans
                for p in (
                    plan_item.get("required_permissions", {}).get("read", [])
                    if isinstance(plan_item.get("required_permissions"), dict)
                    else []
                )
            }),
            "mutation_permissions_deferred": sorted({
                p
                for plan_item in plans
                for p in (
                    plan_item.get("required_permissions", {}).get("mutation", [])
                    if isinstance(plan_item.get("required_permissions"), dict)
                    else []
                )
            }),
        },
        "blocked_reasons": sorted({
            r for p in plans for r in p.get("blocked_reasons", [])
        }),
        "redaction_summary": {
            "content_light": True,
            "forbidden_fields_present": False,
            "redaction_rules": len(_FORBIDDEN_PLAN),
            "secret_values_present": False,
            "raw_code_snippets_present": False,
        },
        "content_light_status": "all_plans_content_light",
        "remote_mutation_status": "disabled",
        "local_mutation_status": "disabled",
        "event_fabric_events_emitted": False,
        "telemetry_redaction_implications": "All plan data is content-light: no tokens, auth headers, raw response bodies, code snippets, secret values, or private file contents.",
        "intentionally_deferred": [
            "patch_generation",
            "PR_creation",
            "alert_dismissal",
            "secret_revocation_execution",
            "dependency_update_execution",
            "security_policy_file_write",
        ],
        "recommended_next_slice": "Phase 2 Slice 3 — generate code scanning fix patch proposal with evidence",
    }

    _assert_plan_content_light(report)
    return report


def _assert_plan_content_light(data: dict[str, Any]) -> None:
    serialized = json.dumps(data, sort_keys=True)
    for key in _FORBIDDEN_PLAN:
        if f'"{key}"' in serialized:
            raise ValueError(f"forbidden_key_in_plan: {key}")
    for pattern in (
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "ghr_",
        "github_pat_",
        "BEGIN PRIVATE KEY",
    ):
        if pattern in serialized:
            raise ValueError(f"forbidden_pattern_in_plan: {pattern}")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_security_remediation_plan(
    output_path: Path = _DEFAULT_OUTPUT,
    *,
    queue_path: Path = _DEFAULT_QUEUE,
    max_selected: int = _MAX_SELECTED,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    report = build_security_remediation_plan(
        queue_path=queue_path,
        max_selected=max_selected,
        generated_at_utc=generated_at_utc,
    )
    _write_json(output_path, report)
    return report


__all__ = [
    "_SOURCE_STRATEGIES",
    "SecurityRemediationPlanError",
    "build_security_remediation_plan",
    "write_security_remediation_plan",
]
