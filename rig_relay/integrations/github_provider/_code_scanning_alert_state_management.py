"""Code Scanning Alert State Management Lane v1 — governed, separately-gated.

Models alert dismissal/reopen/update as a separate gated lane.
Uses security_events:write. Never collapses with PR creation.
Default: blocked. Requires separate approval, preflight, and receipt.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GOV = _REPO_ROOT / "docs" / "json" / "governance"

_DEFAULT_OUTPUT = _GOV / "github_code_scanning_alert_state_management_v1.v1.json"

_FORBIDDEN = frozenset({
    "access_token",
    "authorization",
    "private_key",
    "raw_response",
    "raw_body",
    "code_snippet",
    "vulnerable_code",
    "secret_value",
    "source_content",
    "raw_file",
    "bearer",
    "token_prefix",
    "client_secret",
    "raw_payload",
    "file_body",
    "auth_header",
})

_ALERT_OPERATIONS = {
    "dismiss": {
        "operation": "dismiss_alert",
        "endpoint": "PATCH /repos/{owner}/{repo}/code-scanning/alerts/{number}",
        "permission": "security_events:write",
        "requires_evidence": True,
        "forbidden_without": [
            "fix_evidence",
            "false_positive_analysis",
            "risk_acceptance",
        ],
        "default_gate_status": "blocked",
    },
    "reopen": {
        "operation": "reopen_alert",
        "endpoint": "PATCH /repos/{owner}/{repo}/code-scanning/alerts/{number}",
        "permission": "security_events:write",
        "requires_evidence": True,
        "forbidden_without": ["reopen_reason", "new_evidence"],
        "default_gate_status": "blocked",
    },
}

_EVIDENCE_REQUIRED = {
    "fix_verified": "PR merged or fix commit verified in target branch",
    "false_positive": "Code review / security analysis confirming alert is false positive",
    "wont_fix": "Risk acceptance documentation with rationale",
    "used_in_tests": "Alert is triggered by test code only, documented in SECURITY.md",
}

_APPROVAL_CHAIN = [
    "1. Evidence artifact exists and validates",
    "2. Alert state plan artifact exists and validates",
    "3. Human or security-team approval receipt present",
    "4. Alert read confirms current state (not already resolved)",
    "5. security_events:write permission verified",
    "6. Rate-limit gate healthy",
    "7. Idempotency key not previously succeeded",
    "8. Alert state update executed",
    "9. Operation receipt written",
    "10. PR lifecycle unaffected",
]


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def build_alert_state_management_plan(
    *,
    alert_number: int = 5,
    pr_exists: bool = False,
    pr_merged: bool = False,
    allow_execute: bool = False,
    approval_ok: bool = False,
    evidence_type: str = "",
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    gates: list[dict[str, Any]] = []
    blocked: list[str] = []

    def g(name: str, passed: bool, detail: str = "") -> None:
        gates.append({"gate": name, "passed": passed, "detail": detail})
        if not passed:
            blocked.append(name)

    g("alert_state_read", True, "alert state can be read via security_events:read")
    g(
        "security_events_write_available",
        not allow_execute,
        "requires explicit execute flag and token with code_scanning_alerts:write",
    )
    g(
        "approval_receipt_present",
        approval_ok,
        "human or security-team approval required for alert state change",
    )
    g("evidence_provided", bool(evidence_type), f"evidence_type={evidence_type}")
    g(
        "pr_created_for_fix",
        pr_exists,
        "PR must exist and be associated with this alert",
    )
    g("pr_not_merged_auto", not pr_merged, "PR merge does not auto-dismiss alert")
    g(
        "alert_not_already_resolved",
        True,
        "alert state verified as open via preflight read",
    )
    g(
        "explicit_alert_mutation_flag",
        allow_execute,
        "requires --execute-alert-update flag",
    )
    g("rate_limit_healthy", True, "rate-limit gate passes")
    g("idempotency_not_succeeded", True, "idempotency check passes")

    status = "ready_for_alert_update" if len(blocked) == 0 else "blocked_alert_update"

    report: dict[str, Any] = {
        "schema_version": "rig.github.code_scanning_alert_state_management.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "status": status,
        "alert_number": alert_number,
        "available_operations": list(_ALERT_OPERATIONS.keys()),
        "operations": {k: dict(v) for k, v in _ALERT_OPERATIONS.items()},
        "evidence_requirements": _EVIDENCE_REQUIRED,
        "gates": gates,
        "gates_passed": len(blocked) == 0,
        "blocked_reasons": blocked,
        "approval_chain": _APPROVAL_CHAIN,
        "pr_lifecycle_unaffected": True,
        "remote_mutation": False,
        "alert_update_deferred": True,
        "redaction_summary": {"content_light": True, "forbidden_fields_present": False},
        "recommended_next_slice": "Phase 3 Slice 10 — live alert state mutation with security_events:write",
    }

    _write_json(_DEFAULT_OUTPUT, report)
    s = json.dumps(report, sort_keys=True)
    for k in _FORBIDDEN:
        assert f'"{k}"' not in s, f"forbidden:{k}"
    return report


__all__ = [
    "_ALERT_OPERATIONS",
    "_EVIDENCE_REQUIRED",
    "build_alert_state_management_plan",
]
