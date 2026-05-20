"""Code Scanning Fix Patch Proposal v1 — governed, content-light, proposal-only.

Generates a safe, evidence-backed fix strategy for the top-ranked code scanning item.
No patches applied, no PRs created, no alerts dismissed. No raw code in artifacts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.core.utils.io import read_safe

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_REMEDIATION_PLAN = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_remediation_plan_v1.v1.json"
)
_DEFAULT_QUEUE = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_security_queue_v1.v1.json"
)
_DEFAULT_OUTPUT = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_patch_proposal_v1.v1.json"
)

_FORBIDDEN_PROPOSAL = frozenset({
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
    "source_content",
})


class PatchProposalError(Exception):
    """Raised when patch proposal building fails."""


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


def build_code_scanning_patch_proposal(
    *,
    remediation_plan_path: Path = _DEFAULT_REMEDIATION_PLAN,
    queue_path: Path = _DEFAULT_QUEUE,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    plan_artifact = _load_json(remediation_plan_path)
    queue_artifact = _load_json(queue_path)

    if plan_artifact is None:
        raise PatchProposalError(f"Remediation plan not found: {remediation_plan_path}")
    if queue_artifact is None:
        raise PatchProposalError(f"Queue not found: {queue_path}")

    plans = plan_artifact.get("remediation_plans", [])
    if not isinstance(plans, list):
        plans = []

    # Select top-ranked code_scanning item from remediation plan
    cs_plans = [
        p
        for p in plans
        if isinstance(p, dict) and p.get("source_surface") == "code_scanning"
    ]
    selected_plan = cs_plans[0] if cs_plans else None

    queue_items = queue_artifact.get("queue_items", [])
    if not isinstance(queue_items, list):
        queue_items = []

    # Match queue item
    queue_item: dict[str, Any] | None = None
    if selected_plan is not None:
        pid = selected_plan.get("queue_item_id", "")
        for qi in queue_items:
            if isinstance(qi, dict) and qi.get("queue_item_id") == pid:
                queue_item = qi
                break

    proposal_blocked = selected_plan is None or queue_item is None
    alert_number = queue_item.get("alert_number") if queue_item else None
    rule_hash = queue_item.get("rule_id_hash") if queue_item else None
    file_hash = queue_item.get("file_path_hash") if queue_item else None
    sev = queue_item.get("severity", "unknown") if queue_item else "unknown"

    # Build safe location summary from hashes only — no raw paths
    location_parts: list[str] = []
    if rule_hash:
        location_parts.append(f"rule_hash={rule_hash[:16]}")
    if file_hash:
        location_parts.append(f"path_hash={file_hash[:16]}")
    location_summary = (
        "; ".join(location_parts) if location_parts else "location_unknown"
    )

    # Patch strategy: describe approach without code
    patch_strategy = (
        "Investigate the identified CodeQL alert in its repository context. "
        "Review the CodeQL rule that triggered the alert to understand the vulnerability class. "
        "Determine whether the alert is a true positive requiring a fix, or a false positive requiring dismissal with evidence. "
        "If a fix is needed, plan a minimal code change addressing the vulnerability root cause. "
        "The fix should be accompanied by a targeted test verifying the vulnerability is no longer reachable."
    )

    report: dict[str, Any] = {
        "schema_version": "rig.github.code_scanning_patch_proposal.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "source_queue_artifact": str(queue_path),
        "source_remediation_plan_artifact": str(remediation_plan_path),
        "selected_plan_id": selected_plan.get("plan_id") if selected_plan else None,
        "selected_queue_item_id": selected_plan.get("queue_item_id")
        if selected_plan
        else None,
        "source_surface": "code_scanning",
        "alert_identifier_hash": rule_hash,
        "alert_number": alert_number,
        "severity": sev,
        "rule_id_hash": rule_hash,
        "rule_category": (
            "codeql_security"
            if queue_item
            and "codeql" in str(queue_item.get("suggested_group_kind", "")).lower()
            else "unknown"
        ),
        "location_summary_safe": location_summary,
        "affected_path_hashes": [file_hash] if file_hash else [],
        "evidence_available": bool(rule_hash or file_hash),
        "evidence_missing": [
            "raw_source_content_not_available_by_policy",
            "live_repo_access_deferred",
        ]
        if not proposal_blocked
        else ["no_actionable_alert"],
        "patch_strategy": patch_strategy if not proposal_blocked else "",
        "patch_summary_safe": (
            "Remediation proposal for CodeQL security alert: investigate vulnerability class, "
            "determine true positive vs false positive, plan minimal fix with targeted test. "
            "Actual code diff deferred to later dry-run patch-preview lane."
        )
        if not proposal_blocked
        else "No actionable code scanning item available.",
        "proposed_file_operations": [
            "read_alert_context (security_events:read)",
            "read_affected_file (contents:read)",
            "write_fix_file (contents:write — later lane)",
            "create_pull_request (pull_requests:write — later lane)",
        ]
        if not proposal_blocked
        else [],
        "proposed_diff_summary": "Diff generation deferred to dry-run patch-preview lane (Phase 2 Slice 4)",
        "proposed_test_strategy": [
            "targeted unit/integration test relevant to affected path",
            "static analysis check relevant to CodeQL rule category",
            "redaction scan on any generated patch artifacts",
            "schema validation on any generated patch artifacts",
            "do_not_run_full_pytest",
        ],
        "required_read_permissions": [
            "security_events:read",
            "metadata:read",
            "contents:read",
        ],
        "required_mutation_permissions_later": [
            "contents:write",
            "pull_requests:write",
            "security_events:write",
        ],
        "remote_mutation_status": "disabled",
        "local_mutation_status": "disabled",
        "pr_creation_status": "disabled",
        "alert_update_status": "disabled",
        "confidence": "medium",
        "blocked_reasons": []
        if not proposal_blocked
        else ["no_actionable_code_scanning_item"],
        "human_review_required": True,
        "redaction_status": {
            "content_light": True,
            "forbidden_fields_present": False,
            "redaction_rules": len(_FORBIDDEN_PROPOSAL),
            "raw_code_snippets_present": False,
            "raw_source_content_present": False,
        },
        "content_light_status": "proposal_content_light",
        "recommended_next_slice": (
            "Phase 2 Slice 4 — generate dry-run patch preview with evidence, "
            "permission verification, and PR plan readiness"
        ),
    }

    _assert_proposal_content_light(report)
    return report


def _assert_proposal_content_light(data: dict[str, Any]) -> None:
    serialized = json.dumps(data, sort_keys=True)
    for key in _FORBIDDEN_PROPOSAL:
        if f'"{key}"' in serialized:
            raise ValueError(f"forbidden_key_in_proposal: {key}")
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
            raise ValueError(f"forbidden_pattern_in_proposal: {pattern}")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_code_scanning_patch_proposal(
    output_path: Path = _DEFAULT_OUTPUT,
    *,
    remediation_plan_path: Path = _DEFAULT_REMEDIATION_PLAN,
    queue_path: Path = _DEFAULT_QUEUE,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    report = build_code_scanning_patch_proposal(
        remediation_plan_path=remediation_plan_path,
        queue_path=queue_path,
        generated_at_utc=generated_at_utc,
    )
    _write_json(output_path, report)
    return report


__all__ = [
    "PatchProposalError",
    "build_code_scanning_patch_proposal",
    "write_code_scanning_patch_proposal",
]
