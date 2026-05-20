"""Post-PR Security Lifecycle Governance v1.

Models PR + alert lifecycle after PR mutation. Generates alert state plan.
Gates alert dismissal/reopen. Projects cockpit-ready summaries. No auto-dismiss.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.github_provider._fake_github_boundary import (
    FakeGitHubBoundary,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_EXECUTION = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_pr_mutation_execution_v1.v1.json"
)
_DEFAULT_OUTPUT = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_post_pr_lifecycle_v1.v1.json"
)
_DEFAULT_PLAN = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_alert_state_plan_v1.v1.json"
)
_DEFAULT_PROJ = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_post_pr_projection_v1.v1.json"
)
_DEFAULT_TRACE = (
    _REPO_ROOT
    / ".build"
    / "rig-relay"
    / "evidence"
    / "fake_github_post_pr_lifecycle_trace_v1.v1.json"
)

_FORBIDDEN = frozenset({
    "access_token",
    "token_prefix",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "raw_payload",
    "code_snippet",
    "vulnerable_code",
    "file_body",
    "auth_header",
    "bearer",
    "secret_value",
    "source_content",
    "raw_file",
})

_PR_STATES = {
    "no_pr",
    "pr_planned",
    "pr_simulated",
    "pr_created",
    "pr_open",
    "pr_checks_pending",
    "pr_checks_failed",
    "pr_checks_passed",
    "pr_review_required",
    "pr_merged_unverified",
    "pr_merged_verified",
    "pr_closed_without_merge",
}
_ALERT_STATES = {
    "alert_unknown",
    "alert_open",
    "alert_open_pr_created",
    "alert_pending_fix_verification",
    "alert_fixed_by_analysis",
    "alert_false_positive_candidate",
    "alert_dismissal_requested",
    "alert_dismissal_approved",
    "alert_dismissal_rejected",
    "alert_update_ready",
    "alert_update_blocked",
    "alert_closed_deferred",
}

_ALERT_PATHS = [
    {
        "path_id": "fix_verification",
        "description": "Verify the PR fix resolves the vulnerability",
        "required_evidence": ["pr_receipt", "test_results", "fix_analysis"],
        "required_permissions": [],
        "required_approval": "human_or_security_team",
        "remote_mutation": False,
    },
    {
        "path_id": "false_positive",
        "description": "Document why the alert is a false positive",
        "required_evidence": ["false_positive_analysis", "code_review_context"],
        "required_permissions": ["security_events:write"],
        "required_approval": "human_or_security_team",
        "remote_mutation": True,
    },
    {
        "path_id": "wont_fix",
        "description": "Accept the risk, document rationale",
        "required_evidence": ["risk_acceptance_documentation"],
        "required_permissions": ["security_events:write"],
        "required_approval": "human_or_security_team",
        "remote_mutation": True,
    },
    {
        "path_id": "dismissal_request",
        "description": "Request alert dismissal through approval chain",
        "required_evidence": ["fix_evidence_or_fp_analysis"],
        "required_permissions": ["security_events:write"],
        "required_approval": "human_or_security_team",
        "remote_mutation": True,
    },
    {
        "path_id": "direct_update",
        "description": "Directly update alert state (gated)",
        "required_evidence": [
            "pr_receipt",
            "approval_receipt",
            "permission_verification",
        ],
        "required_permissions": ["security_events:write"],
        "required_approval": "human_or_security_team",
        "remote_mutation": True,
    },
]


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


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _determine_pr_state(fb: FakeGitHubBoundary | None, pr_number: int | None) -> str:
    if pr_number is None or fb is None:
        return "no_pr"
    sc, data = fb.get_pr_status(pr_number)
    if sc == 404:
        return "no_pr"
    if isinstance(data, dict):
        if data.get("state") == "closed":
            return "pr_closed_without_merge"
        if data.get("merged") and data.get("checks") == "passing":
            return "pr_merged_verified"
        if data.get("merged"):
            return "pr_merged_unverified"
        if data.get("checks") == "failed":
            return "pr_checks_failed"
        if data.get("checks") == "pending":
            return "pr_checks_pending"
        if data.get("review_required"):
            return "pr_review_required"
        if data.get("checks") == "passing":
            return "pr_checks_passed"
        if data.get("state") == "open":
            return "pr_open"
    return "pr_created"


def _determine_alert_state(
    fb: FakeGitHubBoundary | None, alert_number: int | None
) -> str:
    if alert_number is None or fb is None:
        return "alert_unknown"
    sc, data = fb.get_alert_state(alert_number)
    if sc != 200:
        return "alert_unknown"
    if isinstance(data, dict):
        raw_state = data.get("state", "open")
        if raw_state in ("fixed", "dismissed"):
            return "alert_closed_deferred"
        return "alert_open"
    return "alert_open"


def build_post_pr_lifecycle(
    *,
    execution_path: Path = _DEFAULT_EXECUTION,
    max_fake_boundary: FakeGitHubBoundary | None = None,
    pr_created_override: bool = False,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    execution = _load_json(execution_path)
    pr_created = pr_created_override or (
        execution.get("pr_created") if execution else False
    )
    pr_state = "no_pr"
    alert_state = "alert_unknown"
    alert_number: int | None = 5

    if pr_created and max_fake_boundary is not None:
        pr_state = _determine_pr_state(max_fake_boundary, 1)
        alert_state = _determine_alert_state(max_fake_boundary, alert_number)

    # Alert state plan
    plan = {
        "alert_number": alert_number,
        "current_state": alert_state,
        "paths": _ALERT_PATHS,
        "gates_passed": False,
        "blocked_reasons": [
            "alert_update_disabled_by_default",
            "no_explicit_alert_mutation_flag",
        ],
        "recommended_path": "fix_verification",
        "recommended_action": "wait_for_alert_mutation_gate",
    }

    report: dict[str, Any] = {
        "schema_version": "rig.github.code_scanning_post_pr_lifecycle.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "remote_mutation": False,
        "alert_update": False,
        "alert_update_deferred": True,
        "pr_lifecycle_state": pr_state,
        "alert_lifecycle_state": alert_state,
        "alert_state_plan": plan,
        "causal_chain": [
            {"event": "patch_proposal_generated", "relationship": "observed"},
            {"event": "patch_preview_generated", "relationship": "observed"},
            {"event": "mutation_readiness_passed", "relationship": "observed"},
            {
                "event": "pr_simulated",
                "relationship": "observed"
                if execution and execution.get("pr_created")
                else "correlated_only",
            },
            {"event": "post_pr_lifecycle_checked", "relationship": "observed"},
        ],
        "projection": {
            "alert_number": alert_number,
            "pr_state": pr_state,
            "alert_state": alert_state,
            "pending_gates": ["alert_update_gate", "approval_gate"],
            "next_safe_action": "verify_fix_or_document_false_positive",
            "human_review_required": True,
        },
        "blocked_reasons": [],
        "redaction_summary": {
            "content_light": True,
            "forbidden_fields_present": False,
            "raw_response_bodies": False,
        },
        "recommended_next_slice": "Phase 3 — actual alert state mutation (gated)",
    }
    _assert_clean(report)
    return report


def _assert_clean(data: dict[str, Any]) -> None:
    s = json.dumps(data, sort_keys=True)
    for k in _FORBIDDEN:
        if f'"{k}"' in s:
            raise ValueError(f"forbidden:{k}")
    for p in (
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "ghr_",
        "github_pat_",
        "BEGIN PRIVATE KEY",
    ):
        if p in s:
            raise ValueError(f"forbidden_pattern:{p}")


def write_post_pr_lifecycle(
    output_path: Path = _DEFAULT_OUTPUT,
    *,
    simulate: bool = False,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    fb = FakeGitHubBoundary() if simulate else None
    report = build_post_pr_lifecycle(
        max_fake_boundary=fb, generated_at_utc=generated_at_utc
    )
    _write_json(output_path, report)
    plan_copy = dict(report["alert_state_plan"])
    plan_copy["generated_at"] = report["generated_at"]
    _write_json(_DEFAULT_PLAN, plan_copy)
    proj = dict(report["projection"])
    proj["generated_at"] = report["generated_at"]
    _write_json(_DEFAULT_PROJ, proj)
    if fb:
        fb.write_trace(_DEFAULT_TRACE)
    return report


__all__ = [
    "_ALERT_PATHS",
    "_determine_alert_state",
    "_determine_pr_state",
    "build_post_pr_lifecycle",
    "write_post_pr_lifecycle",
]
